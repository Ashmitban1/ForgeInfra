# FactoryOS — HackUTD 2026

GitHub-ready **three-person team repository**. FactoryOS is a proof-of-concept for data-center information reliability and legacy monitoring modernization. Read `docs/FACTORYOS_AGENT_HANDOFF.md` for full strategy.

## What is actually implemented

✅ FastAPI telemetry API, deterministic mismatch checks, simple in-memory incidents, basic tests; ✅ Arduino UNO sketch + serial gateway + simulator; ✅ minimal React/Vite dashboard reading backend data; ✅ GitHub Actions Python test workflow.

**Not yet implemented or verified on this branch:** physical Arduino connection; Gemini; Jira/Slack; GitHub PR automation; Tiger Data/Atlas writer integration; Solana; Vultr; authenticated production deployment. `legacy_monitor_stub` is only a controlled example, never Northmark's actual software. MongoDB repository adapters have been tested locally.

**Person 2's runnable baseline:** `fixtures/legacy_monitor/monitor.py` is a
standalone, team-authored temperature-only monitor with JSON samples, an execution
adapter, and characterization tests. See [the fixture guide](fixtures/legacy_monitor/README.md).
The original cooling-fault defect is intentionally preserved. A separate manually
authored candidate can be verified with Docker-backed before/after tests:

```sh
docker build -t factoryos-monitor:local backend/modernization/container
python -m backend.modernization.testing --incident-id INC-COOLING-001
```

See [the modernization workflow](backend/modernization/README.md). Approval,
deployment, and live monitor activation remain pending.

**Person 2 step 4:** `python -m uvicorn backend.modernization.app:app --reload`
adds incident-linked background repair jobs, analysis/report/diff reads, and frozen
event replay to the existing local backend. A MongoDB adapter is supplied for the
shared Atlas app; the local wrapper still uses P1's memory store. See the
[modernization API guide](docs/MODERNIZATION_API.md) before integrating.

**Person 2 step 5:** The same wrapper now registers real NVIDIA Nemotron
investigations, validated diagnostic tools, and constrained model-generated rule
candidates with actual Docker verification. Set `NVIDIA_API_KEY` in an ignored
dotenv file or backend environment, submit an incident, and POST its `/investigate`
route. An initial live Ultra run exercised model/tool execution and Docker verification;
the subsequent per-finding citation check is locally tested. Gemini and authorized
activation remain pending. See [the agent guide](backend/agents/README.md).

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
│   ├── agents/                 # P2: Nemotron investigation, tools, grounded results
│   ├── modernization/          # P2: fixture adapter, candidate patch, Docker tests
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

## Collaborate on GitHub

See `docs/GITHUB_PUSH.md` for push commands and `docs/TEAM_TASKS.md` for assignments. See `docs/API_CONTRACT.md` before adding new API endpoints.

The backend currently has **no authentication** and uses **in-memory** storage. Keep it local/isolated until protected. `.env` and credentials are ignored by Git.
