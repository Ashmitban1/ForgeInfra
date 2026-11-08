# FactoryOS API contract (v1)

Base: `http://127.0.0.1:8000`. Run the integrated entry point
`backend.modernization.app:app`: P1's same FastAPI app with P2 routers mounted.
P1 owns telemetry, incidents, lifecycle/history, and optional MongoDB/Tiger Data
persistence. P2 implements incident `/investigate`, `/review`, `/analysis`,
`/repair`, authenticated GET/POST `/approval` and GET `/approval/history`, plus
job/report/diff reads. P3 notifications and approval UI are separate integrations.
See [the modernization API](MODERNIZATION_API.md),
[Nemotron guide](../backend/agents/README.md),
[Gemini guide](../backend/agents/GEMINI_REVIEW.md), and
[human approval guide](HUMAN_APPROVAL_API.md).

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

Ingestion executes the fixed team-authored `fixtures/legacy_monitor/monitor.py`
outside the telemetry lock. `legacy_monitor.source_revision` is its actual SHA-256
source hash, `sampled_at` identifies the sample, and successful output includes
`health: "OK"`, `execution_status: "COMPLETED"`, and
`target_binding: "representative_fixture"`. This is representative legacy software,
not an acquired vendor codebase; its temperature-only fault is preserved.

Execution/validation failure yields `status: "UNKNOWN"`, `health: "DEGRADED"`,
`execution_status: "FAILED"`, a safe error, and `reliability.mismatch: null` with
reason `legacy_monitor_unavailable`. The attempted source hash is retained when
available. Failure never becomes NORMAL. `expected_status` and `should_alert`
remain independent of both monitor and AI availability; stale/future samples
cannot produce a fresh operational alert.

Healthy readings update an existing OPEN incident without automatically resolving
it. Material telemetry/status changes increment `case_generation`, including
fault clearing and recurrence. Investigation/review fields begin PENDING and
integration IDs remain null until their actual workflows populate them.

## Modernization extension (Person 2)

P1 remains the sole canonical incident writer. `SharedIncidentRepository` reads
P1 snapshots and synchronously publishes accepted P2 transitions through P1's
history/persistence callbacks. After P1 restores MongoDB, fresh lifecycle-owned
workers reuse its existing database/client for `repair_jobs`,
`investigation_jobs`, and `review_jobs`. No independent P2 canonical snapshot
writer is mounted. Memory mode is volatile; acknowledged MongoDB jobs survive
restart and unfinished jobs become INTERRUPTED. Use one app worker/process.

`POST /api/incidents/{id}/repair` accepts no body and an optional `Idempotency-Key`
header. It returns a job with status 202 while queued/running, or 200 for a reused
terminal job. Poll the returned `links.job` or the incident's `/analysis` route.
`GET /api/repairs/{job_id}/diff` returns actual plain-text diff content;
`GET /api/repairs/{job_id}/report` returns browser-safe job/report data.

The canonical incident gets an additive `repair` summary with `job_id`, `job_status`,
`repair_id`, `verification_status`, `snapshot_revision`, `trace_id`,
`proposal_origin`, `approval_status`, and `deployed`. This is separate from the
incident's operational `status` and existing AI/integration fields.

Job COMPLETED means execution finished; inspect `result.verification_status` for
the actual verification outcome. The patch is manually authored, approval remains
PENDING, and `deployed` stays false. Offline replay does not change the live monitor.

## Nemotron investigation extension (Person 2, step 5)

`POST /api/incidents/{id}/investigate` accepts no body and an optional
`Idempotency-Key`. It returns 202 for accepted/active jobs, or 200 for a reused
terminal request. Poll `GET /api/investigations/{job_id}` or the incident's existing
`/analysis`. Missing NVIDIA configuration returns 503 before accepting new work.
`GET /api/agents/capabilities` reports configuration and route support, not live
provider health. `GET /api/investigations/{job_id}/patch` returns a real generated
diff only when the final result contains one.

Canonical `investigation` now carries actual status, agent/model, job/trace IDs,
snapshot revision, tool calls/results, evidence IDs, findings, concise summary,
recommended actions, provider metadata, safe errors, and optional generated repair.
Its job's full evidence manifest is available through the investigation job route.
QUEUED jobs appear as PENDING in the canonical incident; actual execution uses
RUNNING/COMPLETED/FAILED/INTERRUPTED. Gemini fields are preserved unchanged.

Investigation and repair jobs have separate namespaces over the same incidents.
The default model is `nvidia/nemotron-3-ultra-550b-a55b`. Model-selected functions
run through validated allowlists; final findings require retrieved evidence and
valid source references. Tool SUCCESS is distinct from passing tests. A candidate
actually authored through the model tool has `proposal_origin=nemotron_generated_patch`
and its own explicit test verification. The existing `/repair` route stays manual.
Neither route approves, deploys, changes live monitoring, or closes equipment faults.

## Gemini independent review extension (Person 2, step 6)

