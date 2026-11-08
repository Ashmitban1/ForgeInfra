"""Validated model findings and browser-facing investigation progress."""

from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: Literal["fixtures/legacy_monitor/monitor.py"]
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    source_revision: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=1500)
    evidence_ids: list[str] = Field(min_length=1, max_length=8)
    source_reference: SourceReference | None = None


class InvestigationConclusion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=2000)
    suspected_cause: str = Field(min_length=1, max_length=300)
    findings: list[Finding] = Field(min_length=1, max_length=8)
    recommended_actions: list[Literal[
        "inspect_equipment", "request_repair_review", "escalate", "human_review",
    ]] = Field(min_length=1, max_length=4)


def investigation_summary(job: dict) -> dict:
    result = job.get("result") or {}
    return {
        "status": "PENDING" if job["status"] == "QUEUED" else job["status"],
        "agent": "nvidia-nemotron", "model": job.get("model"), "job_id": job["job_id"],
        "trace_id": job["trace_id"], "snapshot_revision": job["snapshot_revision"],
        "tool_calls": deepcopy(job.get("tool_calls", [])),
        "findings": deepcopy(result.get("findings", [])),
        "evidence_ids": [item["evidence_id"] for item in job.get("evidence", [])],
        "summary": result.get("summary"), "suspected_cause": result.get("suspected_cause"),
        "recommended_actions": result.get("recommended_actions", []),
        "generated_repair": deepcopy(result.get("generated_repair")),
        "provider_calls": deepcopy(job.get("provider_calls", [])), "error": job.get("error"),
    }
