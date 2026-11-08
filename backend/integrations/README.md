# Jira notifications (Person 3)

Real Jira Cloud v3 Task creation using ADF descriptions, with no changes to P1 main.py
or P2 code. Slack can be added as a separate adapter and notification operation.

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
python -m uvicorn backend.integrations.app:app --reload
```

This explicit integration entry point imports the original P1 app and registers the
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

Incident storage remains volatile; the timestamp in the ledger identity prevents
recycled incident IDs after restart from inheriting an unrelated issue. Keep the
ledger across backend restarts. This supports a single local backend installation;
multiple hosts require a shared durable store. Keep the unauthenticated app local.

## Person 1 coordination

No shared main.py edits were made. Person 1 can adopt registration after review:

```python
from backend.integrations.router import create_notification_router
app.include_router(create_notification_router(_incidents, _lock))
```

Register exactly once, after storage initialization. When adopting this in main.py,
load backend/.env at startup as integrations/app.py does, and run main:app rather
than the wrapper. Replace the injected dict/lock interface when storage becomes
durable. No Person 1 change is required to run the integration entry point today.

## Validation

`python -m pytest -q` covers creation, existing issues, missing incident/config,
authentication, project/permission failures, timeouts/network, uncertain outcomes,
concurrency, ledger reuse, and safe retries. `npm --prefix frontend run build`
checks production compilation. Live KAN verification is pending credentials;
mocked issue keys are test fixtures only.
