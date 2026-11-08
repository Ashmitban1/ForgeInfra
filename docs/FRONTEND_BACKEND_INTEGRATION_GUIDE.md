# Frontend–Backend Integration Guide

Implementation status: completed in the working tree following the sequence below. The original audit and its observed failures are retained as the baseline.

- Official startup: `python -m uvicorn backend.app:app --reload`; both earlier wrappers now alias the same app.
- Notifications use canonical incident publication/history.
- The client, AI controls, real candidate evidence, authenticated decisions, persisted source discovery/history, analytics, host metrics, and honest status handling are connected.
- A local named `person-2` reviewer was configured in the ignored backend dotenv. Its raw credential is stored privately in `.env.approval-token`; restart the backend to load configuration, enter the credential in the Approval panel, and inspect the package. No decision is automatically recorded.
- Candidate activation, PR creation, merging, and deployment remain outside this change.

### Reproduce validation

```sh
python -m pytest -q
npm --prefix frontend test
npm --prefix frontend run build
```

For the full UI acceptance flow, start a fresh isolated server:

```sh
PYTHONPATH=.:tests .venv/bin/python -m uvicorn ui_backend:app --host 127.0.0.1 --port 8002
```

With Vite on port 5173, open an isolated Playwright MCP browser context and run `browser_run_code_unsafe` with `filename: tests/ui_workflow.playwright.js`. The script forwards API calls to the disposable acceptance server, checks investigation/diff/review/approval/rejection/notifications/history/stale evidence/UNKNOWN handling, and uses scripted providers only. The acceptance server must be restarted between runs. These test-only `/__test__` endpoints are never mounted in the production app.

The original inspection below was performed at 2026-11-08T10:34:48.825Z on main before implementation.

## Live evidence

The dashboard at http://127.0.0.1:5173/#/ and Swagger at http://127.0.0.1:8000/docs were inspected with Playwright. Mission Control, Incident Investigation, Engineering, and Oversight were visited with Demo mode off. Checks used reads and navigation; no investigation, review, approval, or notification was submitted during this audit.

| Check | Observed result |
| --- | --- |
| API availability | GET /health: 200 |
| MongoDB | GET /api/storage/health: 200, backend=mongodb, status=OK, no pending writes |
| Tiger Data | GET /api/telemetry/storage/health: 200, status=OK, no pending samples |
| Latest telemetry | 200, devices=[] after server restart |
| Incidents | 200, INC-COOLING-001 exists for RACK-01 |
| Tiger Arduino history | 200; five requested samples returned for RACK-01 |
| Tiger Arduino summary | 200; five buckets returned for the default one-hour window |
| Incident lifecycle | 200; 13 persisted events, five requested in the probe |
| Nemotron/Gemini capability | Routes enabled and both provider keys configured; this does not verify provider availability |
| Approval | Route exists, but authenticated reads return 503: reviewer authentication is not configured |
| Notification capability | GET /api/integrations/capabilities returns 404 |
| Existing AI workflow | Incident investigation FAILED; Gemini PENDING. This is a stored earlier run, not a newly executed test |

The UI's current reads succeed across frontend/backend origins. CORS is not the current connection problem. Aborted requests during React mounting/navigation are separate from the reproducible notification 404.

## 1. Backend endpoint inventory

The running server advertises **27 method/path operations** in /openapi.json. This inventory establishes route presence, not successful execution of every POST.

