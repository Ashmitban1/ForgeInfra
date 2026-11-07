# Person 3 — React starter

This minimal dashboard displays live API responses from Person 1. It is **not** the full planned UI.

From repo root, first run the FastAPI server. Then in a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173. Start the simulator from repo root to populate the dashboard.

Person 3 owns all further front-end work. Do not place secret API tokens in `VITE_*` environment variables; those are exposed to browser users.
