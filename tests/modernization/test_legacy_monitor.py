"""Characterize the original monitor, including its known missed-fault defect."""

import hashlib
import json
import subprocess
import sys

import pytest

from backend.modernization.runner import LEGACY_MONITOR_PATH, run_legacy_monitor
from backend.reliability import independent_expected_status
from backend.schemas.incident import TelemetryEvent


@pytest.mark.parametrize(
    "temperature,fault,legacy_status,expected_status",
    [
        (29.4, False, "NORMAL", "NORMAL"),
        (36, False, "WARNING", "WARNING"),
        (29.4, True, "NORMAL", "WARNING"),
        (36, True, "WARNING", "WARNING"),
        (35, False, "NORMAL", "NORMAL"),
    ],
)
def test_original_monitor_behavior(temperature, fault, legacy_status, expected_status):
    payload = json.loads((LEGACY_MONITOR_PATH.parent / "normal.json").read_text())
    payload.update(temperature_c=temperature, cooling_fault=fault)
    event = TelemetryEvent.model_validate(payload)

    result = run_legacy_monitor(event)

    assert result["status"] == legacy_status
    assert independent_expected_status(temperature, fault) == expected_status
    assert result["device_id"] == event.device_id
    assert result["sampled_at"] == event.model_dump(mode="json")["observed_at"]
    assert result["source_revision"] == (
        "sha256:" + hashlib.sha256(LEGACY_MONITOR_PATH.read_bytes()).hexdigest()
    )


@pytest.mark.parametrize("raw", ["not json", "[]", '{"temperature_c": null}'])
def test_standalone_monitor_rejects_invalid_input(raw):
    result = subprocess.run(
        [sys.executable, str(LEGACY_MONITOR_PATH)],
        input=raw, capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert json.loads(result.stderr)["error"]


@pytest.mark.parametrize("temperature", [None, True, "29.4", float("nan"), 86])
def test_standalone_monitor_rejects_invalid_temperature(temperature):
    payload = json.loads((LEGACY_MONITOR_PATH.parent / "normal.json").read_text())
    payload["temperature_c"] = temperature
    result = subprocess.run(
        [sys.executable, str(LEGACY_MONITOR_PATH)],
        input=json.dumps(payload), capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 1
    assert "temperature_c" in json.loads(result.stderr)["error"]
