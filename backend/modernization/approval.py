"""Version-bound human decisions; no activation or external workflow side effects."""

from copy import deepcopy
import json
from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field

from backend.agents.review import build_review_snapshot, candidate_is_verified, sha256
from backend.agents.review_schemas import ReviewConclusion, fault_context, review_is_current
from backend.modernization.approval_auth import ApprovalAuth, ApprovalAuthError, Reviewer
from backend.modernization.patching import source_hash
from backend.modernization.repository import content_revision, incident_identity
from backend.modernization.runner import LEGACY_MONITOR_PATH
from backend.modernization.testing import utc_now

MAX_PACKAGES = 16
MAX_PACKAGE_BYTES = 256_000
GUARDED_FIELDS = (
    "schema_version", "incident_id", "device_id", "created_at", "updated_at", "status", "severity",
    "hardware", "legacy_monitor", "expected_status", "reliability", "investigation", "decision_review", "approval",
)


class ApprovalConflict(ValueError):
    def __init__(self, message: str, reasons: list[str] | None = None):
        self.reasons = reasons or []
        super().__init__(message)


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    decision: Literal["APPROVE", "REJECT"]
    package_revision: str = Field(pattern=r"^sha256:[0-9a-f]{64}$",
                                  description="Copy package_revision from GET /approval; binds the full review/evidence package")
    candidate_revision: str = Field(pattern=r"^sha256:[0-9a-f]{64}$",
                                    description="Copy candidate_revision from GET /approval; identifies the exact proposed code")
    comment: str = Field(default="", max_length=2000)


def guarded_snapshot(incident: dict) -> dict:
    return {key: deepcopy(incident[key]) for key in GUARDED_FIELDS if key in incident}


