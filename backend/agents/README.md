# Person 2: real Nemotron investigation — step 5

## Run

Use Python 3.11 and a running local Docker daemon. From the repository root:

```sh
source .venv/bin/activate
python -m pip install -r requirements.txt
docker build -t factoryos-monitor:local backend/modernization/container
python -m uvicorn backend.modernization.app:app --reload
```

Set `NVIDIA_API_KEY` in the process environment or an ignored `backend/.env` / root
`.env` file. The wrapper loads environment first, then backend dotenv, then root
dotenv without overwriting existing values. Do not put keys in frontend variables,
source code, chat, screenshots, or committed files. The example string
`"NVIDIA_API_KEY"` is not a credential lookup.

Selected defaults:

```text
Provider: NVIDIA hosted inference
Base URL: https://integrate.api.nvidia.com/v1
Model: nvidia/nemotron-3-ultra-550b-a55b
Client: OpenAI-compatible Python SDK, non-streaming tool responses
```

The API client preserves the selected model and performs no silent model fallback.
Reference: [NVIDIA model/API prototype](https://build.nvidia.com/nvidia/nemotron-3-ultra-550b-a55b).
Docker executes monitor tests; NVIDIA hosts the language model.

## API workflow

Create an incident through existing telemetry ingestion, e.g.:

```sh
python hardware/simulator.py --mode fault
```

Use the returned incident ID in `/docs` or POST:

```sh
curl -X POST -H 'Idempotency-Key: investigation-demo-1' \
  http://127.0.0.1:8000/api/incidents/INC-COOLING-001/investigate
```

| Route | Purpose |
| --- | --- |
| `POST /api/incidents/{id}/investigate` | Capture evidence and queue genuine NVIDIA investigation; 202, or 200 for reused terminal request |
| `GET /api/investigations/{job_id}` | Poll complete progress, actual tool traces, provider metadata, evidence manifest, final findings |
| `GET /api/investigations/{job_id}/patch` | Plain-text model-generated diff once a final investigation result contains a candidate |
| `GET /api/incidents/{id}/analysis` | Existing repair/AI view; investigation progress is attached to the same canonical incident |
| `GET /api/agents/capabilities` | Route support, selected model/key configuration, storage backend; Gemini/approval/deploy remain false |

Check `configured` to distinguish installed routes from configured credentials.
It is not a live-provider health claim. Missing/invalid configuration returns 503
before accepting new work. Unknown incident/job IDs return 404. A different active
investigation returns 409. Existing keys reuse the original job/snapshot.

Job states are QUEUED, RUNNING, COMPLETED, FAILED, INTERRUPTED. Canonical
`investigation.status` maps QUEUED to PENDING for existing frontend compatibility.
An incident that already has a completed investigation can be reinvestigated with
a new explicit idempotency key. Do not assume IDs survive a local memory restart.

### Troubleshoot polling in Swagger

The simulator returns an incident ID such as `INC-COOLING-001`. Enter that only in
POST `/api/incidents/{incident_id}/investigate`. Copy **`job_id` from the actual POST
server response**, such as `investigation-job-...`, into GET
`/api/investigations/{job_id}`. Opening the returned `links.job` URL also works.
Swagger's example response is not an existing job.

A 404 means this backend has no job with that ID. Check for a failed POST, an
incident ID in the job field, a server restart/reload, or a different port/process.
In particular, IDs printed by `python -m scripts.verify_nemotron_live` belong to
that script's private TestClient process and cannot be polled from Uvicorn.
For a stable manual test, start Uvicorn without `--reload`, submit fresh telemetry,
then POST and poll on that same server. A 200 response with `status=FAILED` means
GET is working; inspect the job's `error` and tool results for the execution failure.

## What the agent actually does

`investigation.py` sends tool schemas and the task to Nemotron. The model selects
functions; the backend validates and executes them, sends actual outputs back,
and continues until it receives validated JSON findings or reaches a limit.

Allowlisted tools:

1. `get_incident_snapshot()` — immutable real incident evidence, not a hardcoded event.
2. `inspect_legacy_code()` — known source snapshot, numbered lines, actual hash.
3. `read_monitoring_requirements()` — independent fixture requirements and revision.
4. `run_regression_tests(revision_id)` — actual independent Docker acceptance tests.
5. `verify_monitor_patch(source_revision, status_assignment)` — generate a separate
   candidate from the model's assignment, verify tests, and replay the captured event.

No caller/model tool accepts arbitrary file paths, shell commands, test changes,
deployment actions, notifications, or transfers. Failed arguments/unknown tools
produce actual failed traces, not fabricated successful executions.

A final result must reference retrieved evidence IDs and include a source location
within the actual inspected revision. Incident, code, and requirements tools must
all have executed successfully. Source references must cite code evidence.
Malformed JSON, invented evidence, invalid source references, missing tool use,
provider errors, and exhaustion produce explicit failure instead of fake findings.

Tool `status: SUCCESS` means execution returned a result, **not that tests passed**.
Original regression execution legitimately returns exit code 1 with 4 passes and
one failure. Frontend must inspect actual counts/exit codes and the generated
repair's `verification_status`, never infer repair success from a tool status or
from equipment becoming nominal.

## Genuine generated patches and verification

The model authors a single bounded `status = "WARNING" if CONDITION else "NORMAL"`
assignment against the inspected hash. A Python AST policy permits only this
fixture's temperature/fault condition operations. Other code, imports, file access,
additional statements/targets, and uninspected revisions are rejected.

This intentionally narrow modernization target is a representative team-authored
monitor, not arbitrary enterprise code or Northmark production source.
Acceptance tests are independently authored and cannot be edited by the model.

When `verify_monitor_patch` actually executes, `proposal_origin` is
`nemotron_generated_patch`. Original/candidate tests and snapshot replay run in
the existing restricted Docker workflow. Passing results require original 4/1,
candidate 5/0, correct replay decisions, and unchanged source/diff evidence.

The existing `/repair` and CLI routes still generate their fixed manual candidate
with `manually_authored_demo_patch`. An investigation does not silently submit a
manual repair job or overwrite that job namespace. Read the model-generated result
at `investigation.generated_repair` or the investigation job's
`result.generated_repair`, and use its patch link.

Generated candidate approval stays PENDING; deployed stays false. Replay is offline
and does not replace the live monitor. Equipment faults can remain present and
must still produce WARNING. Incident operational status and Gemini review are
not advanced by this agent.

## Persistence and worker limits

Repair and investigation repositories share the same canonical incidents but use
separate job records and lifecycle recovery. Memory mode uses the same P1 dict/lock
with distinct job dictionaries. MongoDB mode uses `repair_jobs` and
`investigation_jobs` (configurable with `MONGODB_INVESTIGATION_JOBS_COLLECTION`).
Never configure the two namespaces to use the same collection.

Mount both services on the canonical app when P1's Atlas writer is available:

```python
repair = RepairService(repository)
investigation = InvestigationService(repository.for_investigations())
app.include_router(create_modernization_router(repair, investigation))
app.include_router(create_investigation_router(investigation))
```

The current local wrapper remains memory-backed. Atlas itself is not connected
merely by loading the NVIDIA dotenv file. Each service is an in-process bounded
worker, not a distributed queue; run one worker process/replica for its namespace.
Startup recovery marks unfinished jobs INTERRUPTED. Telemetry locks are released
before model/Docker work. Frozen input excludes previous AI results to prevent
recursive snapshots.

Defaults are 6 provider rounds, 8 requested tools, 90 seconds per provider request,
16,384 output tokens, and a 300-second cooperative investigation budget. The budget
is checked between calls; existing Docker tools retain their execution deadlines.
There are at most two diagnostic test runs and two candidate attempts. Environment
overrides are listed in `.env.example`; limits have bounded accepted ranges.

Actual provider response IDs/model/usage and durations are recorded. Credentials,
headers, raw provider exception bodies, and model reasoning streams are not stored
as public evidence. Public findings/traces redact the configured key if echoed.

## Validation and explicit live check

```sh
python -m pytest -q
python -m pytest -q --run-docker-tests
# Optional disposable local MongoDB, never Atlas:
FACTORYOS_TEST_MONGO_URI=mongodb://127.0.0.1:27017 \
  python -m pytest -q --run-mongo-tests --run-docker-tests
```

Provider responses in unit tests are explicitly scripted; production has no
simulated-provider fallback. Real Docker and MongoDB integration tests are opt-in.

To intentionally use real NVIDIA API quota:

```sh
python -m scripts.verify_nemotron_live
```

This creates a fresh simulated incident in a TestClient-owned process, runs the
real agent, and saves its actual public job under ignored modernization artifacts.
It does not send Jira/Slack messages, activate a candidate, or populate a separately
running dashboard backend's memory. API configuration errors/provider failures
produce nonzero exit codes, not simulated success.

An initial real NVIDIA run completed with the selected Ultra model:
4 provider responses; 5 real tools (incident, source, requirements, original tests,
candidate verification); grounded findings; generated candidate VERIFIED; original
test exit 1; candidate exit 0; offline replay NORMAL -> WARNING. Approval remained
PENDING and nothing was deployed. A subsequent guard now requires every finding
with a source reference to cite inspected-code evidence directly; the initial
live response does not satisfy that stricter per-finding rule. The guard passes
local scripted-provider tests. A final live rerun was blocked by automatic approval
review pending explicit permission to send the fixture, requirements, and simulated
incident evidence to NVIDIA. This is observed prototype evidence, not a guarantee
that credentials, quota, or the hosted endpoint remain available later.

Gemini review is step 6 and remains unimplemented. Existing deterministic alerting
does not wait for either model. Shared authentication, Atlas writer integration,
frontend evidence binding, and authorized activation remain separate team work.
