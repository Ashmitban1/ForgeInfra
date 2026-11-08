"""Use actual NVIDIA quota for a simulated incident; no Jira/Slack/deploy actions."""

from datetime import datetime, timezone
import json
import time
import uuid


def main() -> int:
    from fastapi.testclient import TestClient
    from backend.modernization.app import app
    from backend.modernization.patching import DEFAULT_OUTPUT_ROOT

    with TestClient(app) as client:
        event = {
            "schema_version": "1.0", "device_id": "SIM-NEMOTRON-" + uuid.uuid4().hex[:8],
            "source_kind": "simulator", "observed_at": datetime.now(timezone.utc).isoformat(),
            "sequence": 1, "temperature_c": 29.4, "humidity_pct": 54,
            "cooling_fault": True, "fault_is_simulated": True,
        }
        ingested = client.post("/api/telemetry", json=event)
        if ingested.status_code != 200:
            print("Simulated telemetry ingestion failed")
            return 1
        incident_id = ingested.json()["incident_id"]
        response = client.post(f"/api/incidents/{incident_id}/investigate")
        if response.status_code != 202:
            print(json.dumps({"status": response.status_code, "error": response.json().get("detail")}))
            return 1
        job_id = response.json()["job_id"]
        previous = None
        deadline = time.monotonic() + 650
        while time.monotonic() < deadline:
            job = client.get("/api/investigations/" + job_id).json()
            state = (job["status"], len(job["tool_calls"]), len(job["provider_calls"]))
            if state != previous:
                print(json.dumps({"job_id": job_id, "status": state[0], "tool_calls": state[1],
                                  "provider_rounds": state[2]}), flush=True)
                previous = state
            if job["status"] not in ("QUEUED", "RUNNING"):
                output = DEFAULT_OUTPUT_ROOT / (job_id + "-live.json")
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
                print(json.dumps({"evidence_file": str(output), "status": job["status"], "error": job["error"]}))
                return 0 if job["status"] == "COMPLETED" else 1
            time.sleep(1)
        print("Live verification exceeded its deadline")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
