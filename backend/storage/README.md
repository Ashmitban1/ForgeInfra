# MongoDB Atlas incident and evidence persistence (Person 1)

MongoDB is opt-in. Without `MONGODB_URI`, the existing memory-only backend keeps
working. With a URI, incidents are restored at FastAPI startup. Existing response
bodies, incident IDs, collection wrappers and lifecycle behavior stay the same.
`_incidents` and `_lock` remain available for the integration router.

## Atlas setup

1. Create/select an Atlas cluster. Create a **database user**, grant `readWrite`
   on your application database, and allow your laptop's current public IP in
   Atlas Network Access. Website login and database credentials are separate.
2. Get the Python driver URI from Atlas **Connect -> Drivers**. Insert credentials
   locally; percent-encode reserved characters in username/password. Keep the URI
   out of Git, screenshots and chat.
3. Install runtime dependencies from the repository root:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

4. Set process environment variables or these backend-only settings in ignored
   `backend/.env` (root `.env` is also supported):

   ```dotenv
   MONGODB_URI=mongodb+srv://USER:ENCODED_PASSWORD@YOUR_CLUSTER/?retryWrites=true&w=majority
   MONGODB_DATABASE=factoryos
   ```

   Process variables win, then `backend/.env`, then root `.env`. Do not use
   `VITE_*`. TLS validation stays enabled; Atlas SRV URIs use TLS by default.