| Method | Path | Intended consumer |
| --- | --- | --- |
| GET | `/api/system/metrics` | Host CPU/RAM panel; label as backend-host measurements |
| GET | `/api/telemetry/history` | Persistent rack/host charts and historical readings |
| GET | `/api/telemetry/summary` | Time-bucket analytics in Mission Control/Oversight |
| GET | `/api/telemetry/storage/health` | Tiger health/pending-write indicator |
| GET | `/health` | API availability indicator |
| GET | `/api/storage/health` | Mongo mode, status, and pending-write indicator |
| POST | `/api/telemetry` | Arduino gateway/simulator ingestion; not a dashboard polling action |
| GET | `/api/telemetry/latest` | Already used: current rack cards and latest measurements |
| GET | `/api/incidents` | Already used: incident list and counts |
| GET | `/api/incidents/{incident_id}` | Already used: selected incident identity and evidence |
| POST | `/api/incidents/{incident_id}/updates` | Optional operator resolution/reopen with note and concurrency check |
| GET | `/api/incidents/{incident_id}/history` | Persisted incident timeline |
| GET | `/api/modernization/capabilities` | Discover supported repair/analysis/approval and actual storage mode |
| POST | `/api/incidents/{incident_id}/repair` | Optional explicitly labelled manually authored demo verifier |
| GET | `/api/incidents/{incident_id}/analysis` | Current Gemini policy, approval summary, and repair references |
| GET | `/api/repairs/{job_id}` | Poll optional manual repair job |
| GET | `/api/repairs/{job_id}/report` | Manual repair acceptance/replay report |
| GET | `/api/repairs/{job_id}/diff` | Manual repair diff, returned as text |
| GET | `/api/agents/capabilities` | Enable investigation/review controls and show configuration blockers |
| POST | `/api/incidents/{incident_id}/investigate` | Run/Retry investigation button |
| GET | `/api/investigations/{job_id}` | Poll Nemotron job, errors, findings, and generated candidate |
| GET | `/api/investigations/{job_id}/patch` | Actual Nemotron candidate diff, returned as text |
| POST | `/api/incidents/{incident_id}/review` | Request independent Gemini review |
| GET | `/api/reviews/{job_id}` | Poll Gemini and display currentness/effective policy |
| GET (bearer) | `/api/incidents/{incident_id}/approval` | Authenticated package inspection and button eligibility |
| POST (bearer) | `/api/incidents/{incident_id}/approval` | Authenticated human APPROVE/REJECT against inspected hashes |
| GET (bearer) | `/api/incidents/{incident_id}/approval/history` | Authenticated decision/evidence audit |

Documentation/discovery routes are also available at /docs, /redoc, and /openapi.json; they are outside the 27 application operations above.

These additional P3 routes exist in source but are **not mounted on this running server**:

| Method | Path | Source and impact |
| --- | --- | --- |
| GET | /api/integrations/capabilities | backend/integrations/router.py; frontend receives 404 and disables notification actions |
| POST | /api/incidents/{incident_id}/notify | Same router; creates/reuses Jira, then attempts Slack when explicitly requested |

Do not switch to backend.integrations.app:app as the permanent fix: that entry point mounts P3 routes but omits P2 investigation/review/approval routes. backend.modernization.app:app currently has the opposite omission.

## 2. Confirmed discrepancies

| Area | Current frontend behavior | Available backend behavior | Required change |
| --- | --- | --- | --- |
| Basic data | Polls latest telemetry, incident list, and selected incident | These APIs work | Keep this foundation |
| Startup | P3 error tells the user to start a different wrapper | No documented wrapper mounts all features | One shared composition entry point |
| Nemotron | Displays stored tools; no Run/Retry button | Asynchronous investigation endpoints implemented | Submit explicitly and poll returned job link |
| Gemini | Displays raw incident decision_review only | Review jobs and dynamically evaluated policy/currentness implemented | Add review action; render /analysis and review-job responses |
| Repair | Sample diff/tests; outcome inferred from tool execution status | Candidate hashes, before/after acceptance results, replay, and actual diff exist | Replace scaffolds with actual candidate evidence |
| Approval | Disabled buttons; claims POST /api/repairs/{id}/approve is missing | Real endpoint is /api/incidents/{id}/approval | Correct route and configure named reviewer authentication |
| Charts | Stores up to 120 samples per device seen in this tab | Tiger history and time_bucket summaries exist | Fetch historical data; merge/deduplicate new samples |
| Timeline | Incident creation plus browser-observed readings | Persisted incident lifecycle events available | Consume /history; preserve event IDs and timestamps |
| Host monitoring | No host CPU/RAM panel | /api/system/metrics and host history supported | Add a separate backend-host panel |
| Storage messaging | Footer and 404 explanations assume volatile memory | Actual backend is MongoDB with Tiger telemetry | Derive status from health/capability APIs |
| Freshness | deviceHealth ages received_at | Backend evaluates observed_at and reports stale/future reasons | Show observation freshness and transport receipt separately |
| Unknown monitor | null mismatch takes the false branch and says both statuses agree | Failed monitor returns UNKNOWN/DEGRADED and mismatch=null | Preserve true/false/null; render unavailable comparison honestly |
| Recovery display | Browser history can label a rack recovered | Software verification does not establish equipment recovery | Keep telemetry state, candidate verification, and physical status separate |
| Workspace separation | Engineering reuses incident detail; Oversight reuses Mission Control | Relevant evidence/history/analytics APIs already exist | Give each workspace its intended data and actions |

