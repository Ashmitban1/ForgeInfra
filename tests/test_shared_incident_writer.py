"""P1's canonical writer arbitrates P2 publications and P3 incident updates."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event, Lock

from fastapi.testclient import TestClient
import mongomock
import pytest

from backend import main
from backend.agents.review_schemas import material_incident, same_case
from backend.agents.schemas import investigation_summary
from backend.modernization.repository import content_revision, incident_identity
from backend.storage.lifecycle import IncidentUpdate
from backend.storage.mongo import MongoIncidentStore


@pytest.fixture
def writer(monkeypatch):
    for name in ("_incidents", "_latest", "_latest_sequence", "_history", "_fingerprints", "_approval_acks"):
        monkeypatch.setattr(main, name, {})
    monkeypatch.setattr(main, "_lock", Lock())
    monkeypatch.setattr(main, "_next_incident_number", 1)
    monkeypatch.setitem(main.app.state._state, "telemetry_store", None)
    store = MongoIncidentStore(mongomock.MongoClient(), "canonical_writer_test")
    monkeypatch.setattr(main, "_store", store)
    # No lifespan: exercise the real routes/writer with an isolated configured
    # store, without environment credentials, workers, providers, or cloud IO.
    api = TestClient(main.app)
    yield api, store
    api.close()
    store.close()


def telemetry(sequence=1, fault=True, temperature=29.4):
    return {
        "schema_version": "1.0", "device_id": "SIM-CANONICAL-WRITER", "source_kind": "simulator",
        "observed_at": datetime.now(timezone.utc).isoformat(), "sequence": sequence,
        "temperature_c": temperature, "humidity_pct": 54, "cooling_fault": fault,
        "fault_is_simulated": True,
    }


def create_incident(api):
    response = api.post("/api/telemetry", json=telemetry())
    assert response.status_code == 200, response.text
    assert response.headers["x-factoryos-persistence"] == "persisted"
    return main.get_incident_snapshot(response.json()["incident_id"])


def investigation(incident, number=1):
    snapshot = material_incident(incident)
    created = datetime.fromisoformat(incident["created_at"].replace("Z", "+00:00")) + timedelta(seconds=number)
    return {
        "job_id": f"investigation-{number}", "trace_id": f"trace-{number}",
        "incident_id": incident["incident_id"], "incident_identity": incident_identity(incident),
        "snapshot": snapshot, "snapshot_revision": content_revision(snapshot),
        "created_at": created.isoformat(), "status": "COMPLETED", "result": None,
    }


def approval(number=1):
    return {
        "version": 1, "packages": [], "decisions": [{
            "decision_id": f"human-decision-{number}", "decision": "REJECT",
            "request_revision": f"request-revision-{number}", "comment": "Needs further review",
        }],
    }


def test_publication_rejects_stale_identity_and_older_jobs_without_history(writer):
    api, store = writer
    incident = create_incident(api)
    old, new = investigation(incident, 1), investigation(incident, 2)
    jobs = {item["job_id"]: item for item in (old, new)}
    assert main.publish_job(new, "investigation", investigation_summary, jobs.get)
    count = len(main._history)
    assert not main.publish_job(old, "investigation", investigation_summary, jobs.get)
    wrong_incarnation = deepcopy(new)
    wrong_incarnation["incident_identity"] = incident_identity({**incident, "created_at": "2020-01-01T00:00:00Z"})
    assert not main.publish_job(wrong_incarnation, "investigation", investigation_summary, jobs.get)
    assert len(main._history) == count
    assert main.get_incident_snapshot(incident["incident_id"])["investigation"]["job_id"] == new["job_id"]
    assert store.events.count_documents({}) == count


def test_lookup_outside_lock_allows_p3_update_during_p2_publication(writer):
    api, store = writer
    incident = create_incident(api)
    iid = incident["incident_id"]
    old, new = investigation(incident, 1), investigation(incident, 2)
    assert main.publish_job(old, "investigation", investigation_summary, lambda key: None)
    lookup_started, resume = Event(), Event()
    calls = []

    def lookup(job_id):
        assert main._lock.acquire(blocking=False), "Job storage lookup must run outside telemetry lock"
        main._lock.release()
        calls.append(job_id)
        lookup_started.set()
        assert resume.wait(3), "Test must release job lookup"
        return old

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(main.publish_job, new, "investigation", investigation_summary, lookup)
        try:
            assert lookup_started.wait(2)
            updated = api.post(f"/api/incidents/{iid}/updates", json={
                "event_id": "p3-jira-created", "integrations": {"jira_key": "OPS-42", "jira_url": "https://example.test/OPS-42"},
            })
            assert updated.status_code == 200, updated.text
        finally:
            resume.set()
        assert pending.result(timeout=3)
    current = main.get_incident_snapshot(iid)
    assert calls == [old["job_id"]]
    assert current["integrations"]["jira_key"] == "OPS-42"
    assert "slack_message_id" in current["integrations"]
    assert current["investigation"]["job_id"] == new["job_id"]
    assert current["hardware"] == incident["hardware"] and current["case_generation"] == 0
    history = api.get(f"/api/incidents/{iid}/history").json()
    assert history["total"] == 4
    assert [event["kind"] for event in history["events"]] == [
        "telemetry", "investigation_completed", "update", "investigation_completed",
    ]
    assert history["events"][-1]["snapshot"]["integrations"]["jira_key"] == "OPS-42"
    assert store.incidents.find_one({"_id": iid})["integrations"] == current["integrations"]
    assert store.events.count_documents({}) == 4
    # Canonical writes already refresh fingerprints: the compatibility scanner
    # must not invent an additional lifecycle event for the same transitions.
    main._capture_incident_changes()
    main._flush_persistence()
    assert len(main._history) == store.events.count_documents({}) == 4
    assert not any(row["kind"] == "observed_update" for row in main._history.values())


def test_publication_rechecks_when_newer_job_wins_during_lookup(writer):
    api, store = writer
    incident = create_incident(api)
    old, candidate, newest = (investigation(incident, number) for number in (1, 2, 3))
    jobs = {item["job_id"]: item for item in (old, candidate, newest)}
    assert main.publish_job(old, "investigation", investigation_summary, jobs.get)
    started, resume = Event(), Event()
    calls = []

    def racing_lookup(job_id):
        calls.append(job_id)
        if job_id == old["job_id"]:
            started.set()
            assert resume.wait(3)
        return jobs[job_id]

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(main.publish_job, candidate, "investigation", investigation_summary, racing_lookup)
        try:
            assert started.wait(2)
            assert main.publish_job(newest, "investigation", investigation_summary, jobs.get)
        finally:
            resume.set()
        assert not pending.result(timeout=3)
    assert calls == [old["job_id"], newest["job_id"]]
    assert main.get_incident_snapshot(incident["incident_id"])["investigation"]["job_id"] == newest["job_id"]
    assert store.events.count_documents({}) == len(main._history) == 3


def test_approval_cas_rejects_old_read_and_keeps_concurrent_metadata(writer):
    api, store = writer
    expected = create_incident(api)
    iid = expected["incident_id"]
    changed = api.post(f"/api/incidents/{iid}/updates", json={
        "event_id": "p3-slack-sent", "integrations": {"slack_message_id": "thread-42"},
    })
    assert changed.status_code == 200
    assert not main.save_approval(iid, expected, approval())
    assert "approval" not in main.get_incident_snapshot(iid)
    expected = main.get_incident_snapshot(iid)
    assert main.save_approval(iid, expected, approval())
    current = main.get_incident_snapshot(iid)
    assert current["integrations"]["slack_message_id"] == "thread-42"
    assert current["approval_persistence"] == {"status": "PERSISTED", "version": 1}
    assert store.incidents.find_one({"_id": iid})["approval"] == approval()
    history = api.get(f"/api/incidents/{iid}/history").json()
    assert [row["kind"] for row in history["events"]] == ["telemetry", "update", "human_approval"]
    assert not main.save_approval(iid, expected, approval(2))


def test_two_approval_cas_writers_cannot_overwrite_each_other(writer):
    api, store = writer
    expected = create_incident(api)
    iid = expected["incident_id"]
    barrier = Barrier(2)

    def decide(number):
        barrier.wait(timeout=3)
        return number, main.save_approval(iid, expected, approval(number))

    with ThreadPoolExecutor(max_workers=2) as pool:
        decisions = list(pool.map(decide, (1, 2)))
    winners = [number for number, saved in decisions if saved]
    assert len(winners) == 1
    assert main.get_incident_snapshot(iid)["approval"] == approval(winners[0])
    assert store.events.count_documents({"kind": "human_approval"}) == 1


@pytest.mark.parametrize("protected_field,value", [
    ("approval", {"version": 999, "decisions": [{"decision": "APPROVE"}]}),
    ("case_generation", 999),
    ("hardware", {"cooling_fault": False}),
])
def test_public_update_cannot_bypass_privileged_writers(writer, protected_field, value):
    api, store = writer
    incident = create_incident(api)
    response = api.post(f"/api/incidents/{incident['incident_id']}/updates", json={
        "event_id": "attempt-protected-write", protected_field: value,
    })
    assert response.status_code == 422
    assert main.get_incident_snapshot(incident["incident_id"]) == incident
    assert store.events.count_documents({}) == len(main._history) == 1


def test_telemetry_recurrence_and_resolution_do_not_revive_cached_review(writer):
    api, store = writer
    original = create_incident(api)
    iid = original["incident_id"]
    main.update_incident(iid, IncidentUpdate(event_id="seed-completed-review", decision_review={
        "job_id": "review-existing", "status": "COMPLETED", "recommendation": "REQUEST_REPAIR_REVIEW",
        "effective_recommendation": "REQUEST_REPAIR_REVIEW", "actions": ["request_human_review"],
        "policy": {"effective_recommendation": "REQUEST_REPAIR_REVIEW", "advisory_actions": ["request_human_review"],
                   "repair_review_eligible": True, "requires_fresh_telemetry": False, "reasons": []},
    }))
    response = api.post("/api/telemetry", json=telemetry(2, temperature=30.1))
    assert response.status_code == 200
    equivalent = main.get_incident_snapshot(iid)
    assert equivalent["case_generation"] == 0 and same_case(original, equivalent)
    assert equivalent["decision_review"]["status"] == "COMPLETED"
    cleared = api.post("/api/telemetry", json=telemetry(3, fault=False))
    assert cleared.status_code == 200 and cleared.json()["incident_id"] == iid
    healthy = main.get_incident_snapshot(iid)
    assert healthy["status"] == "OPEN" and healthy["hardware"]["cooling_fault"] is False
    assert healthy["case_generation"] == 1 and not same_case(original, healthy)
    assert healthy["decision_review"]["status"] == "STALE"
    assert healthy["decision_review"]["recommendation"] is None
    assert healthy["decision_review"]["policy"]["repair_review_eligible"] is False
    assert "incident_case_changed" in healthy["decision_review"]["policy"]["reasons"]
    recurring = api.post("/api/telemetry", json=telemetry(4))
    assert recurring.status_code == 200 and recurring.json()["incident_id"] == iid
    returned = main.get_incident_snapshot(iid)
    assert returned["case_generation"] == 2 and not same_case(original, returned)
    assert returned["decision_review"]["status"] == "STALE"
    for status, generation in (("RESOLVED", 3), ("OPEN", 4)):
        response = api.post(f"/api/incidents/{iid}/updates", json={
            "event_id": f"operator-{status.lower()}", "status": status, "note": "Operator reviewed this case",
        })
        assert response.status_code == 200, response.text
        assert response.json()["case_generation"] == generation
        assert response.json()["decision_review"]["recommendation"] is None
    final = main.get_incident_snapshot(iid)
    assert final["status"] == "OPEN" and not same_case(original, final)
    assert store.incidents.find_one({"_id": iid})["case_generation"] == 4
    rows = api.get("/api/incidents").json()["incidents"]
    assert rows[0]["decision_review"]["status"] == "STALE"
    assert rows[0]["decision_review"]["actions"] == []
