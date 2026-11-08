"""Real NVIDIA investigation routes; no provider call occurs on telemetry ingestion."""

from contextlib import asynccontextmanager
from copy import deepcopy
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Path, Response
from fastapi.responses import PlainTextResponse
from pymongo.errors import PyMongoError

from backend.agents.nemotron import NemotronError
from backend.modernization.repository import IncidentMissing, RepairBusy
from backend.modernization.service import WorkerCapacity


def public_investigation(job: dict) -> dict:
    result = {key: deepcopy(job[key]) for key in (
        "job_id", "trace_id", "incident_id", "incident_created_at", "device_id", "snapshot",
        "snapshot_revision", "status", "created_at", "updated_at", "agent", "model", "limits",
        "tool_calls", "evidence", "provider_calls", "result", "error", "attached_to_incident",
    ) if key in job}
    patch = (result.get("result") or {}).get("generated_repair")
    if patch:
        patch.pop("diff", None)
    base = "/api/investigations/" + job["job_id"]
    result["links"] = {"job": base, "patch": base + "/patch",
                       "analysis": "/api/incidents/" + job["incident_id"] + "/analysis"}
    return result


def create_investigation_router(service) -> APIRouter:
    @asynccontextmanager
    async def lifespan(app):
        service.start()
        try:
            yield
        finally:
            service.close()

    router = APIRouter(lifespan=lifespan)

    @router.get("/api/agents/capabilities")
    def capabilities():
        try:
            config = service.config_factory()
            configured, model = True, config.model
        except NemotronError:
            configured, model = False, None
        return {"investigate": True, "configured": configured, "model": model,
                "storage_backend": service.repository.backend, "gemini": False,
                "automatic_deploy": False, "approval": False}

    @router.post("/api/incidents/{incident_id}/investigate", status_code=202, responses={
        200: {"description": "Reused completed or failed investigation"},
        404: {"description": "Incident does not exist in this backend"},
        409: {"description": "An investigation is already active or evidence is incomplete"},
        503: {"description": "NVIDIA configuration, worker, or storage is unavailable"},
    })
    def investigate(incident_id: str, response: Response,
                    idempotency_key: Annotated[str | None, Header(min_length=1, max_length=128)] = None) -> dict:
        """Queue an investigation and copy the returned `job_id` into the GET operation.

        `incident_id` identifies the simulator/telemetry incident. The response's
        `job_id` identifies this investigation; `links.job` is the exact polling URL.
        Memory-backed jobs are lost when this backend process restarts. Jobs from
        the standalone live-check script belong to its separate process.
        """
        try:
            job, created = service.submit(incident_id, idempotency_key)
        except IncidentMissing:
            raise HTTPException(404, "Incident not found") from None
        except RepairBusy as error:
            raise HTTPException(409, {"message": "An investigation is already active", "job_id": error.job_id}) from None
        except NemotronError as error:
            raise HTTPException(503, {"code": error.code, "message": str(error)}) from None
        except (WorkerCapacity, PyMongoError):
            raise HTTPException(503, "Investigation worker or incident store unavailable") from None
        except (KeyError, ValueError, TypeError):
            raise HTTPException(409, "Incident evidence or configuration is incomplete") from None
        response.status_code = 202 if job["status"] in ("QUEUED", "RUNNING") else 200
        response.headers["Location"] = "/api/investigations/" + job["job_id"]
        return {**public_investigation(job), "reused": not created}

    def lookup(job_id):
        try:
            job = service.repository.get_job(job_id)
        except PyMongoError:
            raise HTTPException(503, "Investigation store unavailable") from None
        if job is None:
            raise HTTPException(404, (
                "Investigation not found. Use the job_id returned by POST "
                "/api/incidents/{incident_id}/investigate on this backend, not the incident_id. "
                "Memory-backed jobs are lost on restart; standalone live-check jobs "
                "belong to a separate process."
            ))
        return job

    @router.get("/api/investigations/{job_id}", responses={
        404: {"description": "Unknown job ID, different backend process, or memory cleared on restart"},
    })
    def get_investigation(job_id: Annotated[str, Path(description=(
        "Copy job_id from the POST investigate response (investigation-job-...). "
        "Do not enter an INC-COOLING incident ID. Use the same backend process."
    ))]) -> dict:
        """Poll a job using its POST response's `job_id` or open `links.job` directly.

        HTTP 200 means the job was found; inspect `status` and `error` for its
        execution outcome. COMPLETED does not guarantee a verified repair:
        inspect `result.generated_repair.verification_status` when a candidate exists.
        """
        return public_investigation(lookup(job_id))

    @router.get("/api/investigations/{job_id}/patch", response_class=PlainTextResponse)
    def patch(job_id: str):
        job = lookup(job_id)
        generated = (job.get("result") or {}).get("generated_repair")
        if not generated:
            raise HTTPException(409, "No model-generated repair is available")
        return generated["diff"]

    return router
