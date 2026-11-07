# Repository Guidelines

## Project Structure & Module Organization

FactoryOS detects unreliable data-center monitoring information and supports verified legacy-software repairs. Read `README.md`, `docs/API_CONTRACT.md`, and `docs/TEAM_TASKS.md` before contributing; `docs/FACTORYOS_AGENT_HANDOFF.md` provides the broader plan.

- `backend/main.py`, `reliability.py`, `schemas/`, and `storage/`: Person 1's FastAPI, deterministic checks, telemetry models, and storage work.
- `hardware/`: Person 1's UNO R3 firmware, USB serial gateway, and simulator.
- `backend/agents/` and `backend/modernization/`: Person 2's planned Nemotron/Gemini investigation and tested repairs.
- `frontend/src/` and `backend/integrations/`: Person 3's React UI, CSS assets, and planned Jira/Slack/Solana adapters.
- `tests/`: backend tests; `.github/workflows/python-tests.yml`: Python 3.11 CI.

Coordinate route registration in `backend/main.py` with Person 1. Preserve the v1 API contract and incident identifiers across modules.

## Build, Test, and Development Commands

From the repository root, use Python 3.11 and a virtual environment:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn backend.main:app --reload
```

In another terminal, `python hardware/simulator.py --mode fault` submits a simulated cooling fault; `--mode normal` submits healthy telemetry. Run `python -m pytest -q` for backend tests.

Inside `frontend/`, use Node.js 20+: `npm install`, then `npm run dev` for Vite, or `npm run build` for production assets. Backend: port 8000; frontend: 5173. See `README.md` for Windows activation and hardware setup.

## Coding Style & Naming Conventions

Use four-space Python indentation, `snake_case` functions/modules, `PascalCase` classes, and type hints for shared interfaces. Follow existing JSX's two-space indentation, single quotes, and `PascalCase` component names. No formatter or linter is configured; keep edits consistent and focused.

## Testing Guidelines

Use pytest and FastAPI `TestClient`; name files `test_*.py` and functions `test_*`. Use distinct device IDs because API tests share in-memory state. Cover changed reliability behavior, invalid input, and regressions. Modernization work must demonstrate failure before repair and passing regression/baseline tests afterward. No coverage threshold or frontend test runner is configured.

## Commit & Pull Request Guidelines

History contains only `Initialize FactoryOS project`; no established convention exists. Use concise imperative subjects and feature branches such as `feat/telemetry`. PRs should describe behavior, link relevant issues, report validation, and include screenshots for UI changes. Document API/configuration changes and coordinate shared-file edits.

## Security & Evidence

Keep credentials out of Git and browser-exposed `VITE_*` variables. The backend is unauthenticated with volatile storage; keep it local until protected. Label simulations and placeholders honestly. Require authorized human approval before merges or deployments; deterministic alerts must remain independent of AI availability.
