# Person 2: legacy software and test-based modernization

`runner.py` executes the team-authored original monitor in
`fixtures/legacy_monitor/monitor.py` using validated `TelemetryEvent` input.
See `fixtures/legacy_monitor/README.md` for provenance, protocol, and examples.

```python
from backend.modernization.runner import run_legacy_monitor
from backend.schemas.incident import TelemetryEvent

decision = run_legacy_monitor(TelemetryEvent.model_validate(payload))
```

The returned `status`, `sampled_at`, and source-content `source_revision` are
available for Person 1's monitor adapter. `device_id` identifies the evaluated
device. Preserve `docs/API_CONTRACT.md` when wiring this into the backend.
The live API still calls its original stub; no routes were changed here.

Repair acceptance tests now live in
`tests/modernization/test_repair_requirements.py`. Run
`python -m pytest tests/modernization/test_repair_requirements.py --runxfail -q`
to expose the original missed-fault defect (expected exit code 1). See the fixture
guide for baseline cases, strict expected-failure handling, and JUnit evidence.

Next: candidate patch/diff generation, isolated candidate execution, and agent
tools. AI providers, repairs, approval,
and deployment are not implemented. The runner only executes the trusted fixture
and must not be repurposed to execute arbitrary model-generated paths or commands.
