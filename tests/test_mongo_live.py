"""Opt-in real MongoDB test: two independent Python processes, no shared cache."""
import os
import uuid
from datetime import datetime, timezone

import pytest
from pymongo import MongoClient
from pymongo.errors import PyMongoError
import requests
from live_backend import running_backend


@pytest.mark.skipif(not os.getenv("FACTORYOS_TEST_MONGODB_URI"),
                    reason="Set FACTORYOS_TEST_MONGODB_URI to run real MongoDB restart verification")
def test_real_mongodb_survives_process_restart():
    uri = os.environ["FACTORYOS_TEST_MONGODB_URI"]
    database = "factoryos_restart_test_" + uuid.uuid4().hex
    env = dict(os.environ, MONGODB_URI=uri, MONGODB_DATABASE=database, TIGERDATA_DATABASE_URL="")
    client = None
    connected = False
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=3000, timeoutMS=5000)
        client.admin.command("ping")
        connected = True
        with running_backend(env) as base:
            response = requests.post(base + "/api/telemetry", json={
                "device_id": "TEST-REAL-RESTART", "source_kind": "simulator",
                "observed_at": datetime.now(timezone.utc).isoformat(), "sequence": 1,
                "temperature_c": 29.4, "humidity_pct": 54, "cooling_fault": True,
            }, timeout=15)
            assert response.status_code == 200
            assert response.headers["x-factoryos-persistence"] == "persisted"
            iid = response.json()["incident_id"]
            update = requests.post(base + f"/api/incidents/{iid}/updates", json={
                "event_id": "live-investigation", "investigation": {
                    "status": "COMPLETE", "findings": ["Live storage test, not an AI call"]},
            }, timeout=15)
            assert update.status_code == 200
            assert update.headers["x-factoryos-persistence"] == "persisted"
            resolution = requests.post(base + f"/api/incidents/{iid}/updates", json={
                "event_id": "live-resolution", "status": "RESOLVED", "note": "Storage test complete",
            }, timeout=15)
            assert resolution.headers["x-factoryos-persistence"] == "persisted"
        # The first backend process is gone. No telemetry is resubmitted.
        with running_backend(env) as base:
            restored = requests.get(base + f"/api/incidents/{iid}", timeout=15)
            assert restored.status_code == 200
            assert restored.json() == resolution.json()
            history = requests.get(base + f"/api/incidents/{iid}/history", timeout=15).json()
            assert [row["kind"] for row in history["events"]] == ["telemetry", "update", "resolution"]
        assert client[database].incidents.count_documents({}) == 1
        assert client[database].reliability_evidence.count_documents({}) == 1
        assert client[database].reliability_evidence.find_one()["reliability"]["reasons"] == ["legacy_missed_fault"]
        assert client[database].incident_events.count_documents({}) == 3
    except PyMongoError:
        pytest.fail("Real MongoDB connection/operation failed; check the test URI and Atlas network access", pytrace=False)
    finally:
        if connected:
            try:
                # Only the UUID-named database created by THIS test is removed.
                client.drop_database(database)
            except PyMongoError:
                pass
        if client is not None:
            client.close()
