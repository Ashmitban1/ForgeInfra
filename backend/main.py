"""Person 1 prototype: telemetry ingestion and shared read-only incident APIs.
Temporary in-memory data: cleared on server restart. Do not present it as durable storage.
"""
from datetime import datetime, timezone
from threading import Lock

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.schemas.incident import TelemetryEvent
from backend.reliability import analyze_reliability

app = FastAPI(title="FactoryOS Telemetry API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_lock = Lock()
_latest: dict = {}
_incidents: dict[str, dict] = {}
_latest_sequence: dict[tuple[str, str], int] = {}
_next_incident_number = 1


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@app.get("/health")
def health():
    return {"status": "ok", "service": "factoryos-person1"}


@app.post("/api/telemetry")
def receive_telemetry(data: TelemetryEvent):
    global _next_incident_number
    if data.observed_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="observed_at must include timezone offset")
    received = datetime.now(timezone.utc)
    computed = analyze_reliability(
        data.temperature_c, data.cooling_fault, data.observed_at, received
    )
    # Do not allow stale input to drive a fresh operational alert; keep discrepancy for triage.
    data_is_fresh = not any(r in computed["reasons"] for r in
                            ("stale_hardware_reading", "future_observation_timestamp"))
    key = (data.device_id, data.source_kind)
    with _lock:
        last = _latest_sequence.get(key)
        if last is not None and data.sequence <= last:
            raise HTTPException(status_code=409, detail="Duplicate/out-of-order sequence")
        _latest_sequence[key] = data.sequence
        hardware = {
            "temperature_c": data.temperature_c,
            "humidity_pct": data.humidity_pct,
            "cooling_fault": data.cooling_fault,
            "fault_is_simulated": data.fault_is_simulated,
            "source_kind": data.source_kind,
            "observed_at": iso(data.observed_at),
            "received_at": iso(received),
            "sequence": data.sequence,
        }
        result = {
            "schema_version": "1.0",
            "device_id": data.device_id,
            "hardware": hardware,
            "legacy_monitor": {
                "status": computed["legacy_status"],
                "source_revision": "demo-legacy-placeholder-v1",
                "sampled_at": iso(data.observed_at),
            },
            "expected_status": computed["expected_status"],
            "reliability": {
                "mismatch": computed["mismatch"],
                "reasons": computed["reasons"],
                "evidence_quality": computed["evidence_quality"],
                "observation_age_seconds": computed["observation_age_seconds"],
            },
        }
        _latest[data.device_id] = result
        current_id = None
        if computed["reasons"]:
            # Reuse the same open incident for repeated readings from one device.
            for iid, record in _incidents.items():
                if record["device_id"] == data.device_id and record["status"] == "OPEN":
                    current_id = iid
                    break
            if current_id is None:
                current_id = f"INC-COOLING-{_next_incident_number:03d}"
                _next_incident_number += 1
                _incidents[current_id] = {
                    "schema_version": "1.0",
                    "incident_id": current_id,
                    "device_id": data.device_id,
                    "created_at": iso(received),
                    "status": "OPEN",
                    "severity": "HIGH" if data_is_fresh and computed["mismatch"] else "REVIEW",
                    "investigation": {"status": "PENDING", "agent": "nvidia-nemotron",
                                      "tool_calls": [], "findings": [], "evidence_ids": []},
                    "decision_review": {"status": "PENDING", "reviewer": "gemini",
                                        "recommendation": None},
                    "integrations": {"jira_key": None, "jira_url": None,
                                     "slack_message_id": None,
                                     "github_pr_url": None,
                                     "solana_tx_signature": None},
                }
            _incidents[current_id].update(result)
            _incidents[current_id]["updated_at"] = iso(received)
        # Independent, deterministic alert; MUST NOT rely on model availability.
        should_alert = data_is_fresh and computed["expected_status"] == "WARNING"
        return {
            "received": True,
            "incident_id": current_id,
            "should_alert": should_alert,
            **result,
        }


@app.get("/api/telemetry/latest")
def latest_telemetry():
    with _lock:
        return {"devices": list(_latest.values())}


@app.get("/api/incidents")
def get_incidents():
    with _lock:
        return {"incidents": list(_incidents.values())}


@app.get("/api/incidents/{incident_id}")
def get_incident(incident_id: str):
    with _lock:
        incident = _incidents.get(incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="Incident not found")
        return incident