`POST /api/incidents/{id}/review` accepts no body and optional `Idempotency-Key`.
It requires a completed current Nemotron investigation in this backend's job
store. A new/active job returns 202; a reused terminal job returns 200. Missing
incident: 404; missing/changed investigation or active review: 409; missing Gemini
configuration/worker/storage: 503. Poll the returned `links.job`,
`GET /api/reviews/{job_id}`, using the new **review-job** ID.

`GET /api/agents/capabilities` adds `review`, `gemini`, `gemini_configured`, and
`gemini_model`. The default model is `gemini-3.5-flash-lite`, configurable with
`GEMINI_MODEL`; authentication uses backend-only `GEMINI_API_KEY`.

`decision_review` gains actual model/job/trace IDs, review basis, explanation,
risks, evidence IDs, repair assessment, provider metadata, safe errors, and policy.
States: PENDING, RUNNING, COMPLETED, FAILED, INTERRUPTED, STALE. `/analysis`
derives stale status when the monitoring case or investigation no longer matches.
Each job's exact `snapshot_revision` remains immutable. A separate `case_revision`
allows equivalent advancing samples with fresh timestamps and sequence numbers;
material changes or an intervening fault-clear-fault cycle invalidate the review.
Its `recommendation` is the backend policy's effective recommendation;
`model_recommendation` preserves the model's original choice. Job responses expose
raw structured output in `result`, with `result.policy.effective_recommendation`.

New reviews require `result.fault_provenance` (SIMULATED, REPORTED, UNKNOWN),
validated against captured simulation flags. Backend-generated `fault_context`
in policy and canonical review summaries supplies authoritative provenance labels,
a safe equipment-health statement, and `physical_fault_status=NOT_VERIFIED`.
Arduino source kind alone does not prove the fault signal is physical. Historical
reviews without this field remain readable with provenance_validation=NOT_VALIDATED.

Allowed recommendations: ESCALATE, INVESTIGATE_SOFTWARE, REQUEST_REPAIR_REVIEW,
COLLECT_MORE_EVIDENCE, NO_ACTION. Actions are advisory allowlisted strings. Missing
or failed test/replay proof cannot qualify a repair; model output cannot suppress
deterministic mismatch evidence or bypass human approval. Approval stays PENDING,
`actions_executed=[]`, and `deployed=false`. Review does not send Jira/Slack
messages, change operational incident status, or activate the monitor.

Review jobs use their own `review_jobs` namespace through the shared adapter,
backed by the same P1 MongoDB database/client when configured or volatile memory.

## Human decision extension (Person 2)

Authenticated GET `/api/incidents/{id}/approval` returns the exact evidence package,
`package_revision`, `candidate_revision`, current status, and `blocking_reasons`.
POST the same path with decision APPROVE/REJECT, both hashes, and optional comment.
The backend resolves reviewer identity from a per-reviewer bearer credential
configured in `FACTORYOS_APPROVERS_JSON` and records UTC time. Client actor fields
are forbidden. GET `/approval/history` returns frozen packages and decisions.

POST returns 201 for a new decision or 200 for an idempotent retry. Auth errors:
401; missing auth configuration/storage: 503; missing incident: 404; invalid body:
422; stale/changed evidence, blocked approval, conflicting final decision or reused
key with another body: 409. Rejection can remain available when approval is blocked.
Decisions are final per package. Idempotency is scoped by incident and reviewer.

The canonical incident stores an additive `approval` aggregate. `/analysis` adds
its derived current summary: PENDING, APPROVED, REJECTED, or STALE. AI reports keep
their original pending-approval fields; P3 must use `analysis.approval` for human
decisions. Removing an approving reviewer or changing/aging evidence invalidates
execution eligibility without rewriting history. Capabilities add approval support
and `approval_configured`; automatic deployment remains false.

Frozen package/history changes use P1's locked compare-and-set boundary and
canonical persistence queue. With MongoDB, durable readback must confirm the
approval version. Pending persistence returns 503 while retaining the cached audit;
`approval_persistence_pending` blocks execution and an APPROVE reads as STALE.
Retry the same `Idempotency-Key` after recovery to retrieve the existing decision.
Approval views expose `persistence: {status, version}` with status PERSISTED,
PENDING, or VOLATILE. This is derived durability metadata, not part of the frozen
evidence hash.

`ApprovalService.require_approved` rechecks the exact current binding for a future
execution worker. This endpoint itself activates no monitor and performs no merge,
deployment, PR creation, or notifications. Other existing routes remain local
unauthenticated prototype routes. Do not deploy publicly without auth.

## Optional MongoDB persistence

Configure backend-only `MONGODB_URI` and optional `MONGODB_DATABASE` (default
`factoryos`). Incident schemas and existing response bodies are unchanged.
Acknowledged incidents and immutable reliability evidence are upserted in MongoDB;
startup restores incident records, saved source sequences and numeric ID allocation.
Healthy/latest telemetry is not restored. Single application worker/writer only.
P2 summaries and approval history use this same canonical writer; job documents
live in separate collections, not a competing incident database.

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
- Mongo storage health additionally includes `pending_events`. P2 publishes each
  accepted job transition synchronously to history before queued persistence;
  the compatibility scanner only supports older direct-dictionary adapters.
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