Relevant source:
- [Frontend API client](../frontend/src/api.js)
- [App data loading](../frontend/src/App.jsx)
- [Incident details](../frontend/src/pages/IncidentInvestigation.jsx)
- [Sample diff/tests/approval](../frontend/src/components/investigation/Scaffolds.jsx)
- [Health, progress, and verification mapping](../frontend/src/lib/health.js)
- [Browser-only telemetry history](../frontend/src/hooks/useTelemetryHistory.js)
- [Browser-derived timeline](../frontend/src/components/EventTimeline.jsx)
- [Notification registration](../backend/integrations/app.py)
- [AI registration and lifecycle](../backend/modernization/app.py)

### Why the dashboard shows zero racks despite stored readings

At inspection, /api/telemetry/latest returned an empty list while Mongo restored an incident and Tiger returned Arduino history. Backend startup restores incidents and sequence guards, but does not repopulate the process-local latest-reading cache. This is not proof that Tiger ingestion failed.

Short term: show the known incident's last observation as historical/stale and load Tiger history for its source/device. Starting the gateway supplies new current readings. Do not POST old historical readings back into ingestion or replace their timestamps to make the page look live.

An older stored incident can still contain demo-legacy-placeholder-v1. Preserve that historical label; a new reading should record the actually executed monitor hash. Updating the UI must not rewrite old evidence to imply the real runner produced it.

For complete device discovery after restart, including healthy devices without incidents, add a clearly specified persisted source/device listing or latest-per-source backend API. Such an API is a proposed addition, not an endpoint currently available.

## 3. Implementation order and ownership

### Step 1 — Compose one backend (P1 + P2 + P3)

Choose one official startup command. A small backend/app.py composition module can reuse the existing P2 app/lifespan and register the P3 router exactly once. Alternatively extend the current modernization wrapper. Keep the same FastAPI object, P1 incident controller, Mongo client, Tiger store, and P2 worker lifecycle.

Move P3 result mutations through P1's trusted update/history/persistence boundary instead of relying on periodic detection of dictionary changes. Preserve Jira/Slack idempotency ledgers and provider-confirmed references. Do not expose privileged approval writes through the general /updates endpoint.

Add a startup contract test in a fresh process asserting all P1, P2, and P3 routes are present with no duplicate method/path registrations.

Done when: the same server exposes telemetry, investigations, reviews, approvals, history, and notifications. Update startup instructions and the frontend's obsolete alternate-wrapper hint together.

### Step 2 — Expand the frontend client and shared data model (P3 with P2 contracts)

Extend frontend/src/api.js to accept method, JSON body, headers, and AbortSignal. Add a text-response helper for diff routes. Support Authorization and Idempotency-Key only where needed. Decode string errors, structured detail.message/detail.reasons, and validation arrays.

Add functions for capabilities, storage health, analysis, job submission/polling, patch text, approval, incident history, Tiger history/summary, and host metrics. Centralize capability fetching so Jira and Slack do not request the same capability independently every poll.

Use server-returned links.job and job_id; an incident_id is not a job ID. Keep a stable idempotency key for retries of one action. A deliberate retry of a terminal failed/interrupted job uses a new key. Never submit side-effecting POSTs from mount effects or polling hooks.

Use:
- Incident endpoint for identity, operational status, source evidence, and provider references.
- /analysis for dynamically evaluated Gemini policy and approval summary.
- Specific job endpoint for full evidence, status, and failure details.
- Authenticated /approval for the inspected full package and authoritative eligibility.
- Tiger APIs for historical measurements and incident /history for lifecycle events.

Done when: views can consume these sources through one consistent client without embedding provider credentials or duplicating orchestration in components.

### Step 3 — Connect Incident Investigation (P2 + P3)

Add Run investigation / Retry investigation controls gated by capabilities and active-job state. POST /investigate, display QUEUED/RUNNING, poll links.job, then refresh analysis and incident data.

Show job.error.code/message prominently. Handle FAILED and INTERRUPTED, preserve the prior run as historical evidence, and provide intentional retry. Add explicit QUEUED, STALE, INTERRUPTED, APPROVED, REJECTED, and unconfigured states; the current classifier only handles a subset.

