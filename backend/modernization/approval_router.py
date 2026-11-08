"""Authenticated human decisions over an exact, frozen repair/evidence package."""

from copy import deepcopy
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pymongo.errors import PyMongoError

from backend.modernization.approval import ApprovalConflict, ApprovalDecision
from backend.modernization.approval_auth import ApprovalAuthError, Reviewer
from backend.modernization.repository import IncidentMissing


def create_approval_router(service) -> APIRouter:
    router = APIRouter()
    bearer = HTTPBearer(auto_error=False, scheme_name="FactoryOSReviewer",
                        description="Named reviewer token configured by the backend administrator; never an AI provider key.")

    def authenticate(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> Reviewer:
        try:
            auth = service.auth_factory()
        except ApprovalAuthError:
            raise HTTPException(503, "Reviewer authentication is not configured") from None
        reviewer = auth.authenticate(credentials.credentials) if credentials and credentials.scheme.lower() == "bearer" else None
        if reviewer is None:
            raise HTTPException(401, "Valid reviewer credential required", headers={"WWW-Authenticate": "Bearer"})
        return reviewer

    def run(operation):
        try:
            return operation()
        except IncidentMissing:
            raise HTTPException(404, "Incident not found") from None
        except ApprovalConflict as error:
            raise HTTPException(409, {"message": str(error), "reasons": error.reasons}) from None
        except PyMongoError:
            raise HTTPException(503, "Approval incident store unavailable") from None
        except (KeyError, TypeError, ValueError, OSError):
            raise HTTPException(409, "Approval evidence is incomplete or invalid") from None

    @router.get("/api/incidents/{incident_id}/approval")
    def get_approval(incident_id: str, reviewer: Annotated[Reviewer, Depends(authenticate)]) -> dict:
        """Inspect the current candidate, frozen-package hash, evidence, and eligibility.

        Copy package_revision and candidate_revision into POST /approval. This
        read creates no decision. can_reject can remain true when can_approve is
        false, including a failed verification or missing/stale Gemini review.
        """
        return run(lambda: service.view(service.repository.get_incident_snapshot(incident_id)))

    @router.post("/api/incidents/{incident_id}/approval", status_code=201, responses={
        200: {"description": "Idempotent retry of the original decision"},
        401: {"description": "Missing or invalid reviewer credential"},
        409: {"description": "Changed package, blocked approval, or existing conflicting decision"},
        503: {"description": "Reviewer authentication or incident store unavailable"},
    })
    def decide(incident_id: str, body: ApprovalDecision, response: Response,
               reviewer: Annotated[Reviewer, Depends(authenticate)],
               idempotency_key: Annotated[str | None, Header(min_length=1, max_length=128)] = None) -> dict:
        """Record APPROVE or REJECT against the exact package inspected by the reviewer.

        Identity and timestamp come from the backend. Decision records and frozen
        evidence are appended atomically to the same incident. A decision is final
        for that package; a new reviewed package requires a fresh decision. This
        endpoint does not activate code, merge, deploy, notify, or create a PR.
        """
        def operation():
            result, created = service.decide(incident_id, body, reviewer, idempotency_key)
            response.status_code = 201 if created else 200
            return {**result, "reused": not created}
        return run(operation)

    @router.get("/api/incidents/{incident_id}/approval/history")
    def history(incident_id: str, reviewer: Annotated[Reviewer, Depends(authenticate)]) -> dict:
        """Read immutable API audit records and the evidence package each decision bound."""
        return run(lambda: {"incident_id": incident_id,
                            **deepcopy(service.state(service.repository.get_incident_snapshot(incident_id)))})

    return router
