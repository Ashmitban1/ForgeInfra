"""Import a GET /api/incidents backup without changing incident identities."""
import argparse
import json
from pathlib import Path

from backend.schemas.incident import TelemetryEvent
from backend.storage.mongo import MongoIncidentStore, StorageUnavailable, store_from_environment


def import_incidents(payload: dict, store: MongoIncidentStore) -> int:
    rows = payload["incidents"]
    existing = {row["incident_id"]: row for row in store.load_incidents()}
    seen = set()
    for row in rows:
        iid = row["incident_id"]
        if iid in seen:
            raise ValueError("Duplicate incident ID in backup")
        seen.add(iid)
        TelemetryEvent.model_validate({
            "schema_version": row["schema_version"], "device_id": row["device_id"],
            **row["hardware"],
        })
        # Only new incidents or exact reimports: never overwrite newer DB state.
        if iid in existing and existing[iid] != row:
            raise ValueError("Backup conflicts with an existing MongoDB incident; import aborted")
        for field in ("created_at", "status", "severity", "updated_at", "legacy_monitor",
                      "expected_status", "reliability", "investigation", "decision_review",
                      "integrations"):
            if field not in row:
                raise ValueError("Backup is missing an incident field")
    for row in rows:
        store.queue(row)
    if not store.flush() or store.health()["status"] != "OK":
        raise StorageUnavailable("Backup import is not confirmed; safely retry the same file")
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, type=Path)
    args = parser.parse_args()
    store = None
    try:
        store = store_from_environment()
        if store is None:
            raise ValueError("Set MONGODB_URI before importing")
        payload = json.loads(args.file.read_text(encoding="utf-8-sig"))
        count = import_incidents(payload, store)
        print(f"Imported {count} incident(s); MongoDB writes confirmed")
    except (StorageUnavailable, ValueError, KeyError, TypeError, OSError):
        parser.exit(1, "Import failed: check configuration, backup shape, and incident conflicts.\n")
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    main()
