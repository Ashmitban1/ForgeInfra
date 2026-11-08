"""Tiger Data/TimescaleDB telemetry storage. No in-memory history masquerades as SQL."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import os
import re
from threading import Lock

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from backend.storage.lifecycle import fingerprint
from backend.storage.mongo import StorageUnavailable


class TigerTelemetryStore:
    def __init__(self, uri: str, schema: str = "factoryos"):
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", schema):
            raise StorageUnavailable("Invalid Tiger Data schema")
        try:
            params = conninfo_to_dict(uri)
        except psycopg.Error:
            raise StorageUnavailable("Invalid Tiger Data configuration") from None
        # Default to server identity verification; never permit plaintext fallback.
        if params.get("sslmode", "verify-full") not in {"require", "verify-ca", "verify-full"}:
            raise StorageUnavailable("Tiger Data requires TLS")
        self._params = {**params, "sslmode": params.get("sslmode", "verify-full"),
                        "connect_timeout": 3, "application_name": "factoryos",
                        "tcp_user_timeout": 5000,
                        "options": "-c statement_timeout=3000 -c lock_timeout=1000 -c timezone=UTC"}
        self.schema = schema
        self.table = sql.Identifier(schema, "telemetry")
        self._lock = Lock()
        self._flush_lock = Lock()
        self._pending: dict[str, dict] = {}
        self._last_error: str | None = None

    def _connect(self):
        return psycopg.connect(**self._params, row_factory=dict_row)

    def initialize(self) -> None:
        try:
            with self._connect() as conn:
                if conn.execute("SELECT extversion FROM pg_extension WHERE extname='timescaledb'").fetchone() is None:
                    raise StorageUnavailable("Tiger Data requires the TimescaleDB extension")
                conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
                conn.execute(sql.SQL("""
                    CREATE TABLE IF NOT EXISTS {} (
                        observed_at TIMESTAMPTZ NOT NULL,
                        event_id TEXT NOT NULL,
                        received_at TIMESTAMPTZ NOT NULL,
                        source_kind TEXT NOT NULL,
                        source_id TEXT NOT NULL,
                        sequence BIGINT,
                        temperature_c DOUBLE PRECISION,
                        humidity_pct DOUBLE PRECISION,
                        cooling_fault BOOLEAN,
                        fault_is_simulated BOOLEAN,
                        cpu_utilization_pct DOUBLE PRECISION,
                        memory_utilization_pct DOUBLE PRECISION,
                        memory_total_bytes BIGINT,
                        memory_available_bytes BIGINT,
                        memory_used_bytes BIGINT,
                        status TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        PRIMARY KEY (observed_at, event_id)
                    )
                """).format(self.table))
                conn.execute("SELECT create_hypertable(%s::regclass, 'observed_at', if_not_exists => TRUE)",
                             (f"{self.schema}.telemetry",))
                conn.execute(sql.SQL("CREATE INDEX IF NOT EXISTS telemetry_source_time_idx ON {} "
                                     "(source_kind, source_id, observed_at DESC)").format(self.table))
        except psycopg.Error:
            raise StorageUnavailable("Tiger Data initialization unavailable") from None

    def queue_arduino(self, receipt: dict) -> None:
        sample = deepcopy(receipt)
        hw = sample["hardware"]
        identity = {"source_kind": hw["source_kind"], "source_id": sample["device_id"],
                    "sequence": hw["sequence"], "observed_at": hw["observed_at"]}
        row = {**identity, "event_id": fingerprint(identity), "received_at": hw["received_at"],
               "temperature_c": hw["temperature_c"], "humidity_pct": hw["humidity_pct"],
               "cooling_fault": hw["cooling_fault"], "fault_is_simulated": hw["fault_is_simulated"],
               "status": "OK", "payload": sample}
        with self._lock:
            self._pending.setdefault(row["event_id"], row)

    def queue_host(self, metrics: dict) -> None:
        sample = deepcopy(metrics)
        identity = {"source_kind": "host_system", "source_id": sample["source"]["host_id"],
                    "observed_at": sample["observed_at"]}
        cpu, memory = sample["cpu"] or {}, sample["memory"] or {}
        row = {**identity, "event_id": fingerprint(identity),
               "received_at": datetime.now(timezone.utc).isoformat(),
               "cpu_utilization_pct": cpu.get("utilization_pct"),
               "memory_utilization_pct": memory.get("utilization_pct"),
               "memory_total_bytes": memory.get("total_bytes"),
               "memory_available_bytes": memory.get("available_bytes"),
               "memory_used_bytes": memory.get("used_bytes"),
               "status": sample["status"], "payload": sample}
        with self._lock:
            self._pending.setdefault(row["event_id"], row)

    def flush(self) -> bool:
        if not self._flush_lock.acquire(blocking=False):
            return False
        try:
            with self._lock:
                batch = list(self._pending.items())[:100]
            if not batch:
                return True
            columns = ["observed_at", "event_id", "received_at", "source_kind", "source_id",
                       "sequence", "temperature_c", "humidity_pct", "cooling_fault",
                       "fault_is_simulated", "cpu_utilization_pct", "memory_utilization_pct",
                       "memory_total_bytes", "memory_available_bytes", "memory_used_bytes",
                       "status", "payload"]
            # One bounded batch statement, not N independently timed statements.
            values = sql.SQL(", ").join(
                sql.SQL("({})").format(sql.SQL(", ").join(sql.Placeholder() for _ in columns))
                for _ in batch
            )
            statement = sql.SQL("INSERT INTO {} ({}) VALUES {} "
                                "ON CONFLICT (observed_at, event_id) DO NOTHING").format(
                self.table, sql.SQL(", ").join(map(sql.Identifier, columns)), values,
            )
            with self._connect() as conn:
                conn.execute(statement, tuple(
                    Jsonb(row["payload"]) if name == "payload" else row.get(name)
                    for _, row in batch for name in columns))
            # Remove only AFTER transaction commit succeeds; uncertain commit is
            # safely retried through the hypertable's composite unique key.
            with self._lock:
                for event_id, row in batch:
                    if self._pending.get(event_id) is row:
                        self._pending.pop(event_id)
                self._last_error = None
            return True
        except psycopg.Error:
            with self._lock:
                self._last_error = "tigerdata_unavailable"
            return False
        finally:
            self._flush_lock.release()

    def history(self, source_kind: str, source_id: str, start: datetime, end: datetime,
                limit: int) -> list[dict]:
        try:
            with self._connect() as conn:
                rows = conn.execute(sql.SQL(
                    "SELECT observed_at, received_at, event_id, status, payload FROM {} "
                    "WHERE source_kind=%s AND source_id=%s AND observed_at >= %s AND observed_at < %s "
                    "ORDER BY observed_at DESC, event_id DESC LIMIT %s"
                ).format(self.table), (source_kind, source_id, start, end, limit)).fetchall()
            return list(reversed(rows))
        except psycopg.Error:
            raise StorageUnavailable("Tiger Data history unavailable") from None

    def summary(self, source_kind: str, source_id: str, start: datetime, end: datetime,
                bucket_seconds: int) -> list[dict]:
        try:
            with self._connect() as conn:
                return conn.execute(sql.SQL("""
                    SELECT time_bucket(%s::interval, observed_at) AS bucket_start,
                           count(*) AS sample_count,
                           avg(temperature_c) AS temperature_c_avg,
                           min(temperature_c) AS temperature_c_min,
                           max(temperature_c) AS temperature_c_max,
                           avg(humidity_pct) AS humidity_pct_avg,
                           avg(cpu_utilization_pct) AS cpu_utilization_pct_avg,
                           avg(memory_utilization_pct) AS memory_utilization_pct_avg,
                           count(*) FILTER (WHERE cooling_fault) AS fault_count,
                           count(*) FILTER (WHERE status <> 'OK') AS collection_error_count
                    FROM {} WHERE source_kind=%s AND source_id=%s
                      AND observed_at >= %s AND observed_at < %s
                    GROUP BY bucket_start ORDER BY bucket_start LIMIT 10080
                """).format(self.table),
                    (timedelta(seconds=bucket_seconds), source_kind, source_id, start, end)).fetchall()
        except psycopg.Error:
            raise StorageUnavailable("Tiger Data summary unavailable") from None

    def health(self) -> dict:
        with self._lock:
            return {"backend": "tigerdata", "status": "DEGRADED" if self._last_error else (
                "PENDING" if self._pending else "OK"), "pending_samples": len(self._pending),
                "error": self._last_error}


def tiger_from_environment() -> TigerTelemetryStore | None:
    # Mongo configuration loader already loads backend/root dotenv during lifespan.
    uri = os.getenv("TIGERDATA_DATABASE_URL", "").strip()
    if not uri:
        return None
    return TigerTelemetryStore(uri, os.getenv("TIGERDATA_SCHEMA", "factoryos"))
