from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import Mock

import mongomock
import pytest
from fastapi.testclient import TestClient
from pymongo.errors import ConnectionFailure

from backend import main
from backend.storage import mongo
from backend.storage.import_incidents import import_incidents


@pytest.mark.parametrize("method,collection", [("load_incidents", "incidents"), ("load_events", "events")])
def test_restore_keeps_cursor_batches_inside_startup_deadline(method, collection, monkeypatch):
    store = mongo.MongoIncidentStore(mongomock.MongoClient(), "restore")
    active = []

    @contextmanager
    def deadline(seconds):
        assert seconds == 60
        active.append(True)
        try:
            yield
        finally:
            active.pop()

    class Cursor:
        def batch_size(self, size):
            assert size == 100
            return self

        def __iter__(self):
            assert active, "Cursor must be fully consumed within the restore deadline"
            yield {"incident_id": "RESTORED"}
            assert active
            yield {"incident_id": "RESTORED-SECOND-BATCH"}

    monkeypatch.setattr(mongo, "timeout", deadline)
    monkeypatch.setattr(getattr(store, collection), "find", Mock(return_value=Cursor()))
    assert len(getattr(store, method)()) == 2
    assert not active


def test_partial_history_read_failure_never_returns_partial_restore(monkeypatch):
    store = mongo.MongoIncidentStore(mongomock.MongoClient(), "restore")

    class Cursor:
        def batch_size(self, size):
            return self

        def __iter__(self):
            yield {"incident_id": "PARTIAL"}
            raise ConnectionFailure("mongodb://secret:password@private-host")

    monkeypatch.setattr(store.events, "find", Mock(return_value=Cursor()))
    with pytest.raises(mongo.StorageUnavailable, match="^MongoDB lifecycle retrieval unavailable$"):
        store.load_events()


def event(device="TEST-MONGO", sequence=1):
    return {
        "schema_version": "1.0", "device_id": device, "source_kind": "simulator",
        "observed_at": datetime.now(timezone.utc).isoformat(), "sequence": sequence,
        "temperature_c": 29.4, "humidity_pct": 54, "cooling_fault": True,
        "fault_is_simulated": True,
    }


@pytest.fixture
def database(monkeypatch):
    client = mongomock.MongoClient()
    monkeypatch.setattr(main, "_incidents", {})
    monkeypatch.setattr(main, "_latest", {})
    monkeypatch.setattr(main, "_latest_sequence", {})
    monkeypatch.setattr(main, "_next_incident_number", 1)
    monkeypatch.setattr(main, "_store", None)
    monkeypatch.setattr(main, "_history", {})
    monkeypatch.setattr(main, "_fingerprints", {})
    monkeypatch.setattr(main, "tiger_from_environment", lambda: None)
    monkeypatch.setattr(main, "store_from_environment", lambda: mongo.MongoIncidentStore(client, "test"))
    return client["test"]


def test_upserts_one_incident_and_preserves_each_evidence_snapshot(database):
    with TestClient(main.app) as api:
        first = api.post("/api/telemetry", json=event())
        assert first.status_code == 200
        assert first.headers["x-factoryos-persistence"] == "persisted"
        iid = first.json()["incident_id"]
        second = api.post("/api/telemetry", json=event(sequence=2))
        assert second.json()["incident_id"] == iid
        assert database.incidents.count_documents({}) == 1
        assert database.reliability_evidence.count_documents({}) == 2
        assert database.incidents.find_one({"_id": iid})["hardware"]["sequence"] == 2
        assert sorted(e["hardware"]["sequence"] for e in database.reliability_evidence.find()) == [1, 2]
        detail = api.get("/api/incidents/" + iid).json()
        assert "_id" not in detail
        assert detail["reliability"]["reasons"] == ["legacy_missed_fault"]
        assert api.get("/api/storage/health").json()["status"] == "OK"


