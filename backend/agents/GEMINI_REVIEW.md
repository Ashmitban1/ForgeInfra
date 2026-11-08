# Gemini independent review — step 6

Gemini reviews a completed Nemotron investigation. Its JSON recommendation and
the backend policy result are attached to the same incident's `decision_review`.
It does not execute recommended actions, approve a patch, close the incident, or
activate the candidate. Deterministic telemetry alerts continue independently.

## Configure and run

Set `GEMINI_API_KEY` in the ignored root/backend `.env` or backend environment.
The P2 wrapper loads process environment first, then backend dotenv, then root
dotenv. Existing environment values win. Start from the repository root:

```sh
source .venv/bin/activate
python -m pip install -r requirements.txt
docker build -t factoryos-monitor:local backend/modernization/container
python -m uvicorn backend.modernization.app:app
```

The client uses existing `httpx` with Google's native REST API:
`https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`.
Default model: `gemini-3.5-flash-lite`; override with `GEMINI_MODEL`. No fallback
model is selected silently. The key is sent as `x-goog-api-key`, never in a URL.
Requests specify `responseMimeType=application/json` and `responseJsonSchema`;
Pydantic and evidence validation remain mandatory after the response.
See [Google's API reference](https://ai.google.dev/api/generate-content) and
[model documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite).

Defaults: one provider request per accepted job, 90-second request timeout,
8,192 output tokens, 200 KB maximum evidence JSON, and a bounded in-process queue.
`GEMINI_REQUEST_TIMEOUT_SECONDS` accepts 1–120; `GEMINI_MAX_TOKENS` accepts
256–16,384. Retries require an explicit new idempotency key after failure.
Credentials/provider error bodies and raw reasoning are excluded from results.

## Test in Swagger

1. Run `python hardware/simulator.py --mode fault` in another activated terminal.
2. At `http://127.0.0.1:8000/docs`, POST the returned incident ID to `/investigate`.
3. Copy that POST's **actual `job_id`** and poll `/api/investigations/{job_id}`
   until COMPLETED. Inspect the generated repair's actual verification outcome.
4. POST `/api/incidents/{incident_id}/review` using the **incident ID**. No body
   is required. Optional `Idempotency-Key` identifies one request/snapshot.
5. Copy the new **`review-job-...` ID** and poll `/api/reviews/{job_id}`, or open
   its `links.job`. Re-execute GET to refresh progress. Read `error` if FAILED.
6. GET `/api/incidents/{incident_id}/analysis`; `decision_review` contains the
   persisted recommendation, explanation, risks, evidence citations, and policy.

After restarting an older backend, fully refresh Swagger to reload its route
schema. Changing only the URL fragment can leave the old page's route list visible.

An active/new job returns 202; reused terminal jobs return 200. An unknown incident
returns 404. Missing/incomplete/changed investigation evidence or an already active
review returns 409. Missing Gemini configuration/worker/storage returns 503.
`/api/agents/capabilities` adds `review`, `gemini`, `gemini_configured`, and
`gemini_model`. Configured is not a live-provider health check.

Keep the same server running: memory jobs disappear on restart. The standalone
Nemotron smoke script's jobs belong to its private TestClient process and cannot
be used here. If live telemetry changed after investigation, investigate the latest
snapshot again before requesting review.

## Evidence and policy

The service captures the exact investigation ID, incident/source revisions,
successful tool results and evidence hashes, original numbered source and
requirements, findings, candidate diff, independent Docker tests, and offline
replay. It verifies evidence hashes and excludes previous reviews/integrations
from the input. Malformed/unknown citations, schema violations, forbidden action
names, incomplete responses, and provider errors fail honestly without a fake review.

The structured result contains `recommendation`, `severity`, `actions`,
`evidence_ids`, `repair_assessment`, `risks`, `needs_human_approval`, and
`explanation`. Allowed recommendations: ESCALATE, INVESTIGATE_SOFTWARE,
REQUEST_REPAIR_REVIEW, COLLECT_MORE_EVIDENCE, NO_ACTION.

Use **`result.policy.effective_recommendation`** in job responses. In `/analysis`,
`decision_review.recommendation` is the effective recommendation;
`model_recommendation` preserves Gemini's original choice. The policy checks real
before/after test outcomes, source/diff revisions, and replay before setting
`repair_review_eligible`. A model cannot promote a failed/unverified candidate.
An unsupported NO_ACTION recommendation cannot suppress a deterministic mismatch.
Telemetry older than P1's 90-second limit or over 10 seconds in the future requires
fresh evidence; GET review and `/analysis` recalculate this policy as time passes.
Offline repair evidence can remain valid while current telemetry
needs refreshing.

Human approval stays PENDING and `actions_executed=[]`, `deployed=false` throughout.
Action names are suggestions for P3/human review; this service sends no Jira/Slack
messages. Simulation flags remain visible, and software replay does not establish
physical recovery.

Reviews are tied to an exact incident/investigation snapshot. A changed snapshot
while a review runs marks it STALE. GET review and `/analysis` also derive STALE
when previously reviewed telemetry/investigations change, suppressing the current
recommendation. Historical stored results remain available for auditing. P3 should
consume these routes for freshness rather than treating a historical incident
summary as current authorization.

## Persistence and integration

The local wrapper still shares P1's memory dict/lock. Mongo mode shares the exact
canonical incidents with separate `repair_jobs`, `investigation_jobs`, and
`review_jobs` collections. `MONGODB_REVIEW_JOBS_COLLECTION` configures the last;
all names must be distinct. Atlas's telemetry/incident writer remains P1's work.

```python
repair = RepairService(repository)
investigation = InvestigationService(repository.for_investigations())
review = ReviewService(repository.for_reviews(), repository.for_investigations())
app.include_router(create_modernization_router(repair, investigation, review))
app.include_router(create_investigation_router(investigation, review))
app.include_router(create_review_router(review))
```

Each namespace has one bounded background worker. Use one process/replica;
startup recovery interrupts only that namespace's unfinished jobs. This is not a
distributed task queue. The original incident status, telemetry, investigation,
and repair records are preserved by review attachment.

## Verification

```sh
python -m pytest -q
python -m pytest -q --run-docker-tests
# Disposable local MongoDB only:
FACTORYOS_TEST_MONGO_URI=mongodb://127.0.0.1:27017 \
  python -m pytest -q --run-docker-tests --run-mongo-tests

# Explicit real Google quota, entirely synthetic input and no repository source:
python -m scripts.verify_gemini_live
```

Automated provider responses are explicitly mocked; production has no mock fallback.
The last command validates the actual Google key/model/HTTP/schema with fabricated
input. It saves ignored evidence and does not create a real incident/review job or
claim the full NVIDIA-to-Google chain was live-tested. The Swagger workflow sends
actual captured investigation evidence to Google and consumes provider quota.

During implementation, the real Google synthetic check succeeded with the default
model and full review schema. A subsequent live Playwright/Swagger test, with
explicit approval for the evidence transfers, completed the NVIDIA -> real Docker
verification -> Gemini -> combined analysis chain. Gemini made one real request;
duplicate submission reused the same review job. Telemetry aged beyond 90 seconds
during manual browser interaction, and policy correctly required fresh evidence
while retaining the verified candidate's eligibility for human review.

After an observed simulation-wording error, reviews now require the structured
`fault_provenance` field: SIMULATED, REPORTED, or UNKNOWN. The backend checks it
against `hardware.fault_is_simulated` and rejects missing/contradictory values as
INVALID_REVIEW. Real Arduino temperatures do not establish a physical fault when
the fault switch is simulated. REPORTED also does not mean physically confirmed.

Use backend-generated `decision_review.fault_context` (also in job result policy)
for UI provenance labels and its `statement` for the equipment-health summary.
`physical_fault_status` remains NOT_VERIFIED. The stricter prompt applies to both
risks and explanation; free-text prose remains advisory. Old stored reviews remain
readable and are marked `provenance_validation=NOT_VALIDATED`; new validated
reviews are marked VALIDATED. Restart the backend to load the change and use a new
idempotency key to request a new review rather than reusing an old result.
The integrated chain also passes local scripted-provider tests, actual Docker
checks, and disposable MongoDB persistence/restart checks.