5. Preserve any current memory-only incidents as below, then start **one process**:

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload
   ```

   Person 3's wrapper on an integrated branch must retain this app's lifespan.
   Do not run both entry points in separate processes expecting shared live state.

## Preserve an incident already in memory

Before stopping/reloading the old backend or changing watched files:

```powershell
$incidentBackup = Invoke-RestMethod http://127.0.0.1:8000/api/incidents
$incidentBackup | ConvertTo-Json -Depth 30 | Set-Content -Encoding UTF8 .factoryos-incidents-backup.json
```

Stop the backend with Ctrl+C. Configure MongoDB, then import with the server stopped:

```powershell
.\.venv\Scripts\python.exe -m backend.storage.import_incidents --file .factoryos-incidents-backup.json
```

Start the backend after confirmed import. IDs, timestamps and existing fields are
preserved; exact reimports are safe. A differing stored incident with the same ID
aborts import. The backup filename is Git-ignored. This recovers only the latest
evidence retained in each incident, not past events never stored. If the old
process already restarted, its unpersisted incidents cannot be recovered.

## Layout and durability

- `incidents`: `_id` equals unchanged `incident_id`. `$set` upserts update one
  document; Mongo `_id` is excluded from public responses.
- `reliability_evidence`: immutable snapshots of incident/device IDs, hardware,
  source/timestamps, legacy output, expected status and reliability. A stable
  event key and `$setOnInsert` deduplicate retries and retain earlier evidence.
- `incident_events`: complete incident snapshots for telemetry, investigation,
  result updates, resolution and reopening, with idempotent event identities.
  Use the shared `/api/incidents/{id}/updates` boundary for every lifecycle change.
- Writes require majority acknowledgement. Each latest incident snapshot follows
  its own evidence and lifecycle writes, before older audit backlog is drained;
  older history cannot monopolize the short flush budget ahead of current state.
  The collections are not one transaction. Retry reconciles partial completion.
- Every accepted reading updates an existing OPEN incident, including fault
  clearing/recurrence. The gateway submits roughly every two seconds; a retry
  worker also runs every two seconds. The frontend polls the API every three
  seconds; it reads the backend's live state rather than querying Mongo directly.
  Operational status remains OPEN until an explicit resolution; check
  `hardware.cooling_fault` and `expected_status` for current sensor state.
- Startup restores incidents including their saved AI/integration fields. The
  next numeric ID is above the highest saved `INC-COOLING-NNN`; last problematic
  event sequences are restored per device/source.
- Healthy/latest telemetry history remains memory-only. Recovery does not
  auto-close incidents. `PARTIAL` semantics remain unchanged.
- The shared update API persists investigation/decision/integration results and
  explicit resolution/reopening. A compatibility scanner captures the latest
  direct dictionary edits every two seconds and on graceful shutdown; intermediate
  edits between scans cannot be reconstructed. Use the shared update boundary for
  complete transition history. No teammate modules were modified.

**Use one app worker/writer per database.** Dictionary state and numeric ID
allocation are not distributed. Multiple workers/hosts could allocate colliding
IDs; shared counters/coordination are separate work.

## Failure handling

- Configured MongoDB unavailable at startup: sanitized startup failure, rather
  than an empty history or reused IDs. No URI: explicit memory-only mode.
- Runtime failure: alert and local incident still return. Snapshots remain in a
  memory retry queue; a worker retries every two seconds and ingestion also flushes.
- Startup incident and lifecycle restoration each have a 60-second total deadline
  and request batches of 100 documents, so growing history does not use the short
  operational-write deadline. An incomplete restore still fails startup; no
  history is discarded or silently skipped.
- Driver deadlines and a three-second flush budget bound operational network waits. No Mongo
  IO occurs under the telemetry lock.
- POST header `X-FactoryOS-Persistence`: `persisted` = incident writes acknowledged
  and queues drained; `pending` = durability unconfirmed; `disabled` = memory mode;
  `not_applicable` = healthy input with no incident/evidence or pending writes.
- `GET /api/storage/health`: backend, `OK` / `PENDING` / `DEGRADED` (memory:
  `DISABLED`), pending counts (including `pending_events`) and safe error code. This describes last-write/queue
  state, not a continuous connectivity probe. `/health` is unchanged.
- The retry queue is NOT a disk outbox. Termination during a write outage loses
  unacknowledged data. Shutdown retries and warns if pending writes remain.
  Restore connectivity and wait for `OK`, or export incidents before stopping.
  A prolonged outage can grow the queue; this is a local prototype.
- Public persistence errors do not contain URIs/passwords/raw driver diagnostics.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Default persistence tests use **mongomock**, not Atlas. They verify upserts,
snapshot/deduplication, restart hydration/retrieval, ID/sequence continuation,
outage retry, partial writes, safe errors, backup import/conflicts and memory mode.
CI installs development dependencies and uses Python 3.11.

Opt-in real MongoDB restart test:

```powershell
# Set locally to an authorized TEST cluster URI. Never commit the value.
$env:FACTORYOS_TEST_MONGODB_URI = $env:MONGODB_URI
.\.venv\Scripts\python.exe -m pytest tests/test_mongo_live.py -q
```

If MongoDB is configured only in a dotenv file, set the opt-in test variable
separately in your shell; pytest does not load dotenv for this flag. The test
user needs read/write and dropDatabase privileges for its generated
`factoryos_restart_test_<UUID>` database; use a test cluster. The test launches
two real Uvicorn processes over HTTP: one writes investigation/resolution and
exits, the other retrieves the same incident/history. It verifies evidence/event
counts and removes only its UUID database.
Missing URI skips; a supplied URI that cannot connect fails. No Atlas success
should be claimed until this or the manual check passes.

## Manual restart proof

1. Start configured backend and send a fault. Record its returned ID and confirm
   the persistence header is `persisted`.
2. Check `/api/storage/health`: `OK`, zero pending counts. Confirm records in Atlas
   Data Explorer collections `incidents` and `reliability_evidence`.
3. Stop and restart FastAPI with the same URI/database. Do not resubmit telemetry.
4. GET `/api/incidents/{original-id}` and `/api/incidents`: the saved original
   incident and its evidence fields must still exist.
5. Send a higher-sequence fault for the same device: reuse the OPEN ID, retain
   one incident document, and add another evidence snapshot.

References:
- https://www.mongodb.com/docs/atlas/connect-to-database-deployment/
- https://www.mongodb.com/docs/languages/python/pymongo-driver/current/crud/update/

See [the lifecycle/Tiger Data integration handoff](../../docs/STORAGE_INTEGRATION.md)
for the shared update API, chart queries, Tiger Cloud setup, real-service checks,
and explicit implementation versus verification status.
