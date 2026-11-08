"""Incident repair API; storage and worker are injected rather than duplicated."""

from contextlib import asynccontextmanager
from copy import deepcopy
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Header, HTTPException, Response
from fastapi.responses import PlainTextResponse
from pymongo.errors import PyMongoError

from backend.modernization.repository import IncidentMissing, RepairBusy, incident_identity
from backend.modernization.service import RepairService, WorkerCapacity


def public_job(job: dict) -> dict:
    view = {key: deepcopy(job[key]) for key in (
        "job_id", "trace_id", "incident_id", "incident_created_at", "device_id", "snapshot",
        "snapshot_revision", "status", "created_at", "updated_at", "proposal_origin",
        "approval_status", "deployed", "result", "error", "attached_to_incident",
    ) if key in job}
    if view.get("result"):
        view["result"].pop("diff", None)
    base = "/api/repairs/" + job["job_id"]
    view["links"] = {
        "job": base, "report": base + "/report", "diff": base + "/diff",
        "analysis": "/api/incidents/" + quote(job["incident_id"], safe="") + "/analysis",
    }
    return view


def create_modernization_router(service: RepairService, investigation_service=None, review_service=None, approval_service=None) -> APIRouter:
    @asynccontextmanager
    async def lifespan(app):
        service.start()
        try:
            yield
        finally:
            service.close()

    router = APIRouter(lifespan=lifespan)

    def job_or_404(job_id: str) -> dict:
        try:
            job = service.repository.get_job(job_id)
        except PyMongoError:
            raise HTTPException(503, "The incident/job store is unavailable") from None
        if job is None:
            raise HTTPException(404, "Repair job not found")
        return job

    @router.get("/api/modernization/capabilities")
    def capabilities():
        return {"repair": True, "analysis": True, "investigate": investigation_service is not None,
                "review": review_service is not None,
                "storage_backend": service.repository.backend, "worker": "single_process_background",
                "proposal_origin": "manually_authored_demo_patch", "approval": approval_service is not None, "deploy": False}

    @router.post("/api/incidents/{incident_id}/repair")
    def repair(
        incident_id: str, response: Response,
        idempotency_key: Annotated[str | None, Header(min_length=1, max_length=128)] = None,
    ):
        try:
            job, created = service.submit(incident_id, idempotency_key)
        except IncidentMissing:
            raise HTTPException(404, "Incident not found") from None
        except RepairBusy as error:
            raise HTTPException(409, {"message": "Another repair request is active for this incident",
                                      "job_id": error.job_id}) from None
        except WorkerCapacity:
            raise HTTPException(503, "Repair worker unavailable or queue full; poll existing jobs and retry later") from None
        except (ValueError, KeyError, TypeError):
            raise HTTPException(409, "Incident evidence is incomplete or outside the supported legacy_missed_fault scenario") from None
        except PyMongoError:
            raise HTTPException(503, "The incident/job store is unavailable") from None
        response.status_code = 202 if job["status"] in ("QUEUED", "RUNNING") else 200
        response.headers["Location"] = "/api/repairs/" + job["job_id"]
        return {**public_job(job), "reused": not created, "storage_backend": service.repository.backend}

    @router.get("/api/incidents/{incident_id}/analysis")
    def analysis(incident_id: str):
        try:
            snapshot = service.repository.get_incident_snapshot(incident_id)
            job = service.repository.latest_job(incident_identity(snapshot))
            review = review_service.current_summary(snapshot) if review_service else snapshot.get("decision_review")
            approval = approval_service.current_summary(snapshot) if approval_service else None
        except IncidentMissing:
            raise HTTPException(404, "Incident not found") from None
        except (KeyError, TypeError, ValueError):
            raise HTTPException(409, "The stored incident is missing its canonical identity fields") from None
        except PyMongoError:
            raise HTTPException(503, "The incident/job store is unavailable") from None
        view = {
            "schema_version": "1.0", "incident_id": incident_id,
            "investigation": snapshot.get("investigation"), "decision_review": review,
            "repair": public_job(job) if job else None, "storage_backend": service.repository.backend,
        }
        if approval_service is not None:
            view["approval"] = approval
        return view

    @router.get("/api/repairs/{job_id}")
    def get_job(job_id: str):
        return public_job(job_or_404(job_id))

    @router.get("/api/repairs/{job_id}/report")
    def report(job_id: str):
        return public_job(job_or_404(job_id))

    @router.get("/api/repairs/{job_id}/diff", response_class=PlainTextResponse)
    def diff(job_id: str):
        job = job_or_404(job_id)
        if not job.get("result"):
            raise HTTPException(409, "No repair result is available yet")
        return job["result"]["diff"]

    return router
