from copy import deepcopy
import time

from fastapi.testclient import TestClient

from backend.modernization.mongo_repository import MongoIncidentRepository


def poll(client, job_id, timeout=40):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get("/api/investigations/" + job_id).json()
        if job["status"] not in ("QUEUED", "RUNNING"):
            return job
        time.sleep(0.02)
    raise AssertionError("Investigation integration test timed out")


def test_scripted_model_assignment_gets_real_docker_verification(agent_system, agent_docker_image):
    app, base, service, clients = agent_system("patch")
    with TestClient(app) as client:
        job_id = client.post("/api/incidents/INC-AGENT-TEST/investigate").json()["job_id"]
        job = poll(client, job_id)
        assert job["status"] == "COMPLETED", job
        generated = job["result"]["generated_repair"]
        assert generated["proposal_origin"] == "nemotron_generated_patch"
        assert generated["verification_status"] == "VERIFIED"
        assert generated["tests"]["original"]["exit_code"] == 1
        assert generated["tests"]["candidate"]["passed"] == 5
        assert generated["replay"]["candidate"]["status"] == "WARNING"
        assert generated["approval_status"] == "PENDING" and not generated["deployed"]
        assert 'event.get("cooling_fault", False)' in client.get(job["links"]["patch"]).text
        assert base.jobs == {}  # No implicit manual repair submission.


def test_investigation_records_persist_in_separate_mongo_collection(
    agent_system, agent_snapshot, agent_mongo_database,
):
    database = agent_mongo_database
    database.incidents.insert_one(deepcopy(agent_snapshot))
    repository = MongoIncidentRepository(database.incidents, database.repair_jobs)
    app, base, service, clients = agent_system(repository=repository)
    with TestClient(app) as client:
        response = client.post("/api/incidents/INC-AGENT-TEST/investigate", headers={"Idempotency-Key": "persist"})
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        job = poll(client, job_id)
        assert job["status"] == "COMPLETED"
        assert database.repair_jobs.count_documents({}) == 0
        assert database.investigation_jobs.count_documents({}) == 1
        assert database.incidents.find_one({})["investigation"]["status"] == "COMPLETED"
        assert database.incidents.find_one({})["decision_review"]["status"] == "PENDING"
    recreated = MongoIncidentRepository(database.incidents, database.repair_jobs)
    second, *_ = agent_system(repository=recreated)
    with TestClient(second) as client:
        assert client.get("/api/investigations/" + job_id).json()["result"]["findings"]
        response = client.post("/api/incidents/INC-AGENT-TEST/investigate", headers={"Idempotency-Key": "persist"})
        assert response.status_code == 200 and response.json()["reused"]


def test_investigation_recovery_never_interrupts_repair_jobs(agent_mongo_database):
    database = agent_mongo_database
    base = MongoIncidentRepository(database.incidents, database.repair_jobs)
    database.repair_jobs.insert_one({"job_id": "repair-only", "incident_identity": "identity",
                                   "request_key": "repair-key", "status": "RUNNING", "active": True})
    investigations = base.for_investigations()
    assert investigations.interrupt_incomplete() == []
    assert database.repair_jobs.find_one({"job_id": "repair-only"})["status"] == "RUNNING"
