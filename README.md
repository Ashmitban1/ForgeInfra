# FactoryOS — HackUTD 2026

GitHub-ready **three-person team repository**. FactoryOS is a proof-of-concept for data-center information reliability and legacy monitoring modernization. Read `docs/FACTORYOS_AGENT_HANDOFF.md` for full strategy.

## What is actually implemented

✅ FastAPI telemetry API, deterministic mismatch checks, simple in-memory incidents, basic tests; ✅ Arduino UNO sketch + serial gateway + simulator; ✅ minimal React/Vite dashboard reading backend data; ✅ GitHub Actions Python test workflow.

**User-verified:** physical Arduino-to-FastAPI ingestion and simulated fault detection.
**Implemented:** optional MongoDB incident/evidence/lifecycle persistence and Tiger Data telemetry history/time-bucket summaries. Atlas Arduino incident persistence/restart is user-verified. Real Tiger host writes, history, SQL summaries and restart retrieval are independently verified; physical Arduino OFF/ON/OFF history in Tiger remains unverified. See `docs/STORAGE_INTEGRATION.md` for configuration and evidence boundaries.
**Not yet implemented or verified in this checkout:** real legacy application modernization; Nemotron/Gemini; Jira/Slack; GitHub PR automation; Solana; Vultr; authenticated production deployment. `legacy_monitor_stub` is only a controlled example, never Northmark's actual software.

## Folders
```text
FactoryOS/
├── .github/workflows/python-tests.yml
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
├── backend/
│   ├── main.py                 # P1: FastAPI and incidents
│   ├── reliability.py          # P1: checks + temporary legacy stub
│   ├── schemas/incident.py     # Shared Pydantic input schema
│   ├── storage/                # P1: database work pending
│   ├── agents/                 # P2: AI agents pending
│   ├── modernization/          # P2: legacy fixture and repair pending
│   └── integrations/           # P3: Jira, Slack, Solana pending
├── hardware/
│   ├── arduino/factoryos_arduino/factoryos_arduino.ino
│   ├── serial_gateway.py
│   └── simulator.py
├── frontend/
│   ├── package.json
│   ├── index.html
│   └── src/{App.jsx,main.jsx,styles.css}
├── tests/test_api.py
└── docs/{API_CONTRACT.md,TEAM_TASKS.md,GITHUB_PUSH.md,FACTORYOS_AGENT_HANDOFF.md}
```

## Run locally (Windows PowerShell)

**Terminal 1 — Backend, from repository root:**
```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn backend.main:app --reload
```
Open http://127.0.0.1:8000/docs and http://127.0.0.1:8000/health. If PowerShell blocks activation, run `.\.venv\Scripts\python.exe` instead of `python`.

**Terminal 2 — Simulated input and tests:**
```powershell
python hardware/simulator.py --mode normal
python hardware/simulator.py --mode fault
python -m pytest -q
```
On fault input the backend should detect `legacy_missed_fault` and `reliability.mismatch: true`.

**Terminal 3 — Basic React dashboard:**
```powershell
cd frontend
npm install
npm run dev
```
Open http://127.0.0.1:5173. Requires Node.js 20+.

## Connect your actual ELEGOO UNO R3

1. Open `hardware/arduino/factoryos_arduino/factoryos_arduino.ino` in Arduino IDE.
2. Install the Adafruit **DHT sensor library** and **Adafruit Unified Sensor**.
3. For a *three-pin* DHT11 module labeled S/+/-: `S → D2`, `+ → 5V`, `- → GND`. For a two-pin tilt switch: one terminal to `D3`, other to `GND`. **Verify the actual board/module labels**, disconnect power during wiring. A bare DHT11 has a different layout.
4. Upload sketch to Uno. Check Serial Monitor at **9600 baud**; close it before gateway.
5. From repo root (FastAPI must be running):
```powershell
python -m serial.tools.list_ports
python hardware/serial_gateway.py --port COM3
```
Replace `COM3` with your actual port. `cooling_fault` is a **switch-simulated** equipment failure, not a measurement of a real cooling system. No mains or real equipment controls.

## Backend host metrics

After installing `requirements.txt`, open `http://127.0.0.1:8000/api/system/metrics`
for timestamped CPU and RAM measurements from the machine running FastAPI.
The source includes its hostname and is separate from Arduino/rack telemetry.
CPU sampling takes approximately 0.1 seconds per request. `OK` means both
metrics were collected; `DEGRADED` retains one successful metric; `UNAVAILABLE`
returns HTTP 503 with null metrics and safe error codes. This reports collection
health, not whether CPU/RAM utilization is operationally safe. See
`docs/API_CONTRACT.md` for field names and failure semantics.

## MongoDB persistence

Set backend-only `MONGODB_URI` and optional `MONGODB_DATABASE` in your environment
or ignored `backend/.env` to persist incidents and immutable reliability evidence.
No URI keeps memory mode. Configured startup restores saved incidents and IDs.
Use `/api/storage/health` and the telemetry response's `X-FactoryOS-Persistence`
header to check acknowledged versus pending writes. During an outage alerts keep
working, but unacknowledged writes are queued only in memory. Use one backend
worker per database. See [storage setup, migration and restart tests](backend/storage/README.md)
before restarting a process that holds unsaved incidents.

## Lifecycle results and Tiger Data history

Use `POST /api/incidents/{id}/updates` for idempotent investigation, integration,
and resolution records; inspect `/api/incidents/{id}/history` for saved snapshots.
Set backend-only `TIGERDATA_DATABASE_URL` to a Tiger Cloud PostgreSQL connection
URL to store accepted Arduino/simulator events plus periodic host CPU/RAM samples.
Query `/api/telemetry/history` and `/api/telemetry/summary` with source filters.
These are real database adapters; live cloud verification requires configured
credentials. See [setup, API examples and teammate handoff](docs/STORAGE_INTEGRATION.md).

## Collaborate on GitHub

See `docs/GITHUB_PUSH.md` for push commands and `docs/TEAM_TASKS.md` for assignments. See `docs/API_CONTRACT.md` before adding new API endpoints.

The backend currently has **no authentication**. Incident storage is memory-only
unless MongoDB is configured. Keep it local/isolated until protected. `.env` and
credentials are ignored by Git.
