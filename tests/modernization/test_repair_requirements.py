"""Independently authored acceptance criteria for the monitoring repair.

Run with --runxfail to expose the original defect as a real test failure.
The same option will let a future candidate pass without expected-failure marks.
"""

import pytest

from backend.modernization.runner import run_legacy_monitor
from backend.schemas.incident import TelemetryEvent


def monitor_event(temperature: float, cooling_fault: bool) -> TelemetryEvent:
    return TelemetryEvent(
        schema_version="1.0",
        device_id="REPAIR-ACCEPTANCE-01",
        source_kind="simulator",
        observed_at="2026-11-07T20:00:00Z",
        sequence=1,
        temperature_c=temperature,
        humidity_pct=54,
        cooling_fault=cooling_fault,
        fault_is_simulated=True,
    )


@pytest.mark.parametrize(
    "temperature,cooling_fault,required_status",
    [
        pytest.param(29.4, False, "NORMAL", id="healthy"),
        pytest.param(36, False, "WARNING", id="high-temperature"),
        pytest.param(35, False, "NORMAL", id="strict-threshold-boundary"),
        pytest.param(36, True, "WARNING", id="high-temperature-with-fault"),
    ],
)
def test_monitor_preserves_temperature_behavior(temperature, cooling_fault, required_status):
    result = run_legacy_monitor(monitor_event(temperature, cooling_fault))
    assert result["status"] == required_status


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Known original defect: a cooling fault below the temperature threshold is ignored",
)
def test_cooling_fault_requires_warning():
    result = run_legacy_monitor(monitor_event(29.4, True))
    assert result["status"] == "WARNING", (
        "Cooling fault must produce WARNING at 29.4 C; "
        f"monitor returned {result['status']} ({result['source_revision']})"
    )
