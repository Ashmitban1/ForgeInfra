# RepairProof Phase 2 — real Devnet adapter, disabled by default

The adapter uses `solders==0.27.1` for real Ed25519 signatures, legacy transaction
construction/deserialization, and signature verification. A bounded `httpx`
JSON-RPC client implements the required official Solana methods. No custom
program, new SDK dependency, wallet generation, funding, or startup RPC is needed.
Existing v1 approval/package/commitment serialization and golden fixtures are
unchanged. The approved evidence is never rewritten by the publisher.

## Configuration

Backend-only configuration, in an ignored dotenv file or process environment:

```env
SOLANA_ENABLED=false
SOLANA_RPC_URL=https://api.devnet.solana.com
SOLANA_VERIFY_RPC_URL=https://api.devnet.solana.com
SOLANA_EXPECTED_GENESIS_HASH=EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG
SOLANA_ALLOWED_PUBLISHER=<dedicated Devnet publisher public key>
SOLANA_PUBLISHER_KEYPAIR_PATH=<absolute private path outside this repository>
SOLANA_MAX_FEE_LAMPORTS=10000
SOLANA_RPC_TIMEOUT_SECONDS=10
```

The verification URL defaults to the publishing URL when unset. An independently
operated verification RPC is preferable. Both must return the pinned Devnet
genesis hash; a URL or Explorer cluster query alone is insufficient. RPC URLs
must use HTTPS, without userinfo, fragments, whitespace, or mainnet hostnames.
URLs are never included in capabilities, proof responses, or driver errors.
Configuration objects hide URLs/private paths in their representations.

RPC deadlines must be 1–30 seconds. Connect timeout is capped at 5 seconds.
Clients ignore environment proxy settings, follow no redirects, use zero HTTP
retries, allowlist methods, bound responses to 256 KB, validate JSON-RPC version
and request IDs, and return safe error codes. No RPC method is invoked merely
by importing/configuring the app or reading capabilities/readiness.

`live_provider_available=true` means the implementation is present, not that the
network has been contacted successfully. `provider_configured` reports whether
RPC/public-key/path configuration was accepted. Missing/insecure key-file metadata
blocks readiness. Actual private bytes and public-key matching are validated
only during an authorized preparation. The application loads the factory during
its lifespan; a controlled backend restart is needed to load new code/config.

## Signer setup — operator steps, not performed by implementation/tests

After separate approval to provision a wallet:

1. Use a dedicated **Devnet-only** wallet, never a mainnet/funded personal wallet.
2. Use the Solana CLI to create it in a private directory outside the repository,
   following the CLI's backup instructions; never paste its output or seed into chat.
   For example, set `umask 077`, create a private directory, and run
   `solana-keygen new --outfile /absolute/private/path/devnet-publisher.json`.
3. Set the key file to owner-only permissions (`chmod 600 ...`). The implemented
   POSIX loader rejects symlinks, nonregular files, other owners, files readable
   by group/others, malformed key arrays, and keys that do not match the configured
   public key. The supported file is the CLI's JSON array of 64 byte integers.
4. Obtain the public key using `solana-keygen pubkey /absolute/private/path/devnet-publisher.json`
   and configure `SOLANA_ALLOWED_PUBLISHER` exactly. This public key is not the
   human reviewer identity; it is the authenticated application's publisher.
5. With funding authorization, obtain Devnet SOL and inspect the balance using
   explicit `--url https://api.devnet.solana.com`. Do not use production funds.
6. Leave `SOLANA_ENABLED=false` until one specific publication is authorized.

The loader reconstructs an existing signer only after current durable approval
and reviewer authorization pass. It creates no wallet/account and exposes no
generic signing endpoint. Private key bytes are not persisted in MongoDB or sent
to RPC/frontend. A Windows live signer would require a separately hardened loader;
the current owner/mode/no-follow checks target POSIX systems.

## Fees and transaction restrictions

Transactions contain exactly one Memo Program instruction, one required publisher
signature (also fee payer), and that explicit signer account. Other programs,
extra instructions/accounts, transfers, priority-fee instructions, invalid
signatures, noncanonical transaction bytes, and transactions larger than 1232 bytes
are rejected. The memo contains only the existing versioned proof ID/commitment.

The adapter obtains `getFeeForMessage` before signing, requires sufficient
`getBalance`, saves the quote and fee ceiling with the signed transaction, checks
blockhash expiry and the fee quote again immediately before broadcast, and
requires the finalized receipt fee to be within the ceiling. A null quote blocks
publication. The configurable ceiling is capped at 100,000 lamports. This is a
prebroadcast fee policy plus receipt validation, not a new on-chain absolute-fee
ceiling instruction; the base fee is determined by the network at execution.

## Authorization and recovery

The existing reviewer bearer token is mandatory; only the reviewer who recorded
the exact approval may publish. SOLANA_ENABLED, MongoDB majority readback,
current `require_approved()` eligibility, and exact package/candidate/decision
bindings must pass before construction. Authorization is rechecked before
preparation and immediately before entering SUBMITTING. This does not weaken
freshness, Gemini, Docker, source-revision, or reviewer-revocation gates.

