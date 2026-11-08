# Integrated modernization API

## Local end-to-end run

Start Docker Desktop and build the existing image once. From the repository root:

```sh
source .venv/bin/activate
python -m pip install -r requirements.txt
docker build -t factoryos-monitor:local backend/modernization/container
python -m uvicorn backend.app:app --reload
```

In another activated terminal:

```sh
python hardware/simulator.py --mode fault
```

Use the actual returned `incident_id`; do not assume it is always `INC-COOLING-001`.
Open `http://127.0.0.1:8000/docs`, or use:

```sh
curl -X POST -H 'Idempotency-Key: repair-demo-1' \
  http://127.0.0.1:8000/api/incidents/INC-COOLING-001/repair
curl http://127.0.0.1:8000/api/incidents/INC-COOLING-001/analysis
```

The repair returns immediately while Docker runs in a background thread. Poll the
returned `links.job`; use `links.diff` and `links.report` for actual evidence.
There is no need to send a source path, model prompt, shell command, or image name.
Requests cannot select code to execute. This step supports the known
`legacy_missed_fault` cooling scenario only.

## One canonical incident writer

`backend.app:app` is P1's same FastAPI app with P2 routes mounted.
Start this single entry point for telemetry, storage, investigation, review, approval, and Jira/Slack notifications. The older modernization and integrations startup modules alias the same complete app.

P1 owns the canonical incident cache, lock, MongoDB writer, reliability evidence,
and lifecycle history. `SharedIncidentRepository` reads through P1's snapshot
callback and synchronously publishes each accepted P2 job transition through P1's
controller. P2 never writes competing incident snapshots directly to MongoDB.

With backend-only `MONGODB_URI` and optional `MONGODB_DATABASE` (default
`factoryos`), P1 restores storage before the wrapper creates fresh repositories
and workers. P2 reuses that existing database/client for job-only collections:
`repair_jobs`, `investigation_jobs`, and `review_jobs`. Optional
`MONGODB_REPAIR_JOBS_COLLECTION`, `MONGODB_INVESTIGATION_JOBS_COLLECTION`, and
`MONGODB_REVIEW_JOBS_COLLECTION` override those names; they must be distinct and
cannot collide with `incidents`, `reliability_evidence`, or `incident_events`.
P1 owns connection shutdown. Do not mount a separate `MongoIncidentRepository`
as a canonical incident writer in this app.

Without MongoDB, incidents and jobs are volatile. Check
`GET /api/modernization/capabilities` for the actual `storage_backend`, and
`GET /api/storage/health` for pending canonical writes. Runtime outage queues are
memory-only until acknowledged. Configured MongoDB startup fails safely if
restoration cannot complete. Local tests do not establish live Atlas connectivity.

## Endpoints and response contract

| Method/path | Behavior |
| --- | --- |
| `GET /api/modernization/capabilities` | Actual storage mode and registered repair/investigate/review/approval features; deploy remains false |
| `POST /api/incidents/{id}/repair` | Validate an existing incident, freeze evidence, and reserve/queue one job |
| `GET /api/incidents/{id}/analysis` | Existing AI fields plus the latest repair job for that incident incarnation |
| `GET /api/repairs/{job_id}` | Poll one job, including its snapshot and result |
| `GET /api/repairs/{job_id}/report` | Same browser-safe job/report data |
| `GET /api/repairs/{job_id}/diff` | Real diff as plain text, or 409 while unavailable |

POST takes no body. Optional `Idempotency-Key` is 1–128 characters. A reused key
returns the original job/snapshot even if live telemetry has changed. Without a
key, identical snapshot/source/test inputs reuse the existing job. A different
request while that incident has an active job returns 409 with its job ID. A new
key permits an intentional retry after a failed/interrupted job.

Example shape only; IDs and timestamps must come from actual responses:

```json
{
  "job_id": "repair-job-<uuid>",
  "trace_id": "repair-trace-<uuid>",
  "incident_id": "INC-COOLING-001",
  "incident_created_at": "<captured timestamp>",
  "device_id": "RACK-01",
  "status": "QUEUED",
  "snapshot": {},
  "snapshot_revision": "sha256:<actual hash>",
  "proposal_origin": "manually_authored_demo_patch",
  "approval_status": "PENDING",
  "deployed": false,
  "result": null,
  "error": null,
  "links": {
    "job": "/api/repairs/repair-job-<uuid>",
    "report": "/api/repairs/repair-job-<uuid>/report",
    "diff": "/api/repairs/repair-job-<uuid>/diff",
    "analysis": "/api/incidents/INC-COOLING-001/analysis"
  }
}
```

Actual jobs also contain `created_at` and `updated_at`. The POST response adds
`reused` and `storage_backend` and sets `Location` to the job URL.
`attached_to_incident` records whether a finished job still belonged to the same
incident incarnation. Old results never attach to a recycled ID after restart.

Job states are `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`, `INTERRUPTED`.
`COMPLETED` means the verifier finished, **not that tests passed**. Inspect
`result.verification_status`: this uses the step 3 outcomes plus
`INCIDENT_NOT_REPRODUCED` if the captured event does not reproduce as expected.
Worker exceptions produce FAILED with a safe error; database errors return 503
without connection strings. Unknown records are 404; unsupported evidence or an
active conflicting request is 409; a full/shutting-down worker is 503.

