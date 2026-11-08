# FactoryOS API contract (v1)

Base: `http://127.0.0.1:8000`. Owner P1: `GET /health`, `POST /api/telemetry`, `GET /api/telemetry/latest`, `GET /api/incidents`, `GET /api/incidents/{incident_id}` (implemented, in-memory). P2 implemented via `backend.modernization.app:app`: `POST /api/incidents/{id}/investigate`, `GET /api/incidents/{id}/analysis`, `POST /api/incidents/{id}/repair`, investigation job/patch and repair job/report/diff reads. P3 notification/approval routes are not registered on this branch. See [the modernization API](MODERNIZATION_API.md) and [Nemotron agent guide](../backend/agents/README.md).

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
