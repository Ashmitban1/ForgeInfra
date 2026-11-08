"""Incident-to-job API behavior, independent of provider credentials or Docker."""

from copy import deepcopy
from datetime import datetime, timezone
from threading import Event, Lock
import time
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from pymongo.errors import ConnectionFailure

from backend.modernization.repository import MemoryIncidentRepository, content_revision
from backend.modernization.router import create_modernization_router
from backend.modernization.service import RepairService


def sample_incident():
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": "1.0", "incident_id": "INC-API-TEST", "device_id": "RACK-API-TEST",
        "created_at": now, "updated_at": now, "status": "OPEN", "severity": "HIGH",
        "hardware": {"temperature_c": 29.4, "humidity_pct": 54, "cooling_fault": True,
                     "source_kind": "simulator", "fault_is_simulated": True,
                     "observed_at": now, "received_at": now, "sequence": 1},
        "legacy_monitor": {"status": "NORMAL", "source_revision": "demo-legacy-placeholder-v1", "sampled_at": now},
        "expected_status": "WARNING", "reliability": {"mismatch": True, "reasons": ["legacy_missed_fault"]},
        "investigation": {"status": "PENDING", "tool_calls": []},
        "decision_review": {"status": "PENDING", "recommendation": None},
        "integrations": {"jira_key": None},
    }


def sample_result():
    return {"repair_id": "repair-test", "verification_status": "VERIFIED",
            "proposal_origin": "manually_authored_demo_patch", "approval_status": "PENDING",
            "deployed": False, "diff": "--- original\n+++ candidate\n+ cooling_fault\n",
            "tests": {"original": {"exit_code": 1, "passed": 4, "failed": 1},
                      "candidate": {"exit_code": 0, "passed": 5, "failed": 0}}}


def make_system(tmp_path, pipeline=None, max_pending=4):
    records = {"INC-API-TEST": sample_incident()}
    repository = MemoryIncidentRepository(records, Lock())
    service = RepairService(repository, tmp_path, pipeline or (lambda snapshot, root: sample_result()), max_pending)
    app = FastAPI()
    app.include_router(create_modernization_router(service))
    return app, repository, service, records


