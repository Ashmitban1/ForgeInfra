# FactoryOS API contract (v1)

Base: `http://127.0.0.1:8000`. Owner P1: `GET /health`, `POST /api/telemetry`, `GET /api/telemetry/latest`, `GET /api/incidents`, `GET /api/incidents/{incident_id}` (implemented, in-memory). P2 proposed: `POST /api/incidents/{id}/investigate`, `GET /api/incidents/{id}/analysis`, `POST /api/incidents/{id}/repair` (not implemented). P3 implemented via `backend.integrations.app:app`: `POST /api/incidents/{id}/notify`; proposed: `POST /api/repairs/{id}/approve` (not implemented).

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

## Jira notification extension

See `backend/integrations/README.md` for setup and request/response examples. POST notify creates a real Jira Task and records `jira_key`, `jira_id`, and `jira_url` under incident integrations. Repeated confirmed requests return the same issue; uncertain attempts return 409 for manual reconciliation. The original `backend.main:app` remains unchanged pending Person 1 registration.

`GET /api/integrations/capabilities` is an additive integration-router endpoint returning `{"jira":{"notify":true}}`. The frontend checks route support before enabling creation; it does not expose credential state.

## Combined Jira + Slack notification extension

`POST /api/incidents/{id}/notify` now creates/reuses Jira first and then sends Slack.
Existing Jira response fields remain compatible. When Jira succeeds, HTTP 200
returns `notification_status` (`DELIVERED` or `PARTIAL`) plus `slack_status`,
`slack_error`, `slack_already_exists`, and confirmed `slack_channel_id`,
`slack_message_ts`, `slack_message_id` (timestamp compatibility alias).
`integrations` contains the updated incident integration fields, also available
through existing incident GET routes. Missing Slack configuration yields partial
success with the actual Jira reference retained; Jira errors retain existing HTTP
error behavior and no Slack send is attempted.

Slack states: `NOT_CONFIGURED`, `FAILED` (explicit rejection; corrected retry
allowed), `PENDING`, `UNCONFIRMED` (manual reconciliation before retry), `DELIVERED`
(confirmed channel and timestamp). Absent Slack fields on an older incident mean
no recorded delivery, not successful delivery. Capability response adds
`"slack":{"notify":true}` alongside Jira. Configuration remains backend-only.