Add Request Gemini review after a completed current investigation. Poll its returned link and render result.recommendation alongside result.policy.effective_recommendation, reasons, requires_fresh_telemetry, currentness, and fault_context. Backend 409s remain authoritative if evidence changes.

Never equate a completed provider request with passing tests or human approval. Preserve SIMULATED/REPORTED/UNKNOWN provenance and the unverified physical-health statement.

Done when: one incident can be investigated and reviewed entirely from the UI, with clear failures and stale-evidence handling.

### Step 4 — Connect Engineering evidence (P2 + P3)

For the main AI workflow, read GET /api/investigations/{job_id}:
- result.generated_repair.verification_status and proposal_origin.
- tests.original and tests.candidate: exit_code, passed, failed, skipped, cases, and output.
- original_revision, candidate_revision, diff_revision, snapshot_revision.
- replay.original.status, replay.candidate.status, detection_gap_fixed, and cooling_fault_still_present.
- Fetch links.patch as text for the actual diff.

The selected candidate is also attached under incident.investigation.generated_repair after a completed investigation. /analysis.repair is the separate manually authored demo-repair job; it is not the Nemotron candidate. Do not select an unrelated manual repair merely because this field exists.

If exposing POST /repair, label it as the manually authored demo verifier and use /api/repairs/{job_id}, /report, and /diff. The current human approval package is built from the investigation's generated repair, not this independent demo job.

Handle absent candidates, failed verification, null replay, and unavailable diff as real states. A failed job can contain partial tool evidence without a final candidate. Do not manufacture successful candidate results from tool status=SUCCESS.

Done when: sample source/test content is absent from live evidence panels and before/after results agree with the selected job.

### Step 5 — Connect human decisions (P2 auth/config + P3 UI)

Configure FACTORYOS_APPROVERS_JSON following [the approval guide](HUMAN_APPROVAL_API.md). The current server reports approval_configured=false; implementing buttons alone will not remove its 503 response.

Use a named reviewer credential, kept out of VITE_* variables and source control. For this prototype, a reviewer can supply it to an in-memory session. NVIDIA/Gemini keys remain backend-only and are never reviewer credentials.

GET /api/incidents/{id}/approval with the bearer credential. Show the full candidate/package, blocking_reasons, persistence, and existing decision. Enable each action from its own can_approve / can_reject flag; rejection can be permitted when approval is blocked.

POST the exact inspected package_revision and candidate_revision, decision=APPROVE or REJECT, and optional comment. Reviewer identity and timestamps come from the backend. On 409, refresh the package and require another inspection. On a persistence-related 503, retain the decision request's idempotency key and show pending confirmation.

Render human status from /analysis.approval, not the historical approval_status=PENDING in model reports. Approval does not apply code, deploy, resolve incidents, or prove equipment recovery.

Done when: the UI can inspect, approve/reject, and display audit history without bypassing backend eligibility checks.

### Step 6 — Connect charts, history, and host health (P1 + P3)

Keep /api/telemetry/latest for current readings. Fetch:
- /api/telemetry/history?source_kind=arduino_serial&source_id=RACK-01 for rack history.
- /api/telemetry/summary with the same source and bucket_seconds=60, 300, 900, or 3600 for aggregates.
- /api/incidents/{id}/history for persisted incident events.
- /api/system/metrics for the backend host; use its source.host_id with source_kind=host_system for host history.

History samples contain observed_at, received_at, event_id, status, and payload; the rack fields are under payload.hardware, not directly on the row. Summary buckets expose temperature_c_avg/min/max, humidity_pct_avg, fault_count, sample_count, and host utilization averages. Distinguish source kinds when merging samples.

Deduplicate by stored event_id or sample identity, sort by observation time, and keep original timestamps. Use real incident event IDs/kinds/recorded_at; older P3 changes may be generic observed_update events until Step 1 adopts canonical publication. Global incident timelines may initially aggregate a bounded set of incident histories; no global event-feed endpoint exists yet.

Suggested polling: current telemetry/incident/job state every 2–3 seconds while visible; history/summary/health every 10–30 seconds and on window changes. Cancel obsolete requests. Jobs stop active polling at terminal state, while currentness can still be refreshed through analysis.

Show historical/stale readings distinctly from current data. Interpret observed_at with backend stale/future reasons and the 90-second/10-second policy. Keep real temperature measurements distinct from a switch-simulated fault, and backend-host CPU/RAM distinct from rack hardware.

