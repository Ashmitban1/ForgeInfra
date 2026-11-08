"""Bounded in-process jobs for the local integration backend (one worker process)."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import BoundedSemaphore, Lock
import uuid

from backend.modernization.patching import DEFAULT_OUTPUT_ROOT
from backend.modernization.pipeline import execute_incident_repair, incident_event
from backend.modernization.repository import (
    IncidentRepository, content_revision, incident_identity,
)
from backend.modernization.runner import LEGACY_MONITOR_PATH
from backend.modernization.patching import source_hash
from backend.modernization.testing import ACCEPTANCE_SUITE, utc_now


class WorkerCapacity(RuntimeError):
    pass


class RepairService:
    job_kind = "repair"

    def __init__(
        self, repository: IncidentRepository, output_root: Path = DEFAULT_OUTPUT_ROOT,
        pipeline=execute_incident_repair, max_pending: int = 4,
    ):
        self.repository = repository
        self.output_root = output_root
        self.pipeline = pipeline
        self.slots = BoundedSemaphore(max_pending)
        self.lifecycle_lock = Lock()
        self.executor = None
        self.closed = False

    def start(self):
        with self.lifecycle_lock:
            if self.closed:
                raise WorkerCapacity("The repair worker is shutting down")
            if self.executor is None:
                for job in self.repository.interrupt_incomplete():
                    self.repository.attach_job(job)
                self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="factoryos-" + self.job_kind)

    def prepare_snapshot(self, snapshot: dict) -> dict:
        # Human audit packages must never recursively enter future repair jobs.
        return {key: value for key, value in snapshot.items() if key != "approval"}

    def validate_snapshot(self, snapshot: dict):
        incident_event(snapshot)

    def request_identity(self, snapshot: dict) -> str:
        return content_revision({
            "snapshot_revision": content_revision(snapshot),
            "original_revision": source_hash(LEGACY_MONITOR_PATH),
            "acceptance_revision": source_hash(ACCEPTANCE_SUITE),
        })

    def job_metadata(self) -> dict:
        return {"proposal_origin": "manually_authored_demo_patch", "approval_status": "PENDING", "deployed": False}

    def close(self):
        with self.lifecycle_lock:
            self.closed = True
            executor = self.executor
        if executor is not None:
            executor.shutdown(wait=True)

    def submit(self, incident_id: str, idempotency_key: str | None = None) -> tuple[dict, bool]:
        self.start()
        snapshot = self.prepare_snapshot(self.repository.get_incident_snapshot(incident_id))
        identity = incident_identity(snapshot)
        # A retry refers to its original snapshot, even if live telemetry recovered.
        if idempotency_key:
            previous = self.repository.find_request(identity, idempotency_key)
            if previous:
                return previous, False
        self.validate_snapshot(snapshot)
        request_key = idempotency_key or self.request_identity(snapshot)
        previous = self.repository.find_request(identity, request_key)
        if previous:
            return previous, False
        if not self.slots.acquire(blocking=False):
            raise WorkerCapacity("The repair queue is full; poll existing jobs and retry later")
        job = None
        try:
            now = utc_now()
            job, created = self.repository.reserve_job({
                "job_id": self.job_kind + "-job-" + uuid.uuid4().hex,
                "trace_id": self.job_kind + "-trace-" + uuid.uuid4().hex,
                "incident_id": incident_id, "incident_identity": identity,
                "incident_created_at": snapshot["created_at"], "device_id": snapshot["device_id"],
                "request_key": request_key, "snapshot": snapshot,
                "snapshot_revision": content_revision(snapshot),
                "status": "QUEUED", "active": True, "created_at": now, "updated_at": now,
                **self.job_metadata(), "result": None, "error": None,
            })
            if not created:
                self.slots.release()
                return job, False
            self.repository.attach_job(job)
            self.executor.submit(self._run, job)
            return job, True
        except Exception:
            self.slots.release()
            if job is not None:
                failed = self.repository.update_job(job["job_id"], {
                    "status": "FAILED", "active": False, "updated_at": utc_now(),
                    "error": "The repair worker could not accept this job; use a new request key to retry.",
                })
                self.repository.attach_job(failed)
            raise

    def _run(self, job: dict):
        try:
            running = self.repository.update_job(job["job_id"], {"status": "RUNNING", "updated_at": utc_now()})
            self.repository.attach_job(running)
            result = self.pipeline(deepcopy(job["snapshot"]), self.output_root)
            changes = {
                "status": "COMPLETED", "active": False, "updated_at": utc_now(), "result": result,
            }
            finished = {**running, **changes}
            attached = self.repository.attach_job(finished)
            # Publish terminal job status only after its incident attachment was attempted.
            self.repository.update_job(job["job_id"], {**changes, "attached_to_incident": attached})
        except Exception:
            # Provider/database exception strings may contain connection details.
            # Retain raw verifier evidence locally; return only this safe API error.
            try:
                failed = self.repository.update_job(job["job_id"], {
                    "status": "FAILED", "active": False, "updated_at": utc_now(),
                    "error": "Repair execution failed. Check the backend worker and local verification evidence.",
                })
                self.repository.attach_job(failed)
            except Exception:
                pass  # Durable unfinished jobs become INTERRUPTED on the next single-worker startup.
        finally:
            self.slots.release()
