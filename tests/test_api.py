from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from backend.main import app
from backend.reliability import analyze_reliability

client = TestClient(app)


def event(device, seq, fault):
    return {
        "schema_version": "1.0", "device_id": device,
        "source_kind": "simulator", "observed_at": datetime.now(timezone.utc).isoformat(),
        "sequence": seq, "temperature_c": 29.4,
        "humidity_pct": 54, "cooling_fault": fault,
        "fault_is_simulated": True,
    }


def test_healthy_reading():
    r = client.post("/api/telemetry", json=event("TEST-HEALTHY", 1, False))
    assert r.status_code == 200
    assert r.json()["reliability"]["mismatch"] is False
    assert r.json()["should_alert"] is False


def test_fault_creates_incident():
    r = client.post("/api/telemetry", json=event("TEST-FAULT", 1, True))
    assert r.status_code == 200
    body = r.json()
    assert body["should_alert"] is True
    assert body["reliability"]["mismatch"] is True
    assert "legacy_missed_fault" in body["reliability"]["reasons"]
    inc = client.get("/api/incidents/" + body["incident_id"])
    assert inc.status_code == 200
    assert inc.json()["integrations"]["jira_key"] is None


def test_duplicate_sequence_rejected():
    sample = event("TEST-DUPLICATE", 1, False)
    assert client.post("/api/telemetry", json=sample).status_code == 200
    assert client.post("/api/telemetry", json=sample).status_code == 409


def test_stale_input_is_not_fresh_operational_alert():
    sample = event("TEST-STALE", 1, True)
    sample["observed_at"] = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    r = client.post("/api/telemetry", json=sample)
    assert r.status_code == 200
    assert r.json()["should_alert"] is False
    assert "stale_hardware_reading" in r.json()["reliability"]["reasons"]
