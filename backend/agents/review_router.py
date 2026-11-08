"""Gemini recommendation jobs; human approval and external actions remain separate."""

from contextlib import asynccontextmanager
from copy import deepcopy
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Header, HTTPException, Path, Response
from pymongo.errors import PyMongoError

from backend.agents.gemini import GeminiError
from backend.agents.review import ReviewNotReady
from backend.modernization.repository import IncidentMissing, RepairBusy
from backend.modernization.service import WorkerCapacity


def public_review(job: dict) -> dict:
    view = {key: deepcopy(job[key]) for key in (
        "job_id", "trace_id", "incident_id", "device_id", "status", "current", "snapshot_revision",
        "created_at", "updated_at", "reviewer", "model", "limits", "provider_calls", "result",
        "error", "attached_to_incident",
    ) if key in job}
    view["review_basis"] = deepcopy(job["snapshot"]["review_input"]["basis"])
    base = "/api/reviews/" + job["job_id"]
    view["links"] = {
        "job": base, "analysis": "/api/incidents/" + quote(job["incident_id"], safe="") + "/analysis",
        "investigation": "/api/investigations/" + view["review_basis"]["investigation_job_id"],
    }
    return view


def create_review_router(service) -> APIRouter:
    @asynccontextmanager
    async def lifespan(app):
        service.start()
        try:
            yield
        finally:
            service.close()

    router = APIRouter(lifespan=lifespan)

    @router.post("/api/incidents/{incident_id}/review", status_code=202, responses={
        200: {"description": "Reused terminal review"},
        404: {"description": "Incident does not exist"},
        409: {"description": "Complete a current Nemotron investigation first, or poll an active review"},
        503: {"description": "Gemini configuration, worker, or incident store unavailable"},
    })
    def review(incident_id: str, response: Response,
               idempotency_key: Annotated[str | None, Header(min_length=1, max_length=128)] = None) -> dict:
        """Review the incident's completed Nemotron investigation with Gemini.

        No body is required. Copy the returned `job_id` (review-job-...) into GET
        `/api/reviews/{job_id}`, or open `links.job`. The result is advisory, not
        human approval. It executes no integrations or deployments. Jobs must be
        polled on this same backend; memory state is cleared on restart.
        """
        try:
            job, created = service.submit(incident_id, idempotency_key)
            view = service.current_view(job)
        except IncidentMissing:
            raise HTTPException(404, "Incident not found") from None
        except RepairBusy as error:
            raise HTTPException(409, {"message": "A Gemini review is already active", "job_id": error.job_id}) from None
        except ReviewNotReady as error:
            raise HTTPException(409, str(error)) from None
        except GeminiError as error:
            raise HTTPException(503, {"code": error.code, "message": str(error)}) from None
        except (WorkerCapacity, PyMongoError):
            raise HTTPException(503, "Review worker or incident store unavailable") from None
        except (KeyError, ValueError, TypeError):
            raise HTTPException(409, "Investigation evidence is incomplete or invalid") from None
        response.status_code = 202 if job["status"] in ("QUEUED", "RUNNING") else 200
        response.headers["Location"] = "/api/reviews/" + job["job_id"]
        return {**public_review(view), "reused": not created}

    @router.get("/api/reviews/{job_id}", responses={404: {"description": "Review job not found on this backend"}})
    def get_review(job_id: Annotated[str, Path(description="Copy review-job-... from the POST /review server response")]) -> dict:
        """Poll the real review and inspect status, error, result, and deterministic policy.

        COMPLETED means a valid Gemini review was received. STALE means telemetry
        or the investigation changed; its recommendation is no longer current.
        `/analysis` also marks old reviews stale. Inspect policy's
        `effective_recommendation`; raw model text cannot approve a repair.
        """
        try:
            job = service.repository.get_job(job_id)
            if job is None:
                raise HTTPException(404, "Review not found. Use the review-job ID returned by POST /review on this backend; memory jobs are cleared on restart.")
            return public_review(service.current_view(job))
        except PyMongoError:
            raise HTTPException(503, "Review store unavailable") from None

    return router
