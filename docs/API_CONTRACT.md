# FactoryOS API contract (v1)

Base: `http://127.0.0.1:8000`. Owner P1: `GET /health`, `POST /api/telemetry`, `GET /api/telemetry/latest`, `GET /api/incidents`, `GET /api/incidents/{incident_id}` (implemented, in-memory). P2 implemented via `backend.modernization.app:app`: incident `/investigate`, `/review`, `/analysis`, `/repair`; investigation/review job reads; investigation patch and repair report/diff reads. P3 notification/approval routes are not registered on this branch. See [the modernization API](MODERNIZATION_API.md), [Nemotron guide](../backend/agents/README.md), and [Gemini guide](../backend/agents/GEMINI_REVIEW.md).

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

Incidents include investigation and decision-review fields set `PENDING` until actual Nemotron and Gemini calls, and provider IDs set `null` until Jira/Slack/Solana integrations are working. Storage resets whenever FastAPI restarts. Do not deploy publicly without auth.

## Modernization extension (Person 2)

The P2 wrapper mounts a background repair router on P1's existing app and dictionary;
it does not edit the P1 handlers or create a second incident store. Its local state
is volatile. A tested MongoDB repository adapter is supplied for the canonical Atlas
app; P1's Atlas telemetry/incident writer has not been connected on this branch.

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
derives stale status when live telemetry or the investigation no longer matches.
Its `recommendation` is the backend policy's effective recommendation;
`model_recommendation` preserves the model's original choice. Job responses expose
raw structured output in `result`, with `result.policy.effective_recommendation`.

Allowed recommendations: ESCALATE, INVESTIGATE_SOFTWARE, REQUEST_REPAIR_REVIEW,
COLLECT_MORE_EVIDENCE, NO_ACTION. Actions are advisory allowlisted strings. Missing
or failed test/replay proof cannot qualify a repair; model output cannot suppress
deterministic mismatch evidence or bypass human approval. Approval stays PENDING,
`actions_executed=[]`, and `deployed=false`. Review does not send Jira/Slack
messages, change operational incident status, or activate the monitor.

Review jobs use a separate `review_jobs` MongoDB collection over the same canonical
incidents, or a separate job dictionary over P1's same memory dict/lock. The local
wrapper remains memory-backed. Atlas writer integration is still separate.
