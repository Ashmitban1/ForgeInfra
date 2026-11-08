"""Incident/job interface and local adapter; P1 remains owner of canonical storage."""

from copy import deepcopy
import hashlib
import json
from typing import Protocol

from fastapi.encoders import jsonable_encoder


class IncidentMissing(LookupError):
    pass


class RepairBusy(RuntimeError):
    def __init__(self, job_id: str):
        self.job_id = job_id
        super().__init__("An incident repair is already running")


def snapshot_of(incident: dict) -> dict:
    # Repairs must never recursively snapshot earlier jobs or database internals.
    return jsonable_encoder(deepcopy({
        key: value for key, value in incident.items() if key not in ("_id", "repair")
    }))


def content_revision(value: dict) -> str:
    content = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def incident_identity(snapshot: dict) -> str:
    return content_revision({
        "incident_id": snapshot["incident_id"], "created_at": snapshot["created_at"],
        "device_id": snapshot["device_id"],
    })


def repair_summary(job: dict) -> dict:
    return {
        "job_id": job["job_id"], "job_status": job["status"],
        "repair_id": (job.get("result") or {}).get("repair_id"),
        "verification_status": (job.get("result") or {}).get("verification_status"),
        "proposal_origin": "manually_authored_demo_patch",
        "approval_status": "PENDING", "deployed": False,
        "snapshot_revision": job["snapshot_revision"], "trace_id": job["trace_id"],
    }


class IncidentRepository(Protocol):
    backend: str

    def get_incident_snapshot(self, incident_id: str) -> dict: ...
    def find_request(self, identity: str, request_key: str) -> dict | None: ...
    def reserve_job(self, job: dict) -> tuple[dict, bool]: ...
    def get_job(self, job_id: str) -> dict | None: ...
    def latest_job(self, identity: str) -> dict | None: ...
    def update_job(self, job_id: str, changes: dict) -> dict: ...
    def attach_job(self, job: dict) -> bool: ...
    def interrupt_incomplete(self) -> list[dict]: ...
    def save_approval(self, incident_id: str, expected_incident: dict, approval: dict) -> bool: ...


class MemoryIncidentRepository:
    """Use P1's actual dict/lock; only job records are additional local state."""

    backend = "memory"

    def __init__(self, incidents: dict, lock, *, field="repair", summarizer=repair_summary):
        self.incidents = incidents
        self.lock = lock
        self.field = field
        self.summarizer = summarizer
        self.jobs: dict[str, dict] = {}
        self._investigations = None
        self._reviews = None

    def for_investigations(self):
        from backend.agents.schemas import investigation_summary
        if self._investigations is None:
            self._investigations = MemoryIncidentRepository(
                self.incidents, self.lock, field="investigation", summarizer=investigation_summary,
            )
        return self._investigations

    def for_reviews(self):
        from backend.agents.review_schemas import decision_review_summary
        if self._reviews is None:
            self._reviews = MemoryIncidentRepository(
                self.incidents, self.lock, field="decision_review", summarizer=decision_review_summary,
            )
        return self._reviews

    def get_incident_snapshot(self, incident_id: str) -> dict:
        with self.lock:
            if incident_id not in self.incidents:
                raise IncidentMissing(incident_id)
            return snapshot_of(self.incidents[incident_id])

    def find_request(self, identity: str, request_key: str) -> dict | None:
        with self.lock:
            return deepcopy(next((job for job in self.jobs.values()
                                  if job["incident_identity"] == identity
                                  and job["request_key"] == request_key), None))

    def reserve_job(self, job: dict) -> tuple[dict, bool]:
        with self.lock:
            matching = [value for value in self.jobs.values()
                        if value["incident_identity"] == job["incident_identity"]]
            previous = next((value for value in matching if value["request_key"] == job["request_key"]), None)
            if previous:
                return deepcopy(previous), False
            active = next((value for value in matching if value["active"]), None)
            if active:
                raise RepairBusy(active["job_id"])
            self.jobs[job["job_id"]] = deepcopy(job)
            return deepcopy(job), True

    def get_job(self, job_id: str) -> dict | None:
        with self.lock:
            return deepcopy(self.jobs.get(job_id))

    def latest_job(self, identity: str) -> dict | None:
        with self.lock:
            values = [job for job in self.jobs.values() if job["incident_identity"] == identity]
            return deepcopy(max(values, key=lambda job: job["created_at"])) if values else None

    def update_job(self, job_id: str, changes: dict) -> dict:
        with self.lock:
            self.jobs[job_id].update(deepcopy(changes))
            return deepcopy(self.jobs[job_id])

    def attach_job(self, job: dict) -> bool:
        with self.lock:
            incident = self.incidents.get(job["incident_id"])
            if incident is None or incident_identity(snapshot_of(incident)) != job["incident_identity"]:
                return False
            current = incident.get(self.field, {})
            if current.get("job_id") not in (None, job["job_id"]):
                previous = self.jobs.get(current["job_id"])
                if previous and previous["created_at"] > job["created_at"]:
                    return False
            if self.field == "decision_review":
                from backend.agents.review_schemas import review_job_view
                incident[self.field] = self.summarizer(review_job_view(incident, job))
            else:
                incident[self.field] = self.summarizer(job)
            return True

    def interrupt_incomplete(self) -> list[dict]:
        with self.lock:
            interrupted = []
            for job in self.jobs.values():
                if job["active"]:
                    job.update(status="INTERRUPTED", active=False,
                               error=f"The previous {self.field} worker stopped; submit a new request key to retry.")
                    interrupted.append(deepcopy(job))
            return interrupted

    def save_approval(self, incident_id: str, expected_incident: dict, approval: dict) -> bool:
        from backend.modernization.approval import guarded_snapshot
        with self.lock:
            current = self.incidents.get(incident_id)
            if current is None:
                raise IncidentMissing(incident_id)
            if guarded_snapshot(snapshot_of(current)) != guarded_snapshot(expected_incident):
                return False
            current["approval"] = deepcopy(approval)
            return True
