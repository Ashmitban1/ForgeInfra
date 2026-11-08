"""Person 1 telemetry API with optional MongoDB incident/evidence persistence."""
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
import logging
from threading import Event, Lock, Thread

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware

from backend.schemas.incident import TelemetryEvent
from backend.reliability import analyze_reliability
from backend.system_metrics import collect_system_metrics, router as system_metrics_router
from backend.storage.mongo import MongoIncidentStore, store_from_environment
from backend.storage.lifecycle import IncidentUpdate, fingerprint, history_event, utc_now
from backend.storage.tiger import tiger_from_environment
from backend.telemetry_history import router as telemetry_history_router


def _remember_incident(incident: dict, kind: str = "telemetry", event_id: str | None = None,
                       request_hash: str | None = None, note: str | None = None) -> None:
    """Call under _lock; capture a complete lifecycle snapshot without database IO."""
    change = history_event(incident, kind, event_id, request_hash, note)
    _history.setdefault((incident["incident_id"], change["event_id"]), change)
    _fingerprints[incident["incident_id"]] = fingerprint(incident)
    if _store is not None:
        _store.queue(incident, change)


def _capture_incident_changes() -> None:
    """Compatibility bridge for integrations that still mutate the shared dictionary."""
    if _store is None:
        return
    with _lock:
        for incident in _incidents.values():
            if _fingerprints.get(incident["incident_id"]) != fingerprint(incident):
                incident["updated_at"] = utc_now()
                _remember_incident(incident, "observed_update")


def _retry_persistence(stop: Event, store: MongoIncidentStore) -> None:
    while not stop.wait(2):
        _capture_incident_changes()
        store.flush()


def _sample_host_telemetry(stop: Event, store) -> None:
    while not stop.is_set():
        store.queue_host(collect_system_metrics())
        store.flush()
        if stop.wait(5):
            break


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _store, _next_incident_number
    store = None
    tiger = None
    stop = Event()
    worker = None
    sampler = None
    app.state.telemetry_store = None
    try:
        store = store_from_environment()
        tiger = tiger_from_environment()
        if tiger is not None:
            tiger.initialize()
            app.state.telemetry_store = tiger
        if store is not None:
            # Fail startup rather than present an empty history or reuse IDs when
            # a configured database cannot be read. Driver errors are sanitized.
            restored = store.load_incidents()
            changes = store.load_events()
            # Recover a lifecycle event acknowledged just before a crash that
            # prevented its latest-snapshot upsert from completing.
            records = {row["incident_id"]: row for row in restored}
            recovered = {}
            for change in sorted(changes, key=lambda row: row["recorded_at"]):
                snapshot = change["snapshot"]
                current = records.get(snapshot["incident_id"])
                if current is None or snapshot["updated_at"] > current["updated_at"]:
                    records[snapshot["incident_id"]] = deepcopy(snapshot)
                    recovered[snapshot["incident_id"]] = change
            with _lock:
                _incidents.clear()
                _incidents.update(records)
                _history.clear()
                _history.update({(row["incident_id"], row["event_id"]): row for row in changes})
                _fingerprints.clear()
                _fingerprints.update({iid: fingerprint(row) for iid, row in records.items()})
                numbers = [int(iid.removeprefix("INC-COOLING-")) for iid in _incidents
                           if iid.startswith("INC-COOLING-")
                           and iid.removeprefix("INC-COOLING-").isdigit()]
                _next_incident_number = max(numbers, default=0) + 1
                for row in records.values():
                    hw = row["hardware"]
                    key = (row["device_id"], hw["source_kind"])
                    _latest_sequence[key] = max(_latest_sequence.get(key, -1), hw["sequence"])
            _store = store
            for iid, change in recovered.items():
                store.queue(records[iid], change)
            store.flush()
            worker = Thread(target=_retry_persistence, args=(stop, store), daemon=True)
            worker.start()
        if tiger is not None:
            sampler = Thread(target=_sample_host_telemetry, args=(stop, tiger), daemon=True)
            sampler.start()
        yield
    finally:
        stop.set()
        if worker is not None:
            worker.join()
        if sampler is not None:
            sampler.join()
        if store is not None:
            _capture_incident_changes()
            store.flush()
            if any(store.health()[key] for key in ("pending_incidents", "pending_evidence", "pending_events")):
                logging.getLogger(__name__).warning(
                    "MongoDB writes remain pending at shutdown; durability is not confirmed"
                )
            store.close()
        if tiger is not None:
            tiger.flush()
            if tiger.health()["pending_samples"]:
                logging.getLogger(__name__).warning(
                    "Tiger Data samples remain pending at shutdown; durability is not confirmed"
                )
        app.state.telemetry_store = None
        _store = None

