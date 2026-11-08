# FactoryOS — Person 3 Follow-up Summary

This update covers work since `PERSON_3_PROGRESS_AND_HANDOFF.md` was first created,
through the push of commit `2d50a33` on `feat/dashboard`.

## Outcome

Slack bot connectivity has been verified with one real generic test message.
The combined Jira → Slack incident notification workflow is implemented, tested
with mocked providers, and pushed to the Person 3 branch. A fresh, complete live
incident notification through the combined workflow has **not been confirmed**.

## Slack configuration and live connectivity

- Checked backend/.env without displaying credentials; confirmed it is ignored
  by Git and untracked.
- Initially found SLACK_BOT_TOKEN missing. After local configuration, auth.test
  succeeded for workspace **hackutd26**, workspace ID `T0CGPBNUD5E`.
- Channel verification initially failed because the bot lacked a read scope.
  A later check confirmed **chat:write**, channel access, bot membership, and an
  active, unarchived channel using conversations.info with GET parameters.
- Verified destination: **#factoryos-incidents**, channel ID `C0CFUREPTGS`.
- Sent exactly one generic connection test message:

  > FactoryOS integration test — Slack notifications are working. No real infrastructure incident.

- Slack returned **ok: true**, channel `C0CFUREPTGS`, timestamp
  **`1794107859.146339`**.
- Message link:
  https://hackutd26.slack.com/archives/C0CFUREPTGS/p1794107859146339

This message verified connectivity only. It was not a full incident notification
containing a Jira reference.

## Combined Jira and Slack workflow

Extended the existing `POST /api/incidents/{id}/notify` route:

1. Fetch the incident from existing shared in-memory storage.
2. Create or reuse its confirmed Jira Task.
3. Send Slack an incident message containing incident ID, rack/device, severity,
   timestamps, temperature/humidity, cooling-fault status, explicit simulated-fault
   disclosure, mismatch evidence, and the real Jira URL.
4. Store confirmed Slack channel and message timestamp against the incident and
   in the persistent local notification ledger.

The adapter checks Slack's actual `ok`, matching channel, and valid message ts
before recording delivery. It disables mention parsing and link previews.
Credentials stay exclusively on the backend.

### Partial success and retries

- Jira success plus Slack failure returns **PARTIAL**, retaining the real Jira
  reference. A corrected retry reuses that ticket.
- Confirmed Slack delivery is reused instead of deliberately sending again.
- Known explicit rejections, such as missing_scope or not_in_channel, permit a
  corrected retry. Rate limits require waiting before retrying.
- Timeouts, network failures, unknown provider errors, and malformed confirmations
  leave delivery **UNCONFIRMED**. Interrupted reservations may remain **PENDING**.
  Both block another automatic send until manual reconciliation.
- This prevents intentional duplicates; it does not promise exactly-once delivery
  after ambiguous provider outcomes.

## Frontend updates

- Added Jira/Slack route capability checks before enabling notification actions.
- Added **Create Jira Issue & Notify Slack** and **Notify Slack / Retry** actions.
- Kept **View Jira Issue** for the confirmed ticket.
- Added actual Slack delivery status, channel, timestamp, and actionable errors.
- Disabled retry for pending/unconfirmed delivery and concurrent submissions.
- Kept demo notifications disabled and preserved the existing Motion animations,
  layout, routing, and other frontend work.

## Tests and validation

- **53 backend tests passed**, including existing API tests and combined Jira/Slack
  delivery, missing configuration, provider errors, partial success, safe retries,
  concurrent requests, persistent-ledger reuse, and ambiguous-outcome blocking.
- **Frontend production build passed**.
- Configured-token exclusion checks passed before pushing.
- Local tests used Python 3.15; Python 3.11 validation remains pending.
- Existing Starlette deprecation and Motion bundle warnings were non-fatal.
- No full browser-driven Jira + Slack incident delivery has been verified.

## Live incident testing: important distinction

