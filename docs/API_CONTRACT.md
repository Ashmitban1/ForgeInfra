# FactoryOS API contract (v1)

Base: `http://127.0.0.1:8000`. Owner P1: `GET /health`, `POST /api/telemetry`, `GET /api/telemetry/latest`, `GET /api/incidents`, `GET /api/incidents/{incident_id}` (implemented; optional MongoDB incident persistence). P2 proposed: `POST /api/incidents/{id}/investigate`, `GET /api/incidents/{id}/analysis`, `POST /api/incidents/{id}/repair` (not implemented). P3 proposed: `POST /api/incidents/{id}/notify`, `POST /api/repairs/{id}/approve` (not implemented).

## Input: POST /api/telemetry
```json
{
  "schema_version": "1.0", "device_id": "RACK-01",
  "source_kind": "simulator", "observed_at": "2026-11-07T20:00:00Z",
  "sequence": 1, "temperature_c": 29.4, "humidity_pct": 54,
  "cooling_fault": true, "fault_is_simulated": true
}
```
This is SAMPLE data. The Arduino gateway uses `source_kind: "arduino_serial"`. A source label is not authenticated proof. Post response contains `received`, optional `incident_id`, `should_alert`, `hardware`, `legacy_monitor`, `expected_status`, and `reliability`. A discrepancy should result in `reliability.mismatch: true` and `reliability.reasons` containing `legacy_missed_fault`.

`legacy_monitor.source_revision` presently identifies a placeholder function, **not genuine reverse engineering**. P2 will integrate the actual controlled legacy fixture without breaking this contract.

Incidents include investigation and decision-review fields set `PENDING` until actual Nemotron and Gemini calls, and provider IDs set `null` until Jira/Slack/Solana integrations are working. Memory-mode storage resets whenever FastAPI restarts; configured MongoDB restores saved incidents. Do not deploy publicly without auth.

## Optional MongoDB persistence

Configure backend-only `MONGODB_URI` and optional `MONGODB_DATABASE` (default
`factoryos`). Incident schemas and existing response bodies are unchanged.
Acknowledged incidents and immutable reliability evidence are upserted in MongoDB;
startup restores incident records, saved source sequences and numeric ID allocation.
Healthy/latest telemetry is not restored. Single application worker/writer only.

`POST /api/telemetry` adds the header `X-FactoryOS-Persistence`: `persisted`,
`pending`, `disabled` or `not_applicable` (healthy input without a saved incident).
Runtime outages retain local alerts and queue writes for retry. Queued data is
memory-only and not restart-safe until acknowledged. Configured startup fails
safely if MongoDB is unreachable instead of serving empty history.

`GET /api/storage/health` returns `backend` (`memory` or `mongodb`), `status`
(`DISABLED`, `OK`, `PENDING`, `DEGRADED`), `pending_incidents`, `pending_evidence`,
and `error` (null or safe code `mongodb_unavailable`). Existing `/health` stays
unchanged. See `backend/storage/README.md` for migration, setup and restart proof.

## Host metrics: GET /api/system/metrics

Separate, read-only Person 1 endpoint for the machine running FastAPI. These are
real host CPU/RAM readings, not Arduino readings or evidence of rack cooling health.
It does not create rack incidents or alter the v1 incident schema. Host samples
are optionally stored separately in Tiger Data as described below.

Response fields: `schema_version: "1.0"`, `source` (`kind: "host_system"`,
`host_id`: OS hostname, `collector: "psutil"`, `scope: "backend_host"`,
`is_simulated: false`), UTC `sample_started_at` and `observed_at`, `status`,
`cpu`, `memory`, and `errors`. In a container, host identity/counters reflect
the OS view available to psutil; this is not guaranteed container quota usage.

`cpu` contains `utilization_pct` and `sample_interval_seconds: 0.1` (aggregate
CPU sampled over a positive interval). `memory` contains `total_bytes`,
`available_bytes`, `used_bytes`, and `utilization_pct`, as reported by psutil.
Memory percentage is based on available RAM; OS accounting means `used_bytes`
need not equal total minus available. `observed_at` marks collection completion.

HTTP 200 / `OK`: both collected; HTTP 200 / `DEGRADED`: one collected;
HTTP 503 / `UNAVAILABLE`: neither collected or dependency missing. Failed metrics
are null. `errors` contains safe `{metric, code}` objects (`collection_failed`
or `dependency_unavailable`), never raw exception text. Responses use
`Cache-Control: no-store`. This synchronous endpoint runs outside telemetry locks;
host collection failure does not change `/health` or deterministic rack alerts.
Install the updated requirements before starting the server.

When Tiger Data is configured, host samples from this endpoint are also written
to its hypertable; a separate five-second background sampler runs without UI
polling. Existing host response fields and status codes are unchanged.

Existing `reliability.evidence_quality` is `PARTIAL` whenever any reliability reason
exists, including a fresh `legacy_missed_fault`; otherwise it is `CURRENT`.
Thus `PARTIAL` alone does not indicate a hardware measurement failure.

## Additive lifecycle and telemetry-history interfaces (Person 1)

The user confirmed no conflicting teammate update/history routes are in use.
Existing incident bodies and telemetry input stay unchanged. Full request/response
details, examples, teammate boundaries and live checks are in
[`STORAGE_INTEGRATION.md`](STORAGE_INTEGRATION.md).

- `POST /api/incidents/{id}/updates`: required idempotency `event_id`; optional
  `expected_updated_at`, investigation/decision_review/integrations objects,
  severity, status (`OPEN`/`RESOLVED`), note. Status requests require a reason.
  Shallow merges retain unspecified object keys. Returns the existing incident
  shape. Identical retries are idempotent; changed reuse/stale revision yields 409.
  This records results and does not invoke providers or authorize deployments.
- `GET /api/incidents/{id}/history?limit=100`: `{incident_id,total,events}` with
  complete snapshots, notes, event IDs and timestamps, most recent 1..500 events
  ordered chronologically. Mongo `incident_events` retains the lifecycle.
- Mongo storage health additionally includes `pending_events`; runtime retry
  also captures observed changes made by older in-process integration adapters.
- `GET /api/telemetry/history`: requires `source_kind` and `source_id`; optional
  `start`, `end`, `limit` (1..1000). Returns `{source_kind,source_id,start,end,samples}`.
- `GET /api/telemetry/summary`: same source/time filters and `bucket_seconds`
  (60/300/900/3600). Returns `{source_kind,source_id,start,end,bucket_seconds,buckets}`
  using Tiger Data `time_bucket` averages, extrema and counts.
- Both telemetry queries default to the last hour, require timezone-aware bounds,
  limit windows to seven days, and return 503 if Tiger Data is disabled/unavailable.
  `source_kind` is `arduino_serial`, `simulator` or `host_system`; host sources
  are not added to the existing TelemetryEvent input enum.
- `GET /api/telemetry/storage/health`: `{backend,status,pending_samples,error}`.
  Tiger Data uses `TIGERDATA_DATABASE_URL` and optional `TIGERDATA_SCHEMA`.
  Ingest/host responses expose independent `X-FactoryOS-Telemetry-Persistence`.

All runtime write retry queues are memory-only. Only acknowledged service writes
are restart-safe. Single backend worker/writer remains required. Neither cloud
connection has been verified merely by implementing these interfaces.
