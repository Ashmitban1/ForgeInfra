"""Execute the fixed, trusted legacy fixture, never arbitrary model-written code."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from pydantic import ValidationError

from backend.schemas.incident import TelemetryEvent

LEGACY_MONITOR_PATH = Path(__file__).resolve().parents[2] / "fixtures/legacy_monitor/monitor.py"


class LegacyMonitorError(RuntimeError):
    """The fixture failed to execute or returned an invalid result."""


def run_legacy_monitor(event: TelemetryEvent) -> dict:
    """Return the original monitor's decision for validated telemetry.

    Fixed command, minimal environment, isolated Python imports, and a timeout
    constrain this trusted fixture invocation. This is not an OS sandbox.
    """
    expected_revision = "sha256:" + hashlib.sha256(LEGACY_MONITOR_PATH.read_bytes()).hexdigest()
    environment = {key: os.environ[key] for key in ("SYSTEMROOT",) if key in os.environ}
    try:
        process = subprocess.run(
            [sys.executable, "-I", "-S", str(LEGACY_MONITOR_PATH)],
            input=event.model_dump_json(),
            capture_output=True,
            text=True,
            timeout=5,
            cwd=LEGACY_MONITOR_PATH.parent,
            env=environment,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise LegacyMonitorError("Legacy monitor could not complete") from error
    if process.returncode != 0:
        raise LegacyMonitorError(f"Legacy monitor exited {process.returncode}: {process.stderr.strip()}")
    try:
        result = json.loads(process.stdout)
        if not isinstance(result, dict):
            raise ValueError("Expected an object")
        if (result.get("status") not in ("NORMAL", "WARNING")
                or result.get("device_id") != event.device_id
                or result.get("sampled_at") != event.model_dump(mode="json")["observed_at"]
                or result.get("source_revision") != expected_revision):
            raise ValueError("Output did not match the fixture protocol")
    except ValueError as error:
        raise LegacyMonitorError("Invalid legacy monitor output") from error
    return result


def main() -> int:
    try:
        event = TelemetryEvent.model_validate_json(sys.stdin.read())
        print(json.dumps(run_legacy_monitor(event)))
    except (ValidationError, LegacyMonitorError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
