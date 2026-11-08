"""The ingestion adapter executes the real baseline and fails without fake health."""

from datetime import datetime, timedelta, timezone
import hashlib
import subprocess

import pytest

from backend import legacy_runtime
from backend.modernization.runner import LEGACY_MONITOR_PATH, LegacyMonitorError
from backend.reliability import analyze_reliability
from backend.schemas.incident import TelemetryEvent


def event(temperature=29.4, fault=True, age=0):
    now = datetime.now(timezone.utc)
    return TelemetryEvent(
        device_id="SIM-LEGACY-RUNTIME", source_kind="simulator",
        observed_at=now - timedelta(seconds=age), sequence=1,
        temperature_c=temperature, humidity_pct=54, cooling_fault=fault, fault_is_simulated=True,
    ), now


@pytest.mark.parametrize("temperature,fault,status,expected,mismatch", [
    (29.4, False, "NORMAL", "NORMAL", False),
    (29.4, True, "NORMAL", "WARNING", True),
    (36, False, "WARNING", "WARNING", False),
    (35, False, "NORMAL", "NORMAL", False),
])
def test_actual_legacy_execution_and_revision(temperature, fault, status, expected, mismatch):
    sample, now = event(temperature, fault)
    legacy, computed = legacy_runtime.evaluate_legacy_telemetry(sample, now)
    assert legacy["status"] == status and legacy["execution_status"] == "COMPLETED"
    assert legacy["source_revision"] == "sha256:" + hashlib.sha256(LEGACY_MONITOR_PATH.read_bytes()).hexdigest()
    assert legacy["sampled_at"] == sample.model_dump(mode="json")["observed_at"]
    assert computed["expected_status"] == expected and computed["mismatch"] is mismatch


@pytest.mark.parametrize("failure", [
    LegacyMonitorError("private runner stderr"),
    subprocess.TimeoutExpired("private command", 5),
    OSError("private executable path"),
    RuntimeError("private unexpected runner failure"),
])
def test_failed_monitor_is_unknown_and_fault_alert_remains_independent(monkeypatch, failure):
    def unavailable(sample):
        raise failure
    monkeypatch.setattr(legacy_runtime, "run_legacy_monitor", unavailable)
    sample, now = event()
    legacy, computed = legacy_runtime.evaluate_legacy_telemetry(sample, now)
    assert legacy["status"] == "UNKNOWN" and legacy["health"] == "DEGRADED"
    assert legacy["execution_status"] == "FAILED"
    assert computed["expected_status"] == "WARNING"
    assert computed["mismatch"] is None
    assert computed["reasons"] == ["legacy_monitor_unavailable"]
    assert "private" not in str(legacy) + str(computed)


def test_failure_does_not_invent_a_healthy_monitor_result(monkeypatch):
    monkeypatch.setattr(legacy_runtime, "run_legacy_monitor", lambda sample: {})
    sample, now = event(fault=False)
    legacy, computed = legacy_runtime.evaluate_legacy_telemetry(sample, now)
    assert legacy["status"] == "UNKNOWN" and computed["mismatch"] is None
    assert computed["expected_status"] == "NORMAL"
    assert "legacy_monitor_unavailable" in computed["reasons"]


def test_stale_reading_and_monitor_failure_are_both_preserved(monkeypatch):
    def unavailable(sample):
        raise LegacyMonitorError("test failure")
    monkeypatch.setattr(legacy_runtime, "run_legacy_monitor", unavailable)
    sample, now = event(age=120)
    legacy, computed = legacy_runtime.evaluate_legacy_telemetry(sample, now)
    assert computed["reasons"] == ["stale_hardware_reading", "legacy_monitor_unavailable"]
    assert computed["expected_status"] == "WARNING" and computed["mismatch"] is None


def test_explicit_monitor_result_is_used_instead_of_temperature_stub():
    sample, now = event()
    computed = analyze_reliability(sample.temperature_c, sample.cooling_fault, sample.observed_at, now,
                                   legacy_monitor={"status": "WARNING"})
    assert computed["legacy_status"] == "WARNING" and computed["mismatch"] is False
    assert computed["reasons"] == []
