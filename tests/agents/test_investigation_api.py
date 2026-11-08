import time

from fastapi.testclient import TestClient
import pytest

from backend.agents.nemotron import NemotronError
from backend.modernization.repository import content_revision


def await_investigation(client, job_id, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get("/api/investigations/" + job_id)
        assert response.status_code == 200, response.text
        job = response.json()
        if job["status"] not in ("QUEUED", "RUNNING"):
            return job
        time.sleep(0.01)
    pytest.fail("Investigation did not complete before its test deadline")


def test_real_functions_and_grounded_results_with_scripted_provider(agent_system):
    app, base, service, clients = agent_system()
    with TestClient(app) as client:
        queued = client.post("/api/incidents/INC-AGENT-TEST/investigate", headers={"Idempotency-Key": "once"})
        assert queued.status_code == 202
        job = await_investigation(client, queued.json()["job_id"])
        assert job["status"] == "COMPLETED", job
        assert len(job["tool_calls"]) == 3
        assert all(call["status"] == "SUCCESS" for call in job["tool_calls"])
        assert all(call["duration_ms"] >= 0 for call in job["tool_calls"])
        assert len(job["evidence"]) == 3 and len(job["provider_calls"]) == 2
        assert job["snapshot_revision"] == content_revision(job["snapshot"])
        assert "investigation" not in job["snapshot"]  # No recursive snapshots of previous traces.
        assert "unit-test-secret" not in str(job)
        analysis = client.get("/api/incidents/INC-AGENT-TEST/analysis").json()
        assert analysis["investigation"]["status"] == "COMPLETED"
        assert analysis["investigation"]["findings"]
        assert analysis["repair"] is None and analysis["decision_review"]["status"] == "PENDING"
        repeated = client.post("/api/incidents/INC-AGENT-TEST/investigate", headers={"Idempotency-Key": "once"})
        assert repeated.status_code == 200 and repeated.json()["reused"]
        assert len(clients) == 1
        assert base.jobs == {}  # Investigation jobs are not repair jobs.
        assert client.get(job["links"]["patch"]).status_code == 409
    assert clients[0].closed


def test_polling_requires_job_id_from_the_same_backend(agent_system):
    app, *_ = agent_system()
    with TestClient(app) as client:
        response = client.post("/api/incidents/INC-AGENT-TEST/investigate")
        job = await_investigation(client, response.json()["job_id"])
        wrong = client.get("/api/investigations/INC-AGENT-TEST")
        assert wrong.status_code == 404
        assert "not the incident_id" in wrong.json()["detail"]
        assert client.get(job["links"]["job"]).json()["job_id"] == job["job_id"]
        schema = client.get("/openapi.json").json()
        assert "202" in schema["paths"]["/api/incidents/{incident_id}/investigate"]["post"]["responses"]
    separate_app, *_ = agent_system()
    with TestClient(separate_app) as separate:
        missing = separate.get(job["links"]["job"])
        assert missing.status_code == 404
        assert "separate process" in missing.json()["detail"]


@pytest.mark.parametrize("mode", ["invented_evidence", "wrong_line", "source_without_code_evidence", "bad_json", "loop", "unsafe", "extra_argument"])
def test_invalid_or_ungrounded_outputs_never_complete(agent_system, mode):
    app, base, service, clients = agent_system(mode)
    with TestClient(app) as client:
        response = client.post("/api/incidents/INC-AGENT-TEST/investigate")
        job = await_investigation(client, response.json()["job_id"])
        assert job["status"] == "FAILED" and job["result"] is None
        assert job["error"]["code"] in {"INVESTIGATION_LIMIT", "TOOL_LIMIT"}
        assert client.get("/api/incidents/INC-AGENT-TEST/analysis").json()["investigation"]["findings"] == []
        if mode in {"unsafe", "extra_argument"}:
            assert all(call["status"] == "FAILED" for call in job["tool_calls"])
            assert job["evidence"] == []


@pytest.mark.parametrize("mode,code", [("auth", "PROVIDER_AUTHENTICATION"), ("duplicate", "INVALID_TOOL_CALL")])
def test_provider_and_protocol_errors_are_explicit(agent_system, mode, code):
    app, *_ = agent_system(mode)
    with TestClient(app) as client:
        job_id = client.post("/api/incidents/INC-AGENT-TEST/investigate").json()["job_id"]
        job = await_investigation(client, job_id)
        assert job["status"] == "FAILED" and job["error"]["code"] == code
        assert "unit-test-secret" not in str(job)
        if mode == "auth":
            assert job["tool_calls"] == []
            assert job["provider_calls"][0]["status"] == "FAILED"


def test_missing_credentials_reject_before_queueing(agent_system):
    def missing():
        raise NemotronError("NOT_CONFIGURED", "Configure NVIDIA_API_KEY")
    app, base, service, clients = agent_system(config_factory=missing)
    with TestClient(app) as client:
        assert not client.get("/api/agents/capabilities").json()["configured"]
        response = client.post("/api/incidents/INC-AGENT-TEST/investigate")
        assert response.status_code == 503
        assert service.repository.jobs == {} and clients == []
        assert client.post("/api/incidents/missing/investigate").status_code == 404


def test_known_secret_is_removed_from_final_model_text(agent_system):
    app, *_ = agent_system("leak")
    with TestClient(app) as client:
        job_id = client.post("/api/incidents/INC-AGENT-TEST/investigate").json()["job_id"]
        job = await_investigation(client, job_id)
        assert job["status"] == "COMPLETED"
        assert "unit-test-secret" not in str(job)
        assert "[REDACTED]" in job["result"]["summary"]
