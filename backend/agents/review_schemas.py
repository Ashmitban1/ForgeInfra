"""Structured advisory recommendations and their exact investigation basis."""

from copy import deepcopy
from datetime import datetime
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from fastapi.encoders import jsonable_encoder

from backend.modernization.repository import content_revision

MATERIAL_FIELDS = (
    "schema_version", "incident_id", "device_id", "created_at", "updated_at", "status",
    "severity", "hardware", "legacy_monitor", "expected_status", "reliability", "case_generation",
)


def material_incident(incident: dict) -> dict:
    return jsonable_encoder({key: deepcopy(incident[key]) for key in MATERIAL_FIELDS if key in incident})


def _temperature_band(temperature) -> str:
    if type(temperature) not in (int, float) or not math.isfinite(temperature):
        return "INVALID_OR_MISSING"
    if temperature < 0:
        return "LT0"
    if temperature == 0:
        return "EQ0"
    if temperature < 1:
        return "0_TO1"
    if temperature == 1:
        return "EQ1"
    if temperature < 35:
        return "1_TO35"
    if temperature == 35:
        return "EQ35"
    return "GT35"


def case_revision(incident: dict) -> str:
    """Hash the monitoring case, separately from the exact captured sample.

    The constrained candidate grammar can compare temperature against 35 and
    booleans (numeric 0/1), or use its truthiness. Preserve all seven intervals and
    equality points at those boundaries. Sample identity/times and within-band
    sensor jitter do not change the case. Unknown
    hardware/reliability fields remain bound conservatively; new monitoring rules
    must extend this projection if they use additional measurements. An ingestion
    generation binds intervening case changes, including fault-clear-fault cycles.
    Missing generations are legacy generation zero without rewriting old evidence.
    """
    material = material_incident(incident)
    material.setdefault("case_generation", 0)
    hardware = deepcopy(material.get("hardware") or {})
    temperature = hardware.pop("temperature_c", None)
    hardware.pop("humidity_pct", None)  # The current monitor does not use humidity.
    for key in ("observed_at", "received_at", "sequence"):
        hardware.pop(key, None)
    hardware["temperature_band"] = _temperature_band(temperature)
    legacy = deepcopy(material.get("legacy_monitor") or {})
    legacy.pop("sampled_at", None)
    reliability = deepcopy(material.get("reliability") or {})
    reliability.pop("observation_age_seconds", None)
    if isinstance(reliability.get("reasons"), list):
        reliability["reasons"] = sorted(set(reliability["reasons"]))
    return content_revision({
        **{key: value for key, value in material.items()
           if key not in {"updated_at", "hardware", "legacy_monitor", "reliability"}},
        "hardware": hardware, "legacy_monitor": legacy, "reliability": reliability,
    })


def _sample_time(hardware: dict, key: str) -> datetime:
    value = hardware[key]
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Sample time must include timezone")
    return parsed


def same_case(captured: dict, current: dict) -> bool:
    """Allow fresh compatible samples, never changed or replayed sample records."""
    try:
        if case_revision(captured) != case_revision(current):
            return False
        before, after = captured["hardware"], current["hardware"]
        if before == after:
            return True  # Includes metadata-only lifecycle/history updates.
        if (type(before.get("sequence")) is not int or type(after.get("sequence")) is not int
                or after["sequence"] <= before["sequence"]):
            return False
        before_observed, after_observed = _sample_time(before, "observed_at"), _sample_time(after, "observed_at")
        before_received, after_received = _sample_time(before, "received_at"), _sample_time(after, "received_at")
        return (after_observed >= before_observed and after_received >= before_received
                and (after_observed > before_observed or after_received > before_received))
    except (KeyError, TypeError, ValueError):
        return False


