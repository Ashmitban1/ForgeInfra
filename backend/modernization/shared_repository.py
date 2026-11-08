"""P2 jobs with P1-owned canonical incident reads, publications, and approval CAS.

The Mongo adapter below is used only for its job methods. Incident mutations are
always delegated to P1's controller, so its cache/history/persistence writer sees
every accepted transition and cannot overwrite a competing P2 incident writer.
"""

from copy import deepcopy
import os
import re
from threading import Lock, RLock
from typing import Callable

from backend.modernization.mongo_repository import MongoIncidentRepository
from backend.modernization.repository import MemoryIncidentRepository, repair_summary, snapshot_of


COLLECTION_ENV = {
    "repair": ("MONGODB_REPAIR_JOBS_COLLECTION", "repair_jobs"),
    "investigation": ("MONGODB_INVESTIGATION_JOBS_COLLECTION", "investigation_jobs"),
    "decision_review": ("MONGODB_REVIEW_JOBS_COLLECTION", "review_jobs"),
}
RESERVED_COLLECTIONS = {"incidents", "reliability_evidence", "incident_events"}


def job_collection_names(overrides: dict[str, str] | None = None) -> dict[str, str]:
    names = {field: os.environ.get(variable, default) for field, (variable, default) in COLLECTION_ENV.items()}
    if overrides:
        if set(overrides) - set(COLLECTION_ENV):
            raise ValueError("Unknown P2 job namespace")
        names.update(overrides)
    if (any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", name)
            or name in RESERVED_COLLECTIONS or name.startswith("system.") for name in names.values())
            or len(set(names.values())) != len(names)):
        raise ValueError("P2 job collections must be distinct and separate from canonical storage")
    return names


class SharedIncidentRepository:
    """One incident controller, isolated P2 job namespaces, optional durable jobs.

    ``get_snapshot(id)`` returns P1's canonical incident or raises IncidentMissing.
    ``publish_job(job, field, summarizer, previous_job_lookup)`` performs the
    identity/newer-job checks, review freshness projection, history publication,
    and persistence through P1; it returns whether the summary was accepted.
    ``save_approval(id, expected_incident, approval)`` is P1's trusted atomic CAS
    boundary and must honor durable acknowledgement before authorizing execution.

    Construct after P1's lifespan has restored incidents. Pass its existing
    ``store.incidents.database`` to persist jobs; this class never owns or closes
    that database client. An absent database is explicitly volatile memory mode.
    """

    def __init__(
        self,
        get_snapshot: Callable,
        publish_job: Callable,
        save_approval: Callable,
        *,
        database=None,
        field: str = "repair",
        summarizer: Callable = repair_summary,
        collection_names: dict[str, str] | None = None,
        _registry: dict | None = None,
        _registry_lock=None,
    ):
        if field not in COLLECTION_ENV:
            raise ValueError("Unknown P2 job namespace")
        self._get_snapshot = get_snapshot
        self._publish_job = publish_job
        self._save_approval = save_approval
        self._database = database
        self.field = field
        self.summarizer = summarizer
        self.collection_names = job_collection_names(collection_names)
        self._registry = {} if _registry is None else _registry
        self._registry_lock = _registry_lock if _registry_lock is not None else RLock()
        if database is None:
            # This incidental incident map is never read or mutated: only the
            # established in-memory job implementation is delegated below.
            self._job_store = MemoryIncidentRepository({}, Lock(), field=field, summarizer=summarizer)
        else:
            # P1 owns incidents. Do not call this object's incident methods.
            self._job_store = MongoIncidentRepository(
                database["incidents"], database[self.collection_names[field]], field=field, summarizer=summarizer,
            )
        self.backend = self._job_store.backend
        self._registry[field] = self

    @property
    def jobs(self):
        """Job records/collection, retained for existing local tooling and tests."""
        return self._job_store.jobs

    def _namespace(self, field: str, summarizer: Callable):
        with self._registry_lock:
            if field not in self._registry:
                SharedIncidentRepository(
                    self._get_snapshot, self._publish_job, self._save_approval,
                    database=self._database, field=field, summarizer=summarizer,
                    collection_names=self.collection_names, _registry=self._registry,
                    _registry_lock=self._registry_lock,
                )
            return self._registry[field]

    def for_investigations(self):
        from backend.agents.schemas import investigation_summary
        return self._namespace("investigation", investigation_summary)

    def for_reviews(self):
        from backend.agents.review_schemas import decision_review_summary
        return self._namespace("decision_review", decision_review_summary)

    def get_incident_snapshot(self, incident_id: str) -> dict:
        return snapshot_of(self._get_snapshot(incident_id))

    def find_request(self, identity: str, request_key: str) -> dict | None:
        return self._job_store.find_request(identity, request_key)

    def reserve_job(self, job: dict) -> tuple[dict, bool]:
        return self._job_store.reserve_job(job)

    def get_job(self, job_id: str) -> dict | None:
        return self._job_store.get_job(job_id)

    def latest_job(self, identity: str) -> dict | None:
        return self._job_store.latest_job(identity)

    def update_job(self, job_id: str, changes: dict) -> dict:
        return self._job_store.update_job(job_id, changes)

    def interrupt_incomplete(self) -> list[dict]:
        return self._job_store.interrupt_incomplete()

    def attach_job(self, job: dict) -> bool:
        return self._publish_job(deepcopy(job), self.field, self.summarizer, self.get_job)

    def save_approval(self, incident_id: str, expected_incident: dict, approval: dict) -> bool:
        return self._save_approval(incident_id, deepcopy(expected_incident), deepcopy(approval))

    def close(self):
        """P1's lifespan owns the database connection; no independent client."""
