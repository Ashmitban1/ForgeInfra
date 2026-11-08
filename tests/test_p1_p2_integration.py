"""P1 telemetry plus durable P2 workflows, with explicitly scripted providers."""

from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
from unittest.mock import Mock
import uuid

from fastapi.testclient import TestClient
import mongomock
import pytest
from pymongo.errors import ConnectionFailure
from pymongo import MongoClient

from backend import main
from backend.agents import tools as tools_module
from backend.agents.gemini import GeminiConfig
from backend.agents.nemotron import MODEL, NemotronConfig
from backend.modernization import app as combined
from backend.modernization.approval import ApprovalConflict
from backend.modernization.approval_auth import token_digest
from backend.modernization.patching import source_hash
from backend.modernization.runner import LEGACY_MONITOR_PATH
from backend.storage.mongo import MongoIncidentStore


def _load_helpers(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parent / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agents = _load_helpers("p1_p2_scripted_agents", "agents/conftest.py")
approval_helpers = _load_helpers("p1_p2_scripted_approval", "modernization/test_approval_api.py")
HEADERS = approval_helpers.ALICE


def telemetry(sequence=1, *, fault=True, temperature=29.4, humidity=54):
    return {
        "schema_version": "1.0", "device_id": "SIM-P1-P2-INTEGRATION", "source_kind": "simulator",
        "observed_at": datetime.now(timezone.utc).isoformat(), "sequence": sequence,
        "temperature_c": temperature, "humidity_pct": humidity,
        "cooling_fault": fault, "fault_is_simulated": True,
    }


def _clear_process_state(monkeypatch):
    for name in ("_incidents", "_latest", "_latest_sequence", "_history", "_fingerprints", "_approval_acks"):
        monkeypatch.setattr(main, name, {})
    monkeypatch.setattr(main, "_store", None)
    monkeypatch.setattr(main, "_next_incident_number", 1)


@pytest.fixture(params=["mongomock", "mongo"])
def integrated(tmp_path, monkeypatch, request):
    """Use P1's actual writer and lifecycle, never an external Mongo/provider."""
    _clear_process_state(monkeypatch)
    durable = request.param == "mongo"
    if durable:
        if not request.config.getoption("--run-mongo-tests"):
            pytest.skip("Enable disposable local MongoDB with --run-mongo-tests")
        uri = os.getenv("FACTORYOS_TEST_MONGO_URI", "")
        if not uri.startswith(("mongodb://127.0.0.1:", "mongodb://localhost:")):
            pytest.fail("Use a disposable local FACTORYOS_TEST_MONGO_URI")
        client = MongoClient(uri, serverSelectionTimeoutMS=3000, tz_aware=True)
        client.admin.command("ping")
        database = client["factoryos_p1_p2_test_" + uuid.uuid4().hex]
    else:
        client = mongomock.MongoClient()
        database = client["p1_p2_integration"]
    stores, providers = [], []

    def store_factory():
        # Each lifespan owns/closes its client; an independent inspection client
        # lets a real Mongo restart test observe the same disposable database.
        store_client = MongoClient(uri, serverSelectionTimeoutMS=3000, tz_aware=True) if durable else client
        store = MongoIncidentStore(store_client, database.name)
        stores.append(store)
        return store

    def provider_factory(config):
        provider = agents.ScriptedClient(config, "patch")
        providers.append(provider)
        return provider

    monkeypatch.setattr(main, "store_from_environment", store_factory)
    monkeypatch.setattr(main, "tiger_from_environment", lambda: None)
    # Foreground routes flush synchronously; keep outage checks deterministic.
    monkeypatch.setattr(main, "_retry_persistence", lambda stop, store: None)
    monkeypatch.setattr(tools_module, "execute_incident_repair", approval_helpers.scripted_verifier)
    monkeypatch.setenv("FACTORYOS_APPROVERS_JSON", json.dumps({
        "alice": token_digest(approval_helpers.ALICE_TOKEN),
    }))
    monkeypatch.setenv("MONGODB_REPAIR_JOBS_COLLECTION", "repair_jobs")
    monkeypatch.setenv("MONGODB_INVESTIGATION_JOBS_COLLECTION", "investigation_jobs")
    monkeypatch.setenv("MONGODB_REVIEW_JOBS_COLLECTION", "review_jobs")
    monkeypatch.setattr(combined.service, "output_root", tmp_path / "repairs")
    monkeypatch.setattr(combined.investigation_service, "output_root", tmp_path / "investigations")
    monkeypatch.setattr(combined.investigation_service, "client_factory", provider_factory)
    monkeypatch.setattr(combined.investigation_service, "config_factory", lambda: NemotronConfig(
        api_key="scripted-p1-p2-nvidia-key", model=MODEL, max_rounds=4, max_tool_calls=6,
    ))
    monkeypatch.setattr(combined.review_service, "output_root", tmp_path / "reviews")
    monkeypatch.setattr(combined.review_service, "client_factory", approval_helpers.ScriptedReviewer)
    monkeypatch.setattr(combined.review_service, "config_factory", lambda: GeminiConfig(
        api_key="scripted-p1-p2-google-key",
    ))
    try:
        yield {"database": database, "stores": stores, "providers": providers, "durable": durable}
    finally:
        if durable:
            client.drop_database(database.name)
        client.close()


def prepare(api):
    ingested = api.post("/api/telemetry", json=telemetry())
    assert ingested.status_code == 200, ingested.text
    assert ingested.json()["should_alert"] and ingested.headers["x-factoryos-persistence"] == "persisted"
    assert ingested.json()["legacy_monitor"]["source_revision"] == source_hash(LEGACY_MONITOR_PATH)
    incident_id = ingested.json()["incident_id"]
    path = f"/api/incidents/{incident_id}"
    queued = api.post(path + "/investigate")
    assert queued.status_code == 202, queued.text
    investigation = approval_helpers.poll(api, queued.json()["links"]["job"])
    assert investigation["result"]["generated_repair"]["verification_status"] == "VERIFIED"
    queued = api.post(path + "/review", headers={"Idempotency-Key": "integrated-review"})
    assert queued.status_code == 202, queued.text
    review = approval_helpers.poll(api, queued.json()["links"]["job"])
    view = api.get(path + "/approval", headers=HEADERS)
    assert view.status_code == 200, view.text
    assert view.json()["can_approve"], view.text
    return path, view.json(), investigation, review


def approve(api, path, view, key="integrated-approval"):
    response = api.post(path + "/approval", headers={**HEADERS, "Idempotency-Key": key},
                        json=approval_helpers.decision(view))
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "APPROVED" and not response.json()["deployed"]
    return response.json()


def assert_execution_allowed(incident_id, view):
    return combined.approval_service.require_approved(
        incident_id, view["package_revision"], view["candidate_revision"],
    )


def test_full_telemetry_investigation_review_approval_survives_restart(integrated, monkeypatch):
    database = integrated["database"]
    with TestClient(combined.app) as api:
        assert api.get("/api/agents/capabilities").json()["storage_backend"] == "mongodb"
        # Any accidental use of P2's former incident writer is a regression.
        for repository in (combined.service.repository, combined.investigation_service.repository,
                           combined.review_service.repository):
            for method in ("get_incident_snapshot", "attach_job", "save_approval"):
                monkeypatch.setattr(repository._job_store, method, Mock(side_effect=AssertionError("P1 writer bypassed")))
        path, view, investigation, review = prepare(api)
        incident_id = path.rsplit("/", 1)[-1]
        result = approve(api, path, view)
        assert assert_execution_allowed(incident_id, view)["decision"]["decision_id"] == result["recorded_decision"]["decision_id"]
        current = api.get(path).json()
        assert current["status"] == "OPEN" and current["hardware"]["cooling_fault"]
        assert current["investigation"]["job_id"] == investigation["job_id"]
        assert current["decision_review"]["job_id"] == review["job_id"]
        assert main.get_incident_snapshot(incident_id)["approval_persistence"] == {"status": "PERSISTED", "version": 1}
        stored = database.incidents.find_one({"_id": incident_id}, {"_id": 0})
        assert stored == current and "approval_persistence" not in stored
        history = api.get(path + "/history").json()
        kinds = [entry["kind"] for entry in history["events"]]
        assert {"telemetry", "investigation_queued", "investigation_running", "investigation_completed",
                "decision_review_queued", "decision_review_running", "decision_review_completed", "human_approval"} <= set(kinds)
        assert history["events"][-1]["snapshot"]["approval"]["version"] == 1
        assert database.incident_events.count_documents({"incident_id": incident_id}) == history["total"]
        assert database.investigation_jobs.count_documents({}) == database.review_jobs.count_documents({}) == 1
        assert database.repair_jobs.count_documents({}) == 0
        assert all(provider.closed for provider in integrated["providers"])
    _clear_process_state(monkeypatch)
    with TestClient(combined.app) as api:
        assert api.get(path).json() == current
        assert api.get(path + "/history").json() == history
        assert api.get(investigation["links"]["job"]).json()["status"] == "COMPLETED"
        assert api.get(review["links"]["job"]).json()["status"] == "COMPLETED"
        assert api.get(path + "/approval", headers=HEADERS).json()["status"] == "APPROVED"
        assert_execution_allowed(incident_id, view)
        retried = api.post(path + "/investigate")
        assert retried.status_code == 200 and retried.json()["reused"]
        assert retried.json()["job_id"] == investigation["job_id"]
        assert len(integrated["providers"]) == 1


def test_metadata_and_equivalent_fresh_telemetry_preserve_review_but_health_change_invalidates(integrated):
    database = integrated["database"]
    with TestClient(combined.app) as api:
        path, view, investigation, review = prepare(api)
        incident_id = path.rsplit("/", 1)[-1]
        approve(api, path, view)
        metadata = api.post(path + "/updates", json={
            "event_id": "p3-jira-link", "integrations": {"jira_key": "FACTORY-42"},
            "note": "Frontend linked the incident to the team ticket.",
        })
        assert metadata.status_code == 200, metadata.text
        fresh = api.post("/api/telemetry", json=telemetry(2, temperature=30.1, humidity=57))
        assert fresh.status_code == 200 and fresh.json()["incident_id"] == incident_id
        approval = api.get(path + "/approval", headers=HEADERS).json()
        assert approval["status"] == "APPROVED" and approval["package_revision"] == view["package_revision"], approval
        assert api.get(review["links"]["job"]).json()["current"]
        assert_execution_allowed(incident_id, view)
        repeated = api.post(path + "/investigate")
        assert repeated.status_code == 200 and repeated.json()["job_id"] == investigation["job_id"]
        # The canonical writer must retain P2 evidence and P3 links as telemetry advances.
        snapshot = database.incidents.find_one({"_id": incident_id})
        assert snapshot["hardware"]["sequence"] == 2 and snapshot["integrations"]["jira_key"] == "FACTORY-42"
        assert snapshot["approval"]["version"] == 1 and snapshot["investigation"]["job_id"] == investigation["job_id"]
        assert database.reliability_evidence.count_documents({}) == 2
        healthy = api.post("/api/telemetry", json=telemetry(3, fault=False))
        assert healthy.status_code == 200 and not healthy.json()["should_alert"]
        assert healthy.json()["incident_id"] == incident_id
        assert api.get(path + "/approval", headers=HEADERS).json()["status"] == "STALE"
        assert not api.get(review["links"]["job"]).json()["current"]
        with pytest.raises(ApprovalConflict):
            assert_execution_allowed(incident_id, view)
        # A fault returning after an intervening recovery requires new evidence.
        assert api.post("/api/telemetry", json=telemetry(4)).status_code == 200
        assert api.get(path + "/approval", headers=HEADERS).json()["status"] == "STALE"


def test_failed_approval_write_blocks_execution_and_retry_recovers_without_duplicate(integrated, monkeypatch):
    database = integrated["database"]
    with TestClient(combined.app) as api:
        path, view, investigation, review = prepare(api)
        incident_id = path.rsplit("/", 1)[-1]
        body = approval_helpers.decision(view)
        headers = {**HEADERS, "Idempotency-Key": "recover-approval"}
        with monkeypatch.context() as outage:
            outage.setattr(main._store.incidents, "update_one", Mock(side_effect=ConnectionFailure("scripted-only-outage")))
            failed = api.post(path + "/approval", headers=headers, json=body)
            assert failed.status_code == 503, failed.text
            pending = main.get_incident_snapshot(incident_id)
            assert pending["approval_persistence"] == {"status": "PENDING", "version": 1}
            assert database.incidents.find_one({"_id": incident_id}).get("approval") is None
            assert database.incident_events.count_documents({"kind": "human_approval"}) == 1
            blocked = api.get(path + "/approval", headers=HEADERS).json()
            assert blocked["status"] != "APPROVED" and not blocked["can_approve"], blocked
            with pytest.raises(ApprovalConflict):
                assert_execution_allowed(incident_id, view)
            retry = api.post(path + "/approval", headers=headers, json=body)
            assert retry.status_code in (200, 503)
            if retry.status_code == 200:
                assert retry.json()["reused"] and retry.json()["status"] != "APPROVED"
            assert len(main._incidents[incident_id]["approval"]["decisions"]) == 1
            # Further P1/P3 changes must preserve the pending human decision.
            update = api.post(path + "/updates", json={"event_id": "p3-during-outage", "integrations": {"jira_key": "FACTORY-PENDING"}})
            assert update.status_code == 200 and update.headers["x-factoryos-persistence"] == "pending"
        assert main._flush_persistence()
        recovered = api.post(path + "/approval", headers=headers, json=body)
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["reused"] and recovered.json()["status"] == "APPROVED"
        assert recovered.json()["recorded_decision"]["decision_id"] == pending["approval"]["decisions"][0]["decision_id"]
        assert_execution_allowed(incident_id, view)
        snapshot = database.incidents.find_one({"_id": incident_id})
        assert snapshot["integrations"]["jira_key"] == "FACTORY-PENDING"
        assert snapshot["approval"]["version"] == len(snapshot["approval"]["decisions"]) == 1
        assert database.incident_events.count_documents({"kind": "human_approval"}) == 1
        assert api.get("/api/storage/health").json()["status"] == "OK"


def test_acknowledged_approval_event_recovers_after_snapshot_loss_and_restart(integrated, monkeypatch):
    database = integrated["database"]
    with TestClient(combined.app) as api:
        path, view, investigation, review = prepare(api)
        incident_id = path.rsplit("/", 1)[-1]
        with monkeypatch.context() as outage:
            outage.setattr(main._store.incidents, "update_one", Mock(side_effect=ConnectionFailure()))
            response = api.post(path + "/approval", headers={**HEADERS, "Idempotency-Key": "crash-approval"},
                                json=approval_helpers.decision(view))
            assert response.status_code == 503, response.text
            event = database.incident_events.find_one({"kind": "human_approval"})
            assert event["snapshot"]["approval"]["version"] == 1
            assert database.incidents.find_one({"_id": incident_id}).get("approval") is None
            # Simulate losing unacknowledged process-local work, keeping the
            # lifecycle event already committed before the failed snapshot.
            main._store._pending_incidents.clear()
    _clear_process_state(monkeypatch)
    with TestClient(combined.app) as api:
        view_after = api.get(path + "/approval", headers=HEADERS).json()
        assert view_after["status"] == "APPROVED" and view_after["version"] == 1, view_after
        assert_execution_allowed(incident_id, view)
        assert main.get_incident_snapshot(incident_id)["approval_persistence"] == {"status": "PERSISTED", "version": 1}
        assert database.incidents.find_one({"_id": incident_id})["approval"]["version"] == 1
        assert database.incident_events.count_documents({"kind": "human_approval"}) == 1
        retry = api.post(path + "/approval", headers={**HEADERS, "Idempotency-Key": "crash-approval"},
                         json=approval_helpers.decision(view))
        assert retry.status_code == 200 and retry.json()["reused"]
        assert len(integrated["providers"]) == 1


def test_real_mongo_and_docker_verified_candidate_passes_shared_approval_gate(integrated, request, monkeypatch):
    if not integrated["durable"] or not request.config.getoption("--run-docker-tests"):
        pytest.skip("Enable combined local MongoDB/Docker proof with both integration flags")
    from backend.modernization.pipeline import execute_incident_repair
    monkeypatch.setattr(tools_module, "execute_incident_repair", execute_incident_repair)
    with TestClient(combined.app) as api:
        path, view, investigation, review = prepare(api)
        proof = investigation["result"]["generated_repair"]
        assert proof["tests"]["original"]["failed"] > 0
        assert proof["tests"]["candidate"]["failed"] == 0
        assert proof["replay"]["detection_gap_fixed"] and proof["replay"]["cooling_fault_still_present"]
        assert proof["tests"]["candidate"]["stdout"] != "SCRIPTED UNIT VERIFIER"
        approved = approve(api, path, view)
        incident_id = path.rsplit("/", 1)[-1]
        assert_execution_allowed(incident_id, view)
        stored = integrated["database"].incidents.find_one({"_id": incident_id})
        assert stored["approval"]["decisions"][0]["decision_id"] == approved["recorded_decision"]["decision_id"]
        assert stored["decision_review"]["job_id"] == review["job_id"]
