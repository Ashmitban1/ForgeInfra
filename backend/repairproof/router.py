"""Named-reviewer APIs; GET verification never signs, sends, or writes."""
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from pymongo.errors import PyMongoError

from backend.modernization.approval import ApprovalConflict
from backend.modernization.approval_auth import ApprovalAuthError
from backend.modernization.repository import IncidentMissing
from backend.repairproof.repository import ProofConflict
from backend.repairproof.service import ProofUnavailable, ProofMissing


class PublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    decision_id: str = Field(min_length=1, max_length=100)
    package_revision: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    candidate_revision: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


def create_repairproof_router(service):
    router = APIRouter(tags=["RepairProof"])
    bearer = HTTPBearer(auto_error=False)

    def authenticate(response: Response, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        response.headers["Cache-Control"] = "no-store"
        try:
            auth = service.approval.auth_factory()
        except ApprovalAuthError:
            raise HTTPException(503, "Reviewer authentication is not configured") from None
        reviewer = auth.authenticate(credentials.credentials) if credentials and credentials.scheme.lower() == "bearer" else None
        if reviewer is None:
            raise HTTPException(401, "Valid reviewer credential required", headers={"WWW-Authenticate": "Bearer"})
        return reviewer

    def run(operation):
        try:
            return operation()
        except (IncidentMissing, ProofMissing):
            raise HTTPException(404, "Incident or proof not found") from None
        except (ApprovalConflict, ProofConflict) as error:
            raise HTTPException(409, {"message": str(error), "reasons": getattr(error, "reasons", [])}) from None
        except (PyMongoError, ProofUnavailable):
            raise HTTPException(503, "RepairProof unavailable; inspect readiness or existing proof before retrying") from None
        except (ValueError, KeyError, TypeError, OSError):
            raise HTTPException(409, "RepairProof evidence is incomplete or invalid") from None

    def find(proof_id):
        proof = service.repository.get(proof_id)
        if proof is None:
            raise ProofMissing()
        return proof

    @router.get("/api/repair-proofs/capabilities")
    def capabilities():
        return run(service.capabilities)

    @router.get("/api/incidents/{incident_id}/repair-proofs")
    def readiness(incident_id: str, reviewer=Depends(authenticate)):
        return run(lambda: service.readiness(incident_id, reviewer))

    @router.post("/api/incidents/{incident_id}/repair-proofs")
    def publish(incident_id: str, body: PublishRequest, response: Response,
                idempotency_key: Annotated[str, Header(min_length=1, max_length=128)], reviewer=Depends(authenticate)):
        def operation():
            proof, created = service.publish(incident_id, body, reviewer, idempotency_key)
            response.status_code = 202 if created and proof["status"] != "FINALIZED" else 200
            return {**service.public(proof), "reused": not created}
        return run(operation)

    @router.get("/api/repair-proofs/{proof_id}")
    def get_proof(proof_id: str, reviewer=Depends(authenticate)):
        return run(lambda: service.public(find(proof_id)))

    @router.get("/api/repair-proofs/{proof_id}/bundle")
    def bundle(proof_id: str, reviewer=Depends(authenticate)):
        return run(lambda: find(proof_id)["bundle"])

    @router.get("/api/repair-proofs/{proof_id}/verify")
    def verify(proof_id: str, reviewer=Depends(authenticate)):
        return run(lambda: service.verify(find(proof_id)))

    @router.post("/api/repair-proofs/{proof_id}/reconcile")
    def reconcile(proof_id: str, reviewer=Depends(authenticate)):
        """Save verified receipt state only; never signs or broadcasts a retry."""
        def operation():
            proof = find(proof_id)
            if proof["reviewer_id"] != reviewer.reviewer_id:
                raise ProofConflict("Only the approving reviewer may reconcile this proof")
            return service.public(service.reconcile(proof))
        return run(operation)

    return router
