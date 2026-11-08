# Human approval API

The integrated `backend.app:app` registers authenticated human
decisions over one exact candidate and evidence package on P1's same app. It
changes no live monitor, operational incident status, deployment, PR, Jira ticket,
or Slack message.

## Configure reviewer authentication

Each reviewer has a distinct high-entropy bearer token. The backend stores only
its SHA-256 digest mapped to the reviewer identity in `FACTORYOS_APPROVERS_JSON`.
Identity and decision timestamps are never accepted from request bodies.
NVIDIA/Gemini keys are not approval credentials. Missing/invalid configuration
fails closed with 503; missing/incorrect credentials return 401.

Generate a local credential from the repository root (the token file is ignored
by Git and created with owner-only permissions; existing files are not overwritten):

```sh
python - <<'PY'
import hashlib, json, os, secrets
token = secrets.token_urlsafe(32)
path = '.env.approval-token'
with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as f:
    f.write(token + '\n')
digest = 'sha256:' + hashlib.sha256(token.encode()).hexdigest()
print('FACTORYOS_APPROVERS_JSON=' + json.dumps({'person-2': digest}))
print('Reviewer token saved privately in', path)
PY
```

Add the printed `FACTORYOS_APPROVERS_JSON=...` line to the ignored root/backend
`.env`, then restart `backend.app:app`. Process environment takes
precedence over dotenv. Without MongoDB, incidents/jobs are volatile. With
`MONGODB_URI` and optional `MONGODB_DATABASE`, P1 restores canonical records before
fresh P2 workers start; the shared adapter reuses P1's database/client for job
collections. Acknowledged records survive restart and unfinished jobs become
INTERRUPTED. Do not mount a separate P2 incident writer.

In Swagger `/docs`, fully reload the page, click **Authorize**, and enter the raw
token from the private file under **FactoryOSReviewer**. Swagger adds `Bearer`.
These are server-managed local reviewer credentials, not an SSO implementation.
Removing a reviewer blocks their token and invalidates execution eligibility for
their previous approvals; rotating a token while retaining the identity preserves
its existing decisions. Environment-file changes require a backend restart.

Approval routes authenticate reviewers; other existing telemetry/read/AI routes
still use the project's local unauthenticated prototype configuration. Keep that
scope in mind when connecting P3 or preparing deployment.

## Review and decide

First complete a current Nemotron investigation and Gemini review. For approval,
the actual Docker tests/replay must verify the generated candidate and Gemini
must assess it as SUITABLE_FOR_HUMAN_REVIEW with matching provenance. The current
telemetry must satisfy P1's freshness policy (90 seconds old / 10 seconds future).
Model disagreements, changed evidence, and legacy reviews missing provenance
validation block approval.

| Route | Behavior |
| --- | --- |
| GET `/api/incidents/{id}/approval` | Authenticated inspection of candidate, full evidence package, hashes, current decision, and blocking reasons |
| POST `/api/incidents/{id}/approval` | Authenticated APPROVE or REJECT; 201 new decision, 200 idempotent retry |
| GET `/api/incidents/{id}/approval/history` | Authenticated read of frozen packages and immutable API decision records |
| GET `/api/incidents/{id}/analysis` | Adds an `approval` summary; P3 should use its current status |

Copy **both hash values from the actual GET `/approval` response**:

```json
{
  "decision": "APPROVE",
  "package_revision": "sha256:<copy full package hash>",
  "candidate_revision": "sha256:<copy full candidate hash>",
  "comment": "Reviewed the exact diff, tests, replay, and Gemini assessment."
}
```

Use REJECT for rejection. Comments are optional (maximum 2,000 characters).
Rejection remains available for an identifiable candidate even with missing/failed
review, failed verification, or stale telemetry. A missing candidate cannot be
approved/rejected. Unknown incident: 404; malformed body: 422; changed package,
blocked approval, conflicting decision, or reused key with another body: 409.

An optional `Idempotency-Key` is scoped to the incident incarnation and authenticated
reviewer. Without it, the exact request fingerprint supplies idempotency. Repeating
the same decision returns its original ID/timestamp without another audit entry,
even if it has since become stale. A decision is final for that package. Obtain a
new reviewed package to make a new decision; existing records cannot be rewritten.

## Binding, persistence, and execution

The package freezes the incident snapshot, investigation/source references,
generated code/diff hashes, actual test/replay evidence, and exact Gemini job/result.
Changing the candidate, diff, tests, investigation, or review changes its hash and
requires a fresh decision. Dynamic freshness checks are outside the package hash,
so merely viewing evidence does not change the hash. Policy reasons and check time
are also recorded on each decision.

The canonical incident's `approval` aggregate holds frozen packages and decision
history. P1 performs a compare-and-set under its existing lock against the expected
incident/approval state, then queues the canonical snapshot and lifecycle event
through its sole MongoDB writer. Conflicting concurrent changes cannot silently
overwrite a decision. State is bounded to 16 packages per incident, 256 KB per
package. History is append-only through this API, not cryptographically tamper-proof
against privileged database administrators.

MongoDB authorization requires a durable readback confirming the approval version.
If acknowledgement remains pending, POST returns **503**, retains the cached audit
record, and prevents execution. GET/analysis expose `persistence: {status, version}`:
PERSISTED for confirmed MongoDB state, PENDING for unconfirmed writes, and VOLATILE
for explicit memory mode. This ephemeral metadata is outside the evidence hash.
An unacknowledged APPROVE is STALE with `approval_persistence_pending`.

After storage recovers, retry the exact request with the **same Idempotency-Key**.
Once durable readback succeeds, it returns the original decision ID/timestamp
with 200 instead of creating another audit entry. Pending retry queues are memory-only;
termination before acknowledgement can lose unpersisted state.

`analysis.approval.status` is PENDING, APPROVED, REJECTED, or STALE. Approval can
become stale through changed evidence, expired telemetry, or reviewer removal.
Exact captured `snapshot_revision` values never change. Review/approval currency
also checks a semantic monitoring case: compatible advancing fresh samples can
preserve eligibility. P1 increments `case_generation` on material telemetry/status
changes, including a healthy sample clearing the fault. A later recurrence cannot
revive an old decision, even when measurements match the original fault.
The original model reports' `approval_status=PENDING` remain historical AI evidence;
**human authorization lives in the separate approval aggregate**.

The future activation/PR worker must call this immediately before acting:

```python
authorization = approval_service.require_approved(
    incident_id, package_revision, candidate_revision,
)
```

It fails unless the exact candidate/package is currently approved and eligible,
including checking the original fixture revision. The worker must use the returned
package and check the actual target/artifact revision when applying it. No execution
endpoint is implemented by this change; this API grants no automatic deployment.

## Validation

```sh
python -m pytest -q tests/modernization/test_approval_api.py
python -m pytest -q --run-docker-tests
FACTORYOS_TEST_MONGO_URI=mongodb://127.0.0.1:27017 \
  python -m pytest -q --run-docker-tests --run-mongo-tests
```

Default tests use scripted verifier/model responses and mongomock for integration
storage. Opt-in tests exercise real Docker verification and disposable local
MongoDB persistence/restart/races; they do not establish live Atlas or physical
hardware operation. No test approves a real operational repair or performs an
external workflow action.
