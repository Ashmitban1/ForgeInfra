"""Deterministic checks, independent of legacy execution and AI availability."""
from datetime import datetime, timezone

STALE_AFTER_SECONDS = 90


def legacy_monitor_stub(temperature_c: float) -> str:
    """Placeholder representing old temperature-only logic; not Northmark code."""
    return "WARNING" if temperature_c > 35 else "NORMAL"


def independent_expected_status(temperature_c: float, cooling_fault: bool) -> str:
    # Simulated fault switch indicates an explicit fault in our DEMO scenario.
    return "WARNING" if (cooling_fault or temperature_c > 35) else "NORMAL"


def analyze_reliability(temperature_c: float, cooling_fault: bool,
                        observed_at: datetime, now: datetime, *,
                        legacy_monitor: dict | None = None) -> dict:
    """Compare actual monitor evidence with independent expected behavior.

    Four-argument callers retain the original characterization behavior. Live
    ingestion supplies an explicit result from ``evaluate_legacy_telemetry``;
    an unavailable result is UNKNOWN, never a successful NORMAL fallback.
    """
    if observed_at.tzinfo is None:
        raise ValueError("observed_at needs timezone information")
    reasons = []
    age = (now - observed_at.astimezone(timezone.utc)).total_seconds()
    if age > STALE_AFTER_SECONDS:
        reasons.append("stale_hardware_reading")
    if age < -10:
        reasons.append("future_observation_timestamp")
    legacy = (legacy_monitor_stub(temperature_c) if legacy_monitor is None
              else legacy_monitor.get("status"))
    expected = independent_expected_status(temperature_c, cooling_fault)
    available = legacy in ("NORMAL", "WARNING")
    mismatch = legacy != expected if available else None
    if not available:
        legacy = "UNKNOWN"
        reasons.append("legacy_monitor_unavailable")
    elif mismatch:
        reasons.append("legacy_missed_fault")
    return {
        "legacy_status": legacy,
        "expected_status": expected,
        "mismatch": mismatch,
        "reasons": reasons,
        "evidence_quality": "PARTIAL" if reasons else "CURRENT",
        "observation_age_seconds": round(age, 2),
    }
