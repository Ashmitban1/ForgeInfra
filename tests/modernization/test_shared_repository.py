"""Controller delegation and durable job namespaces without cloud/provider calls."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from unittest.mock import Mock

import mongomock
import pytest

from backend.modernization.repository import IncidentMissing, RepairBusy, content_revision, incident_identity, snapshot_of
from backend.modernization.shared_repository import SharedIncidentRepository


class Controller:
    """Test-only P1 authority; the adapter must never bypass these callbacks."""

    def __init__(self, incident):
        self.incidents = {incident["incident_id"]: deepcopy(incident)}
        self.lock = Lock()
        self.publications = []
        self.approval_writes = []

    def get_snapshot(self, incident_id):
        with self.lock:
            if incident_id not in self.incidents:
                raise IncidentMissing(incident_id)
            return deepcopy(self.incidents[incident_id])

    def publish_job(self, job, field, summarizer, previous_job_lookup):
        incident = self.get_snapshot(job["incident_id"])
        if incident_identity(incident) != job["incident_identity"]:
            return False
        previous_id = incident.get(field, {}).get("job_id")
        if previous_id and previous_id != job["job_id"]:
            previous = previous_job_lookup(previous_id)
            if previous and previous["created_at"] > job["created_at"]:
                return False
        summary = summarizer(job)
        with self.lock:
            self.incidents[job["incident_id"]][field] = deepcopy(summary)
            self.publications.append((job["job_id"], field))
        return True

    def save_approval(self, incident_id, expected_incident, approval):
        with self.lock:
            current = self.incidents.get(incident_id)
            if current is None:
                raise IncidentMissing(incident_id)
            if snapshot_of(current) != expected_incident:
                return False
            current["approval"] = deepcopy(approval)
            self.approval_writes.append(deepcopy(approval))
            return True


@pytest.fixture
def incident():
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": "1.0", "incident_id": "INC-SHARED-TEST", "device_id": "SIM-SHARED",
        "created_at": now, "updated_at": now, "status": "OPEN", "severity": "HIGH",
        "hardware": {"observed_at": now, "received_at": now, "sequence": 1,
                     "temperature_c": 29.4, "humidity_pct": 54, "cooling_fault": True,
                     "fault_is_simulated": True, "source_kind": "simulator"},
        "legacy_monitor": {"status": "NORMAL", "source_revision": "unit-baseline"},
        "expected_status": "WARNING", "reliability": {"mismatch": True, "reasons": ["legacy_missed_fault"]},
    }


@pytest.fixture
def system(incident):
    def make(database=None, controller=None):
        controller = controller or Controller(incident)
        repository = SharedIncidentRepository(controller.get_snapshot, controller.publish_job,
                                              controller.save_approval, database=database)
        return repository, controller
    return make


def job(incident, key="request-1", job_id="job-1", created_at=None):
    return {
        "job_id": job_id, "trace_id": "trace-" + job_id, "incident_id": incident["incident_id"],
        "incident_identity": incident_identity(incident), "device_id": incident["device_id"],
        "request_key": key, "snapshot": snapshot_of(incident), "snapshot_revision": content_revision(incident),
        "status": "QUEUED", "active": True,
        "created_at": created_at or incident["created_at"], "updated_at": incident["updated_at"],
        "result": None, "error": None,
    }


@pytest.mark.parametrize("durable", [False, True])
def test_incident_reads_and_writes_only_use_the_controller(system, incident, durable, monkeypatch):
    database = mongomock.MongoClient().integration if durable else None
    repository, controller = system(database)
    for method in ("get_incident_snapshot", "attach_job", "save_approval"):
        monkeypatch.setattr(repository._job_store, method, Mock(side_effect=AssertionError("Bypassed P1 controller")))
    record, created = repository.reserve_job(job(incident))
    assert created
    assert repository.attach_job(record)
    assert controller.publications == [(record["job_id"], "repair")]
    assert repository.get_incident_snapshot(incident["incident_id"]).get("repair") is None
    assert controller.get_snapshot(incident["incident_id"])["repair"]["job_id"] == record["job_id"]
    expected = repository.get_incident_snapshot(incident["incident_id"])
    approval = {"version": 1, "packages": [], "decisions": [{"decision": "REJECT"}]}
    assert repository.save_approval(incident["incident_id"], expected, approval)
    approval["decisions"].clear()
    assert controller.approval_writes[0]["decisions"] == [{"decision": "REJECT"}]
    assert not repository.save_approval(incident["incident_id"], expected, {"version": 2})
    if durable:
        # P1's fake controller intentionally has no database writer. A direct P2
        # incident mutation would put a document here, violating delegation.
        assert database.incidents.count_documents({}) == 0


def test_mongo_jobs_survive_repository_recreation_without_writing_incidents(system, incident):
    database = mongomock.MongoClient().integration
    repository, controller = system(database)
    record, created = repository.reserve_job(job(incident))
    assert created and repository.backend == "mongodb"
    result = {"repair_id": "scripted-unit-result", "verification_status": "VERIFIED"}
    repository.update_job(record["job_id"], {"status": "COMPLETED", "active": False, "result": result})
    completed = repository.get_job(record["job_id"])
    assert repository.attach_job(completed)
    recreated, same_controller = system(database, controller)
    restored = recreated.get_job(record["job_id"])
    assert restored["result"] == result and "_id" not in restored
    assert recreated.find_request(record["incident_identity"], record["request_key"])["job_id"] == record["job_id"]
    repeated, created = recreated.reserve_job(job(incident, job_id="different-retry-id"))
    assert not created and repeated["job_id"] == record["job_id"]
    assert database.repair_jobs.count_documents({}) == 1
    assert same_controller.get_snapshot(incident["incident_id"])["repair"]["job_id"] == record["job_id"]


@pytest.mark.parametrize("durable", [False, True])
def test_namespaces_share_controller_but_have_independent_active_jobs(system, incident, durable):
    database = mongomock.MongoClient().integration if durable else None
    repair, controller = system(database)
    investigation = repair.for_investigations()
    review = repair.for_reviews()
    assert investigation is review.for_investigations()
    assert review is investigation.for_reviews()
    assert investigation is investigation.for_investigations()
    for repository, name in [(repair, "repair"), (investigation, "investigation"), (review, "review")]:
        record, created = repository.reserve_job(job(incident, key=name, job_id=name + "-job"))
        assert created and record["active"]
    interrupted = review.interrupt_incomplete()
    assert [record["job_id"] for record in interrupted] == ["review-job"]
    assert review.get_job("review-job")["status"] == "INTERRUPTED"
    assert repair.get_job("repair-job")["status"] == "QUEUED"
    assert investigation.get_job("investigation-job")["status"] == "QUEUED"
    assert controller.publications == []


@pytest.mark.parametrize("durable", [False, True])
def test_atomic_active_collision_and_same_request_retries(system, incident, durable):
    database = mongomock.MongoClient().integration if durable else None
    repository, controller = system(database)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda number: repository.reserve_job(job(incident, job_id=f"retry-{number}")), range(2)))
    assert sum(created for record, created in results) == 1
    first_id = results[0][0]["job_id"]
    assert all(record["job_id"] == first_id for record, created in results)
    with pytest.raises(RepairBusy) as error:
        repository.reserve_job(job(incident, key="conflicting-request", job_id="conflicting-job"))
    assert error.value.job_id == first_id


def test_publication_keeps_newer_job_and_rejects_another_incarnation(system, incident):
    repository, controller = system()
    old = job(incident, job_id="old", created_at="2026-11-08T01:00:00Z")
    repository.reserve_job(old)
    repository.update_job("old", {"status": "COMPLETED", "active": False})
    new = job(incident, key="new", job_id="new", created_at="2026-11-08T02:00:00Z")
    repository.reserve_job(new)
    assert repository.attach_job(new)
    assert not repository.attach_job(old)
    controller.incidents[incident["incident_id"]]["created_at"] = "2026-11-09T00:00:00Z"
    assert not repository.attach_job(new)
    with pytest.raises(IncidentMissing):
        repository.get_incident_snapshot("missing")


def test_custom_names_and_parent_owned_client(system, incident, monkeypatch):
    monkeypatch.setenv("MONGODB_REPAIR_JOBS_COLLECTION", "p2_repair")
    monkeypatch.setenv("MONGODB_INVESTIGATION_JOBS_COLLECTION", "p2_investigation")
    monkeypatch.setenv("MONGODB_REVIEW_JOBS_COLLECTION", "p2_review")
    database = mongomock.MongoClient().integration
    repository, controller = system(database)
    assert repository.jobs.name == "p2_repair"
    assert repository.for_investigations().jobs.name == "p2_investigation"
    assert repository.for_reviews().jobs.name == "p2_review"
    close = Mock()
    monkeypatch.setattr(database.client, "close", close)
    repository.close()
    assert not close.called


@pytest.mark.parametrize("names", [
    {"repair": "incidents"}, {"investigation": "incident_events"}, {"decision_review": "reliability_evidence"},
    {"repair": "shared", "investigation": "shared"}, {"repair": "system.jobs"}, {"repair": "bad$name"},
    {"repair": ""}, {"unknown_namespace": "jobs"}, {"repair": None},
])
def test_bad_collection_names_fail_before_any_indexes_or_writes(incident, names):
    controller = Controller(incident)
    database = mongomock.MongoClient().integration
    with pytest.raises(ValueError):
        SharedIncidentRepository(controller.get_snapshot, controller.publish_job, controller.save_approval,
                                 database=database, collection_names=names)
    assert database.list_collection_names() == []


def test_controller_failures_and_false_commit_are_not_masked(system, incident, monkeypatch):
    repository, controller = system()
    expected = repository.get_incident_snapshot(incident["incident_id"])
    monkeypatch.setattr(repository, "_save_approval", lambda *args: False)
    assert not repository.save_approval(incident["incident_id"], expected, {"version": 1})
    def unavailable(*args):
        raise RuntimeError("test-only persistence unavailable")
    monkeypatch.setattr(repository, "_publish_job", unavailable)
    with pytest.raises(RuntimeError, match="persistence unavailable"):
        repository.attach_job(job(incident))