Signed bytes, locally known signature, blockhash, last valid height, and fee policy
are acknowledged/read back in MongoDB before any `sendTransaction`. Preflight
remains enabled, with finalized commitment and `maxRetries=0`. A successful send
response is not confirmation. A timeout/unexpected response remains UNKNOWN;
the record may still say SUBMITTING if receipt persistence failed.

Retries never generate a new blockhash, sign again, or broadcast again. They look
up the saved signature with historical status search and finalized transaction
retrieval. Null/expired results alone never authorize replacement. PREPARED and
PREPARATION_FAILED reservations remain conservatively blocked, including failures
before sending; resolve them explicitly rather than creating another attempt.
This feature does not claim exactly-once behavior across a database and chain.

GET `/api/repair-proofs/{id}/verify` independently rebuilds the saved commitment,
checks Devnet, successful execution, finalized status, exact wire transaction,
actual Ed25519 signatures, expected publisher/Memo/payload, matching slot, and fee.
The browser separately hashes the canonical evidence/approval bytes via Web Crypto.
This is RPC-backed verification, not a consensus light client or independent proof
that tests ran. It does not establish deployment or equipment recovery.

POST `/api/repair-proofs/{id}/reconcile` adds one authenticated route:

- No body or idempotency key required.
- Only the approving reviewer may call it.
- Returns HTTP 200 with the existing public proof response (including saved
  verification); 401/404/409/503 have the existing meanings.
- Persists receipt/UNKNOWN state using compare-and-set; never prepares/signs/sends.
- Works with publishing disabled, so a submitted proof can be reconciled safely.
- The panel's **Reconcile status (no resubmit)** button uses this route.

The existing capabilities and per-incident readiness add `provider_configured`;
readiness also adds `enabled`. Public proof responses add `error_code` (null or a
safe preparation error). A finalized verification adds `fee_lamports`. Existing
routes and the canonical incident writer are otherwise unchanged.

## Exact one-transaction procedure — only after explicit authorization

1. Confirm no proof/request reservation already exists for incident
   `INC-COOLING-003`, decision `approval-decision-d57a5d0b598d45a2b4a3658914ad8763`,
   on the pinned Devnet network. Inspect the dedicated proof API and MongoDB;
   historical incident IDs alone are insufficient.
2. Complete authorized Devnet wallet/configuration/funding setup above. Keep the
   flag false while preparing. Verify the RPC genesis and available fee balance
   using read-only operator tooling after permission for live network checks.
3. Perform a controlled restart to load Phase 2 after checking volatile data risk.
   Confirm MongoDB OK, reviewer authentication, and configured publisher metadata.
4. Generate a genuine new observation from the same explicitly simulated device
   if telemetry has aged. Preserve its case and original incident. The existing
   approved candidate/review may remain reusable; do not approve again. Recheck
   current approval is APPROVED, PERSISTED version 1, and bound to the exact hashes.
5. Obtain explicit authorization for **one fee-paying Devnet Memo**. Only then set
   SOLANA_ENABLED=true in the private backend configuration and reload it through
   a controlled restart. Refresh same-case simulation if required by the gate.
6. Authenticate with the approving reviewer. Submit exactly one POST to
   `/api/incidents/INC-COOLING-003/repair-proofs`, with a recorded stable
   `Idempotency-Key` and body:

```json
{
  "decision_id": "approval-decision-d57a5d0b598d45a2b4a3658914ad8763",
  "package_revision": "sha256:a835aadb53727fa42ad2984a3a1ce27088d6f50fdd028d144443a0b03a8afbcb",
  "candidate_revision": "sha256:ed1febab0e090c80e118206bd41a409047ffa9580b5ae70e5bc7779eaf5d2242"
}
```

7. If the response is ambiguous, GET per-incident readiness to find the durable
   reservation. Do not submit a different transaction or generate a replacement.
8. Use POST `/{proof_id}/reconcile` to persist actual finality, and GET
   `/{proof_id}/verify` plus the browser bundle check to verify the commitment.
   Report the signature, fee, slot, and Devnet Explorer URL only after verification.
9. Disable publishing again and apply that configuration through a controlled
   restart. Verification/reconciliation can remain available without broadcasting.

No live transaction, wallet provisioning/funding, approval, or AI rerun was
performed while implementing this layer. The earlier human decision is historical
evidence; it may currently project as STALE when telemetry has aged. A matching
fresh same-case observation can restore eligibility without rewriting that decision.

## Tests

`python -m pytest -q tests/repairproof` exercises real SDK signatures using the
already-published RFC 8032 TEST 1 key vector, reconstructed only as disposable test
data. It generates no random key or application wallet. All HTTP uses
`httpx.MockTransport`; no Solana RPC is contacted. Tests cover signer-file security,
fee limits, wrong networks, invalid signatures, replay/extra instructions, approval
gates before any RPC, ambiguous send recovery, and receipt persistence. Existing
Phase 1 commitment golden fixtures are unchanged. Run frontend tests/build too.

Primary references: [Memo Program](https://www.solana-program.com/docs/memo),
[fee quotes](https://solana.com/docs/rpc/http/getfeeformessage),
[submission semantics](https://solana.com/docs/rpc/http/sendtransaction),
[finalized transaction retrieval](https://solana.com/docs/rpc/http/gettransaction),
[public Ed25519 test vectors](https://www.rfc-editor.org/rfc/rfc8032#section-7.1).
