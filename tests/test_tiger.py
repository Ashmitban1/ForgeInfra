from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, Mock

from fastapi.testclient import TestClient
import psycopg
import pytest

from backend import main, system_metrics
from backend.storage.mongo import StorageUnavailable
from backend.storage.tiger import TigerTelemetryStore


def receipt(sequence=1, source="arduino_serial"):
    return {"schema_version": "1.0", "device_id": "TEST-TIGER", "hardware": {
        "source_kind": source, "sequence": sequence, "observed_at": "2026-11-07T22:00:00Z",
        "received_at": "2026-11-07T22:00:01Z", "temperature_c": 29.4,
        "humidity_pct": 54, "cooling_fault": True, "fault_is_simulated": True,
    }}


def metrics():
    return {"schema_version": "1.0", "source": {"host_id": "TEST-HOST", "is_simulated": False},
            "observed_at": "2026-11-07T22:00:00Z", "status": "OK", "errors": [],
            "cpu": {"utilization_pct": 12.5}, "memory": {"utilization_pct": 40.0,
            "total_bytes": 1000, "available_bytes": 600, "used_bytes": 400}}


@pytest.fixture
def store(monkeypatch):
    instance = TigerTelemetryStore("postgresql://test:secret@localhost/test?sslmode=require")
    connection = MagicMock()
    connection.__enter__.return_value = connection
    monkeypatch.setattr(instance, "_connect", lambda: connection)
    return instance, connection


def test_initialize_requires_actual_timescale_extension_and_hypertable(store):
    instance, connection = store
    instance.initialize()
    statements = [call.args[0] for call in connection.execute.call_args_list]
    assert "pg_extension" in statements[0]
    assert "PRIMARY KEY (observed_at, event_id)" in statements[2].as_string()
    assert "create_hypertable" in statements[3]
    connection.execute.return_value.fetchone.return_value = None
    with pytest.raises(StorageUnavailable, match="TimescaleDB extension"):
        instance.initialize()


def test_queue_deduplicates_and_retains_source_and_simulation_labels(store):
    instance, connection = store
    first = receipt()
    instance.queue_arduino(first)
    instance.queue_arduino(first)
    instance.queue_arduino(receipt(source="simulator"))
    instance.queue_host(metrics())
    assert instance.health()["pending_samples"] == 3
    first["hardware"]["temperature_c"] = 99
    rows = list(instance._pending.values())
    assert rows[0]["temperature_c"] == 29.4
    assert rows[0]["fault_is_simulated"] is True
    assert rows[2]["source_kind"] == "host_system"
    assert rows[2]["source_id"] == "TEST-HOST"
    assert rows[2]["cpu_utilization_pct"] == 12.5
    assert instance.flush()
    statement = connection.execute.call_args.args[0]
    assert "ON CONFLICT (observed_at, event_id) DO NOTHING" in statement.as_string()
    assert instance.health()["status"] == "OK"


def test_write_outage_and_ambiguous_commit_retain_queue_without_secret_leak(store):
    instance, connection = store
    instance.queue_arduino(receipt())
    connection.__exit__.side_effect = psycopg.OperationalError("private connection credentials")
    assert instance.flush() is False
    assert instance.health()["pending_samples"] == 1
    assert instance.health()["error"] == "tigerdata_unavailable"
    assert "private" not in str(instance.health())
    connection.__exit__.side_effect = None
    assert instance.flush()
    assert instance.health()["pending_samples"] == 0


def test_query_filters_are_parameterized_and_history_is_chronological(store):
    instance, connection = store
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=1)
    malicious_id = "rack'; DROP TABLE telemetry; --"
    connection.execute.return_value.fetchall.return_value = [{"sequence": 2}, {"sequence": 1}]
    assert instance.history("arduino_serial", malicious_id, start, end, 10) == [{"sequence": 1}, {"sequence": 2}]
    statement, params = connection.execute.call_args.args
    assert malicious_id not in statement.as_string()
    assert params == ("arduino_serial", malicious_id, start, end, 10)
    instance.summary("host_system", "TEST-HOST", start, end, 300)
    statement, params = connection.execute.call_args.args
    assert "time_bucket" in statement.as_string()
    assert "avg(cpu_utilization_pct)" in statement.as_string()
    assert params == (timedelta(seconds=300), "host_system", "TEST-HOST", start, end)


@pytest.mark.parametrize("schema", ["bad;drop", "UPPER", "schema.name", ""])
def test_schema_injection_is_rejected(schema):
    with pytest.raises(StorageUnavailable):
        TigerTelemetryStore("postgresql://localhost/test", schema)


def test_plaintext_configuration_is_rejected():
    with pytest.raises(StorageUnavailable, match="TLS"):
        TigerTelemetryStore("postgresql://localhost/test?sslmode=disable")


def test_unavailable_history_returns_safe_503(store):
    instance, connection = store
    connection.execute.side_effect = psycopg.OperationalError("secret")
    with pytest.raises(StorageUnavailable, match="history unavailable") as exc:
        instance.history("host_system", "HOST", datetime.now(timezone.utc), datetime.now(timezone.utc), 10)
    assert "secret" not in str(exc.value)


