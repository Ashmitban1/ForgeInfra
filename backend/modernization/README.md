# Person 2: legacy software and test-based modernization

## Run step 3 with Docker

Start Docker Desktop (or a local Docker Engine), then run from the repository root:

```sh
source .venv/bin/activate
docker build -t factoryos-monitor:local backend/modernization/container
python -m backend.modernization.testing --incident-id INC-COOLING-001
```

Build the image once; rebuild when its Dockerfile changes. Only the initial image
build needs network access. The build context excludes everything except the
Dockerfile. The monitor uses only Python's standard library; tests run on the host.
No backend, hardware, or provider credentials are required.

The incident ID is an optional correlation label; no incident is fetched or updated.
`--output-dir /tmp/factoryos-repairs` overrides the default artifact root.
`--image` selects a prepared image; verification resolves and records its immutable
ID once and uses that same ID for both versions, without pulling during tests.

## Repair and evidence

The fixed patch is **manually authored**, not AI-generated. It adds the cooling-fault
condition while preserving the strict temperature threshold. Each invocation creates
a new Git-ignored `artifacts/modernization/repair-<unique-id>/` containing:

```text
original/monitor.py
candidate/monitor.py
repair.diff
original-tests.xml                 # Actual JUnit failure/baseline results
candidate-tests.xml
{original,candidate}-pytest.{stdout,stderr}.txt
{original,candidate}-containers.jsonl
report.json
```

Both source copies run the same independently authored acceptance tests with
`--runxfail`. Expected-failure handling cannot hide a failing candidate. VERIFIED
requires exactly four baseline passes plus the known missed-fault failure on the
original, and five passes on the candidate. Missing/skipped tests, failures, timeouts,
changed sources/diffs, or unavailable Docker cannot produce VERIFIED.

The report stores source/diff/test hashes, the image ID, real pytest commands, exit
codes, per-case results, and artifact paths/hashes. JSONL traces retain actual Docker
commands, input/output, timing, and cleanup results. Exit code 0 means the defined
repair checks passed; exit code 1 means verification failed. Available evidence is
retained on failure. Approval stays PENDING and deployed stays false.

## Container boundary

Each event executes in a new non-root container with only that monitor file mounted
read-only. Networking is disabled, the root filesystem is read-only, all Linux
capabilities are dropped, and privilege escalation is disabled. CPU, memory, process,
and file-descriptor limits are applied. No repository, credentials, host environment
variables, or Docker socket are passed into the container.

Each invocation has a 15-second deadline; containers are removed after completion
and forcibly removed on timeout. There is no host-execution fallback. Docker access
is needed only by the trusted host orchestration. This is a local demo workflow for
the reviewed fixture repair, not a production service accepting arbitrary programs.

## Tests and integration

```sh
python -m pytest -q                         # Normal suite; Docker tests skipped
python -m pytest -q --run-docker-tests      # Includes real Docker execution/cleanup
```

- `runner.py`: original step 1 trusted-fixture adapter; unchanged.
- `patching.py`: separate copies, fixed patch, diff, and hashes.
- `docker_runner.py`: restricted container execution and result validation.
- `testing.py`: same-suite before/after testing and repair report CLI.

```python
from backend.modernization.patching import create_demo_proposal
from backend.modernization.testing import verify_proposal

proposal = create_demo_proposal()
report = verify_proposal(proposal, incident_id="INC-COOLING-001")
```

See `fixtures/legacy_monitor/README.md` for fixture provenance. Coordinate with Person
1 before wiring this into the shared backend and preserve `docs/API_CONTRACT.md`.
Step 4 now supplies shared incident/job interfaces and API registration through
the wrapper below. Step 5 adds real Nemotron investigation and generated candidates;
Gemini review, authorized approval, and candidate activation remain pending.

## Step 4: incident repair API

```sh
python -m uvicorn backend.modernization.app:app --reload
```

This mounts the modernization router onto P1's existing app and in-memory store
without editing P1's files. Submit a simulator/hardware fault, POST the returned
incident ID to `/api/incidents/{id}/repair`, and poll its `/analysis` or returned
job URL. The bounded background worker runs step 3 plus actual event-snapshot
replay; GET report/diff routes expose real browser-safe evidence.

`repository.py` defines the injected storage interface and local adapter;
`mongo_repository.py` implements canonical MongoDB incident reads, job persistence,
atomic reservations, and incident result attachment. The local wrapper remains
explicitly memory-backed until P1's canonical Atlas writer/app is connected.
See [the full API and integration guide](../../docs/MODERNIZATION_API.md).

The same wrapper also mounts `/investigate` through a separate investigation service
and job namespace. `create_model_proposal()` accepts only an AST-validated single
monitoring assignment against the inspected hash; its tested candidates are labeled
`nemotron_generated_patch`. The manual CLI and `/repair` retain their original
manual labels. See [the agent guide](../agents/README.md).
