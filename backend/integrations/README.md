# Jira and Slack notifications (Person 3)

Real Jira Cloud v3 Task creation using ADF descriptions, with no changes to P1 main.py
or P2 code. Slack now follows Jira through the same notification router; see the current combined workflow below.

## Local setup

Install requirements in a Python 3.11 virtual environment:

```sh
python -m pip install -r requirements.txt
```

Create **backend/.env** with the following values (see root .env.example):

```env
JIRA_BASE_URL=https://YOUR-SITE.atlassian.net
JIRA_EMAIL=YOUR-ATLASSIAN-EMAIL
JIRA_API_TOKEN=YOUR-TOKEN
JIRA_PROJECT_KEY=KAN
```

Use an Atlassian API token supporting Basic authentication against your site URL.
The account needs Browse Projects and Create Issues access in hackUTD26 (KAN),
with Task available and any project-specific required fields configured. Credentials
stay on the backend; never use VITE_* for them. backend/.env is Git ignored.
Environment variables take precedence over that file.

Run from the repository root:

```sh
python -m uvicorn backend.app:app --reload
```

The unified entry point reuses the existing P1/P2 app and registers the
separate notification router. Existing GET and telemetry endpoints are preserved.
Starting backend.main:app alone does not register notifications.

In another activated terminal:

```sh
python hardware/simulator.py --mode fault
```

Then start the frontend with `npm --prefix frontend run dev`. Open
http://127.0.0.1:5173 without demo mode, select the incident, open Incident
Investigation, and click **Create Jira Issue**. The button changes to **View Jira
Issue · KAN-…** only after backend confirmation. Simulated telemetry is real
backend data and can create a real Jira issue, explicitly marked simulated in its
description. Frontend fixture/demo mode cannot submit to Jira.

## API

No request body is required:

```http
POST /api/incidents/INC-COOLING-001/notify
```

Illustrative response, not evidence of live creation:

```json
{
  "incident_id": "INC-COOLING-001",
  "provider": "jira",
  "already_exists": false,
  "jira_key": "KAN-3",
  "jira_id": "10003",
  "jira_url": "https://YOUR-SITE.atlassian.net/browse/KAN-3"
}
```

Repeated requests return the confirmed result with `already_exists: true`.
GET incident responses expose the same fields under `integrations` (including
additive `jira_id`). Errors use FastAPI's `{"detail":"actionable message"}`:
404 incident missing; 503 missing/invalid configuration or rate limit;
502 Jira authentication, permissions, fields, network, or invalid confirmation;
409 pending/uncertain previous attempt. Upstream response bodies are never exposed.

## Duplicate prevention and reconciliation

The ignored `.factoryos-jira.sqlite3` ledger reserves an attempt **before** POSTing
and stores the confirmed key/ID/URL. Concurrent requests cannot issue another POST.
There are no automatic HTTP retries. Explicit rejection (400/401/403/404/422/429)
permits a corrected retry. Timeouts, connection failures, 5xx, and invalid success
responses leave a pending reservation: Jira may already have created the issue.
A retry returns 409, never a speculative success or another creation request.

For an uncertain attempt, stop the backend, inspect Jira for the incident ID and
created timestamp, and inspect `jira_attempts` using a SQLite client. Its identity
contains site, project, incident ID, and incident created timestamp. If an issue
exists, update that row's `result` with a JSON object containing the actual
`jira_key`, `jira_id`, `jira_url`; the next notify request attaches it to storage.
Delete a pending row only after confirming Jira did not create the issue. Never
clear the ledger simply to bypass a 409. Reconciliation is intentionally manual.

Incident storage uses P1's configured MongoDB writer, or explicit volatile memory mode when disabled. The ledger identity includes the incident creation timestamp so recycled IDs cannot inherit unrelated references. Keep the local ledger across restarts; multiple hosts require shared durable reservations.

## Shared application and persistence

Start `backend.app:app`. The previous modernization and integrations wrappers alias this same app, including all P1/P2/P3 routes. No alternative server is needed for notifications.

The router reads through P1's canonical snapshot callback and publishes integration-only fields through `main.publish_notification`. Each accepted change checks the incident incarnation, preserves a confirmed Slack delivery, and queues its lifecycle event and snapshot under P1's lock. Database IO runs outside the lock. Retries retain the existing provider ledgers and do not create extra events for unchanged references.

## Validation

`python -m pytest -q` covers creation, existing issues, missing incident/config,
authentication, project/permission failures, timeouts/network, uncertain outcomes,
concurrency, ledger reuse, and safe retries. `npm --prefix frontend run build`
checks production compilation. Live verification succeeded against KAN: Task KAN-4 (ID 10013),
https://muhdaymanhaque.atlassian.net/browse/KAN-4. Jira GET read-back verified project,
Task type, simulated-fault disclosure, and the stored reference. Repeating notify
returned the same key with already_exists=true. Mocked issue keys remain fixtures.

The latest local run passed 27 backend tests and the frontend production build.
The available virtual environment runs Python 3.15; Python 3.11 was not available
for local validation. Existing Starlette deprecation and Motion bundle warnings
were non-fatal.

