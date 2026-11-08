# Run FactoryOS with Docker

Use Docker Desktop with Compose 2.24+ on macOS, or Docker Engine with Compose on
Linux. Run commands from the repository root. These containers are for local use;
the API still needs authentication beyond reviewer routes before public exposure.

## Start the application

```sh
# Only if you do not already have a root .env:
cp .env.example .env
docker compose up --build -d
docker compose ps
```

Open the dashboard at http://localhost:5173/#/ and Swagger at
http://localhost:8000/docs. Stop existing native servers on those ports first, or
prefix Compose commands with `FRONTEND_PORT=5174 BACKEND_PORT=8001`.

The frontend is a compiled React build served by nginx, which proxies `/api/`
and `/health` to FastAPI. Browser requests stay on the frontend origin; Docker
service names never need to resolve in the browser. Backend images include the
legacy fixture and acceptance tests used by the repair pipeline. Uvicorn runs one
worker, as required by the current job and canonical incident design.

MongoDB runs locally with a persistent named volume and no published database
port. This starts a **new local database**, separate from existing Atlas incidents.
Set `MONGODB_URI` and `MONGODB_DATABASE` in the project-root `.env` to use Atlas instead.
The unused local Mongo service will still run. Configure `TIGERDATA_DATABASE_URL`
to retain your existing hosted Tiger Data connection; no local Tiger substitute
is provisioned. Without it, telemetry history storage is disabled.

Use the project-root `.env` as the shared configuration source: Compose reads
port settings from it and injects its values into the backend at runtime, after
the non-secret defaults in `docker/backend.env`. Explicit empty values override
defaults too; an empty `MONGODB_URI` disables incident persistence. Move any
needed configuration from `backend/.env` into the root file yourself; the nested
file is not loaded by Compose. All `.env` files remain excluded from images.

The nginx frontend, MongoDB, simulator, and candidate sandboxes do not receive
backend provider credentials. The frontend uses its same-origin API proxy.
Never pass secrets as frontend build arguments. After editing `.env`, recreate
the backend (restart alone does not reload environment values):

```sh
docker compose up -d backend
docker compose logs --tail=100 backend
```

## Send telemetry

```sh
docker compose run --rm simulator --mode fault
docker compose run --rm simulator --mode normal
```

The simulator runs only when explicitly invoked. For actual Arduino input, keep
the USB gateway on macOS; Docker Desktop does not automatically pass through the
Mac serial device. With the host Python dependencies installed:

```sh
python -m serial.tools.list_ports
python hardware/serial_gateway.py --port /dev/cu.usbmodemYOUR_DEVICE \
  --url http://127.0.0.1:8000/api/telemetry
```

Use your actual port and close Arduino Serial Monitor first. Host CPU/RAM metrics
now describe the backend's container environment, not necessarily the Mac's full
resources.

## Enable Docker-backed repair verification

The base stack intentionally has no Docker socket. Investigation tools that
verify candidates will report Docker unavailable until this opt-in is enabled:

```sh
mkdir -p artifacts/modernization
docker build -t factoryos-monitor:local backend/modernization/container
docker compose -f compose.yaml -f compose.sandbox.yaml up --build -d
```

Use both `-f` options for subsequent stack commands. This override mounts the host
Docker socket and runs the backend as root for socket access. That grants the
backend control of the Docker daemon; use it only on a trusted local machine.
Individual candidate containers still have no network, a read-only filesystem,
an unprivileged user, resource limits, and only their source file mounted.

Artifacts are bind-mounted under `artifacts/modernization`; the configured host
path lets sibling containers read the exact same candidate files. Run Compose
from this repository root so `PWD` points to the correct directory. Neither the
repository nor provider credentials are mounted into candidate containers.

## Persistence and cleanup

Mongo incidents/jobs, notification SQLite deduplication, and repair artifacts
survive normal container recreation. `docker compose down` stops/removes the
stack while retaining named volumes. `docker compose down -v` deletes local
database, ledger, and base-stack artifact volumes. Sandbox bind-mounted artifacts
remain on disk. Avoid switching between named-volume and sandbox artifact storage
mid-workflow: existing jobs refer to evidence in their original storage.

Check `/api/storage/health` and `/api/telemetry/storage/health` for actual database
health. Container health checks establish HTTP/database readiness, not live AI
provider connectivity. Use `docker compose up -d --build` after code changes;
this setup does not hot-reload source files.

To build either image separately, use `docker build -f backend/Dockerfile -t
factoryos-backend .` from the root, or `docker build -t factoryos-frontend
frontend`. The backend requires the root context because it includes fixtures and
acceptance tests outside `backend/`.