class ApprovalService:
    def __init__(self, repository, investigations, reviews, *, auth_factory=ApprovalAuth.from_environment):
        self.repository = repository
        self.investigations = investigations
        self.reviews = reviews
        self.auth_factory = auth_factory

    def configured(self) -> bool:
        try:
            self.auth_factory()
            return True
        except ApprovalAuthError:
            return False

    def state(self, incident: dict) -> dict:
        state = deepcopy(incident.get("approval") or {"version": 0, "packages": [], "decisions": []})
        if (not isinstance(state, dict) or not isinstance(state.get("version"), int)
                or not isinstance(state.get("packages"), list) or not isinstance(state.get("decisions"), list)):
            raise ApprovalConflict("Stored approval history is invalid")
        return state

    def package(self, incident: dict) -> dict | None:
        source_id = (incident.get("investigation") or {}).get("job_id")
        source = self.investigations.get_job(source_id) if source_id else None
        if not source or source.get("incident_identity") != incident_identity(incident):
            return None
        repair = (source.get("result") or {}).get("generated_repair")
        if not repair:
            return None
        review_id = (incident.get("decision_review") or {}).get("job_id")
        review = self.reviews.repository.get_job(review_id) if review_id else None
        if review and (review.get("incident_identity") != incident_identity(incident)
                       or review["snapshot"]["review_input"]["basis"]["investigation_job_id"] != source_id):
            review = None
        data = {
            "schema_version": "1.0", "incident_identity": incident_identity(incident),
            "incident": deepcopy(source["snapshot"]),
            "investigation": {key: deepcopy(source.get(key)) for key in (
                "job_id", "snapshot_revision", "model", "status", "result", "evidence", "tool_calls",
            )},
            "review": {key: deepcopy(review.get(key)) for key in (
                "job_id", "snapshot_revision", "model", "status", "result", "provider_calls",
            )} if review else None,
            "binding": {
                "investigation_job_id": source_id, "review_job_id": review["job_id"] if review else None,
                "incident_revision": source["snapshot_revision"], "original_revision": repair["original_revision"],
                "candidate_revision": repair["candidate_revision"], "diff_revision": repair["diff_revision"],
                "tests_revision": content_revision(repair["tests"]), "replay_revision": content_revision(repair["replay"]),
                "review_result_revision": content_revision(review["result"]) if review and review.get("result") else None,
            },
        }
        if len(json.dumps(data).encode("utf-8")) > MAX_PACKAGE_BYTES:
            raise ApprovalConflict("Approval evidence package exceeds its supported size")
        return {"package_revision": content_revision(data), "candidate_revision": repair["candidate_revision"], "data": data}

    def eligibility(self, incident: dict, package: dict | None) -> list[str]:
        if package is None:
            return ["no_candidate"]
        reasons = []
        data = package["data"]
        source = data["investigation"]
        repair = source["result"]["generated_repair"]
        try:
            bundle = build_review_snapshot(incident, self.investigations)["review_input"]
            if not candidate_is_verified(bundle):
                reasons.append("candidate_not_verified")
        except (KeyError, TypeError, ValueError):
            reasons.append("investigation_evidence_invalid_or_stale")
        if sha256(repair["diff"]) != repair["diff_revision"]:
            reasons.append("diff_revision_changed")
        if source_hash(LEGACY_MONITOR_PATH) != repair["original_revision"]:
            reasons.append("target_source_revision_changed")
        review_ref = data["review"]
        if not review_ref:
            return reasons + ["gemini_review_missing"]
        raw_review = self.reviews.repository.get_job(review_ref["job_id"])
        if not raw_review or raw_review.get("status") != "COMPLETED" or not review_is_current(incident, raw_review):
            return reasons + ["gemini_review_not_current"]
        if content_revision(raw_review.get("result")) != data["binding"]["review_result_revision"]:
            return reasons + ["gemini_review_changed"]
        basis = raw_review["snapshot"]["review_input"]["basis"]
        if (basis["investigation_result_revision"] != content_revision(source["result"])
                or content_revision(raw_review["snapshot"]) != raw_review["snapshot_revision"]):
            return reasons + ["reviewed_evidence_changed"]
        try:
            result = raw_review["result"]
            conclusion = ReviewConclusion.model_validate({key: value for key, value in result.items() if key != "policy"})
            known = {entry["evidence_id"] for entry in source["evidence"]}
            if not set(conclusion.evidence_ids).issubset(known):
                reasons.append("gemini_evidence_invalid")
            if conclusion.fault_provenance != fault_context(data["incident"])["fault_provenance"]:
                reasons.append("gemini_provenance_invalid")
            if conclusion.repair_assessment != "SUITABLE_FOR_HUMAN_REVIEW":
                reasons.append("gemini_did_not_recommend_repair_review")
            policy = self.reviews.current_view(raw_review, incident)["result"]["policy"]
            if not policy["repair_review_eligible"]:
                reasons.append("candidate_not_eligible")
            if policy["requires_fresh_telemetry"]:
                reasons.append("fresh_telemetry_required")
            if policy["effective_recommendation"] in {"NO_ACTION", "COLLECT_MORE_EVIDENCE"}:
                reasons.append("gemini_policy_blocks_approval")
            if "model_disagrees_with_deterministic_incident_evidence" in policy["reasons"]:
                reasons.append("gemini_review_disagreement")
        except (KeyError, TypeError, ValueError):
            reasons.append("gemini_review_invalid")
        return list(dict.fromkeys(reasons))

    def view(self, incident: dict, *, include_package: bool = True) -> dict:
        state = self.state(incident)
        package = self.package(incident)
        reasons = self.eligibility(incident, package)
        try:
            auth = self.auth_factory()
        except ApprovalAuthError:
            auth = None
            reasons.append("reviewer_authentication_not_configured")
        decision = next((item for item in reversed(state["decisions"])
                         if package and item["package_revision"] == package["package_revision"]), None)
        if decision and decision["decision"] == "APPROVE" and auth and decision["reviewer_id"] not in auth.reviewers:
            reasons.append("approving_reviewer_no_longer_authorized")
        status = "PENDING"
        if decision:
            status = "REJECTED" if decision["decision"] == "REJECT" else "STALE" if reasons else "APPROVED"
        elif state["decisions"]:
            status = "STALE"
        result = {
            "incident_id": incident["incident_id"], "status": status, "version": state["version"],
            "can_approve": package is not None and not reasons and decision is None,
            "can_reject": auth is not None and package is not None and decision is None,
            "authentication_configured": auth is not None,
            "blocking_reasons": reasons, "decision": deepcopy(decision),
            "package_revision": package["package_revision"] if package else None,
            "candidate_revision": package["candidate_revision"] if package else None,
            "history_count": len(state["decisions"]), "deployed": False,
        }
        if include_package:
            result["package"] = package
        return result

    def current_summary(self, incident: dict) -> dict:
        try:
            return self.view(incident, include_package=False)
        except (KeyError, TypeError, ValueError, OSError):
            return {"incident_id": incident["incident_id"], "status": "PENDING", "can_approve": False,
                    "can_reject": False, "blocking_reasons": ["approval_evidence_invalid"], "deployed": False}

    def decide(self, incident_id: str, request: ApprovalDecision, reviewer: Reviewer,
               idempotency_key: str | None = None) -> tuple[dict, bool]:
        payload_revision = content_revision({"reviewer_id": reviewer.reviewer_id, **request.model_dump()})
        for _ in range(3):
            incident = self.repository.get_incident_snapshot(incident_id)
            key_revision = content_revision({"incident_identity": incident_identity(incident),
                                             "reviewer_id": reviewer.reviewer_id,
                                             "key": idempotency_key or payload_revision})
            state = self.state(incident)
            previous = next((item for item in state["decisions"] if item["request_key_revision"] == key_revision), None)
            if previous:
                if previous["request_revision"] != payload_revision:
                    raise ApprovalConflict("Idempotency key already identifies a different decision")
                return {**self.view(incident), "recorded_decision": previous}, False
            package = self.package(incident)
            if (not package or package["package_revision"] != request.package_revision
                    or package["candidate_revision"] != request.candidate_revision):
                raise ApprovalConflict("Candidate or evidence package changed; inspect the current approval package")
            if any(item["package_revision"] == request.package_revision for item in state["decisions"]):
                raise ApprovalConflict("This package already has a final decision; a new reviewed package is required")
            reasons = self.eligibility(incident, package)
            if request.decision == "APPROVE" and reasons:
                raise ApprovalConflict("Candidate is not eligible for approval", reasons)
            if len(state["packages"]) >= MAX_PACKAGES:
                raise ApprovalConflict("Approval history limit reached; archive this incident before further decisions")
            now = utc_now()
            decision = {
                "decision_id": "approval-decision-" + uuid.uuid4().hex,
                "package_revision": request.package_revision, "candidate_revision": request.candidate_revision,
                "decision": request.decision, "reviewer_id": reviewer.reviewer_id,
                "decided_at": now, "comment": request.comment, "request_key_revision": key_revision,
                "request_revision": payload_revision,
                "eligibility_at_decision": {"can_approve": not reasons, "blocking_reasons": reasons, "checked_at": now},
            }
            state["packages"].append({**deepcopy(package), "frozen_at": now})
            state["decisions"].append(decision)
            state["version"] += 1
            if self.repository.save_approval(incident_id, incident, state):
                current = self.repository.get_incident_snapshot(incident_id)
                return {**self.view(current), "recorded_decision": decision}, True
        raise ApprovalConflict("Incident or decision changed concurrently; refresh and retry")

    def require_approved(self, incident_id: str, package_revision: str, candidate_revision: str) -> dict:
        """Future activation/PR code must call this immediately before acting."""
        incident = self.repository.get_incident_snapshot(incident_id)
        view = self.view(incident)
        if (view["status"] != "APPROVED" or view["package_revision"] != package_revision
                or view["candidate_revision"] != candidate_revision):
            raise ApprovalConflict("No current approval authorizes this exact candidate", view["blocking_reasons"])
        return {"decision": view["decision"], "package": view["package"]}
