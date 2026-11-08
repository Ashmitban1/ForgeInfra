"""Real MongoDB checks in a unique disposable database; never use Atlas test data."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import os
import time
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pymongo import MongoClient
import pytest

from backend.modernization.mongo_repository import MongoIncidentRepository
from backend.modernization.pipeline import execute_incident_repair
from backend.modernization.repository import RepairBusy, incident_identity
from backend.modernization.router import create_modernization_router
from backend.modernization.service import RepairService


def incident():
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": "1.0", "incident_id": "INC-MONGO-TEST", "device_id": "RACK-MONGO",
        "created_at": now, "updated_at": now, "status": "OPEN",
        "hardware": {"source_kind": "simulator", "observed_at": now, "received_at": now,
                     "sequence": 1, "temperature_c": 27.2, "humidity_pct": 50,
                     "cooling_fault": True, "fault_is_simulated": True},
        "legacy_monitor": {"status": "NORMAL", "source_revision": "demo-legacy-placeholder-v1"},
        "expected_status": "WARNING", "reliability": {"reasons": ["legacy_missed_fault"]},
        "investigation": {"status": "PENDING"}, "decision_review": {"status": "PENDING"},
    }


def result():
    return {"repair_id": "repair-mongo-test", "verification_status": "VERIFIED",
            "diff": "--- original\n+++ candidate\n", "approval_status": "PENDING", "deployed": False}


def await_job(client, job_id, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get("/api/repairs/" + job_id)
        assert response.status_code == 200, response.text
        document = response.json()
        if document["status"] not in ("QUEUED", "RUNNING"):
            return document
        time.sleep(0.02)
    pytest.fail("Job did not finish before deadline")


@pytest.fixture
def mongo_database(request):
    if not request.config.getoption("--run-mongo-tests"):
        pytest.skip("Enable real MongoDB checks with --run-mongo-tests")
    uri = os.environ.get("FACTORYOS_TEST_MONGO_URI", "")
    if not uri.startswith(("mongodb://127.0.0.1:", "mongodb://localhost:")):
        pytest.fail("FACTORYOS_TEST_MONGO_URI must point to a disposable local MongoDB")
    client = MongoClient(uri, serverSelectionTimeoutMS=3000, tz_aware=True)
    client.admin.command("ping")
    database_name = "factoryos_test_" + uuid.uuid4().hex
    try:
        yield client[database_name]
    finally:
        client.drop_database(database_name)
        client.close()


def test_mongo_job_and_incident_results_survive_service_recreation(mongo_database, tmp_path):
    source = incident()
    mongo_database.incidents.insert_one(deepcopy(source))
    repository = MongoIncidentRepository(mongo_database.incidents, mongo_database.repair_jobs)
    executions = []

    def pipeline(snapshot, output):
        executions.append(snapshot)
        return result()

    service = RepairService(repository, tmp_path, pipeline)
    app = FastAPI()
    app.include_router(create_modernization_router(service))
    with TestClient(app) as client:
        response = client.post("/api/incidents/INC-MONGO-TEST/repair", headers={"Idempotency-Key": "persist"})
        assert response.status_code == 202 and response.json()["storage_backend"] == "mongodb"
        job_id = response.json()["job_id"]
        completed = await_job(client, job_id)
        assert completed["status"] == "COMPLETED"
        assert completed["result"]["verification_status"] == "VERIFIED"
        assert mongo_database.incidents.find_one({"incident_id": source["incident_id"]})["repair"]["job_id"] == job_id

    recreated = MongoIncidentRepository(mongo_database.incidents, mongo_database.repair_jobs)
    second = FastAPI()
    second.include_router(create_modernization_router(RepairService(recreated, tmp_path, pipeline)))
    with TestClient(second) as client:
        assert client.get("/api/incidents/INC-MONGO-TEST/analysis").json()["repair"]["job_id"] == job_id
        response = client.post("/api/incidents/INC-MONGO-TEST/repair", headers={"Idempotency-Key": "persist"})
        assert response.status_code == 200 and response.json()["reused"]
    assert len(executions) == 1
    assert "_id" not in completed["snapshot"]


def test_mongo_atomic_reservations_and_restart_recovery(mongo_database, tmp_path):
    source = incident()
    mongo_database.incidents.insert_one(deepcopy(source))
    repository = MongoIncidentRepository(mongo_database.incidents, mongo_database.repair_jobs)
    identity = incident_identity(repository.get_incident_snapshot(source["incident_id"]))

    def job(key="same"):
        return {"job_id": "repair-job-" + uuid.uuid4().hex, "incident_id": source["incident_id"],
                "incident_identity": identity, "request_key": key, "snapshot_revision": "test",
                "trace_id": "test", "created_at": source["created_at"], "status": "QUEUED",
                "active": True, "result": None}

    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(lambda _: repository.reserve_job(job()), range(6)))
    assert sum(created for document, created in responses) == 1
    job_id = responses[0][0]["job_id"]
    assert len({document["job_id"] for document, created in responses}) == 1
    with pytest.raises(RepairBusy):
        repository.reserve_job(job("different"))
    service = RepairService(repository, tmp_path, lambda snapshot, output: result())
    service.start()
    try:
        recovered = repository.get_job(job_id)
        assert recovered["status"] == "INTERRUPTED" and not recovered["active"]
        assert repository.reserve_job(job("new-after-restart"))[1]
    finally:
        service.close()


def test_mongo_recycled_incident_cannot_attach_old_job(mongo_database):
    source = incident()
    mongo_database.incidents.insert_one(deepcopy(source))
    repository = MongoIncidentRepository(mongo_database.incidents, mongo_database.repair_jobs)
    old_job = {"job_id": "old-job", "incident_id": source["incident_id"],
               "incident_identity": incident_identity(repository.get_incident_snapshot(source["incident_id"]))}
    mongo_database.incidents.update_one({"incident_id": source["incident_id"]}, {"$set": {"created_at": "new-incarnation"}})
    assert repository.attach_job(old_job) is False
    assert "repair" not in mongo_database.incidents.find_one({"incident_id": source["incident_id"]})


def test_actual_ingested_incident_gets_docker_report_and_snapshot_replay(tmp_path, docker_image):
    from backend import main as core
    from backend.modernization.repository import MemoryIncidentRepository

    app = FastAPI()
    app.post("/api/telemetry")(core.receive_telemetry)
    app.get("/api/incidents/{incident_id}")(core.get_incident)
    repository = MemoryIncidentRepository(core._incidents, core._lock)
    app.include_router(create_modernization_router(RepairService(repository, tmp_path, execute_incident_repair)))
    with TestClient(app) as client:
        source = incident()
        event = {"schema_version": "1.0", "device_id": "DOCKER-API-" + uuid.uuid4().hex[:8],
                 **source["hardware"]}
        received = client.post("/api/telemetry", json=event)
        assert received.status_code == 200, received.text
        incident_id = received.json()["incident_id"]
        queued = client.post(f"/api/incidents/{incident_id}/repair")
        assert queued.status_code == 202, queued.text
        completed = await_job(client, queued.json()["job_id"], timeout=40)
        assert completed["status"] == "COMPLETED", completed
        actual = completed["result"]
        assert actual["verification_status"] == "VERIFIED", actual
        assert actual["tests"]["original"]["exit_code"] == 1
        assert actual["tests"]["candidate"]["passed"] == 5
        assert actual["replay"]["original"]["status"] == "NORMAL"
        assert actual["replay"]["candidate"]["status"] == "WARNING"
        assert actual["replay"]["candidate"]["device_id"] == event["device_id"]
        assert actual["replay"]["cooling_fault_still_present"] is True
        assert actual["replay"]["mode"] == "offline_snapshot_replay"
        assert not actual["deployed"] and actual["approval_status"] == "PENDING"
        assert str(tmp_path) not in str(completed)
        assert 'event.get("cooling_fault", False)' in client.get(completed["links"]["diff"]).text
        assert client.get(f"/api/incidents/{incident_id}").json()["repair"]["verification_status"] == "VERIFIED"