def test_history_api_validates_windows_sources_limits_and_storage(monkeypatch):
    monkeypatch.setitem(main.app.state._state, "telemetry_store", None)
    api = TestClient(main.app)
    base = "/api/telemetry/history?source_kind=arduino_serial&source_id=RACK-01"
    assert api.get(base).status_code == 503
    assert api.get(base + "&limit=1001").status_code == 422
    assert api.get(base + "&start=2026-11-01T00:00:00&end=2026-11-02T00:00:00").status_code == 422
    assert api.get(base + "&start=2026-10-01T00:00:00Z&end=2026-11-02T00:00:00Z").status_code == 422
    assert api.get(base + "&start=2026-11-02T00:00:00Z&end=2026-11-01T00:00:00Z").status_code == 422
    assert api.get("/api/telemetry/history?source_kind=invalid&source_id=RACK-01").status_code == 422
    assert api.get("/api/telemetry/summary?source_kind=host_system&source_id=HOST&bucket_seconds=1").status_code == 422
    fake = Mock()
    fake.history.return_value = [{"event_id": "one", "payload": receipt()}]
    fake.summary.return_value = [{"bucket_start": "2026-11-07T22:00:00Z", "sample_count": 2}]
    main.app.state.telemetry_store = fake
    assert api.get(base).json()["samples"][0]["event_id"] == "one"
    assert fake.history.call_args.args[:2] == ("arduino_serial", "RACK-01")
    assert api.get("/api/telemetry/summary?source_kind=host_system&source_id=HOST&bucket_seconds=60").json()["buckets"][0]["sample_count"] == 2
    fake.history.side_effect = StorageUnavailable("safe failure")
    assert api.get(base).status_code == 503


def test_accepted_telemetry_and_host_endpoint_are_forwarded_without_schema_changes(monkeypatch):
    fake = Mock()
    fake.health.return_value = {"status": "OK"}
    monkeypatch.setitem(main.app.state._state, "telemetry_store", fake)
    monkeypatch.setattr(main, "_incidents", {})
    monkeypatch.setattr(main, "_latest_sequence", {})
    monkeypatch.setattr(main, "_store", None)
    monkeypatch.setattr(system_metrics, "collect_system_metrics", metrics)
    api = TestClient(main.app)
    response = api.post("/api/telemetry", json={
        "device_id": "TEST-TIGER-API", "source_kind": "arduino_serial", "sequence": 1,
        "observed_at": datetime.now(timezone.utc).isoformat(), "temperature_c": 29.4,
        "humidity_pct": 54, "cooling_fault": True, "fault_is_simulated": True,
    })
    assert response.status_code == 200
    assert response.json()["should_alert"] is True
    assert response.json()["reliability"]["mismatch"] is True
    fake.queue_arduino.assert_called_once_with(response.json())
    assert response.headers["x-factoryos-telemetry-persistence"] == "persisted"
    assert api.get("/api/system/metrics").json() == metrics()
    fake.queue_host.assert_called_once_with(metrics())


def test_periodic_host_sampling_does_not_require_dashboard_requests(monkeypatch):
    fake = Mock()
    stop = Mock()
    stop.is_set.return_value = False
    stop.wait.return_value = True
    monkeypatch.setattr(main, "collect_system_metrics", metrics)
    main._sample_host_telemetry(stop, fake)
    fake.queue_host.assert_called_once_with(metrics())
    fake.flush.assert_called_once()


def test_partial_host_samples_keep_unavailable_measurements_null(store):
    instance, _ = store
    sample = metrics()
    sample["status"] = "DEGRADED"
    sample["cpu"] = None
    instance.queue_host(sample)
    row = next(iter(instance._pending.values()))
    assert row["cpu_utilization_pct"] is None
    assert row["memory_utilization_pct"] == 40.0
    assert row["status"] == "DEGRADED"


def test_runtime_tiger_outage_does_not_suppress_fault_response(monkeypatch):
    fake = Mock()
    fake.flush.return_value = False
    fake.health.return_value = {"status": "DEGRADED"}
    monkeypatch.setitem(main.app.state._state, "telemetry_store", fake)
    monkeypatch.setattr(main, "_incidents", {})
    monkeypatch.setattr(main, "_latest_sequence", {})
    monkeypatch.setattr(main, "_store", None)
    response = TestClient(main.app).post("/api/telemetry", json={
        "device_id": "TEST-TIGER-OUTAGE", "source_kind": "arduino_serial", "sequence": 1,
        "observed_at": datetime.now(timezone.utc).isoformat(), "temperature_c": 29.4,
        "humidity_pct": 54, "cooling_fault": True,
    })
    assert response.status_code == 200
    assert response.json()["should_alert"] is True
    assert response.headers["x-factoryos-telemetry-persistence"] == "pending"


def test_configured_tiger_initialization_failure_is_explicit_and_closes_mongo(monkeypatch):
    fake_mongo, fake_tiger = Mock(), Mock()
    fake_mongo.health.return_value = {"pending_incidents": 0, "pending_evidence": 0, "pending_events": 0}
    fake_tiger.health.return_value = {"pending_samples": 0}
    fake_tiger.initialize.side_effect = StorageUnavailable("Tiger Data initialization unavailable")
    monkeypatch.setattr(main, "store_from_environment", lambda: fake_mongo)
    monkeypatch.setattr(main, "tiger_from_environment", lambda: fake_tiger)
    with pytest.raises(StorageUnavailable, match="initialization unavailable"):
        with TestClient(main.app):
            pytest.fail("Configured database must not silently become mock storage")
    fake_mongo.close.assert_called_once()
