"""Opt-in real Tiger Data write/history/time_bucket and backend restart check."""
from datetime import datetime, timedelta, timezone
import os
import uuid

import psycopg
from psycopg import sql
import pytest
import requests

from backend.storage.tiger import TigerTelemetryStore
from live_backend import running_backend


@pytest.mark.skipif(not os.getenv("FACTORYOS_TEST_TIGERDATA_URL"),
                    reason="Set FACTORYOS_TEST_TIGERDATA_URL for real Tiger Data verification")
def test_real_tiger_history_buckets_deduplication_and_restart():
    uri = os.environ["FACTORYOS_TEST_TIGERDATA_URL"]
    schema = "factoryos_test_" + uuid.uuid4().hex
    env = dict(os.environ, MONGODB_URI="", TIGERDATA_DATABASE_URL=uri, TIGERDATA_SCHEMA=schema)
    store = TigerTelemetryStore(uri, schema)
    base_time = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=1)
    bounds = {"source_kind": "simulator", "source_id": "TEST-TIGER-LIVE",
              "start": (base_time - timedelta(minutes=1)).isoformat(),
              "end": (base_time + timedelta(minutes=2)).isoformat()}
    created = False
    try:
        store.initialize()
        created = True
        with running_backend(env) as base:
            for sequence, temperature in enumerate([20.0, 30.0], 1):
                response = requests.post(base + "/api/telemetry", json={
                    "device_id": "TEST-TIGER-LIVE", "source_kind": "simulator", "sequence": sequence,
                    "observed_at": (base_time + timedelta(seconds=sequence)).isoformat(),
                    "temperature_c": temperature, "humidity_pct": 50, "cooling_fault": sequence == 2,
                    "fault_is_simulated": True,
                }, timeout=20)
                assert response.status_code == 200
                assert response.headers["x-factoryos-telemetry-persistence"] == "persisted"
                # Exercise the actual SQL unique key on a repeated write.
                store.queue_arduino(response.json())
                assert store.flush()
            host = requests.get(base + "/api/system/metrics", timeout=20)
            assert host.status_code == 200
            host_id = host.json()["source"]["host_id"]
        with running_backend(env) as base:
            history = requests.get(base + "/api/telemetry/history", params=bounds, timeout=15)
            assert history.status_code == 200
            assert len(history.json()["samples"]) == 2
            assert [row["payload"]["hardware"]["temperature_c"] for row in history.json()["samples"]] == [20.0, 30.0]
            summary = requests.get(base + "/api/telemetry/summary", params={**bounds, "bucket_seconds": 60}, timeout=15)
            assert summary.status_code == 200
            bucket = summary.json()["buckets"][0]
            assert bucket["sample_count"] == 2
            assert bucket["temperature_c_avg"] == 25.0
            assert bucket["fault_count"] == 1
            assert bucket["cpu_utilization_pct_avg"] is None
            host_history = requests.get(base + "/api/telemetry/history", params={
                "source_kind": "host_system", "source_id": host_id,
            }, timeout=15)
            assert len(host_history.json()["samples"]) >= 1
        with store._connect() as conn:
            row = conn.execute("SELECT count(*) AS count FROM timescaledb_information.hypertables "
                               "WHERE hypertable_schema=%s AND hypertable_name='telemetry'", (schema,)).fetchone()
            assert row["count"] == 1
    except psycopg.Error:
        pytest.fail("Live Tiger Data operation failed; check service credentials, TLS and extension", pytrace=False)
    finally:
        if created:
            try:
                with store._connect() as conn:
                    # Only this test's generated schema is removed, never user tables.
                    conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            except psycopg.Error:
                pass
