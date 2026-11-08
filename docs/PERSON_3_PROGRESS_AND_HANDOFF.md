# FactoryOS — Person 3 Progress and Team Handoff

Updated: November 7, 2026  
Role: Frontend + Operations  
Branch: `feat/dashboard`

## What Person 3 completed

### React dashboard and incident investigation

- Built Mission Control with an animated data hall, rack cards, telemetry panels,
  sparklines, incident lists, and an event timeline.
- Added Incident Investigation with selected-incident details, reliability mismatch
  evidence, investigation progress, agent activity/recommendation displays, and
  repair verification presentation.
- Connected the dashboard to the existing backend telemetry and incident GET APIs,
  with polling, loading, empty, stale-data, and API-error states.
- Preserved the existing Motion animations and frontend routing.
- Kept demo fixtures separate from API data. Demo agent progress, recommendations,
  diffs, and test results are illustrative; they are not proof of real agent calls
  or repairs. Approval actions remain disabled scaffolds.

### Real Jira Cloud integration

- Implemented Jira Cloud REST API v3 Task creation for project `KAN` (`hackUTD26`)
  at `https://muhdaymanhaque.atlassian.net`.
- Added a separate notification router for
  `POST /api/incidents/{incident_id}/notify`.
- The adapter looks up a backend incident and sends its ID, rack/device, temperature,
  humidity, cooling-fault status, simulated-fault disclosure, timestamps, severity,
  and reliability mismatch evidence using an Atlassian Document Format description.
- Stores the actual confirmed Jira issue key, ID, and URL in the incident's
  `integrations` fields. No fabricated creation success.
- Handles missing configuration, authentication failures, permission/project/field
  errors, rate limiting, timeouts, and network failures without exposing provider
  response bodies or credentials.
- Added Create Jira Issue to Incident Investigation, with pending, success, and
  failure states. A confirmed issue becomes a View Jira Issue link.
- Blocks duplicate requests while pending and reuses existing confirmed references.
- Added `GET /api/integrations/capabilities`; creation is enabled only when the
  backend reports notification-route support. Demo fixtures cannot submit to Jira.

### Duplicate prevention

An ignored local SQLite ledger reserves an attempt before contacting Jira and
retains confirmed references. Concurrent or repeated submissions cannot create a
second issue for the same incident identity. Explicit Jira rejections permit a
corrected retry. An uncertain outcome, such as a timeout, blocks further creation
with HTTP 409 until manually reconciled against Jira.

Keep `.factoryos-jira.sqlite3` across restarts. Do not delete it to bypass a 409.
Incident storage itself is still in-memory; the ledger also includes the incident
creation timestamp so recycled IDs after a restart do not inherit unrelated issues.
This is a local-installation approach; multiple hosts need shared durable storage.

## Live Jira verification: successful

One real integration test created and read back:

- Issue: **KAN-4**
- Jira issue ID: **10013**
- Link: https://muhdaymanhaque.atlassian.net/browse/KAN-4
- Jira confirmed the project is KAN, the issue type is Task, and the description
  discloses that the fault was simulated.
- A repeated notification returned the same issue with `already_exists: true`.
- The backend incident GET response contained the confirmed Jira reference.

This used the actual FastAPI telemetry/notification routes via TestClient and real
HTTPS requests to Jira. It did not automate a browser click. The smoke test's
in-process incident disappears after the script exits; KAN-4 remains in Jira.
A separately running dashboard backend will not automatically contain that incident.

## Validation

- Backend: **27 tests passed**, covering existing API behavior, successful Jira
  creation, existing references, invalid incident IDs, missing configuration,
  authentication/project/permission errors, rate limiting, network failures,
  uncertain confirmations, safe retries, concurrency, ledger reuse, capability
  reporting, and invalid configuration.
- Frontend production build: **passed**.
- Live Jira creation, read-back, and duplicate-reference verification: **passed**.
- Git whitespace/diff and credential-exclusion checks: **passed**.
- Latest local test environment used Python 3.15; required Python 3.11 validation
  remains pending. Starlette deprecation and Motion bundle warnings were non-fatal.
- Full browser interaction remains a manual verification step.

## How teammates can run it

From the repository root, create/activate a Python 3.11 virtual environment and
install dependencies:

