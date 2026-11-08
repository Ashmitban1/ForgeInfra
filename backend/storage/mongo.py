"""Optional incident snapshots and immutable reliability evidence in MongoDB."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from threading import Lock

from dotenv import load_dotenv
from pymongo import MongoClient, timeout
from pymongo.errors import PyMongoError
from pymongo.write_concern import WriteConcern
from backend.storage.lifecycle import history_event


class StorageUnavailable(RuntimeError):
    """Safe public error: never include connection strings or driver diagnostics."""


class MongoIncidentStore:
    def __init__(self, client: MongoClient, database: str):
        self.client = client
        db = client.get_database(database, write_concern=WriteConcern(w="majority"))
        self.incidents = db["incidents"]
        self.evidence = db["reliability_evidence"]
        self.events = db["incident_events"]
        self._lock = Lock()
        self._flush_lock = Lock()
        self._pending_incidents: dict[str, dict] = {}
        self._pending_evidence: dict[str, dict] = {}
        self._pending_events: dict[str, dict] = {}
        self._last_error: str | None = None

    def load_incidents(self) -> list[dict]:
        try:
            self.client.admin.command("ping")
            return list(self.incidents.find({}, {"_id": 0}))
        except PyMongoError:
            raise StorageUnavailable("MongoDB incident retrieval unavailable") from None

    def load_events(self) -> list[dict]:
        try:
            return list(self.events.find({}, {"_id": 0}))
        except PyMongoError:
            raise StorageUnavailable("MongoDB lifecycle retrieval unavailable") from None

    def queue(self, incident: dict, lifecycle_event: dict | None = None) -> None:
        """Capture evidence before later telemetry mutates the canonical incident."""
        snapshot = deepcopy(incident)
        event = {
            "schema_version": snapshot["schema_version"],
            "incident_id": snapshot["incident_id"],
            "device_id": snapshot["device_id"],
            "hardware": snapshot["hardware"],
            "legacy_monitor": snapshot["legacy_monitor"],
            "expected_status": snapshot["expected_status"],
            "reliability": snapshot["reliability"],
        }
        identity = [snapshot["incident_id"], snapshot["created_at"],
                    snapshot["device_id"], snapshot["hardware"]["source_kind"],
                    snapshot["hardware"]["sequence"], snapshot["hardware"]["observed_at"]]
        evidence_id = hashlib.sha256(json.dumps(identity).encode("utf-8")).hexdigest()
        change = deepcopy(lifecycle_event) if lifecycle_event is not None else history_event(snapshot)
        change_id = hashlib.sha256(json.dumps([
            snapshot["incident_id"], snapshot["created_at"], change["event_id"],
        ]).encode("utf-8")).hexdigest()
        with self._lock:
            self._pending_incidents[snapshot["incident_id"]] = snapshot
            self._pending_evidence.setdefault(evidence_id, event)
            self._pending_events.setdefault(change_id, change)

    def flush(self) -> bool:
        with timeout(3):
            return self._flush_pending()

    def _flush_pending(self) -> bool:
        """Idempotently retry pending writes; never hold the telemetry lock here."""
        if not self._flush_lock.acquire(blocking=False):
            return False
        try:
            with self._lock:
                evidence = list(self._pending_evidence.items())
                incidents = list(self._pending_incidents.items())
                events = list(self._pending_events.items())
            # Evidence first: an incident's acknowledged snapshot has its evidence.
            for evidence_id, event in evidence:
                self.evidence.update_one(
                    {"_id": evidence_id}, {"$setOnInsert": event}, upsert=True,
                )
                with self._lock:
                    self._pending_evidence.pop(evidence_id, None)
            for change_id, change in events:
                self.events.update_one({"_id": change_id}, {"$setOnInsert": change}, upsert=True)
                with self._lock:
                    self._pending_events.pop(change_id, None)
            for incident_id, snapshot in incidents:
                # Existing v1 fields only; do not erase teammate-owned fields that
                # may have been added independently to the stored document.
                self.incidents.update_one(
                    {"_id": incident_id}, {"$set": snapshot}, upsert=True,
                )
                with self._lock:
                    if self._pending_incidents.get(incident_id) is snapshot:
                        self._pending_incidents.pop(incident_id)
            with self._lock:
                self._last_error = None
            return True
        except PyMongoError:
            with self._lock:
                self._last_error = "mongodb_unavailable"
            return False
        finally:
            self._flush_lock.release()

    def health(self) -> dict:
        with self._lock:
            pending = len(self._pending_incidents) + len(self._pending_evidence) + len(self._pending_events)
            return {
                "backend": "mongodb",
                "status": "DEGRADED" if self._last_error else ("PENDING" if pending else "OK"),
                "pending_incidents": len(self._pending_incidents),
                "pending_evidence": len(self._pending_evidence),
                "pending_events": len(self._pending_events),
                "error": self._last_error,
            }

    def close(self) -> None:
        self.client.close()

    def approval_acknowledged(self, incident_id: str, created_at: str, version: int) -> bool:
        """Read back the exact incarnation/version before authorizing execution."""
        try:
            with timeout(3):
                return self.incidents.find_one(
                    {"_id": incident_id, "created_at": created_at, "approval.version": {"$gte": version}},
                    {"_id": 1},
                ) is not None
        except PyMongoError:
            with self._lock:
                self._last_error = "mongodb_unavailable"
            return False


def store_from_environment() -> MongoIncidentStore | None:
    root = Path(__file__).resolve().parents[2]
    # Process variables take priority. Match teammates' backend/.env convention.
    load_dotenv(root / "backend" / ".env", override=False)
    load_dotenv(root / ".env", override=False)
    uri = os.getenv("MONGODB_URI", "").strip()
    if not uri:
        return None
    try:
        client = MongoClient(
            uri, serverSelectionTimeoutMS=2000, connectTimeoutMS=2000,
            socketTimeoutMS=2000, timeoutMS=3000,
        )
        database = os.getenv("MONGODB_DATABASE", "factoryos").strip()
        try:
            return MongoIncidentStore(client, database)
        except (PyMongoError, ValueError):
            client.close()
            raise
    except (PyMongoError, ValueError):
        raise StorageUnavailable("MongoDB configuration invalid or unavailable") from None
