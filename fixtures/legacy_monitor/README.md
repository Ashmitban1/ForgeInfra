# Representative legacy monitor — original version

This application was authored for FactoryOS's controlled modernization demo.
It is not Northmark software or an imported production system. It represents an
older temperature-only monitor that has not adopted a newer cooling-fault input.
No repair or AI integration is implemented in this fixture.

## Run on macOS

From the repository root, with the project's virtual environment activated:

```sh
python fixtures/legacy_monitor/monitor.py < fixtures/legacy_monitor/normal.json
python fixtures/legacy_monitor/monitor.py < fixtures/legacy_monitor/fault.json
python -m backend.modernization.runner < fixtures/legacy_monitor/fault.json
python -m pytest tests/modernization -q
```

The standalone monitor needs only Python's standard library. The adapter also
uses the project's Pydantic telemetry schema. Neither needs a running API,
hardware, network access, or credentials.

## Input and output

One JSON object goes to stdin; one decision object comes back on stdout.
The original monitor validates `device_id`, timezone-aware `observed_at`, and
finite `temperature_c` in the shared sensor range (-40 to 85). It ignores
additional fields, including `cooling_fault` and humidity. The adapter validates
the full shared telemetry schema before running the monitor.

Output contains `device_id`, `status`, `sampled_at` (the input observation time),
and `source_revision` (SHA-256 of the executed source file). Invalid input exits
with code 1 and a JSON error on stderr. The hash identifies source content;
it is not an approval, signature, or proof that a measurement is true.

Both sample files return **NORMAL**, even though `fault.json` has a simulated
cooling fault. That missed fault is the intentional modernization target.
Temperatures strictly above 35 return WARNING; exactly 35 returns NORMAL.
The samples have fixed historical timestamps and are for offline replay, not
fresh telemetry submission to the API. Their temperatures and humidity are
synthetic examples, not physical measurements.

## Repair boundary

Preserve this original as a reproducible baseline; generate future candidate
repairs in a separate workspace. The independently authored acceptance criteria
in `tests/modernization/test_repair_requirements.py` require WARNING for a
cooling fault at 29.4 C and preserve healthy, hot, combined-fault, and exactly
35 C behavior. Expected statuses are literal requirements, not calculated by
the monitor or the independent reliability implementation.

### Reproduce the missing-fault regression

```sh
python -m pytest tests/modernization/test_repair_requirements.py --runxfail -q
```

Against the original, this command should report **1 failed, 4 passed** and exit
with code **1**. The assertion includes the executed source hash and the actual
NORMAL result versus the required WARNING result. This is intentional evidence
of the defect, not a repaired monitor.

To retain machine-readable test evidence, add
`--junitxml=/tmp/factoryos-legacy-regression.xml`. Pytest records the real failure
and passing baseline cases in that file; it does not change the exit code.

Normal `python -m pytest -q` runs mark this one known defect as **XFAIL** using
`strict=True` and `raises=AssertionError`. Execution errors still fail the suite;
an unexpected pass also fails so a changed original cannot silently go unnoticed.
`--runxfail` disables that mark and applies the actual acceptance criterion.
Future candidate verification must use `--runxfail` too, so the candidate must
pass every requirement. Candidate execution and repair generation are step 3.

The adapter only executes this known fixture with a fixed command and timeout.
It is not a sandbox for AI-generated code. Candidate execution needs a separate
isolation design. Person 1's live API still uses its existing stub until the
adapter and source revision are explicitly wired into the shared backend.