def test_new_lifespan_restores_incidents_ids_schema_and_sequence(database, monkeypatch):
    with TestClient(main.app) as api:
        original = api.post("/api/telemetry", json=event()).json()
        iid = original["incident_id"]
        snapshot = api.get("/api/incidents/" + iid).json()
    # Discard every process-local telemetry/incident value, as a restart would.
    monkeypatch.setattr(main, "_incidents", {})
    monkeypatch.setattr(main, "_latest", {})
    monkeypatch.setattr(main, "_latest_sequence", {})
    monkeypatch.setattr(main, "_next_incident_number", 1)
    with TestClient(main.app) as api:
        assert api.get("/api/incidents/" + iid).json() == snapshot
        assert api.get("/api/incidents").json() == {"incidents": [snapshot]}
        assert api.post("/api/telemetry", json=event()).status_code == 409
        assert api.post("/api/telemetry", json=event(sequence=2)).json()["incident_id"] == iid
        new = api.post("/api/telemetry", json=event("TEST-MONGO-NEW"))
        assert new.json()["incident_id"] == "INC-COOLING-002"
        assert database.incidents.count_documents({}) == 2
        assert api.get("/api/incidents/unknown").status_code == 404


def test_arduino_fault_clear_recurrence_updates_same_incident_and_api(database):
    with TestClient(main.app) as api:
        iid = None
        for sequence, fault in enumerate((True, False, True), 1):
            reading = {**event("RACK-HARDWARE-REGRESSION", sequence),
                       "source_kind": "arduino_serial", "cooling_fault": fault}
            response = api.post("/api/telemetry", json=reading)
            assert response.status_code == 200
            iid = iid or response.json()["incident_id"]
            assert response.json()["incident_id"] == iid
            assert response.headers["x-factoryos-persistence"] == "persisted"
            for snapshot in (api.get(f"/api/incidents/{iid}").json(),
                             api.get("/api/incidents").json()["incidents"][0],
                             database.incidents.find_one({"_id": iid})):
                assert snapshot["hardware"]["cooling_fault"] is fault
                assert snapshot["hardware"]["sequence"] == sequence
                assert snapshot["expected_status"] == ("WARNING" if fault else "NORMAL")
                assert snapshot["status"] == "OPEN"
        assert database.incidents.count_documents({}) == 1
        assert database.incident_events.count_documents({}) == 3


def test_latest_incident_does_not_wait_for_unrelated_older_history(database, monkeypatch):
    with TestClient(main.app) as api:
        iid = api.post("/api/telemetry", json=event()).json()["incident_id"]
        store = main._store
        for sequence in (2, 3):
            snapshot = deepcopy(main._incidents[iid])
            snapshot["hardware"]["sequence"] = sequence
            snapshot["hardware"]["cooling_fault"] = sequence == 2
            store.queue(snapshot)
        update = store.events.update_one

        def fail_old_event(query, change, **kwargs):
            if change["$setOnInsert"]["snapshot"]["hardware"]["sequence"] == 2:
                raise ConnectionFailure("Older audit write temporarily unavailable")
            return update(query, change, **kwargs)

        with monkeypatch.context() as failure:
            failure.setattr(store.events, "update_one", fail_old_event)
            assert not store.flush()
            latest = database.incidents.find_one({"_id": iid})
            assert latest["hardware"]["sequence"] == 3
            assert latest["hardware"]["cooling_fault"] is False
            assert database.incident_events.find_one({"snapshot.hardware.sequence": 3})
            assert store.health()["pending_incidents"] == 0
            assert store.health()["pending_events"] == 1
        assert store.flush()
        assert database.incident_events.count_documents({}) == 3
        assert store.health()["status"] == "OK"


def test_outage_keeps_alerts_and_retries_without_duplicates(database, monkeypatch):
    with TestClient(main.app) as api:
        with monkeypatch.context() as failure:
            failure.setattr(main._store.evidence, "update_one", Mock(
                side_effect=ConnectionFailure("mongodb://secret-user:secret-password@private-host"),
            ))
            response = api.post("/api/telemetry", json=event())
            assert response.status_code == 200
            assert response.json()["should_alert"] is True
            assert response.headers["x-factoryos-persistence"] == "pending"
            health = api.get("/api/storage/health")
            assert health.json()["status"] == "DEGRADED"
            assert health.json()["pending_incidents"] == 1
            assert health.json()["pending_evidence"] == 1
            assert "secret" not in health.text + response.text
            assert api.get("/api/incidents/" + response.json()["incident_id"]).status_code == 200
            assert api.get("/health").status_code == 200
        assert main._store.flush()
        assert main._store.flush()
        assert database.incidents.count_documents({}) == 1
        assert database.reliability_evidence.count_documents({}) == 1
        assert main._store.health()["status"] == "OK"


