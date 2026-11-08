"""UNO R3 Serial -> FactoryOS HTTP gateway. Requires physical Arduino hardware.
Run while uvicorn is running, and CLOSE Arduino Serial Monitor first.
"""
import argparse
import json
import time
from datetime import datetime, timezone

import requests
import serial


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, help="COM3 or /dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--url", default="http://127.0.0.1:8000/api/telemetry")
    args = parser.parse_args()
    seq = int(time.time() * 1000)
    with serial.Serial(args.port, args.baud, timeout=5) as board:
        time.sleep(2)  # UNO auto-reset after opening port
        print("Connected:", args.port)
        while True:
            raw = board.readline().decode("utf-8", errors="replace").strip()
            if not raw:
                continue
            try:
                reading = json.loads(raw)
                at = utc_now()  # UNO has no synchronized real-time clock
                event = {
                    "schema_version": "1.0", "device_id": "RACK-01",
                    "source_kind": "arduino_serial", "observed_at": at, "received_at": at,
                    "sequence": seq, "temperature_c": reading["temperature_c"],
                    "humidity_pct": reading["humidity_pct"],
                    "cooling_fault": bool(reading["cooling_fault"]),
                    "fault_is_simulated": True,
                }
                seq += 1
                r = requests.post(args.url, json=event, timeout=10)
                result = r.json()
                print(r.status_code, {
                    "incident_id": result.get("incident_id"),
                    "device_id": event["device_id"], "sequence": event["sequence"],
                    "cooling_fault": event["cooling_fault"],
                    "persistence": r.headers.get("X-FactoryOS-Persistence", "unknown"),
                    "reliability": result.get("reliability"),
                })
                r.raise_for_status()
            except (ValueError, KeyError) as err:
                print("Skipped non-JSON or incomplete serial line:", raw, err)
            except requests.RequestException as err:
                print("POST failed, retry on next sensor reading:", err)


if __name__ == "__main__":
    main()
