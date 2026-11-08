# RepairProof Phase 1 — mocked providers only

This describes the original Phase 1 boundary. The current, still-disabled live
adapter and operator procedure are documented in [RepairProof Phase 2](REPAIRPROOF_PHASE2.md).

RepairProof commits to the exact generated candidate, frozen evidence package,
and authenticated human decision. This is a Devnet-only implementation boundary;
the integrated application deliberately installs **no live RPC client or signer**.
`SOLANA_ENABLED=false` is the default. Setting it true alone cannot send anything.
No wallet generation/loading, faucet, or HTTP provider is included.

## Run and inspect

Install the updated `requirements.txt` (adds `solders==0.27.1`), then run:

```sh
python -m uvicorn backend.app:app --reload
npm --prefix frontend run dev
```

Open the existing Investigation or Engineering workspace, select a real incident,
and inspect the Human Approval package with a named reviewer credential. The
RepairProof panel shares that in-memory session and shows blocking reasons.
Demo fixtures cannot publish. No new frontend route is needed.

## Preconditions

Publication requires enabled configuration, an explicitly injected adapter,
MongoDB storage, a PERSISTED approval with an exact majority-read-back match,
and the existing `ApprovalService.require_approved()` gate. Its generated-patch,
Docker evidence, current Gemini review, freshness, source revision, reviewer
revocation, and exact package/candidate checks remain unchanged. Only the reviewer
who recorded that approval may publish it. Other configured reviewers can read
and verify evidence.

Memory/PENDING approvals cannot publish. There is no memory proof repository
fallback. A later stale approval does not invalidate the historical commitment;
it prevents new authorization and is shown separately in readiness.

## Exact API contract

All routes except capabilities require `Authorization: Bearer <reviewer token>`.
Authenticated responses use `Cache-Control: no-store`.

| Method and path | Response |
|---|---|
| GET `/api/repair-proofs/capabilities` | `enabled`, `network: devnet`, `publish_ready`, `blocking_reasons`, `live_provider_available: false` |
| GET `/api/incidents/{id}/repair-proofs` | `incident_id`, `ready`, `blocking_reasons`, `package_revision`, `candidate_revision`, `decision_id`, `proof` (for the current decision; latest historical proof if there is no current decision; otherwise null) |
| POST `/api/incidents/{id}/repair-proofs` | Public proof plus `reused`; required `Idempotency-Key` header |
| GET `/api/repair-proofs/{proof_id}` | Public proof |
| GET `/api/repair-proofs/{proof_id}/bundle` | Exact canonical-byte bundle described below |
| GET `/api/repair-proofs/{proof_id}/verify` | Fresh read-only verification; never persists, signs, sends, or creates a replacement |

POST body (all fields required; extra fields forbidden):

```json
{
  "decision_id": "approval-decision-<existing ID>",
  "package_revision": "sha256:<64 lowercase hex characters>",
  "candidate_revision": "sha256:<64 lowercase hex characters>"
}
```

Public proof fields:

```json
{
  "proof_id": "proof-<deterministic SHA-256 identity>",
  "incident_id": "<existing incident ID>",
  "status": "UNKNOWN",
  "signature": "<saved transaction signature or null>",
  "created_at": "<UTC timestamp>",
  "verification": null,
  "network": "devnet",
  "commitment": "sha256:<64 hex characters>",
  "package_revision": "sha256:<64 hex characters>",
  "candidate_revision": "sha256:<64 hex characters>",
  "explorer_url": "https://explorer.solana.com/tx/<signature>?cluster=devnet",
  "reused": false
}
```

`reused` appears only on POST. Signature/Explorer URL may be null. An Explorer
link is not evidence of successful execution. POST returns 202 for new unresolved
work, 200 for finalized work or any reused reservation. Errors: 401 invalid
reviewer; 404 missing incident/proof; 409 stale/invalid evidence, wrong approving
reviewer, conflicting request key or concurrent transition; 422 invalid/missing
body/header; 503 disabled/provider/storage/auth configuration unavailable.
Provider/driver exception text and credentials are never returned.

Verification returns `status` and `reason`. States: NOT_SUBMITTED, UNKNOWN,
PENDING, CHAIN_FAILED, MISMATCH, FINALIZED. A FINALIZED result additionally includes
`slot`, `signer`, `network`, and `commitment`. No missing transaction is interpreted
as permission to create another transaction.

## Canonical commitment

