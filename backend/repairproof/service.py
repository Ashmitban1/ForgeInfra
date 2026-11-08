"""Approval-gated proof orchestration. An uncertain send is never retried."""
import os

from backend.modernization.approval import ApprovalConflict
from backend.modernization.repository import content_revision, incident_identity
from backend.modernization.testing import utc_now
from backend.repairproof.commitment import build_bundle
from backend.repairproof.memo import MEMO_PROGRAM, InvalidTransaction
from backend.repairproof.repository import ProofConflict


class ProofUnavailable(RuntimeError):
    pass


class ProofMissing(LookupError):
    pass


def enabled():
    return os.environ.get("SOLANA_ENABLED", "false").lower() == "true"


class RepairProofService:
    def __init__(self, approval, repository, adapter=None, *, enabled_factory=enabled):
        self.approval, self.repository, self.adapter = approval, repository, adapter
        self.enabled_factory = enabled_factory

    def capabilities(self):
        reasons = []
        if not self.enabled_factory():
            reasons.append("solana_disabled")
        if not self.repository.durable:
            reasons.append("mongodb_required")
        if not self.approval.configured():
            reasons.append("reviewer_authentication_not_configured")
        if self.adapter is None:
            reasons.append("solana_publisher_configuration_required")
        elif not self.adapter.configured():
            reasons.append("solana_publisher_key_unavailable")
        return {"enabled": self.enabled_factory(), "network": "devnet", "publish_ready": not reasons,
                "blocking_reasons": reasons, "live_provider_available": True,
                "provider_configured": self.adapter is not None}

    def close(self):
        if self.adapter is not None:
            self.adapter.close()

    def readiness(self, incident_id, reviewer=None):
        incident = self.approval.repository.get_incident_snapshot(incident_id)
        view = self.approval.view(incident)
        reasons = self.capabilities()["blocking_reasons"] + view["blocking_reasons"]
        if view["status"] != "APPROVED":
            reasons.append("current_human_approval_required")
        if view.get("persistence", {}).get("status") != "PERSISTED":
            reasons.append("durable_approval_required")
        if reviewer and view.get("decision") and view["decision"]["reviewer_id"] != reviewer.reviewer_id:
            reasons.append("approving_reviewer_required")
        if self.repository.durable and view.get("status") == "APPROVED":
            self.repository.frozen(incident)
        proof = self.repository.latest(incident_identity(incident), (view.get("decision") or {}).get("decision_id"))
        return {"incident_id": incident_id, "ready": not reasons,
                "enabled": self.enabled_factory(), "provider_configured": self.adapter is not None,
                "blocking_reasons": list(dict.fromkeys(reasons)),
                "package_revision": view.get("package_revision"), "candidate_revision": view.get("candidate_revision"),
                "decision_id": (view.get("decision") or {}).get("decision_id"),
                "proof": self.public(proof) if proof else None}

    def authorize(self, incident_id, request, reviewer):
        incident = self.approval.repository.get_incident_snapshot(incident_id)
        if incident.get("approval_persistence", {}).get("status") != "PERSISTED":
            raise ProofUnavailable("Approval must be durably persisted in MongoDB")
        gate = self.approval.require_approved(incident_id, request.package_revision, request.candidate_revision)
        state = self.repository.frozen(incident)
        decision = next((d for d in state["decisions"] if d["decision_id"] == request.decision_id), None)
        package = next((p for p in state["packages"] if p["package_revision"] == request.package_revision), None)
        if (not decision or not package or decision != gate["decision"]
                or package["data"] != gate["package"]["data"]
                or decision["reviewer_id"] != reviewer.reviewer_id):
            raise ProofConflict("Only the approving reviewer may publish the exact frozen decision")
        return incident, package, decision

    def publish(self, incident_id, request, reviewer, key):
        if (not self.enabled_factory() or not self.repository.durable or self.adapter is None
                or not self.adapter.configured()):
            raise ProofUnavailable("RepairProof disabled or durable storage/provider unavailable")
        incident = self.approval.repository.get_incident_snapshot(incident_id)
        identity = incident_identity(incident)
        revision = content_revision(request.model_dump())
        request_key = content_revision({"incident_identity": identity, "reviewer": reviewer.reviewer_id, "key": key})
        proof_id = "proof-" + content_revision({"incident_identity": identity, "decision": request.decision_id,
                                               "network": self.adapter.config.genesis_hash})[7:]
        existing = self.repository.get(proof_id)
        if existing:
            if existing["reviewer_id"] != reviewer.reviewer_id or existing["request_revision"] != revision:
                raise ProofConflict("Proof belongs to another reviewer or evidence package")
            self.repository.bind_request(request_key, revision, proof_id)
            return self.reconcile(existing), False
        incident, package, decision = self.authorize(incident_id, request, reviewer)
        bundle = build_bundle(package, decision, proof_id=proof_id, signer=self.adapter.config.publisher,
                              genesis_hash=self.adapter.config.genesis_hash, memo_program=MEMO_PROGRAM)
        proof = {"proof_id": proof_id, "incident_id": incident_id, "incident_identity": identity,
                 "decision_id": decision["decision_id"], "reviewer_id": reviewer.reviewer_id,
                 "genesis_hash": self.adapter.config.genesis_hash, "bundle": bundle,
                 "request_revision": revision, "request_key": request_key, "status": "PREPARED", "created_at": utc_now()}
        self.repository.bind_request(request_key, revision, proof_id)
        proof, created = self.repository.reserve(proof)
        if not created:
            return self.reconcile(proof), False
        self.authorize(incident_id, request, reviewer)
        try:
            signed = self.adapter.prepare(proof)
        except Exception as error:
            self.repository.transition(proof_id, "PREPARED", {"status": "PREPARATION_FAILED",
                "error_code": getattr(error, "code", "transaction_preparation_failed")})
            raise ProofUnavailable("Transaction preparation failed; no submission attempted") from None
        proof = self.repository.transition(proof_id, "PREPARED", {"status": "SIGNED", **signed})
        # Re-evaluate freshness/revocation after preparation, immediately before
        # the single permitted broadcast. Never hold the canonical incident lock.
        authorized, _, _ = self.authorize(incident_id, request, reviewer)
        proof = self.repository.transition(proof_id, "SIGNED", {"status": "SUBMITTING",
            "authorized_at": utc_now(), "approval_version": authorized["approval"]["version"]})
        try:
            self.adapter.submit(proof)
        except Exception:
            # May have landed. Persist UNKNOWN; even if this write fails, the
            # pre-send SUBMITTING record still prevents a second broadcast.
            proof = self.repository.transition(proof_id, "SUBMITTING", {"status": "UNKNOWN"})
        else:
            proof = self.repository.transition(proof_id, "SUBMITTING", {"status": "SUBMITTED"})
        return self.reconcile(proof), True

    def verify(self, proof):
        if self.adapter is None:
            raise ProofUnavailable("Solana verification provider not configured")
        if not proof.get("signature"):
            return {"status": "NOT_SUBMITTED", "reason": "no_signed_transaction"}
        # Rebuild all commitment layers from saved canonical bytes, independently
        # of the current (possibly stale) incident. Historical proofs stay useful.
        import base64
        import json
        from backend.repairproof.commitment import DOMAIN, canonical_bytes, digest
        bundle = proof["bundle"]
        try:
            envelope_raw = base64.b64decode(bundle["envelope_bytes_b64"], validate=True)
            envelope = json.loads(envelope_raw)
            package = json.loads(base64.b64decode(bundle["package_bytes_b64"], validate=True))
            decision = json.loads(base64.b64decode(bundle["approval_bytes_b64"], validate=True))
            expected = build_bundle({"data": package, "package_revision": envelope["package_revision"],
                                     "candidate_revision": envelope["candidate_revision"]}, decision,
                                    proof_id=proof["proof_id"], signer=self.adapter.config.publisher,
                                    genesis_hash=self.adapter.config.genesis_hash, memo_program=MEMO_PROGRAM)
            if (expected != bundle or canonical_bytes(envelope) != envelope_raw
                    or digest(DOMAIN + envelope_raw) != bundle["commitment"]):
                raise ValueError()
            return self.adapter.verify(proof)
        except InvalidTransaction:
            return {"status": "MISMATCH", "reason": "transaction_verification_failed"}
        except (ValueError, KeyError, TypeError):
            return {"status": "MISMATCH", "reason": "evidence_commitment_mismatch"}
        except Exception:
            raise ProofUnavailable("Verification provider unavailable; do not resubmit") from None

    def reconcile(self, proof):
        if proof["status"] in {"PREPARED", "PREPARATION_FAILED", "FINALIZED", "CHAIN_FAILED"}:
            return proof
        verification = self.verify(proof)
        status = verification["status"]
        # UNKNOWN/PENDING preserve an uncertain send; never prepare or send here.
        target = status if status in {"FINALIZED", "CHAIN_FAILED", "MISMATCH"} else "UNKNOWN"
        return self.repository.transition(proof["proof_id"], proof["status"],
            {"status": target, "verification": verification, "checked_at": utc_now()})

    @staticmethod
    def public(proof):
        return {key: proof.get(key) for key in ("proof_id", "incident_id", "status", "signature", "created_at", "verification", "error_code")} | {
            "network": "devnet", "commitment": proof["bundle"]["commitment"],
            "package_revision": proof["bundle"]["envelope"]["package_revision"],
            "candidate_revision": proof["bundle"]["envelope"]["candidate_revision"],
            "explorer_url": ("https://explorer.solana.com/tx/" + proof["signature"] + "?cluster=devnet")
                if proof.get("signature") else None}