Done when: chart history survives browser refresh and no live or historical sample is invented.

### Step 7 — Finish notification and operations behavior (P1 + P3)

Once mounted, reuse /notify; no additional Jira-only or Slack-only endpoint is currently advertised. Show Jira confirmation separately from Slack delivery and notification_status=PARTIAL. Persisted Jira alone must not mark the entire Jira/Slack step complete; use slack_status=DELIVERED for Slack.

Keep pending/uncertain-delivery retry safeguards. Notifications can run independently of AI and approval; their success does not resolve the incident. Any optional resolve/reopen action uses /updates with event_id, note, and expected_updated_at, rather than changing local React state.

Drive footer, availability messages, and status badges from actual capability/storage responses. Replace claims that investigation/repair/approval/history APIs are unimplemented. API reachable, fresh device data, configured providers, and durable storage are distinct statuses.

## 4. Suggested file work list

| File/module | Change |
| --- | --- |
| Backend composition + docs | One startup target with all routers and preserved lifecycles |
| backend/integrations/router.py | Canonical incident publication/history instead of raw dictionary mutation |
| frontend/src/api.js | JSON bodies, auth, idempotency, structured errors, text responses, new API functions |
| frontend/src/App.jsx | Shared capabilities/health, persisted data loading, selected-incident analysis |
| frontend/src/pages/IncidentInvestigation.jsx | AI controls, dynamic policy/approval, job evidence |
| frontend/src/components/investigation/Agents.jsx | Job errors, retry/review controls, policy/provenance |
| frontend/src/components/investigation/Scaffolds.jsx | Replace live samples and disabled placeholder approval with actual API consumers |
| frontend/src/components/investigation/RepairVerification.jsx | Real tests/replay/candidate state |
| frontend/src/lib/health.js | Full status mapping, observation freshness, separate software/equipment states |
| frontend/src/components/MismatchEvidence.jsx | Tri-state comparison; UNKNOWN/DEGRADED handling and unavailable reason |
| frontend/src/hooks/useTelemetryHistory.js | Tiger-backed history plus deduplicated live samples |
| frontend/src/components/EventTimeline.jsx | Persisted lifecycle events and honest event labels |
| frontend/src/components/WorkspaceContext.jsx and Shell.jsx | Actual features/storage/configuration messaging |
| frontend/src/pages/MissionControl.jsx | Historical charts, rack discovery/last-known state, separate host panel |
| frontend/src/components/investigation/JiraAction.jsx | Unified startup hint and notification partial-success behavior |

## 5. End-to-end acceptance checklist

1. Fresh server startup exposes all required routes. Both frontend and backend use one API base; Demo mode is off for live checks.
2. Gateway/simulator reading appears in latest telemetry and Tiger history. Fault mismatch opens/updates the same incident and persists to Mongo.
3. A browser refresh retains historical charts; a backend restart preserves incidents/jobs and displays last-known readings honestly when no fresh device sample exists.
4. Run/Retry investigation produces one job per intended action. StrictMode remounts, double clicks, polling, and reloads do not submit duplicate work.
5. Before/after test counts, actual diff, source/candidate hashes, and replay come from the selected generated candidate. A missing candidate shows no sample substitute.
6. Gemini review displays backend effective policy, provenance, and currentness. A changed fault or expired telemetry blocks old approval; equivalent advancing samples preserve compatible evidence.
7. Configured reviewers can inspect and approve/reject the exact package. Unconfigured/invalid authentication, changed packages, and pending database writes remain blocked.
8. A live monitor failure displays UNKNOWN/DEGRADED and unavailable comparison, never agreement or healthy status. Old observed_at with recent received_at remains stale.
9. Incident timeline shows persisted lifecycle events after refresh. Optional resolution/reopen requires a reason and survives persistence.
10. With explicit authorization for provider messages, one notification creates/reuses Jira and reports Slack delivery or partial failure without duplicate sends.
11. Host CPU/RAM is visibly scoped to the backend host. Storage health and disabled/unavailable features have distinct UI states.
12. Approval leaves the incident and physical fault state independent; deployment/activation remains unavailable until separately implemented.

Use scripted providers and disposable storage for automated acceptance. Existing pytest coverage validates backend pieces, but add combined startup/API contract checks and Playwright flows through the real UI. Live model availability and external Jira/Slack delivery require separately authorized live checks.

