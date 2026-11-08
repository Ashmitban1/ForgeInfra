"""Evaluate trusted representative legacy code before acquiring telemetry locks."""

from datetime import datetime
import hashlib

from backend.modernization.runner import LEGACY_MONITOR_PATH, run_legacy_monitor
from backend.reliability import analyze_reliability
from backend.schemas.incident import TelemetryEvent


def evaluate_legacy_telemetry(event: TelemetryEvent, now: datetime) -> tuple[dict, dict]:
    """Return actual monitor evidence plus independent reliability assessment.

    Only the fixed, trusted baseline fixture is executed here. Candidate code
    continues to require the separate Docker verification/approval workflow.
    Call this outside the shared incident lock: execution has a bounded timeout.
    """
    sampled_at = event.model_dump(mode="json")["observed_at"]
    revision = None
    try:
        revision = "sha256:" + hashlib.sha256(LEGACY_MONITOR_PATH.read_bytes()).hexdigest()
        result = run_legacy_monitor(event)
        if (not isinstance(result, dict) or result.get("status") not in ("NORMAL", "WARNING")
                or result.get("device_id") != event.device_id
                or result.get("sampled_at") != sampled_at or result.get("source_revision") != revision):
            raise ValueError("Legacy result did not match its input/revision")
        legacy = {
            "status": result["status"], "source_revision": result["source_revision"],
            "sampled_at": result["sampled_at"], "health": "OK", "execution_status": "COMPLETED",
            "target_binding": "representative_fixture", "error": None,
        }
    except Exception:
        # The legacy boundary must not suppress deterministic fault alerts.
        # Subprocess stderr/exception text can contain local paths or secrets.
        legacy = {
            "status": "UNKNOWN", "source_revision": revision, "sampled_at": sampled_at,
            "health": "DEGRADED", "execution_status": "FAILED", "target_binding": "representative_fixture",
            "error": {"code": "LEGACY_MONITOR_UNAVAILABLE", "message": "Legacy monitor could not produce a verified result"},
        }
    computed = analyze_reliability(
        event.temperature_c, event.cooling_fault, event.observed_at, now, legacy_monitor=legacy,
    )
    return legacy, computed
