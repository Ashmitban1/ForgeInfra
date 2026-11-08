"""MongoDB/Atlas adapter for P1's canonical incidents and durable P2 repair jobs."""

from copy import deepcopy
import os

from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError

from backend.modernization.repository import (
    IncidentMissing, RepairBusy, incident_identity, repair_summary, snapshot_of,
)


class MongoIncidentRepository:
    backend = "mongodb"

    def __init__(self, incidents, jobs, *, field="repair", summarizer=repair_summary):
        self.incidents = incidents
        self.jobs = jobs
        self.field = field
        self.summarizer = summarizer
        self.client = None
        self._investigations = None
        jobs.create_index("job_id", unique=True)
        jobs.create_index([("incident_identity", 1), ("request_key", 1)], unique=True)
        jobs.create_index("incident_identity", unique=True, name=f"one_active_{field}",
                          partialFilterExpression={"active": True})

    def for_investigations(self):
        from backend.agents.schemas import investigation_summary
        if self._investigations is None:
            collection = os.environ.get("MONGODB_INVESTIGATION_JOBS_COLLECTION", "investigation_jobs")
            if collection == self.jobs.name:
                raise ValueError("Investigation and repair jobs require separate collections")
            self._investigations = MongoIncidentRepository(
                self.incidents, self.jobs.database[collection],
                field="investigation", summarizer=investigation_summary,
            )
        return self._investigations

    @classmethod
    def from_environment(cls):
        uri = os.environ.get("MONGODB_URI")
        if not uri:
            raise ValueError("MONGODB_URI is required for the MongoDB repository")
        client = MongoClient(uri, serverSelectionTimeoutMS=3000, connectTimeoutMS=3000,
                             timeoutMS=5000, tz_aware=True)
        try:
            client.admin.command("ping")
            database = client[os.environ.get("MONGODB_DATABASE", "factoryos")]
            repository = cls(
                database[os.environ.get("MONGODB_INCIDENTS_COLLECTION", "incidents")],
                database[os.environ.get("MONGODB_REPAIR_JOBS_COLLECTION", "repair_jobs")],
            )
        except Exception:
            client.close()
            raise
        repository.client = client
        return repository

    def close(self):
        if self.client is not None:
            self.client.close()

    def get_incident_snapshot(self, incident_id: str) -> dict:
        document = self.incidents.find_one({"incident_id": incident_id})
        if document is None:
            raise IncidentMissing(incident_id)
        return snapshot_of(document)

    def find_request(self, identity: str, request_key: str) -> dict | None:
        return self.jobs.find_one({"incident_identity": identity, "request_key": request_key}, {"_id": 0})

    def reserve_job(self, job: dict) -> tuple[dict, bool]:
        try:
            self.jobs.insert_one(deepcopy(job))
            return deepcopy(job), True
        except DuplicateKeyError:
            previous = self.find_request(job["incident_identity"], job["request_key"])
            if previous:
                return previous, False
            active = self.jobs.find_one({"incident_identity": job["incident_identity"], "active": True})
            if active:
                raise RepairBusy(active["job_id"]) from None
            # The other job may have completed between the insert and lookup.
            self.jobs.insert_one(deepcopy(job))
            return deepcopy(job), True

    def get_job(self, job_id: str) -> dict | None:
        return self.jobs.find_one({"job_id": job_id}, {"_id": 0})

    def latest_job(self, identity: str) -> dict | None:
        return self.jobs.find_one({"incident_identity": identity}, {"_id": 0}, sort=[("created_at", -1)])

    def update_job(self, job_id: str, changes: dict) -> dict:
        document = self.jobs.find_one_and_update(
            {"job_id": job_id}, {"$set": deepcopy(changes)},
            projection={"_id": 0}, return_document=ReturnDocument.AFTER,
        )
        if document is None:
            raise LookupError("Repair job is missing")
        return document

    def attach_job(self, job: dict) -> bool:
        current = self.incidents.find_one({"incident_id": job["incident_id"]})
        if current is None or incident_identity(snapshot_of(current)) != job["incident_identity"]:
            return False
        # Never replace a more recently submitted job's incident summary.
        previous_id = current.get(self.field, {}).get("job_id")
        if previous_id and previous_id != job["job_id"]:
            previous = self.get_job(previous_id)
            if previous and previous["created_at"] > job["created_at"]:
                return False
        result = self.incidents.update_one(
            {"_id": current["_id"], "created_at": current["created_at"],
             self.field: current[self.field]} if self.field in current else
            {"_id": current["_id"], "created_at": current["created_at"], self.field: {"$exists": False}},
            {"$set": {self.field: self.summarizer(job)}},
        )
        return result.matched_count == 1

    def interrupt_incomplete(self) -> list[dict]:
        # This worker is intentionally single-process; call only at its startup.
        active = list(self.jobs.find({"active": True}, {"_id": 0}))
        self.jobs.update_many(
            {"active": True}, {"$set": {"status": "INTERRUPTED", "active": False,
             "error": f"The previous {self.field} worker stopped; submit a new request key to retry."}},
        )
        return [self.get_job(job["job_id"]) for job in active]
