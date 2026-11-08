# FactoryOS — Person 3 frontend

React 19 + Vite + Motion. No additional UI framework, font download, rendering
engine, or runtime dependency was added for the redesign.

## Start locally

```sh
# From repository root; Node.js 20+
npm --prefix frontend install
npm --prefix frontend run dev
```

Open **http://127.0.0.1:5173/** for the product overview. The existing working
application remains available at **http://127.0.0.1:5173/#/**.

For live operational data, run the existing notification-enabled backend separately:

```sh
source .venv/bin/activate
python -m uvicorn backend.integrations.app:app --reload
```

The landing page works without a backend and makes no operational polling requests.
It never creates incidents or sends notifications. Real provider actions require
an explicit click within Investigation. Backend credentials remain in backend/.env;
never use secret VITE_* variables. VITE_API_BASE_URL is a public backend address.

## Routes

| URL fragment | Working destination |
| --- | --- |
| No fragment | New public product overview |
| #overview, #architecture, #people, #mission, #workspaces | Product sections |
| #/ | Original Mission Control route, preserved |
| #/mission | Mission Control alias |
| #/investigate/{incident_id} | Original Incident Investigation route, preserved |
| #/investigate | Selects an available incident, or shows an empty/error state |
| #/engineering/{incident_id} | Existing Investigation with engineering context/evidence navigation |
| #/operations | Existing Mission Control with current incident and notification summary |

Role selection is navigation, never authentication or authorization. Workspaces
reuse incident storage, polling, and existing controls. Selected incident context
is retained within the SPA as users change workspaces, including via the overview.
Explicit incident URLs support reload and browser history. Bare workspace URLs on
fresh load use the existing first-incident selection behavior. Hash routes avoid
server rewrite requirements and preserve existing bookmarks.

## Product overview

- Original SVG geometric F emblem, horizontal wordmark, and compact SVG favicon.
- Silver/graphite design tokens shared with the operational shell and live cards.
- Responsive navigation, large hero, and pointer-responsive SVG server sculpture.
- Five-phase architecture mind map with dotted phase boundaries, surrounding tool
  nodes, example miniatures, sequential entrances, and connector drawing.
- Horizontal exploration controls on desktop/tablet; stacked phases on mobile.
- A separate Detect → Jira/Slack branch shows notifications need not wait for AI
  or candidate tests. Shared data rail sits below all phases.
- Click/focus-accessible phase and tool details explain Input / Processing /
  Output / Technology and actual implementation limits.
- Persona buttons highlight related operational challenges. Workspace links are
  functional and use existing pages, not fabricated role applications.
- Closing mission CTA and overview links throughout the application.
- Motion honors prefers-reduced-motion. Public page has no operational polling;
  its code is lazy-loaded separately from the operational app.

## Data truthfulness in this checkout

Backend storage, agents, and modernization directories currently contain stubs.
Live telemetry ingestion/deterministic incident checks and notification adapters
exist. Jira creation and generic Slack connectivity were verified in earlier work;
a fresh combined live delivery is not claimed here. MongoDB Atlas, Tiger Data,
Nemotron, Gemini orchestration, connected Docker candidate jobs, approval, and
Solana are labeled planned/unsupported where appropriate.

Architecture readings/code are explicitly labeled illustrative, not live results.
The monitor is a deliberately faulty team-authored placeholder, not Northmark
production code. Cooling-fault flags are simulated, separate from physical DHT11
measurements. Host metrics have no API in this checkout and are not fabricated.

Repair verification was made more conservative: tool execution SUCCESS plus a
nominal rack reading cannot establish passing acceptance tests. Without actual
per-incident acceptance evidence, it remains unverified and shows no original/
candidate pass totals. A completed job, verified repair, human approval, production
deployment, and physical equipment recovery are different claims.

## Demo mode and retained functionality

`?demo=1` enables existing explicitly labeled demo fixtures in the operational app;
`?demo=0` disables them. The header's Demo data button also toggles mode. Demo
Jira/Slack submissions remain disabled. The public product examples are always
architecture illustrations, independent of this setting.

The existing DataHall, rack selection, telemetry sparklines, event timeline,
incident list, investigation, source evidence, provider results, loading/error
states, and state-driven animations remain. The API contract and backend code
were not modified by this frontend redesign.

## Verification

```sh
node --test frontend/tests/product.test.mjs
npm --prefix frontend run build
.venv/bin/python -m pytest -q
```

The Node tests cover route compatibility, persona destinations, shared incident
URL mapping, conservative verification semantics, and architecture truthfulness.
Browser QA uses mocked backend data only; it creates no real provider records.
See `docs/PERSON_3_FRONTEND_REDESIGN.md` for results and limits.