app = FastAPI(title="FactoryOS Telemetry API", version="0.1.0", lifespan=lifespan)
app.state.telemetry_store = None
app.include_router(system_metrics_router)
app.include_router(telemetry_history_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    expose_headers=["X-FactoryOS-Persistence", "X-FactoryOS-Telemetry-Persistence"],
)

_lock = Lock()
_latest: dict = {}
_incidents: dict[str, dict] = {}
_latest_sequence: dict[tuple[str, str], int] = {}
_next_incident_number = 1
_store: MongoIncidentStore | None = None
_history: dict[tuple[str, str], dict] = {}
_fingerprints: dict[str, str] = {}


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@app.get("/health")
def health():
    return {"status": "ok", "service": "factoryos-person1"}


@app.get("/api/storage/health")
def storage_health():
    if _store is None:
        return {"backend": "memory", "status": "DISABLED", "pending_incidents": 0,
                "pending_evidence": 0, "pending_events": 0, "error": None}
    return _store.health()


@app.post("/api/telemetry")
def receive_telemetry(data: TelemetryEvent, response: Response):
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
            _remember_incident(_incidents[current_id])
        # Independent, deterministic alert; MUST NOT rely on model availability.
        should_alert = data_is_fresh and computed["expected_status"] == "WARNING"
        receipt = {
            "received": True,
            "incident_id": current_id,
            "should_alert": should_alert,
            **result,
        }
    # Database IO is outside the telemetry lock. Failed writes remain queued for
    # the retry worker, and the deterministic alert still returns to the caller.
    if _store is not None:
        _store.flush()
        state = _store.health()
        response.headers["X-FactoryOS-Persistence"] = (
            ("persisted" if current_id is not None else "not_applicable")
            if state["status"] == "OK" else "pending"
        )
    else:
        response.headers["X-FactoryOS-Persistence"] = "disabled"
    tiger = getattr(app.state, "telemetry_store", None)
    if tiger is not None:
        tiger.queue_arduino(receipt)
        tiger.flush()
        response.headers["X-FactoryOS-Telemetry-Persistence"] = (
            "persisted" if tiger.health()["status"] == "OK" else "pending"
        )
    return receipt


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


def update_incident(incident_id: str, update: IncidentUpdate) -> dict:
    """Shared P2/P3 update boundary: idempotent, snapshot-based, no provider actions."""
    request_hash = fingerprint(update.model_dump())
    with _lock:
        incident = _incidents.get(incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="Incident not found")
        prior = _history.get((incident_id, update.event_id))
        if prior is not None:
            if prior["request_hash"] != request_hash:
                raise HTTPException(status_code=409, detail="event_id already used for different content")
            return deepcopy(incident)
        if update.event_id.startswith("snapshot-"):
            raise HTTPException(status_code=422, detail="snapshot- event IDs are reserved")
        if update.expected_updated_at is not None and update.expected_updated_at != incident["updated_at"]:
            raise HTTPException(status_code=409, detail="Incident changed; fetch it again before updating")
        if update.status == "OPEN" and any(
            row["device_id"] == incident["device_id"] and row["status"] == "OPEN"
            and row["incident_id"] != incident_id for row in _incidents.values()
        ):
            raise HTTPException(status_code=409, detail="This device already has another OPEN incident")
        changes = update.model_dump(exclude_none=True, exclude={"event_id", "expected_updated_at", "note"})
        for field, value in changes.items():
            if isinstance(value, dict):
                incident[field].update(deepcopy(value))
            else:
                incident[field] = value
        incident["updated_at"] = utc_now()
        kind = "resolution" if update.status == "RESOLVED" else (
            "reopen" if update.status == "OPEN" else "update"
        )
        _remember_incident(incident, kind, update.event_id, request_hash, update.note)
        return deepcopy(incident)


@app.post("/api/incidents/{incident_id}/updates")
def post_incident_update(incident_id: str, update: IncidentUpdate, response: Response):
    result = update_incident(incident_id, update)
    if _store is not None:
        _store.flush()
        response.headers["X-FactoryOS-Persistence"] = (
            "persisted" if _store.health()["status"] == "OK" else "pending"
        )
    else:
        response.headers["X-FactoryOS-Persistence"] = "disabled"
    return result


@app.get("/api/incidents/{incident_id}/history")
def get_incident_history(incident_id: str, limit: int = Query(default=100, ge=1, le=500)):
    with _lock:
        if incident_id not in _incidents:
            raise HTTPException(status_code=404, detail="Incident not found")
        changes = sorted((row for (iid, _), row in _history.items() if iid == incident_id),
                         key=lambda row: row["recorded_at"])
        return {"incident_id": incident_id, "total": len(changes), "events": deepcopy(changes[-limit:])}
