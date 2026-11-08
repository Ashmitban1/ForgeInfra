"""Scripted provider responses are test-only; production never simulates NVIDIA."""

from datetime import datetime, timezone
import json
import os
from threading import Lock

from fastapi import FastAPI
from openai.types.chat import ChatCompletion
import pytest
from pymongo import MongoClient

from backend.agents.nemotron import MODEL, NemotronConfig, NemotronError
from backend.agents.router import create_investigation_router
from backend.agents.service import InvestigationService
from backend.modernization.repository import MemoryIncidentRepository
from backend.modernization.router import create_modernization_router
from backend.modernization.service import RepairService


class ScriptedClient:
    def __init__(self, config, mode="normal"):
        self.config, self.mode, self.round = config, mode, 0
        self.closed = False
        self.messages_seen = []

    def complete(self, messages, schemas, remaining_seconds):
        self.round += 1
        self.messages_seen.append(json.dumps(messages))
        if self.mode == "auth":
            raise NemotronError("PROVIDER_AUTHENTICATION", "NVIDIA rejected the request")
        calls = []
        content = None
        outputs = [json.loads(item["content"]) for item in messages if item["role"] == "tool"]
        source = next((item for item in outputs if "lines" in item.get("data", {})), None)
        if self.mode == "unsafe":
            calls = [("run_shell", {"command": "touch /tmp/factoryos-must-not-run"})]
        elif self.mode == "extra_argument":
            calls = [("inspect_legacy_code", {"path": "/etc/passwd"})]
        elif self.mode == "loop":
            calls = [("get_incident_snapshot", {})]
        elif self.round == 1:
            calls = [(name, {}) for name in (
                "get_incident_snapshot", "inspect_legacy_code", "read_monitoring_requirements",
            )]
        elif self.mode == "patch" and self.round == 2:
            calls = [("verify_monitor_patch", {
                "source_revision": source["data"]["source_revision"],
                "status_assignment": 'status = "WARNING" if temperature > 35 or event.get("cooling_fault", False) else "NORMAL"',
            })]
        else:
            line = next(item["line"] for item in source["data"]["lines"] if 'status = "WARNING"' in item["text"])
            evidence = [item["evidence_id"] for item in outputs if "evidence_id" in item]
            conclusion = {
                "summary": "The temperature-only monitor ignores an explicit cooling fault.",
                "suspected_cause": "missing_cooling_fault_condition",
                "findings": [{"summary": "The recorded NORMAL result contradicts the fault requirement.",
                              "evidence_ids": evidence[:3], "source_reference": {
                                  "path": "fixtures/legacy_monitor/monitor.py", "line_start": line,
                                  "line_end": line, "source_revision": source["data"]["source_revision"],
                              }}],
                "recommended_actions": ["inspect_equipment", "request_repair_review"],
            }
            if self.mode == "invented_evidence":
                conclusion["findings"][0]["evidence_ids"] = ["fabricated-evidence"]
            if self.mode == "wrong_line":
                conclusion["findings"][0]["source_reference"]["line_end"] = 9999
            if self.mode == "source_without_code_evidence":
                conclusion["findings"][0]["evidence_ids"] = [evidence[0]]
            if self.mode == "leak":
                conclusion["summary"] = "Accidental value: " + self.config.api_key
            content = "invalid JSON" if self.mode == "bad_json" else json.dumps(conclusion)
        tool_calls = [{"id": f"test-call-{self.round}-{index}", "type": "function",
                       "function": {"name": name, "arguments": json.dumps(arguments)}}
                      for index, (name, arguments) in enumerate(calls)]
        if self.mode == "duplicate" and tool_calls:
            tool_calls[1]["id"] = tool_calls[0]["id"]
        return ChatCompletion.model_validate({
            "id": f"test-response-{self.round}", "object": "chat.completion", "created": 0,
            "model": self.config.model,
            "choices": [{"index": 0, "finish_reason": "tool_calls" if calls else "stop",
                         "message": {"role": "assistant", "content": content, "tool_calls": tool_calls}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        })

    def close(self):
        self.closed = True


@pytest.fixture
def agent_snapshot():
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": "1.0", "incident_id": "INC-AGENT-TEST", "device_id": "RACK-AGENT",
        "created_at": now, "updated_at": now, "status": "OPEN", "severity": "HIGH",
        "hardware": {"source_kind": "simulator", "observed_at": now, "received_at": now,
                     "sequence": 1, "temperature_c": 29.4, "humidity_pct": 54,
                     "cooling_fault": True, "fault_is_simulated": True},
        "legacy_monitor": {"status": "NORMAL", "source_revision": "demo-legacy-placeholder-v1"},
        "expected_status": "WARNING", "reliability": {"mismatch": True, "reasons": ["legacy_missed_fault"]},
        "investigation": {"status": "PENDING", "tool_calls": []},
        "decision_review": {"status": "PENDING", "recommendation": None},
    }


@pytest.fixture
def agent_system(tmp_path, agent_snapshot):
    def make(mode="normal", repository=None, config_factory=None):
        records = {agent_snapshot["incident_id"]: agent_snapshot}
        base = repository or MemoryIncidentRepository(records, Lock())
        clients = []

        def create_client(config):
            client = ScriptedClient(config, mode)
            clients.append(client)
            return client

        config_factory = config_factory or (lambda: NemotronConfig(
            api_key="unit-test-secret", model=MODEL, max_rounds=4, max_tool_calls=6,
        ))
        investigation = InvestigationService(
            base.for_investigations(), tmp_path / "investigations", create_client, config_factory,
        )
        repair = RepairService(base, tmp_path / "repairs")
        app = FastAPI()
        app.include_router(create_modernization_router(repair, investigation))
        app.include_router(create_investigation_router(investigation))
        return app, base, investigation, clients
    return make


@pytest.fixture
def scripted_client_type():
    return ScriptedClient


@pytest.fixture
def agent_docker_image(request):
    if not request.config.getoption("--run-docker-tests"):
        pytest.skip("Enable Docker checks with --run-docker-tests")
    from backend.modernization.docker_runner import resolve_image
    return resolve_image()


@pytest.fixture
def agent_mongo_database(request, monkeypatch):
    if not request.config.getoption("--run-mongo-tests"):
        pytest.skip("Enable local MongoDB checks with --run-mongo-tests")
    uri = os.getenv("FACTORYOS_TEST_MONGO_URI", "")
    if not uri.startswith(("mongodb://127.0.0.1:", "mongodb://localhost:")):
        pytest.fail("Use a disposable local FACTORYOS_TEST_MONGO_URI")
    import uuid
    client = MongoClient(uri, serverSelectionTimeoutMS=3000, tz_aware=True)
    client.admin.command("ping")
    name = "factoryos_agent_test_" + uuid.uuid4().hex
    monkeypatch.setenv("MONGODB_INVESTIGATION_JOBS_COLLECTION", "investigation_jobs")
    try:
        yield client[name]
    finally:
        client.drop_database(name)
        client.close()
