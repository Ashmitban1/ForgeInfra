# Person 3 — FactoryOS dashboard

Two screens, both read from the FastAPI backend (API v1, `docs/API_CONTRACT.md`):

- **Mission Control** (`#/`): KPIs, rack health, current telemetry + session sparkline, source-mismatch evidence, live incidents, event timeline. Uses `GET /api/telemetry/latest` and `GET /api/incidents` (polled every 3s).
- **Incident Investigation** (`#/investigate/{incident_id}`): incident details, progress path, Nemotron tool activity, Gemini recommendation, Jira/Slack IDs. Uses `GET /api/incidents/{id}`.

Scaffolded, clearly labeled "Sample" or "Scaffold", and not backed by the API yet: code diff, regression tests, approval buttons (disabled). No POST requests are made.

```sh
# repo root: run FastAPI, then in another terminal
python hardware/simulator.py --mode fault
cd frontend && npm install && npm run dev   # http://127.0.0.1:5173
```

## Demo mode

While Person 1/2 work is unfinished, click **Demo data: on** in the header (or open `http://127.0.0.1:5173/?demo=1`; `?demo=0` turns it off). It serves hardcoded fixtures from `src/demo/fixtures.js` in the v1 contract shape, with a permanent "Demo mode" banner. Racks cover fault, nominal, over-temperature and stale states; RACK-02 faults for 20s each minute so "Recovered" appears. It only replaces the three GET calls and never runs unless switched on.

## Honesty rules

- Rack state, fan, LEDs, and progress-path animations derive only from API fields. A reading older than 90s (mirrors `STALE_AFTER_SECONDS` in `backend/reliability.py`) is shown as "No recent data".
- "Recovered" and the temperature chart use readings *this browser tab* observed while polling; the API has no history endpoint.
- Unknown agent statuses are shown verbatim. Only `PENDING` is defined in v1.
- Animations use Motion for React with `reducedMotion="user"`; infinite animations are also gated on `useReducedMotion`, and CSS honors `prefers-reduced-motion`.

`VITE_API_BASE_URL` (see `.env.example`) selects the backend. Never put secret tokens in `VITE_*` variables; they are exposed to the browser.

## Cinematic Mission Control (animation layer)

- **Data hall** (`components/DataHall.jsx`): SVG racks plus the pipeline Hardware feed → API → Legacy / Independent check → Incident → Nemotron → Gemini → Repair. Rack LEDs and stage nodes come from API fields; a data packet flies only when a *new* reading (`sequence`/`received_at`) arrives; a ring flashes only when a rack's derived state changes between polls (`hooks/useLiveEvents.js`). The first poll seeds a baseline, so page loads never replay history.
- **Incident progression**: progress-path packets, incident-card highlights, and Nemotron tool-call entrances fire only when the API reports a changed status or a new tool call.
- **Repair verification** (`lib/health.js#repairVerification`): "Verified" requires backend-reported test/verification tool calls that all succeeded *and* the live rack reading nominal. Otherwise it shows "Not verified" (the v1 default).
- **Demo data** is labeled in the hall, header, and banner. Demo INC-COOLING-002 advances through stages on a 90s loop for demonstration only.
- Reduced motion: packets, rings, pulses, scans and number tweens are not rendered; state is still shown statically.