def test_partial_write_is_safe_to_retry(database, monkeypatch):
    with TestClient(main.app) as api:
        with monkeypatch.context() as failure:
            failure.setattr(main._store.incidents, "update_one", Mock(side_effect=ConnectionFailure()))
            api.post("/api/telemetry", json=event())
            assert database.reliability_evidence.count_documents({}) == 1
            assert database.incidents.count_documents({}) == 0
        assert main._store.flush()
        assert database.reliability_evidence.count_documents({}) == 1
        assert database.incidents.count_documents({}) == 1


def test_evidence_is_immutable_and_queue_copies_live_incident(database):
    with TestClient(main.app) as api:
        iid = api.post("/api/telemetry", json=event()).json()["incident_id"]
        snapshot = deepcopy(main._incidents[iid])
        store = main._store
        store.queue(snapshot)
        snapshot["hardware"]["temperature_c"] = 80
        assert store.flush()
        assert database.incidents.find_one({"_id": iid})["hardware"]["temperature_c"] == 29.4
        changed = deepcopy(main._incidents[iid])
        changed["hardware"]["temperature_c"] = 70
        store.queue(changed)
        assert store.flush()
        assert database.reliability_evidence.count_documents({}) == 1
        assert database.reliability_evidence.find_one()["hardware"]["temperature_c"] == 29.4


def test_configured_unreachable_database_fails_startup_safely(database, monkeypatch):
    store = mongo.MongoIncidentStore(mongomock.MongoClient(), "test")
    monkeypatch.setattr(store.client.admin, "command", Mock(
        side_effect=ConnectionFailure("credentials must not escape"),
    ))
    monkeypatch.setattr(main, "store_from_environment", lambda: store)
    with pytest.raises(mongo.StorageUnavailable, match="MongoDB incident retrieval unavailable") as exc:
        with TestClient(main.app):
            pytest.fail("Configured unavailable storage must not serve empty history")
    assert "credentials" not in str(exc.value)
    assert exc.value.__suppress_context__


