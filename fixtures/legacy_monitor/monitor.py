"""Team-authored legacy monitoring fixture; intentionally ignores cooling_fault."""

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
import sys


def evaluate(event: dict) -> dict:
    """Apply the original temperature-only rule to one telemetry record."""
    if not isinstance(event, dict):
        raise ValueError("Expected a JSON object")
    device_id = event.get("device_id")
    if not isinstance(device_id, str) or not device_id.strip():
        raise ValueError("device_id must be a nonempty string")
    sampled_at = event.get("observed_at")
    if not isinstance(sampled_at, str):
        raise ValueError("observed_at must be an ISO timestamp with a timezone")
    timestamp = datetime.fromisoformat(sampled_at.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError("observed_at must include a timezone")
    temperature = event.get("temperature_c")
    if (isinstance(temperature, bool)
            or not isinstance(temperature, (int, float))
            or not math.isfinite(temperature)
            or not -40 <= temperature <= 85):
        raise ValueError("temperature_c must be a finite number between -40 and 85")

    # Original rule: newer fields, including cooling_fault, are ignored.
    status = "WARNING" if temperature > 35 else "NORMAL"
    return {
        "device_id": device_id,
        "status": status,
        "sampled_at": sampled_at,
        "source_revision": "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }


def main() -> int:
    try:
        result = evaluate(json.load(sys.stdin))
    except (ValueError, OverflowError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(result, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
