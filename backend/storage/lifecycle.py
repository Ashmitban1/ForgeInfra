"""Incident update contract and history snapshots, independent of AI/providers."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def fingerprint(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def history_event(incident: dict, kind: str = "telemetry", event_id: str | None = None,
                  request_hash: str | None = None, note: str | None = None) -> dict:
    return {
        "incident_id": incident["incident_id"],
        "event_id": event_id or "snapshot-" + fingerprint(incident),
        "kind": kind, "recorded_at": utc_now(), "request_hash": request_hash,
        "note": note, "snapshot": deepcopy(incident),
    }


class IncidentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    event_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    expected_updated_at: str | None = None
    investigation: dict[str, JsonValue] | None = None
    decision_review: dict[str, JsonValue] | None = None
    integrations: dict[str, str | None] | None = None
    status: Literal["OPEN", "RESOLVED"] | None = None
    severity: Literal["HIGH", "REVIEW"] | None = None
    note: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def require_change(self):
        if self.integrations and any(key.lower().startswith(("solana", "repairproof", "repair_proof"))
                                     for key in self.integrations):
            raise ValueError("RepairProof fields are reserved for authenticated proof workflows")
        values = self.model_dump(exclude={"event_id", "expected_updated_at"}, exclude_none=True)
        if not values:
            raise ValueError("At least one update field or note is required")
        if self.status is not None and (not self.note or not self.note.strip()):
            raise ValueError("Status changes require a reason in note")
        if len(json.dumps(values, allow_nan=False)) > 100_000:
            raise ValueError("Update is too large")
        return self