def test_no_uri_retains_memory_mode(monkeypatch):
    monkeypatch.setattr(mongo, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.delenv("MONGODB_URI", raising=False)
    assert mongo.store_from_environment() is None
    monkeypatch.setattr(main, "store_from_environment", lambda: None)
    monkeypatch.setattr(main, "tiger_from_environment", lambda: None)
    with TestClient(main.app) as api:
        assert api.get("/api/storage/health").json()["status"] == "DISABLED"


def test_bad_configuration_does_not_expose_uri(monkeypatch):
    monkeypatch.setattr(mongo, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("MONGODB_URI", "secret-invalid-uri://user:password@host")
    with pytest.raises(mongo.StorageUnavailable) as exc:
        mongo.store_from_environment()
    assert "password" not in str(exc.value)
    assert exc.value.__suppress_context__


def test_retry_worker_flushes_while_running():
    stop = Mock()
    stop.wait.side_effect = [False, True]
    store = Mock()
    main._retry_persistence(stop, store)
    store.flush.assert_called_once()


def test_import_preserves_ids_and_can_be_repeated(database):
    with TestClient(main.app) as api:
        iid = api.post("/api/telemetry", json=event()).json()["incident_id"]
        backup = api.get("/api/incidents").json()
        database.incidents.delete_many({})
        database.reliability_evidence.delete_many({})
        assert import_incidents(backup, main._store) == 1
        assert import_incidents(backup, main._store) == 1
        assert database.incidents.count_documents({}) == 1
        assert database.incidents.find_one({"_id": iid})["created_at"] == backup["incidents"][0]["created_at"]
        assert database.reliability_evidence.count_documents({}) == 1


def test_import_rejects_conflicts_without_overwriting(database):
    with TestClient(main.app) as api:
        api.post("/api/telemetry", json=event())
        backup = api.get("/api/incidents").json()
        backup["incidents"][0]["created_at"] = "2020-01-01T00:00:00Z"
        with pytest.raises(ValueError, match="conflicts"):
            import_incidents(backup, main._store)
        assert database.incidents.find_one()["created_at"] != "2020-01-01T00:00:00Z"


@pytest.mark.parametrize("collection", ["incidents", "evidence"])
def test_unknown_write_outcome_is_idempotent_on_retry(database, monkeypatch, collection):
    with TestClient(main.app) as api:
        target = getattr(main._store, collection)
        real_update = target.update_one

        def acknowledged_but_connection_lost(*args, **kwargs):
            real_update(*args, **kwargs)
            raise ConnectionFailure("response lost after server write")

        with monkeypatch.context() as failure:
            failure.setattr(target, "update_one", acknowledged_but_connection_lost)
            response = api.post("/api/telemetry", json=event())
            assert response.headers["x-factoryos-persistence"] == "pending"
        assert main._store.flush()
        assert database.incidents.count_documents({}) == 1
        assert database.reliability_evidence.count_documents({}) == 1


def test_newer_queued_snapshot_is_not_discarded_during_flush(database, monkeypatch):
    with TestClient(main.app) as api:
        iid = api.post("/api/telemetry", json=event()).json()["incident_id"]
        store = main._store
        store.queue(main._incidents[iid])
        newer = deepcopy(main._incidents[iid])
        newer["hardware"]["sequence"] = 2
        real_update = store.incidents.update_one

        def queue_during_write(*args, **kwargs):
            store.queue(newer)
            return real_update(*args, **kwargs)

        with monkeypatch.context() as overlap:
            overlap.setattr(store.incidents, "update_one", queue_during_write)
            assert store.flush()
            assert store.health()["pending_incidents"] == 1
        assert store.flush()
        assert store.health()["status"] == "OK"
        assert database.incidents.find_one({"_id": iid})["hardware"]["sequence"] == 2
        assert database.reliability_evidence.count_documents({}) == 2


def test_investigation_resolution_and_reopen_survive_new_lifespan(database, monkeypatch):
    with TestClient(main.app) as api:
        iid = api.post("/api/telemetry", json=event()).json()["incident_id"]
        update = {"event_id": "investigation-1", "investigation": {
            "status": "COMPLETE", "tool_calls": [{"name": "read_evidence"}],
            "findings": ["Controlled test result"], "evidence_ids": ["evidence-1"],
        }, "decision_review": {"status": "COMPLETE", "recommendation": "ESCALATE"},
            "integrations": {"jira_key": "TEST-1"}}
        result = api.post(f"/api/incidents/{iid}/updates", json=update)
        assert result.status_code == 200
        assert result.json()["investigation"]["agent"] == "nvidia-nemotron"
        assert result.json()["integrations"]["jira_key"] == "TEST-1"
        resolve = {"event_id": "resolve-1", "status": "RESOLVED", "note": "Operator confirmed demo recovery"}
        resolved = api.post(f"/api/incidents/{iid}/updates", json=resolve)
        assert resolved.status_code == 200
        assert resolved.json()["status"] == "RESOLVED"
        count = database.incident_events.count_documents({})
        assert api.post(f"/api/incidents/{iid}/updates", json=resolve).status_code == 200
        assert database.incident_events.count_documents({}) == count
    monkeypatch.setattr(main, "_incidents", {})
    monkeypatch.setattr(main, "_history", {})
    monkeypatch.setattr(main, "_fingerprints", {})
    with TestClient(main.app) as api:
        restored = api.get(f"/api/incidents/{iid}").json()
        assert restored == resolved.json()
        history = api.get(f"/api/incidents/{iid}/history").json()
        assert [row["kind"] for row in history["events"]] == ["telemetry", "update", "resolution"]
        assert history["events"][-1]["snapshot"]["status"] == "RESOLVED"
        assert api.post(f"/api/incidents/{iid}/updates", json=resolve).status_code == 200
        reopened = api.post(f"/api/incidents/{iid}/updates", json={
            "event_id": "reopen-1", "status": "OPEN", "note": "Operator reopened demo incident",
        })
        assert reopened.json()["status"] == "OPEN"
        assert api.get(f"/api/incidents/{iid}/history").json()["events"][-1]["kind"] == "reopen"


def test_update_rejects_conflicts_invalid_fields_and_stale_revision(database):
    with TestClient(main.app) as api:
        iid = api.post("/api/telemetry", json=event()).json()["incident_id"]
        url = f"/api/incidents/{iid}/updates"
        assert api.post(url, json={"event_id": "one", "note": "Recorded"}).status_code == 200
        assert api.post(url, json={"event_id": "one", "note": "Different"}).status_code == 409
        assert api.post(url, json={"event_id": "two", "note": "Stale", "expected_updated_at": "old"}).status_code == 409
        assert api.post(url, json={"event_id": "bad", "status": "RESOLVED"}).status_code == 422
        assert api.post(url, json={"event_id": "bad", "device_id": "OTHER"}).status_code == 422
        assert api.post(url, json={"event_id": "bad", "status": "DEPLOYED", "note": "invalid"}).status_code == 422
        assert api.post(url, json={"event_id": "snapshot-reserved", "note": "invalid"}).status_code == 422
        assert api.post("/api/incidents/unknown/updates", json={"event_id": "one", "note": "none"}).status_code == 404
        assert api.get(f"/api/incidents/{iid}/history?limit=0").status_code == 422


def test_legacy_dictionary_integration_changes_are_captured(database):
    with TestClient(main.app) as api:
        iid = api.post("/api/telemetry", json=event()).json()["incident_id"]
        with main._lock:
            main._incidents[iid]["integrations"]["jira_key"] = "TEST-CAPTURE"
        main._capture_incident_changes()
        assert main._store.flush()
        assert database.incidents.find_one({"_id": iid})["integrations"]["jira_key"] == "TEST-CAPTURE"
        assert database.incident_events.find_one({"kind": "observed_update"}) is not None


def test_acknowledged_resolution_event_recovers_after_snapshot_write_failure(database, monkeypatch):
    with TestClient(main.app) as api:
        iid = api.post("/api/telemetry", json=event()).json()["incident_id"]
        with monkeypatch.context() as failure:
            failure.setattr(main._store.incidents, "update_one", Mock(side_effect=ConnectionFailure()))
            response = api.post(f"/api/incidents/{iid}/updates", json={
                "event_id": "resolve-partial", "status": "RESOLVED", "note": "Recovery test",
            })
            assert response.headers["x-factoryos-persistence"] == "pending"
            assert database.incident_events.find_one({"event_id": "resolve-partial"}) is not None
            assert database.incidents.find_one({"_id": iid})["status"] == "OPEN"
            # Discard the pending incident to simulate process loss before retry.
            main._store._pending_incidents.clear()
    monkeypatch.setattr(main, "_incidents", {})
    monkeypatch.setattr(main, "_history", {})
    with TestClient(main.app) as api:
        assert api.get(f"/api/incidents/{iid}").json()["status"] == "RESOLVED"


def test_update_failures_keep_pending_lifecycle_until_recovery(database, monkeypatch):
    with TestClient(main.app) as api:
        iid = api.post("/api/telemetry", json=event()).json()["incident_id"]
        with monkeypatch.context() as failure:
            failure.setattr(main._store.events, "update_one", Mock(side_effect=ConnectionFailure()))
            response = api.post(f"/api/incidents/{iid}/updates", json={
                "event_id": "investigate-pending", "investigation": {"status": "RUNNING"},
            })
            assert response.status_code == 200
            assert response.headers["x-factoryos-persistence"] == "pending"
            assert main._store.health()["pending_events"] == 1
        assert main._store.flush()
        assert database.incidents.find_one({"_id": iid})["investigation"]["status"] == "RUNNING"


def test_resolution_new_fault_and_reopen_preserve_one_open_incident(database):
    with TestClient(main.app) as api:
        iid = api.post("/api/telemetry", json=event()).json()["incident_id"]
        snapshot = api.get(f"/api/incidents/{iid}").json()
        response = api.post(f"/api/incidents/{iid}/updates", json={
            "event_id": "close-optimistic", "expected_updated_at": snapshot["updated_at"],
            "status": "RESOLVED", "note": "Operator resolved the demo",
        })
        assert response.status_code == 200
        new_fault = api.post("/api/telemetry", json=event(sequence=2))
        assert new_fault.json()["incident_id"] != iid
        assert api.post(f"/api/incidents/{iid}/updates", json={
            "event_id": "conflicting-reopen", "status": "OPEN", "note": "Attempted reopening",
        }).status_code == 409
        assert database.incidents.count_documents({"status": "OPEN"}) == 1
