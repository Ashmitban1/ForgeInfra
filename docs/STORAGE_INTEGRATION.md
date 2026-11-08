# Person 1 storage integration contract

Verification status updated November 8, 2026 (America/Chicago).

Persons 2 and 3: the user confirmed that no additional update/history routes
are already in use. These are additive shared interfaces; your owned modules
were not modified. Existing telemetry input, incident objects and GET wrappers
remain compatible. Use the same FastAPI app/lifespan and a single backend worker.

## Implemented versus verified

| Feature | Implementation | Verification in this workspace |
| --- | --- | --- |
| Mongo incident/evidence upserts | Real PyMongo driver | Automated tests; real Atlas connection/read independently checked; Arduino write/restart user-verified |
| Investigation, update, resolution/reopen history | Shared update API, separate Mongo event collection | Automated lifecycle/restart tests with mongomock |
| Real Mongo backend restart check | Two actual Uvicorn processes, HTTP requests | Opt-in automated test remains separate; user verified real Arduino incidents survive restart |
| Tiger Data time-series writes | Real psycopg SQL, TimescaleDB hypertable | Real host CPU/RAM writes independently verified against cloud |
| Recent history and chart summaries | Source-filtered SQL and `time_bucket` | Real stored host samples retrieved; SQL counts/averages independently checked |
| Real Tiger Data restart/query check | Writes, duplicate retry, restart, mean/count assertions | Real host history retained across two backend processes; opt-in simulator test remains separate |
| Tiger Data physical Arduino OFF/ON/OFF history | Existing serial gateway and source-filtered queries | Not yet verified; latest inspection found no stored Arduino rows |
| AI/provider calls and frontend charts | Not added by Person 1 | No new claim about teammate work |

Credentials remain local and excluded from Git. Latest Tiger configuration
inspection found `TIGER_DATABASE_URL`, while application startup requires
`TIGERDATA_DATABASE_URL`. The real host verification supplied the corrected name
only to temporary backend processes, without changing the credential file. Set
the expected name locally before normal startup. The cloud check created the
hypertable and retained real host data; it did not delete shared data.
Default pytest currently reports 51 passed, two opt-in checks skipped, and one
existing Starlette deprecation warning. Mocked tests and separately observed live
results are distinct evidence; no award eligibility is asserted.

## Incident lifecycle: Person 2 and Person 3

`POST /api/incidents/{incident_id}/updates` records results; it does not call a
model, create a Jira ticket, approve a repair, or deploy code. Request example
(illustrative data, not a model result):

```json
{
  "event_id": "investigation-job-42-result",
  "expected_updated_at": "COPY THE CURRENT INCIDENT updated_at VALUE",
  "investigation": {
    "status": "COMPLETE",
    "findings": ["Replace this with actual tool findings"],
    "tool_calls": [],
    "evidence_ids": []
  }
}
```

- `event_id` is required, length 1..100, characters letters/digits/`.`/`_`/`:`/`-`.
  It is unique within the incident. The `snapshot-` prefix is reserved.
- Identical retries return the current incident without adding another event.
  Reusing an ID for different content returns 409, including after a DB-backed
  restart. Keep the original request payload when retrying an uncertain response.
- Optional `expected_updated_at` enables optimistic concurrency: a stale value
  returns 409. Idempotent retries are checked before the revision check.
- Optional top-level fields: `investigation`, `decision_review`, `integrations`,
  `status`, `severity`, `note`. Unknown top-level keys are rejected. JSON result
  payloads are limited to 100 KB per request. Never put credentials in a result.
- Object fields are shallow-merged into the corresponding existing object:
  unspecified keys survive, supplied list/dictionary values replace that key.
  Integration reference values may be strings or null. This does not validate
  that a claimed provider reference exists; only provider adapters should supply
  their confirmed results.
- Status values: `OPEN`, `RESOLVED`; severity values: existing `HIGH`, `REVIEW`.
  A status request requires a nonblank `note` explaining the action. Reopening
  conflicts if the device already has another OPEN incident.
- Response is the existing incident object; no history array is added to it.
  The persistence header reports acknowledged/pending/disabled just as ingestion.
- No authentication is implemented. These local record updates are not an
  authorized production approval workflow and do not authorize any external action.