def wait_for_job(client, job_id, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get("/api/repairs/" + job_id)
        assert response.status_code == 200, response.text
        job = response.json()
        if job["status"] not in ("QUEUED", "RUNNING"):
            return job
        time.sleep(0.01)
    pytest.fail("Repair job did not finish before the test deadline")


def test_submit_poll_analysis_diff_and_shared_incident_attachment(tmp_path):
    app, repository, service, records = make_system(tmp_path)
    with TestClient(app) as client:
        initial = client.get("/api/incidents/INC-API-TEST/analysis").json()
        assert initial["repair"] is None
        response = client.post("/api/incidents/INC-API-TEST/repair")
        assert response.status_code == 202
        job = wait_for_job(client, response.json()["job_id"])
        assert job["status"] == "COMPLETED"
        assert job["result"]["verification_status"] == "VERIFIED"
        assert job["approval_status"] == "PENDING" and not job["deployed"]
        assert "diff" not in job["result"]
        assert str(tmp_path) not in str(job)
        assert client.get(job["links"]["diff"]).text.startswith("--- original")
        assert client.get(job["links"]["report"]).json()["job_id"] == job["job_id"]
        analysis = client.get(job["links"]["analysis"]).json()
        assert analysis["repair"]["job_id"] == job["job_id"]
        assert analysis["investigation"]["status"] == "PENDING"
        assert analysis["decision_review"]["recommendation"] is None
        assert records["INC-API-TEST"]["repair"]["verification_status"] == "VERIFIED"
        assert records["INC-API-TEST"]["status"] == "OPEN"
        assert job["snapshot_revision"] == content_revision(job["snapshot"])


@pytest.mark.parametrize("path,method", [
    ("/api/incidents/missing/repair", "post"),
    ("/api/incidents/missing/analysis", "get"),
    ("/api/repairs/missing", "get"),
    ("/api/repairs/missing/diff", "get"),
])
def test_unknown_records_are_404(tmp_path, path, method):
    app, *_ = make_system(tmp_path)
    with TestClient(app) as client:
        assert getattr(client, method)(path).status_code == 404


def test_same_request_key_reuses_completed_job(tmp_path):
    executions = []

    def pipeline(snapshot, root):
        executions.append(snapshot)
        return sample_result()

    app, repository, service, records = make_system(tmp_path, pipeline)
    with TestClient(app) as client:
        first = client.post("/api/incidents/INC-API-TEST/repair", headers={"Idempotency-Key": "same-request"})
        job = wait_for_job(client, first.json()["job_id"])
        with repository.lock:
            records["INC-API-TEST"]["hardware"]["cooling_fault"] = False
        second = client.post("/api/incidents/INC-API-TEST/repair", headers={"Idempotency-Key": "same-request"})
        assert second.status_code == 200 and second.json()["reused"]
        assert second.json()["job_id"] == job["job_id"]
        assert len(executions) == 1


def test_background_job_freezes_snapshot_and_rejects_conflicting_request(tmp_path):
    entered, release = Event(), Event()

    def pipeline(snapshot, root):
        entered.set()
        assert release.wait(5)
        assert snapshot["hardware"]["temperature_c"] == 29.4
        snapshot["hardware"]["temperature_c"] = -1  # Must not mutate stored job evidence.
        return sample_result()

    app, repository, service, records = make_system(tmp_path, pipeline)
    with TestClient(app) as client:
        try:
            first = client.post("/api/incidents/INC-API-TEST/repair", headers={"Idempotency-Key": "first"})
            job_id = first.json()["job_id"]
            assert entered.wait(2)
            # Analysis and shared store updates remain available while the worker is blocked.
            assert client.get("/api/incidents/INC-API-TEST/analysis").status_code == 200
            assert client.get("/api/repairs/" + job_id + "/diff").status_code == 409
            with repository.lock:
                records["INC-API-TEST"]["hardware"]["temperature_c"] = 40
            repeated = client.post("/api/incidents/INC-API-TEST/repair", headers={"Idempotency-Key": "first"})
            assert repeated.json()["job_id"] == job_id and repeated.json()["reused"]
            conflict = client.post("/api/incidents/INC-API-TEST/repair", headers={"Idempotency-Key": "different"})
            assert conflict.status_code == 409
        finally:
            release.set()
        completed = wait_for_job(client, job_id)
        assert completed["snapshot"]["hardware"]["temperature_c"] == 29.4


def test_recycled_incident_id_never_receives_old_result(tmp_path):
    entered, release = Event(), Event()

    def pipeline(snapshot, root):
        entered.set()
        assert release.wait(5)
        return sample_result()

    app, repository, service, records = make_system(tmp_path, pipeline)
    with TestClient(app) as client:
        try:
            job_id = client.post("/api/incidents/INC-API-TEST/repair").json()["job_id"]
            assert entered.wait(2)
            with repository.lock:
                records["INC-API-TEST"] = sample_incident()  # New creation timestamp/incarnation.
        finally:
            release.set()
        job = wait_for_job(client, job_id)
        assert job["attached_to_incident"] is False
        assert "repair" not in records["INC-API-TEST"]
        assert client.get("/api/incidents/INC-API-TEST/analysis").json()["repair"] is None


def test_pipeline_exception_is_safe_failure_not_fake_success(tmp_path):
    def broken(snapshot, root):
        raise RuntimeError("mongodb://do-not-expose-credentials")

    app, *_ = make_system(tmp_path, broken)
    with TestClient(app) as client:
        job_id = client.post("/api/incidents/INC-API-TEST/repair").json()["job_id"]
        job = wait_for_job(client, job_id)
        assert job["status"] == "FAILED" and job["result"] is None
        assert "do-not-expose" not in str(job)


def test_malformed_or_unsupported_incident_is_not_queued(tmp_path):
    app, repository, service, records = make_system(tmp_path)
    records["INC-API-TEST"]["hardware"]["cooling_fault"] = False
    with TestClient(app) as client:
        assert client.post("/api/incidents/INC-API-TEST/repair").status_code == 409
        assert repository.jobs == {}


def test_queue_capacity_returns_503_without_orphan_job(tmp_path):
    entered, release = Event(), Event()

    def pipeline(snapshot, root):
        entered.set()
        assert release.wait(5)
        return sample_result()

    app, repository, service, records = make_system(tmp_path, pipeline, max_pending=1)
    records["INC-OTHER"] = {**deepcopy(records["INC-API-TEST"]), "incident_id": "INC-OTHER"}
    with TestClient(app) as client:
        try:
            client.post("/api/incidents/INC-API-TEST/repair")
            assert entered.wait(2)
            assert client.post("/api/incidents/INC-OTHER/repair").status_code == 503
            assert len(repository.jobs) == 1
        finally:
            release.set()


def test_database_exception_is_not_exposed(tmp_path, monkeypatch):
    app, repository, *_ = make_system(tmp_path)

    def unavailable(*args):
        raise ConnectionFailure("mongodb://do-not-expose-credentials")

    monkeypatch.setattr(repository, "get_incident_snapshot", unavailable)
    with TestClient(app) as client:
        response = client.post("/api/incidents/INC-API-TEST/repair")
        assert response.status_code == 503
        assert "do-not-expose" not in response.text


def test_default_wrapper_uses_real_p1_ingestion_and_same_incident_store(tmp_path):
    # Import once, after creating an actual incident through P1's existing route.
    from backend.modernization.app import app, service
    service.pipeline = lambda snapshot, root: sample_result()
    service.output_root = tmp_path
    with TestClient(app) as client:
        now = datetime.now(timezone.utc).isoformat()
        event = {"schema_version": "1.0", "device_id": "API-WRAPPER-" + uuid.uuid4().hex[:8],
                 "source_kind": "simulator", "observed_at": now, "sequence": 1,
                 "temperature_c": 29.4, "humidity_pct": 54, "cooling_fault": True,
                 "fault_is_simulated": True}
        received = client.post("/api/telemetry", json=event)
        assert received.status_code == 200
        incident_id = received.json()["incident_id"]
        job_id = client.post(f"/api/incidents/{incident_id}/repair").json()["job_id"]
        wait_for_job(client, job_id)
        incident = client.get(f"/api/incidents/{incident_id}").json()
        assert incident["repair"]["job_id"] == job_id
        assert incident["investigation"]["status"] == "PENDING"