A finished result includes:

- `repair_id`, `verification_status`, `proposal_origin`, `approval_status`, `deployed`.
- `target_binding: "representative_fixture"`, original/candidate/diff revisions.
- `tests.original` and `tests.candidate`: actual exit codes, pass/fail/skip counts,
  individual case outcomes, redacted actual commands, stdout/stderr, truncation flags.
- `replay`: original/candidate decisions for the captured event, expected status,
  `detection_gap_fixed`, `cooling_fault_still_present`, and
  `mode: "offline_snapshot_replay"`.

Raw local output is retained by step 3. Browser output is capped at 32 KiB per
stream and local command/output paths are replaced with `<python>`, `<repo>`, and
`<repair-workspace>`. Public responses never return filesystem paths as download
URLs. Diff reads use the stored job result; there is no arbitrary-file endpoint.

## Evidence, lifecycle, and worker boundary

The immutable snapshot includes original measurements, source/observation time,
simulation flags, recorded monitor decision, and the incident's creation identity.
Its canonical `snapshot_revision` SHA-256 binds the report to those exact inputs;
later readings never rewrite the job. Each job has its own trace ID, and each
proposal has a repair ID.

Reviews separately bind a monitoring `case_revision`. Fresh samples with advancing
sequence/time and equivalent cooling state, temperature threshold band, source,
and reliability can preserve the case despite measurement jitter. Temperature
bands also distinguish exact 0, 1, and 35 boundaries because the constrained
candidate rule language can compare against these values. Material
telemetry or operational-status changes increment P1's `case_generation`.
Healthy samples update an existing OPEN incident without auto-resolving it;
fault-clear-fault transitions cannot revive the old review or approval.

The worker runs the same original/candidate acceptance suites, then replays the
actual frozen event in Docker if those checks pass. This is safe offline
verification, not activation of the candidate. Live telemetry already executes
the fixed, team-authored original fixture via `backend/legacy_runtime.py`, outside
the telemetry lock. It reports the actual source hash and validated decision.
Execution failures produce `status=UNKNOWN`, `health=DEGRADED`, and
`legacy_monitor_unavailable`; no NORMAL result is invented. Expected status and
fresh-data alerts remain deterministic when the monitor or AI is unavailable.
A verified candidate stays offline: replay can end in WARNING while the cooling
fault remains true, and does not close the incident or prove equipment recovery.

The job queue has one execution thread and at most four accepted pending/running
jobs. Store locks are released before Docker runs, so telemetry can continue.
MongoDB uses unique request and partial active-job indexes to prevent duplicate
reservations; acknowledged snapshots/results survive application restart. Every
app lifecycle creates fresh services after P1 restoration. On startup, unfinished
jobs become INTERRUPTED instead of pretending to still run.

Run **one modernization worker process/replica** for this prototype. Startup recovery
assumes exclusive ownership of its job collection; do not mount it in multiple
Uvicorn workers or replicas. Atlas persistence does not turn this in-process executor
into a distributed durable queue. Graceful shutdown waits for accepted work;
unexpected termination requires a new request key to retry interrupted jobs.

The `/repair` route verifies the manually authored demo patch. Nemotron
`/investigate` separately proposes constrained generated candidates, and `/review`
runs independent Gemini review. See [the agent guide](../backend/agents/README.md)
and [Gemini guide](../backend/agents/GEMINI_REVIEW.md). Neither model can authorize
deployment or suppress deterministic alerts.

Authenticated human approval uses P1's locked compare-and-set boundary and the
canonical persistence queue. MongoDB decisions require durable readback. If a
write remains pending, POST returns 503, retains the local audit, and blocks
authorization; retry the same `Idempotency-Key` after recovery. Approval responses
report `persistence.status` as PERSISTED, PENDING, or VOLATILE. See
[the human approval guide](HUMAN_APPROVAL_API.md).

These workflows perform no activation, merge, deployment, PR creation, or
Jira/Slack action. Other routes remain unauthenticated prototype endpoints; keep
the backend local/isolated until protected.

## Validation

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m pytest -q --run-docker-tests
```

Real MongoDB tests additionally require a disposable local server and use a unique
temporary test database, which they remove afterward:

```sh
FACTORYOS_TEST_MONGO_URI=mongodb://127.0.0.1:27017 \
  python -m pytest -q --run-mongo-tests --run-docker-tests
```

These opt-in modernization tests reject Atlas/remote test URIs. MongoDB checks
cover durable results, service recreation, concurrent reservations, interrupted
recovery, and recycled incident IDs. Docker coverage verifies actual acceptance
results and frozen-event replay. Default P1/P2 integration tests use mongomock
and scripted provider/verifier responses; they do not prove physical hardware,
live cloud storage, or current model-provider availability.

Default tests blank developer storage/provider credentials, so ignored `.env`
files cannot turn ordinary tests into cloud writes or live model requests. Live
storage checks use their explicit `FACTORYOS_TEST_*` connection settings.
