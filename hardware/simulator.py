"""Run before wiring the Arduino; clearly labeled simulated telemetry."""
import argparse
import time
from datetime import datetime, timezone
import requests


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000/api/telemetry")
    parser.add_argument("--mode", choices=["normal", "fault"], default="fault")
    parser.add_argument("--count", type=int, default=1)
    args = parser.parse_args()
    sequence = time.time_ns() // 1_000_000  # monotonic enough for this demo source
    for i in range(args.count):
        at = utc_now()
        event = {
            "schema_version": "1.0", "device_id": "RACK-01",
            "source_kind": "simulator", "observed_at": at, "received_at": at,
            "sequence": sequence + i, "temperature_c": 29.4,
            "humidity_pct": 54.0, "cooling_fault": args.mode == "fault",
            "fault_is_simulated": True,
        }
        response = requests.post(args.url, json=event, timeout=10)
        print(response.status_code, response.json())
        response.raise_for_status()
        if i + 1 < args.count:
            time.sleep(2)


if __name__ == "__main__":
    main()