Example explicit resolution:

```json
{
  "event_id": "operator-resolution-42",
  "status": "RESOLVED",
  "note": "Operator confirmed the controlled demo recovered"
}
```

Healthy telemetry still does not auto-resolve an incident. Successful repair
tests alone must not imply resolution of an equipment fault.

`GET /api/incidents/{id}/history?limit=100` returns:

```json
{"incident_id":"INC-COOLING-001","total":0,"events":[]}
```

The shape above illustrates an empty history, not a completed live result.
Events are ordered chronologically; limit is 1..500, selecting the most recent
events. Each event includes `event_id`, `incident_id`, `recorded_at`, `kind`,
`request_hash`, `note`, and a complete incident `snapshot`. Kinds include
`telemetry`, `update`, `resolution`, `reopen`, `observed_update`.

In-process callers may use
`backend.main.update_incident(id, IncidentUpdate(...))`; do not call it while
holding `_lock`. It queues persistence, with background retry; the HTTP endpoint
also flushes before returning its durability header. Use this boundary for every
transition to obtain complete history. A compatibility scanner captures the
latest direct dictionary edits every two seconds and on graceful shutdown; it
cannot reconstruct intermediate edits made between scans or before a hard crash.

Mongo collections are `incidents`, `reliability_evidence`, `incident_events`.
Events/evidence use stable IDs and insert-once upserts. Events include investigation,
decision and integration results in their full snapshot. Startup restores events
and replays a newer acknowledged event if a crash interrupted the corresponding
latest-incident write. This is not a transaction across the three collections.

## Tiger Data setup

1. Create/select a **Tiger Cloud** service; obtain its PostgreSQL connection URL
   from its downloaded credentials or Console. TimescaleDB must be installed.
   Plain PostgreSQL is not silently used as a replacement.
2. Put the following in ignored `backend/.env`, alongside Mongo configuration:

   ```dotenv
   TIGERDATA_DATABASE_URL=postgresql://USER:ENCODED_PASSWORD@HOST:PORT/DATABASE?sslmode=verify-full
   TIGERDATA_SCHEMA=factoryos
   ```

   Use the service's actual URL. Configure `sslrootcert` in the URL if the service
   requires a CA file. Missing `sslmode` defaults to `verify-full`; explicit
   `require`/`verify-ca`/`verify-full` are accepted; plaintext modes are rejected.
   Percent-encode reserved password characters. Never use frontend `VITE_*`.
3. Install `requirements.txt` (or `requirements-dev.txt` for tests), then start
   the existing backend. The configured account needs permission to create a
   schema/table/index and convert the table to a hypertable. Initialization is
   idempotent and does not create/drop a service or install the extension.
4. Startup creates `<schema>.telemetry`, converts it to a hypertable on
   `observed_at`, and indexes `(source_kind, source_id, observed_at DESC)`.
   The primary key `(observed_at, event_id)` meets Timescale's time-column
   uniqueness requirement. Startup failure is sanitized and stops startup;
   a missing URL leaves history explicitly disabled.

Accepted Arduino **and simulator** events are automatically written, including
healthy readings. No firmware, gateway or telemetry POST schema change is needed.
`source_id` is the existing device ID; `source_kind` stays distinct for each source.
The existing psutil endpoint also writes its samples, and a background sampler
collects host CPU/RAM approximately every five seconds without dashboard polling
(collection/write duration adds to that period). Host `source_kind` is
`host_system`; `source_id` is `source.host_id` from `/api/system/metrics`.

The table stores source/observation/receipt identity, measurement columns and the
complete JSON payload. Arduino fault flags remain explicitly simulated. Host
samples are backend-machine measurements, not readings from a data-center rack.
Null metrics remain null on collection failure; sample `status` describes host
collection health, not whether usage is safe. Hardware collection status `OK`
means accepted input; reliability warnings remain in its payload.

Writes use parameterized SQL, JSONB adapters, explicit transaction commit and
`ON CONFLICT DO NOTHING`. Retries keep the first event instead of duplicating it.
MongoDB and Tiger Data have independent acknowledgements; no cross-service
transaction is claimed. Runtime failures retain memory queues for retry and do
not remove deterministic alert responses. Unacknowledged data is not restart-safe.
Prolonged outages can grow these prototype queues.