def fault_context(incident: dict) -> dict:
    """A real sensor channel does not make a switch-simulated fault physical."""
    hardware = incident.get("hardware") or {}
    simulated = hardware.get("fault_is_simulated")
    provenance = "SIMULATED" if simulated is True else "REPORTED" if simulated is False else "UNKNOWN"
    statements = {
        "SIMULATED": "This is a simulated cooling-fault signal. Physical equipment health has not been verified.",
        "REPORTED": "Telemetry reports a cooling-fault signal. A physical equipment failure has not been independently verified.",
        "UNKNOWN": "Cooling-fault provenance is unknown. Physical equipment health has not been verified.",
    }
    return {"fault_provenance": provenance, "fault_is_simulated": simulated if type(simulated) is bool else None,
            "source_kind": hardware.get("source_kind", "unknown"), "physical_fault_status": "NOT_VERIFIED",
            "statement": statements[provenance]}


class ReviewConclusion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    recommendation: Literal[
        "ESCALATE", "INVESTIGATE_SOFTWARE", "REQUEST_REPAIR_REVIEW", "COLLECT_MORE_EVIDENCE", "NO_ACTION",
    ]
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "REVIEW"]
    actions: list[Literal[
        "create_jira_incident", "notify_on_call", "investigate_legacy_code",
        "inspect_equipment", "request_human_review", "collect_fresh_telemetry",
    ]] = Field(min_length=1, max_length=6)
    evidence_ids: list[str] = Field(min_length=1, max_length=16)
    repair_assessment: Literal[
        "SUITABLE_FOR_HUMAN_REVIEW", "CHANGES_REQUIRED", "INSUFFICIENT_EVIDENCE", "NO_CANDIDATE",
    ]
    risks: list[str] = Field(max_length=8)
    needs_human_approval: Literal[True]
    explanation: str = Field(min_length=1, max_length=3000)
    fault_provenance: Literal["SIMULATED", "REPORTED", "UNKNOWN"]


def review_is_current(incident: dict, job: dict) -> bool:
    bundle = job["snapshot"]["review_input"]
    basis = bundle["basis"]
    captured = bundle["incident"]
    investigation = incident.get("investigation") or {}
    return (investigation.get("job_id") == basis["investigation_job_id"]
            and investigation.get("status") == "COMPLETED"
            and investigation.get("snapshot_revision") == basis["incident_revision"]
            and content_revision(captured) == basis["incident_revision"]
            and basis.get("case_revision", case_revision(captured)) == case_revision(captured)
            and same_case(captured, incident))


def review_job_view(incident: dict, job: dict) -> dict:
    view = deepcopy(job)
    current = review_is_current(incident, job) and job["status"] != "STALE"
    view["current"] = current
    if not current:
        view["status"] = "STALE"
        if view.get("result"):
            view["result"]["policy"].update(
                effective_recommendation=None, advisory_actions=[], repair_review_eligible=False,
            )
    return view


def decision_review_summary(job: dict) -> dict:
    result = job.get("result") or {}
    stale = job["status"] == "STALE"
    policy = deepcopy(result.get("policy"))
    return {
        "status": "PENDING" if job["status"] == "QUEUED" else job["status"],
        "reviewer": "gemini", "model": job.get("model"), "job_id": job["job_id"],
        "trace_id": job["trace_id"], "review_basis": deepcopy(job["snapshot"]["review_input"]["basis"]),
        "recommendation": None if stale else (policy or {}).get("effective_recommendation"),
        "model_recommendation": result.get("recommendation"),
        "effective_recommendation": None if stale else (policy or {}).get("effective_recommendation"),
        "severity": result.get("severity"), "actions": [] if stale else (policy or {}).get("advisory_actions", []),
        "evidence_ids": result.get("evidence_ids", []), "risks": result.get("risks", []),
        "repair_assessment": result.get("repair_assessment"), "explanation": result.get("explanation"),
        "fault_context": fault_context(job["snapshot"]["review_input"]["incident"]),
        "provenance_validation": "VALIDATED" if result.get("fault_provenance") else "NOT_VALIDATED",
        "needs_human_approval": True, "approval_status": "PENDING", "deployed": False,
        "policy": policy, "provider_calls": deepcopy(job.get("provider_calls", [])),
        "stale": stale, "error": deepcopy(job.get("error")),
    }