```sh
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows, activate with `.venv\Scripts\Activate.ps1`.

Create your own **backend/.env** using these backend-only variables:

```env
JIRA_BASE_URL=https://muhdaymanhaque.atlassian.net
JIRA_EMAIL=<your authorized Atlassian email>
JIRA_API_TOKEN=<your Atlassian API token>
JIRA_PROJECT_KEY=KAN
```

Do not share credentials through Git, chat, or frontend `VITE_*` variables.
`.env` files are Git-ignored; `.env.example` contains placeholders. The token's
account needs access to KAN and permission to create Tasks.

Start the notification-enabled backend:

```sh
python -m uvicorn backend.integrations.app:app --reload
```

In another activated terminal, submit simulated telemetry:

```sh
python hardware/simulator.py --mode fault
```

Start the frontend (Node.js 20+):

```sh
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173/?demo=0 to ensure live API mode. Select the incident,
open Incident Investigation, and click **Create Jira Issue**. Confirm that the
returned key/link opens a real KAN issue. Refresh/revisit the incident: it should
show **View Jira Issue**, not create another ticket.

Simulated telemetry submitted to the backend is a real backend incident and can
create a real Jira Task; the ticket explicitly discloses the simulation. Demo
fixtures used only inside the frontend are not submitted.

If the page does not load, ensure both processes remain running:

- Frontend: http://127.0.0.1:5173/
- Backend health: http://127.0.0.1:8000/health
- Integration support: http://127.0.0.1:8000/api/integrations/capabilities

The servers were restarted locally after a page-load failure caused by stopped
processes. Teammates must start their own servers.

## API example

No request body is required:

```http
POST /api/incidents/INC-COOLING-001/notify
```

Response shape (example values; use the actual response for your incident):

```json
{
  "incident_id": "INC-COOLING-001",
  "provider": "jira",
  "already_exists": false,
  "jira_key": "KAN-4",
  "jira_id": "10013",
  "jira_url": "https://muhdaymanhaque.atlassian.net/browse/KAN-4"
}
```

Repeated confirmed requests return `already_exists: true` and the same reference.

## Relevant files

| Area | Files |
| --- | --- |
| Dashboard | `frontend/src/pages/`, `frontend/src/components/`, `frontend/src/hooks/`, `frontend/src/styles.css` |
| API and demo separation | `frontend/src/api.js`, `frontend/src/demo/fixtures.js`, `frontend/src/router.js` |
| Jira UI | `frontend/src/components/investigation/JiraAction.jsx`, `frontend/src/pages/IncidentInvestigation.jsx` |
| Jira adapter/router | `backend/integrations/jira.py`, `backend/integrations/router.py` |
| Integration startup | `backend/integrations/app.py` |
| Mocked tests | `tests/test_jira.py` |
| Repeatable live check | `scripts/verify_jira_live.py` |
| Setup and contract | `.env.example`, `.gitignore`, `requirements.txt`, `README.md`, `docs/API_CONTRACT.md`, `backend/integrations/README.md` |

To run checks:

```sh
python -m pytest -q
npm --prefix frontend run build
```

For an explicit live verification, `python -m scripts.verify_jira_live` reuses its
saved incident and ledger result on this machine. Keep the ignored
`.factoryos-jira-live.json` and `.factoryos-jira.sqlite3` files to avoid another test
ticket. On a fresh machine this script can create one real issue; run deliberately.

## Coordination and remaining work

**Person 1:** `backend/main.py`, schemas, hardware, and storage implementation were
not edited. Current integration startup imports P1's app and injects its existing
incident dictionary/lock into a separate router. To use `backend.main:app` directly,
coordinate registration of `create_notification_router(_incidents, _lock)` and
backend environment loading. Register once only; the wrapper already registers
it. Adapt the storage interface when durable persistence arrives.

**Person 2:** agents and modernization code were not modified. Real investigation,
repair, regression-test evidence, and recommendation fields should populate the
existing contract when available. Frontend scaffolds do not claim these steps ran.

**Future Person 3 work:** GitHub repair/approval automation, Solana recording,
and production hosting are not implemented by this Jira work. Keep the current
unauthenticated backend local until authentication and durable storage are ready.

## Git handoff status

- `619bfc6`: animated data-hall Mission Control and repair verification — preserved.
- `de99263`: initial real Jira notifications and dashboard actions — pushed to
  `origin/feat/dashboard` earlier with explicit user authorization.
- Latest live-verification script, route-capability check, additional tests,
  evidence/configuration improvements, documentation updates, and this handoff
  are currently **local uncommitted changes**. They have not been pushed.
- No merge was performed. Teammates pulling the previously pushed branch will
  need the latest changes shared through an authorized commit/push separately.

## Update: Slack incident notifications

The combined Jira → Slack notification adapter and Investigation status UI are now implemented locally. Existing Jira references are reused; confirmed Slack channel/timestamps are stored. Explicit failures permit retries, while uncertain delivery requires reconciliation. Generic Slack connectivity was previously verified, but the new incident message awaits explicit approval. See backend/integrations/README.md for current behavior and the prepared KAN-4 verification. No changes were committed or pushed for this update.