An earlier live Jira-only test had already created **KAN-4**, issue ID `10013`:
https://muhdaymanhaque.atlassian.net/browse/KAN-4

Its historical incident snapshot used INC-COOLING-001 with creation timestamp
`2026-11-08T00:59:35.305222Z`. After a backend restart, incident IDs can be reused.
A new INC-COOLING-001 must not inherit KAN-4 simply because its ID matches.

The first approved attempt to notify that historical incident stopped because the
backend was unavailable. No notification was sent. Later localhost verification
also failed, so manual terminal commands were provided instead of contacting the
providers from Codex.

The manual procedure was corrected to:

- Compare the sensor timestamp with **hardware.observed_at**, not incident.created_at.
- Generate a unique device ID and current sensor timestamp.
- Avoid INC-COOLING-001 and incident IDs already present in storage or the ledger.
- Verify the incident has no Jira/Slack references and no persistent notification
  attempts before sending.
- Reserve a local execution guard before the one notification request.
- Allow at most one new Jira ticket and one Slack message; never automatically
  retry an ambiguous outcome.
- Confirm stored and ledger references using read-only checks after delivery.

No successful execution result for this fresh combined live test has been received.
The saved-snapshot `verify_slack_incident_live.py` is historical tooling and must
not be used as proof that the running backend contains the historical incident.
Use the fresh-test safeguards instead; see `docs/FRESH_NOTIFICATION_TEST.md` and
the corrected terminal procedure supplied in the conversation.

## Persistent ledger verification

Inspected configuration, the repository SQLite file, and available process details
without changing files, restarting services, or contacting Jira/Slack.

- **MATCH:** the configured default path resolves to the repository's
  `.factoryos-jira.sqlite3` using `Path(__file__).resolve().parents[2]`, independent
  of the server's working directory.
- Jira and Slack receive the same ledger path from the notification router.
- The running Uvicorn command used `backend.integrations.app:app --reload` from
  this repository; the worker was a multiprocessing child.
- The repository ledger existed and `jira_attempts` had `identity` and `result`.
- `slack_attempts` was absent at inspection. The Slack adapter creates it lazily
  on first use, so absence alone does not prove a path mismatch.
- The worker's in-memory router closure was not directly inspected; its exact
  runtime path could not be proven independently of startup configuration.

These were observations at inspection time, not a guarantee that the same server
process or configuration is still running now.

## Files and Git status

New files included:

- `backend/integrations/slack.py`
- `tests/test_slack.py`
- `scripts/verify_jira_live.py`
- `scripts/verify_slack_incident_live.py`
- `docs/FRESH_NOTIFICATION_TEST.md`
- `docs/PERSON_3_PROGRESS_AND_HANDOFF.md`

Updated integration router/Jira validation, frontend API/action/result components,
Jira tests, environment placeholders, Git ignores, README, API contract, and
integration documentation.

With explicit authorization, committed and pushed:

**`2d50a33` — Add Slack incident notifications with durable retry tracking**

Branch: `feat/dashboard`
Commit: https://github.com/Ashmitban1/HACKUTD-26-/commit/2d50a33

Credentials and local SQLite/snapshot files were excluded. No merge was performed.
This follow-up summary was created after that push and is not included in it.

## Team coordination and next steps

- **Person 1:** main.py was not edited. Continue using
  `python -m uvicorn backend.integrations.app:app --reload`, or coordinate adoption
  of the existing router factory into main.py. Both providers use the same incident
  dictionary/lock. Durable shared storage is still future work.
- **Person 2:** agents and modernization code were not modified.
- **Person 3:** perform the guarded fresh Jira + Slack end-to-end test from the Mac
  terminal, then record the new Jira key, Slack ts/link, and confirmed references.
  Do not reuse historical associations or retry ambiguous requests.
- Keep the unauthenticated backend local. Production authentication, durable
  multi-host storage, and other integrations remain outside this completed work.
