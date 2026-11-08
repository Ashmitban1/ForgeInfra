# FactoryOS — HackUTD 2026

GitHub-ready **three-person team repository**. FactoryOS is a proof-of-concept for data-center information reliability and legacy monitoring modernization. Read `docs/FACTORYOS_AGENT_HANDOFF.md` for full strategy.

## What is actually implemented

✅ FastAPI telemetry API, deterministic mismatch checks, simple in-memory incidents, basic tests; ✅ Arduino UNO sketch + serial gateway + simulator; ✅ minimal React/Vite dashboard reading backend data; ✅ GitHub Actions Python test workflow.

**Not yet implemented or verified:** physical Arduino connection; real legacy application modernization; Nemotron/Gemini; Jira/Slack; GitHub PR automation; Tiger Data/MongoDB; Solana; Vultr; authenticated production deployment. `legacy_monitor_stub` is only a controlled example, never Northmark's actual software.

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


**Terminal 2 — Basic React dashboard:**
```powershell
cd frontend
npm install
npm run dev
```
Open http://127.0.0.1:5173. Requires Node.js 20+.

## Terminal 3 - Connect your actual ELEGOO UNO R3

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


### Arduino LED Status Indicators

FactoryOS uses two physical LEDs to display the current
cooling-fault state.

- 🟢 Green LED: Normal operation (`cooling_fault: false`)
- 🔴 Red LED: Simulated cooling fault (`cooling_fault: true`)

#### Components

- ELEGOO UNO R3
- DHT11 temperature/humidity sensor
- 1 green LED
- 1 red LED
- 2 current-limiting resistors (220Ω–1kΩ)
- Breadboard and jumper wires

#### Wiring

| Component | Arduino Pin | Breadboard |
|---|---|---|
| DHT11 signal | D2 | Existing connection |
| Cooling-fault input | D3 | Connect to GND to simulate fault |
| Green LED (+) | D8 | Through resistor to G14 |
| Green LED (-) | GND | G15/H15 to negative rail |
| Red LED (+) | D9 | Through resistor to B20 |
| Red LED (-) | GND | B21/D21 to negative rail |

Both LEDs share the breadboard's negative (-) rail,
which connects to Arduino GND.

Each LED must have its own current-limiting resistor.

#### LED Behavior

| Cooling Fault | Green LED | Red LED |
|---|---|---|
| false | ON | OFF |
| true | OFF | ON |

#### Testing

1. Upload `hardware/arduino/factoryos_arduino/factoryos_arduino.ino`.
2. Leave D3 disconnected from GND. Green LED should light up.
3. Connect D3 to GND. Red LED should light up.
4. Disconnect D3 from GND. Green LED should light up again.
5. Close Arduino Serial Monitor.
6. Run the Python serial gateway:

```powershell
.\.venv\Scripts\python.exe hardware/serial_gateway.py --port COM3
```

Replace COM3 with the Arduino's actual serial port.

The LEDs are controlled locally by the Arduino.
No changes to the FastAPI backend, MongoDB Atlas, or
Tiger Data are required.

The serial JSON format remains unchanged:

```json
{
  "temperature_c": 23.8,
  "humidity_pct": 45.0,
  "cooling_fault": false
}
```

Temperature and humidity are real DHT11 measurements.
The cooling-fault input is a simulated equipment-failure
signal, not a measurement from an actual cooling system.

#### Demo

During the FactoryOS demonstration:

1. Show normal operation with the green LED.
2. Activate the D3-to-GND fault.
3. Show the red LED turning on.
4. Demonstrate FastAPI incident detection.
5. Show the incident in MongoDB Atlas.
6. Show the fault history in Tiger Data.
7. Restore normal operation and show the green LED again.