`canonical_bytes()` uses Python JSON with sorted keys, separators `(',', ':')`,
ASCII Unicode escapes, no NaN/Infinity, and UTF-8 encoding. This deliberately
preserves existing approval hash semantics; it is versioned, not a claim of RFC
8785 compatibility. Numeric serialization is therefore part of v1.

The envelope binds schema, deterministic proof ID, incident incarnation identity,
package hash, exact candidate revision, approval decision ID/hash, publisher public
key, pinned Devnet genesis hash, and fixed Memo Program ID. The complete stored
approval decision is hashed, including its reviewer/time/comment and recorded
eligibility. The frozen package transitively covers source/diff/tests/replay and
investigation/review evidence. Mutable notification references, proof status,
transaction/blockhash, and later incident changes are not added to that package.

Commitment: SHA-256 of `FactoryOS/RepairProof/v1\n` followed by canonical envelope
bytes, represented as `sha256:<hex>`. Bundle responses contain `envelope`,
`commitment`, and base64 canonical `envelope_bytes_b64`, `package_bytes_b64`,
`approval_bytes_b64`. The browser hashes those exact bytes using Web Crypto;
it does not reserialize Python JSON. Shared Python/JavaScript golden fixtures
live in `tests/repairproof/golden_v1.json`.

Only an opaque proof ID and commitment enter the Memo. Raw source, incident
evidence, reviewer identity, comments, and credentials stay off-chain. Bundle
access is authenticated. A matching commitment attests to a publisher's recorded
evidence, not physical recovery, deployment, or independent proof of test execution.

## Durable state and recovery

`repair_proofs` and `repair_proof_requests` use the same P1-owned Mongo database
with majority write/read concerns. They never write canonical incident snapshots.
Unique indexes reserve one proof per incident incarnation + decision + genesis;
proof IDs and request keys are unique. Request-key aliases are persisted so a new
retry key cannot later be reused for another body. Indexes are created only when
publishing, avoiding database writes during disabled-feature startup.

PREPARED -> SIGNED -> SUBMITTING -> SUBMITTED/UNKNOWN -> FINALIZED/CHAIN_FAILED.
Preparation failure is PREPARATION_FAILED; invalid evidence/transaction becomes
MISMATCH. The signed bytes, locally known signature, blockhash, and expiry height
are durably saved before SUBMITTING is acknowledged and any broadcast occurs.
Approval is checked again immediately before SUBMITTING. Mongo failure blocks
downstream broadcast; a failure after broadcast leaves the saved signature for
reconciliation. Intentional retries never send, re-sign, or replace transactions.

A new service instance reconciles saved signatures using historical status and
finalized transaction lookups. An abandoned PREPARED reservation remains blocked;
SIGNED/SUBMITTING/UNKNOWN records are inspected without broadcasting. This favors
safety over automatically completing an uncertain attempt. No exactly-once claim
is made. Expiry or a null RPC response alone does not authorize replacement.

The Memo adapter uses injected RPC and signing ports. It pins Devnet genesis,
requires one Ed25519-verified publisher signature and exactly one fixed Memo
instruction with that signer account, forbids other accounts/instructions, checks
exact signed bytes and memo, uses preflight with RPC maxRetries=0, and requires
finalized successful execution. It never constructs transfers. The app does not
instantiate these ports. Tests mock positive signing/Ed25519 results explicitly,
exercise real SDK rejection of invalid signatures, and create no keypair/wallet.

## Shared-file coordination and next live phase

Registration is additive in the existing `backend/modernization/app.py` assembly;
`backend/main.py` remains unchanged. P1's `IncidentUpdate` validator reserves
Solana/RepairProof integration prefixes and rejects forged top-level proof fields.
The panel reads trusted proof records, never generic integration strings.
P2 approval logic is unchanged. Confirm these two small assembly/schema changes
with the respective owners before merging. A future canonical incident receipt
summary/history callback should be coordinated with P1; this phase intentionally
uses the dedicated proof API instead of adding another incident writer.

Before one authorized live transaction: verify real Mongo durability/restart,
configured named approvers, fresh real Nemotron/Docker/Gemini evidence, provision
a separate Devnet signer outside Git, implement/review the bounded HTTP RPC and
signer factories, add fee limits and timeout policy, test valid real signed-wire
fixtures, and explicitly authorize the one transaction. Keep SOLANA_ENABLED false
until then. No new Jira/Slack deliveries are required.

Tests: `python -m pytest -q`, `npm --prefix frontend test`,
`npm --prefix frontend run build`. Default tests use mongomock and scripted Solana,
AI, and verifier providers; they do not establish live MongoDB or chain behavior.
