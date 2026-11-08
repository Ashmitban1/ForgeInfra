# ForgeInfra — HackUTD 2026

ForgeInfra is a three-person proof-of-concept for data-center information reliability
and verified legacy-monitoring repairs. Read
[the project handoff](docs/ForgeInfra_AGENT_HANDOFF.md) for the broader plan.

## What is actually implemented

The integrated backend accepts Arduino-gateway or simulated telemetry, executes
the fixed legacy monitor, and independently computes expected status and alerts.
Incidents feed Nemotron investigation, Docker candidate verification, Gemini
review, and authenticated human approval. React/Vite provides the dashboard.

P1's optional MongoDB writer persists incidents, evidence, and lifecycle history;
P2's jobs use the same database/client. Optional Tiger Data storage supports rack
and host telemetry history/analytics. Without configuration, storage is explicitly
volatile. See [the API contract](docs/API_CONTRACT.md) for routes and failure behavior.

Physical Arduino operation, live Atlas/Tiger Data connectivity, Jira/Slack,
Solana, Vultr deployment, and production authentication are not established by
the local integration tests. The dashboard connects investigation, generated evidence, independent review, human approval, persisted history, host metrics, and notifications. Candidate activation, PR creation, merge, and deployment remain separate.

**Person 2's runnable baseline:** `fixtures/legacy_monitor/monitor.py` is a
standalone, team-authored temperature-only monitor with JSON samples, an execution
adapter, and characterization tests. See [the fixture guide](fixtures/legacy_monitor/README.md).
This is representative team-authored software, not a vendor codebase. Ingestion
now runs this actual fixture and records its SHA-256 source revision. Its original
temperature-only cooling-fault defect is intentionally preserved. A failed monitor
returns `UNKNOWN` / `DEGRADED`; deterministic `should_alert` remains independent.
A separate manually authored candidate can be verified with Docker-backed tests:

```sh
docker build -t ForgeInfra-monitor:local backend/modernization/container
python -m backend.modernization.testing --incident-id INC-COOLING-001
```

See [the modernization workflow](backend/modernization/README.md). Human approval
is available through the P2 wrapper; deployment and live activation remain pending.

**Integrated entry point:** `python -m uvicorn backend.app:app --reload`
mounts P2 routes on P1's same FastAPI app, including Jira/Slack routes. P1 remains the canonical incident writer;
P2 synchronously publishes job transitions through P1's history/persistence
boundary. Fresh workers are created after storage restoration on every app
lifecycle. Acknowledged MongoDB jobs survive restart; unfinished work becomes
`INTERRUPTED`. Use one backend worker/process. See the
[modernization API guide](docs/MODERNIZATION_API.md).

**Person 2 step 5:** The same wrapper now registers real NVIDIA Nemotron
investigations, validated diagnostic tools, and constrained model-generated rule
candidates with actual Docker verification. Set `NVIDIA_API_KEY` in an ignored
dotenv file or backend environment, submit an incident, and POST its `/investigate`
route. The generated candidate is verified offline; activation remains separate.
See [the agent guide](backend/agents/README.md).

**Person 2 step 6:** Set `GEMINI_API_KEY` and POST the incident's `/review` route
after its Nemotron investigation completes. Gemini independently reviews the
captured evidence, source, diff, tests, and replay. Validated recommendations and
deterministic policy results appear in the shared incident's `decision_review`
and `/analysis`. Exact captured evidence stays immutable; compatible advancing
samples can retain the same monitoring case. Material changes, including a fault
clearing and recurring, invalidate previous reviews. See
[the Gemini review guide](backend/agents/GEMINI_REVIEW.md).

**Person 2 human gate:** Configure named reviewer bearer-token digests in
`ForgeInfra_APPROVERS_JSON`, inspect GET `/api/incidents/{id}/approval`, then POST
APPROVE/REJECT against the exact candidate/package hashes. Decisions and frozen
evidence use P1's locked canonical update and persistence queue. MongoDB approval
requires durable readback; pending persistence returns 503 and blocks the gate.
`/analysis` exposes current human approval separately from AI recommendations.
See [the human approval API](docs/HUMAN_APPROVAL_API.md).