## Charting APIs: Person 3

Both APIs require `source_kind` (`arduino_serial`, `simulator`, `host_system`)
and `source_id`; samples from unlike sources are not averaged together.

`GET /api/telemetry/history?source_kind=arduino_serial&source_id=RACK-01&limit=300`

- Optional timezone-aware `start`/`end`; defaults to the last hour, inclusive
  start/exclusive end. Positive windows up to seven days only.
- `limit`: 1..1000. The most recent matching samples are returned chronologically.
- Response: `source_kind`, `source_id`, UTC `start`/`end`, `samples`.
- Each sample has `observed_at`, `received_at`, `event_id`, `status`, `payload`.
  The payload is the original telemetry receipt or host-metrics result.

`GET /api/telemetry/summary?source_kind=arduino_serial&source_id=RACK-01&bucket_seconds=300`

- Same time/source filters; `bucket_seconds`: 60, 300, 900, 3600 (default 300).
- Response: source/window fields, `bucket_seconds`, and chronological `buckets`.
- Each bucket: `bucket_start`, `sample_count`, `temperature_c_avg`,
  `temperature_c_min`, `temperature_c_max`, `humidity_pct_avg`,
  `cpu_utilization_pct_avg`, `memory_utilization_pct_avg`, `fault_count`,
  `collection_error_count`.
- SQL uses real `time_bucket`/aggregate functions. Missing metric averages are
  null; empty intervals are omitted, not fabricated as zero-valued measurements.
  The seven-day/minute-bucket bound permits at most 10,080 buckets.
- Disabled/unavailable storage returns 503; invalid filters return 422.

`GET /api/telemetry/storage/health` returns `backend: tigerdata`, `status`
(`DISABLED`, `OK`, `PENDING`, `DEGRADED`), `pending_samples`, safe `error`.
The new `X-FactoryOS-Telemetry-Persistence` response header distinguishes
`persisted`/`pending` on ingest and host metrics when enabled. Existing Mongo
`X-FactoryOS-Persistence` is independent. Both headers are exposed through CORS.

## Real-service checks and demo evidence

Install development dependencies, then run the default suite:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Set these test variables locally to authorized TEST service credentials (do not
paste credentials into chat). Merely setting runtime dotenv variables does not
opt in to the live tests:

```powershell
# If runtime URIs are already process environment variables:
$env:FACTORYOS_TEST_MONGODB_URI = $env:MONGODB_URI
$env:FACTORYOS_TEST_TIGERDATA_URL = $env:TIGERDATA_DATABASE_URL
.\.venv\Scripts\python.exe -m pytest tests/test_mongo_live.py tests/test_tiger_live.py -q
```

Each opt-in test starts a real Uvicorn HTTP server, writes acknowledged data,
stops that process, starts a second server, and verifies retrieval without replay.
Mongo also verifies investigation/resolution history; Tiger verifies actual
hypertable identity, source isolation, duplicate writes and a known two-sample
average/count computed in SQL. Synthetic test samples are labeled simulator.

Mongo tests create/drop only `factoryos_restart_test_<UUID>`; the test user needs
privileges on that generated DB. Tiger tests create/drop only their generated
`factoryos_test_<UUID>` schema; use an account permitted to do so. Never point
tests at a service where these test writes/cleanup are unauthorized. Missing URI
means SKIPPED; a configured failing service fails the check. Failure diagnostics
are sanitized and child-server output is suppressed to avoid leaking credentials.

For the actual hardware demo: keep the gateway running, show stored rows with
`source_kind=arduino_serial`, show source-filtered history and bucket values, then
restart only the backend and retrieve the same saved incident/history. Preserve
test output and screenshots without connection strings. No merge/deployment or
external message was performed by this storage implementation.

References:
- [Atlas connection setup](https://www.mongodb.com/docs/atlas/connect-to-database-deployment/)
- [Tiger Data connection details](https://www.tigerdata.com/docs/integrate/find-connection-details)
- [Hypertable unique indexes](https://www.tigerdata.com/docs/build/performance-optimization/hypertables-and-unique-indexes)
- [Time buckets](https://www.tigerdata.com/docs/learn/data-lifecycle/time-buckets/about-time-buckets)
