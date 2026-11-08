# Person 2 modernization API — step 4

## Local end-to-end run

Start Docker Desktop and build the existing image once. From the repository root:

```sh
source .venv/bin/activate
python -m pip install -r requirements.txt
docker build -t factoryos-monitor:local backend/modernization/container
python -m uvicorn backend.modernization.app:app --reload
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

## One canonical incident store

`backend.modernization.app:app` imports Person 1's existing app, `_incidents`, and
`_lock`, then mounts the modernization router. The memory repository uses that
same dictionary. The existing incident GET exposes its additive `repair` summary.
The wrapper does not register Person 3's Jira router on this branch.

**This wrapper is local development with volatile memory. It does not connect to
Atlas just because `MONGODB_URI` is present.** Check
`GET /api/modernization/capabilities`: `storage_backend` reports the actual adapter.
Person 1's published backend still has no MongoDB incident writer. Creating a
parallel database that only P2 reads would split the team's canonical incidents.

The MongoDB adapter is implemented and tested against a real local MongoDB server.
Mount it on the same Atlas-backed app/collections that P1's writer uses:

```python
from backend.modernization.mongo_repository import MongoIncidentRepository
from backend.modernization.router import create_modernization_router
from backend.modernization.service import RepairService

# `app` is the team's existing FastAPI app, not a new competing application.
repository = MongoIncidentRepository(database["incidents"], database["repair_jobs"])
app.include_router(create_modernization_router(RepairService(repository)))
```

Alternatively, `MongoIncidentRepository.from_environment()` opens and pings a
connection using `MONGODB_URI`, `MONGODB_DATABASE` (default `factoryos`),
`MONGODB_INCIDENTS_COLLECTION` (default `incidents`), and
`MONGODB_REPAIR_JOBS_COLLECTION` (default `repair_jobs`). Environment loading is
the shared app's responsibility; this helper does not read dotenv files.
The app owner should close an owned client with `repository.close()` at shutdown.
Use timezone-aware MongoDB reads for native BSON dates.

Required incident document shape is the existing v1 public incident contract,
including `incident_id`, `device_id`, `created_at`, `hardware`, `legacy_monitor`,
`expected_status`, and `reliability`. Keep a unique canonical incident ID. Internal
MongoDB `_id` is excluded from public snapshots. P1 updates should preserve
teammate-owned `repair`, `investigation`, `decision_review`, and integration fields;
avoid replacing a whole document with a telemetry-only projection.

P2 adds only repair jobs and the incident's `repair` summary. It does not implement
P1's ingestion persistence, Tiger Data telemetry, or AI updates ahead of step 5.
Atlas itself has not been connected or verified by these local tests.

## Endpoints and response contract

| Method/path | Behavior |
| --- | --- |
| `GET /api/modernization/capabilities` | Real storage mode and enabled features; investigate/approval/deploy are false |
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
Its canonical SHA-256 binds the report to those inputs; later readings do not
rewrite the job. Each job has its own trace ID, and each proposal has a repair ID.

The worker runs the same original/candidate acceptance suites, then replays the
actual frozen event in Docker if those checks pass. This is safe offline
verification, not activation of the candidate. The live monitor still uses P1's
stub until a separately approved integration changes it. A valid replay ends in
WARNING while the cooling fault remains true; monitoring repair is not equipment
recovery and does not close the incident.

The job queue has one execution thread and at most four accepted pending/running
jobs. Store locks are released before Docker runs, so telemetry can continue.
MongoDB uses unique request and partial active-job indexes to prevent duplicate
reservations; source snapshots/results survive service recreation. On startup,
unfinished jobs become INTERRUPTED instead of pretending to still run.

Run **one modernization worker process/replica** for this prototype. Startup recovery
assumes exclusive ownership of its job collection; do not mount it in multiple
Uvicorn workers or replicas. Atlas persistence does not turn this in-process executor
into a distributed durable queue. Graceful shutdown waits for accepted work;
unexpected termination requires a new request key to retry interrupted jobs.

No Nemotron/Gemini calls, approval, merge, deployment, Jira/Slack call, Tiger Data
write, or cloud deployment is performed by these routes. Existing investigation
and decision-review fields remain unchanged. The backend is still unauthenticated;
use the current local/isolated setup until the team's shared deployment is protected.

## Validation

```sh
python -m pytest -q
python -m pytest -q --run-docker-tests
```

Real MongoDB tests additionally require a disposable local server and use a unique
temporary test database, which they remove afterward:

```sh
FACTORYOS_TEST_MONGO_URI=mongodb://127.0.0.1:27017 \
  python -m pytest -q --run-mongo-tests --run-docker-tests
```

The tests intentionally reject Atlas/remote test URIs. MongoDB checks cover durable
results, service recreation, atomic concurrent reservations, interrupted recovery,
and recycled incident IDs. Docker API coverage creates an incident through P1's
real ingestion handler and verifies actual acceptance results and snapshot replay.
