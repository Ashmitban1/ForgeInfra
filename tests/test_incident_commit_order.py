"""Concurrent lifecycle updates must not roll back newer telemetry on restart."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import mongomock

from backend import main
from backend.storage.lifecycle import IncidentUpdate
from backend.storage.mongo import MongoIncidentStore


def clear_process_state(monkeypatch):
    for name in ("_incidents", "_latest", "_latest_sequence", "_history", "_fingerprints", "_approval_acks"):
        monkeypatch.setattr(main, name, {})
    monkeypatch.setattr(main, "_store", None)
    monkeypatch.setattr(main, "_next_incident_number", 1)


def test_telemetry_commit_after_intervening_update_remains_latest_after_restart(monkeypatch):
    client = mongomock.MongoClient()
    clear_process_state(monkeypatch)
    monkeypatch.setattr(main, "store_from_environment", lambda: MongoIncidentStore(client, "commit_order"))
    monkeypatch.setattr(main, "tiger_from_environment", lambda: None)
    monkeypatch.setattr(main, "_retry_persistence", lambda stop, store: None)
    clock = {"now": datetime.now(timezone.utc)}

    class ControlledDatetime:
        @classmethod
        def now(cls, tz=None):
            return clock["now"].astimezone(tz) if tz is not None else clock["now"].replace(tzinfo=None)

    monkeypatch.setattr(main, "datetime", ControlledDatetime)
    monkeypatch.setattr(main, "utc_now", lambda: main.iso(clock["now"]))

    def event(sequence, fault):
        return {
            "device_id": "SIM-COMMIT-ORDER", "source_kind": "simulator",
            "observed_at": main.iso(clock["now"]), "sequence": sequence,
            "temperature_c": 29.4, "humidity_pct": 54,
            "cooling_fault": fault, "fault_is_simulated": True,
        }

    with TestClient(main.app) as api:
        first = api.post("/api/telemetry", json=event(1, True))
        assert first.status_code == 200, first.text
        incident_id = first.json()["incident_id"]
        original_monitor = main.evaluate_legacy_telemetry
        intervening = {}

        def monitor_with_intervening_update(data, received):
            result = original_monitor(data, received)
            # This happens while telemetry runs the legacy subprocess outside
            # _lock, before that telemetry sample commits to the incident.
            clock["now"] += timedelta(seconds=1)
            intervening.update(main.update_incident(incident_id, IncidentUpdate(
                event_id="p3-during-monitor", integrations={"jira_key": "FACTORY-ORDER"},
            )))
            clock["now"] += timedelta(seconds=1)
            return result

        monkeypatch.setattr(main, "evaluate_legacy_telemetry", monitor_with_intervening_update)
        clock["now"] += timedelta(seconds=1)
        sample_received_at = main.iso(clock["now"])
        second = api.post("/api/telemetry", json=event(2, False))
        assert second.status_code == 200 and not second.json()["should_alert"]
        latest = api.get(f"/api/incidents/{incident_id}").json()
        assert latest["hardware"]["received_at"] == sample_received_at
        assert latest["updated_at"] > intervening["updated_at"]
        assert latest["hardware"]["sequence"] == 2 and not latest["hardware"]["cooling_fault"]
        assert latest["case_generation"] == intervening.get("case_generation", 0) + 1
        assert latest["integrations"]["jira_key"] == "FACTORY-ORDER"
        assert client.commit_order.incidents.find_one({"_id": incident_id}, {"_id": 0}) == latest

    clear_process_state(monkeypatch)
    with TestClient(main.app) as api:
        restored = api.get(f"/api/incidents/{incident_id}").json()
        assert restored == latest
        assert restored["hardware"]["sequence"] == 2 and restored["case_generation"] == 1
        assert not restored["hardware"]["cooling_fault"]