To repeat the explicit live test without generating another test ticket:

```sh
python -m scripts.verify_jira_live
```

Keep both ignored .factoryos-jira-live.json and .factoryos-jira.sqlite3. The smoke
test reuses its saved incident identity and confirmed ledger result on subsequent
runs. It uses the actual telemetry and notify FastAPI routes via TestClient, then
reads back the real issue over HTTPS. It does not automate a browser click. The
smoke test's in-process incident disappears on exit; it is not a persistent incident
in a separately running dashboard backend. Use simulator.py against that running
backend to exercise the complete dashboard workflow.

## Route availability

`GET /api/integrations/capabilities` returns `{"jira":{"notify":true}}` when this
router is registered. It exposes no credentials or configuration. The dashboard
checks it before enabling Create Jira Issue; a 404 explains which backend entry
point to start. Capability indicates route support; missing credentials are
reported by POST notify. Existing confirmed references can be returned even if
credentials are subsequently removed.

## Slack incident delivery (current combined workflow)

POST notify now creates/reuses Jira and then sends one incident message to Slack.
Add to backend/.env:

```env
SLACK_BOT_TOKEN=<local bot token>
SLACK_CHANNEL_ID=C0CFUREPTGS
```

The previously verified destination is workspace hackutd26, #factoryos-incidents.
Bot needs chat:write and channel membership. Channel verification tooling also
needs channels:read for public channels. Never expose tokens through VITE_*.
The adapter uses Slack's documented [chat.postMessage API](https://docs.slack.dev/reference/methods/chat.postMessage/),
checks ok=true and a valid matching channel/timestamp before recording delivery,
and disables mention parsing and link previews in incident messages.

The UI action is **Create Jira Issue & Notify Slack**. An existing issue keeps its
View Jira Issue link and offers **Notify Slack / Retry** until confirmed delivered.
Pending/unconfirmed outcomes disable retries and show reconciliation instructions.
Demo fixture notifications remain disabled. The integration facts display actual
Slack delivery status, channel ID, and message timestamp.

Example additive response fields (illustrative, not live-delivery evidence):

```json
{
  "jira_key": "KAN-4",
  "jira_url": "https://muhdaymanhaque.atlassian.net/browse/KAN-4",
  "notification_status": "DELIVERED",
  "slack_status": "DELIVERED",
  "slack_channel_id": "C0CFUREPTGS",
  "slack_message_ts": "1794107859.146339",
  "slack_message_id": "1794107859.146339",
  "slack_error": null,
  "slack_already_exists": false
}
```

Jira success plus missing Slack configuration, explicit rejection, or ambiguous
failure is HTTP 200 with notification_status=PARTIAL; inspect slack_status and
slack_error. Jira remains stored, and retry reuses its issue. Slack success persists
both in shared incident storage and a new slack_attempts table in the same ignored
SQLite ledger. Confirmed messages are not intentionally sent again, including
when Slack configuration changes later. This prevents deliberate duplicates;
it does not promise exactly-once delivery after ambiguous network failures.

Known explicit Slack rejections (e.g. invalid_auth, missing_scope, not_in_channel,
channel_not_found, rate limits) allow a corrected manual retry. Timeouts,
connection errors, 5xx, unknown provider errors, and malformed confirmations are
UNCONFIRMED and block another POST. A reservation left PENDING after interruption
also blocks automatic resend. Stop the backend and reconcile the incident ID,
created timestamp, and Jira link against Slack. In slack_attempts, identity contains
incident ID, incident creation timestamp, and Jira URL. After confirming delivery,
set result to JSON with slack_status=DELIVERED, actual slack_channel_id,
slack_message_ts, slack_message_id, and slack_error=null. Only remove an uncertain
reservation after confirming no delivery occurred. Never clear a ledger just to
retry. Keep the local ledger; multiple hosts need shared durable storage.

No additional main.py registration is needed: the existing integration router now
handles both providers. Person 1 can adopt the same factory registration documented
above after coordination. Restart the integration backend to load these changes
and backend/.env. Teammate-owned main.py, agents, and modernization remain unchanged.

### Prepared live incident verification — approval required

Generic Slack connectivity was verified previously; **this new incident adapter
has not sent a live message yet**. The prepared verification reuses the existing
saved incident INC-COOLING-001, device JIRA-LIVE-VERIFICATION-SIMULATED, and confirmed
KAN-4 reference. It will not create another Jira ticket. Preview without sending:

```sh
python -m scripts.verify_slack_incident_live
```

Only after explicit user approval:

```sh
python -m scripts.verify_slack_incident_live --send
```

It invokes the combined notification endpoint once, prints confirmed channel/ts
and Jira link, and does not automatically retry any failure. A later rerun reuses
the ledger rather than intentionally sending a duplicate. Keep the existing
snapshot and ledger. The older verify_jira_live script now requires --notify-slack
because POST notify also sends Slack; run it only with approval for both providers.

Latest combined-workflow validation: 53 backend tests passed and frontend production build passed. Local Python remains 3.15; Python 3.11 validation is pending.
