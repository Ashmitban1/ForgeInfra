from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend import system_metrics
from backend.reliability import analyze_reliability


client = TestClient(app)


@pytest.fixture
def collector(monkeypatch):
    fake = SimpleNamespace(
        cpu_percent=Mock(return_value=25.0),
        virtual_memory=Mock(return_value=SimpleNamespace(
            total=1000, available=600, used=400, percent=40.0,
        )),
        Error=PermissionError,
    )
    monkeypatch.setattr(system_metrics, "psutil", fake)
    monkeypatch.setattr(system_metrics.socket, "gethostname", lambda: "test-backend")
    return fake


def test_metrics_success_has_identity_units_and_current_timestamps(collector):
    before = datetime.now(timezone.utc)
    response = client.get("/api/system/metrics")
    after = datetime.now(timezone.utc)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["status"] == "OK"
    assert body["errors"] == []
    assert body["source"] == {
        "kind": "host_system", "host_id": "test-backend", "collector": "psutil",
        "scope": "backend_host", "is_simulated": False,
    }
    assert before <= datetime.fromisoformat(body["sample_started_at"]) <= after
    assert datetime.fromisoformat(body["sample_started_at"]) <= datetime.fromisoformat(body["observed_at"]) <= after
    assert body["cpu"] == {"utilization_pct": 25.0, "sample_interval_seconds": 0.1}
    assert body["memory"] == {
        "total_bytes": 1000, "available_bytes": 600,
        "used_bytes": 400, "utilization_pct": 40.0,
    }
    collector.cpu_percent.assert_called_once_with(interval=0.1)


@pytest.mark.parametrize("failed", ["cpu", "memory"])
def test_partial_failure_retains_other_metric_and_hides_error_details(collector, failed):
    reader = collector.cpu_percent if failed == "cpu" else collector.virtual_memory
    reader.side_effect = OSError("sensitive local diagnostic")
    response = client.get("/api/system/metrics")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "DEGRADED"
    assert body[failed] is None
    assert body["memory" if failed == "cpu" else "cpu"] is not None
    assert body["errors"] == [{"metric": failed, "code": "collection_failed"}]
    assert "sensitive" not in response.text


def test_total_failure_returns_503_without_affecting_telemetry(collector):
    collector.cpu_percent.side_effect = PermissionError("denied")
    collector.virtual_memory.side_effect = RuntimeError("unavailable")
    response = client.get("/api/system/metrics")
    assert response.status_code == 503
    assert response.json()["status"] == "UNAVAILABLE"
    assert response.json()["cpu"] is None
    assert response.json()["memory"] is None
    assert client.get("/health").status_code == 200
    event = {
        "device_id": "TEST-METRICS-ISOLATION", "source_kind": "simulator",
        "observed_at": datetime.now(timezone.utc).isoformat(), "sequence": 1,
        "temperature_c": 29.4, "humidity_pct": 54, "cooling_fault": True,
    }
    fault = client.post("/api/telemetry", json=event)
    assert fault.status_code == 200
    assert fault.json()["should_alert"] is True
    assert fault.json()["reliability"]["reasons"] == ["legacy_missed_fault"]


def test_missing_dependency_returns_structured_unavailable(monkeypatch):
    monkeypatch.setattr(system_metrics, "psutil", None)
    response = client.get("/api/system/metrics")
    assert response.status_code == 503
    assert response.json()["errors"] == [
        {"metric": "collector", "code": "dependency_unavailable"},
    ]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 101])
def test_invalid_cpu_percentage_is_not_serialized_as_healthy(collector, value):
    collector.cpu_percent.return_value = value
    response = client.get("/api/system/metrics")
    assert response.status_code == 200
    assert response.json()["status"] == "DEGRADED"
    assert response.json()["cpu"] is None


def test_invalid_memory_counters_are_not_reported_as_healthy(collector):
    collector.virtual_memory.return_value = SimpleNamespace(
        total=1000, available=1001, used=400, percent=40.0,
    )
    response = client.get("/api/system/metrics")
    assert response.json()["status"] == "DEGRADED"
    assert response.json()["memory"] is None


def test_fresh_fault_is_partial_because_it_has_a_mismatch_reason():
    now = datetime.now(timezone.utc)
    fault = analyze_reliability(29.4, True, now, now)
    assert fault["observation_age_seconds"] == 0
    assert fault["reasons"] == ["legacy_missed_fault"]
    assert fault["evidence_quality"] == "PARTIAL"
    assert analyze_reliability(29.4, False, now, now)["evidence_quality"] == "CURRENT"