## Folders
```text
ForgeInfra/
├── .github/workflows/python-tests.yml
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
├── backend/
│   ├── main.py                 # P1: FastAPI and incidents
│   ├── reliability.py          # Independent expected status, freshness, alerts
│   ├── legacy_runtime.py       # Fixed fixture execution and degraded handling
│   ├── schemas/incident.py     # Shared Pydantic input schema
│   ├── storage/                # P1: Mongo incidents/history; Tiger telemetry
│   ├── agents/                 # P2: Nemotron tools and independent Gemini review
│   ├── modernization/          # P2: fixture adapter, candidate patch, Docker tests
│   └── integrations/           # P3: Jira and Slack adapters; Solana pending
├── hardware/
│   ├── arduino/ForgeInfra_arduino/ForgeInfra_arduino.ino
│   ├── serial_gateway.py
│   └── simulator.py
├── frontend/
│   ├── package.json
│   ├── index.html
│   └── src/{App.jsx,main.jsx,styles.css}
├── tests/test_api.py
└── docs/{API_CONTRACT.md,TEAM_TASKS.md,GITHUB_PUSH.md,ForgeInfra_AGENT_HANDOFF.md}
```

## Run locally (Windows PowerShell)

For containerized frontend, backend, and persistent local MongoDB, see
[the Docker guide](docs/DOCKER.md). Quick start from the repository root:

```sh
# If you do not already have a root .env:
cp .env.example .env
docker compose up --build -d
```

Dashboard: http://localhost:5173/#/; API: http://localhost:8000/docs. AI repair
verification requires the guide's optional Docker-socket override.

**Terminal 1 — Backend, from repository root:**
```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn backend.app:app --reload
```
Open http://127.0.0.1:8000/docs and http://127.0.0.1:8000/health. If PowerShell blocks activation, run `.\.venv\Scripts\python.exe` instead of `python`.

On macOS/Linux, create a Python 3.11 virtual environment with
`python3 -m venv .venv`, then `source .venv/bin/activate`, install requirements,
and run the same Uvicorn command. For simulated input, use
`python hardware/simulator.py --mode normal` or `--mode fault`; use the returned
incident ID in Swagger. Docker Desktop is required for candidate verification.


**Terminal 2 — Basic React dashboard:**
```powershell
cd frontend
npm install
npm run dev
```
Open http://127.0.0.1:5173. Requires Node.js 20+.

## Terminal 3 - Connect your actual ELEGOO UNO R3

1. Open `hardware/arduino/ForgeInfra_arduino/ForgeInfra_arduino.ino` in Arduino IDE.
2. Install the Adafruit **DHT sensor library** and **Adafruit Unified Sensor**.
3. For a *three-pin* DHT11 module labeled S/+/-: `S → D2`, `+ → 5V`, `- → GND`. For a two-pin tilt switch: one terminal to `D3`, other to `GND`. **Verify the actual board/module labels**, disconnect power during wiring. A bare DHT11 has a different layout.
4. Upload sketch to Uno. Check Serial Monitor at **9600 baud**; close it before gateway.
5. From repo root (FastAPI must be running):
```powershell
python -m serial.tools.list_ports
python hardware/serial_gateway.py --port COM3
```
Replace `COM3` with your actual port. `cooling_fault` is a **switch-simulated** equipment failure, not a measurement of a real cooling system. No mains or real equipment controls.

## Collaborate on GitHub

See `docs/GITHUB_PUSH.md` for push commands and `docs/TEAM_TASKS.md` for assignments. See `docs/API_CONTRACT.md` before adding new API endpoints.

Set backend-only `MONGODB_URI` / `MONGODB_DATABASE` and
`TIGERDATA_DATABASE_URL` in ignored `.env` files to enable persistence. Inspect
`/api/storage/health`, `/api/telemetry/storage/health`, and
`/api/modernization/capabilities` for actual storage mode. Unacknowledged outage
queues remain memory-only. Never mount an independent P2 incident writer.

Run `python -m pip install -r requirements-dev.txt` and `python -m pytest -q`.
Default tests isolate developer storage and provider credentials. Provider
responses in automated integration tests are scripted. Optional real
Docker/local MongoDB tests are described in [the modernization guide](docs/MODERNIZATION_API.md).

Approval routes authenticate named reviewers; other backend routes remain
unauthenticated. Keep the complete backend local/isolated until protected.
`.env` and credentials are ignored by Git.
