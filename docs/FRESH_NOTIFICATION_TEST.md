# Fresh notification test — awaiting explicit approval

No live notification has been authorized or executed for this test. Preserve
backend/.env, the existing snapshot, and .factoryos-jira.sqlite3. Do not run the
old verify_slack_incident_live script: it restores the old KAN-4 incident in a
separate TestClient process rather than testing the running server.

## Preflight

Against http://127.0.0.1:8000, GET /health, /api/integrations/capabilities,
/api/incidents, and /api/telemetry/latest. Require healthy responses and both
notification capabilities. Record the current incident IDs and created_at values.
If these requests fail, stop before creating telemetry or notifying providers.

The old ledger records INC-COOLING-001 created at
2026-11-08T00:59:35.305222Z as KAN-4 (Jira ID 10013). This is historical local
evidence only. Never attach it to a newly created incident or assume it exists
in the running backend. Incident ID alone is insufficient after restart.

## Approved live sequence (not executed)

1. Generate a unique device ID: E2E-NOTIFY- followed by a fresh UUID hex string.
   Confirm that device is absent from the current telemetry and incident lists.
2. POST /api/telemetry exactly once with schema_version=1.0, that device ID,
   source_kind=simulator, observed_at=current UTC at execution, sequence=1,
   temperature_c=29.4, humidity_pct=54, cooling_fault=true,
   fault_is_simulated=true. Do not use a fixed historical observation timestamp.
3. Capture the returned incident_id dynamically. GET that incident and verify
   the unique device, fresh created_at, mismatch=true, legacy_missed_fault,
   simulated fault disclosure, and no existing Jira/Slack references. Stop if
   any reference is already present. Do not assume INC-COOLING-001 is the new ID.
4. POST /api/incidents/{captured_id}/notify once. This may create one new Jira
   Task in the configured KAN project and send one Slack message to the
   configured channel (previously C0CFUREPTGS, #factoryos-incidents).
   Verify destination configuration before the approved send without printing
   tokens. Do not reuse KAN-4 or override credentials.
5. Require a new Jira key, numeric jira_id, and matching Jira URL, plus
   notification_status=DELIVERED, slack_status=DELIVERED, matching channel,
   and valid slack_message_ts. slack_message_id must equal that timestamp.
6. GET the incident again and compare all returned provider references. Read
   back the Jira issue and exact Slack message using existing authorized
   credentials where permissions allow; check the incident/device, timestamps,
   simulation disclosure, and canonical Jira link. If Slack history permission
   is absent, report read-back as unverified; do not change scopes or tokens.
7. Only after confirmed delivery, repeat notify once to verify duplicate
   prevention. Require the same Jira key/ID/URL and Slack channel/timestamp,
   already_exists=true and slack_already_exists=true. Check provider read-back
   for the same records. Do not repeat notify after an ambiguous first outcome.

## Failure expectations

- Jira failure: no Slack send. Uncertain Jira outcomes must block retry with 409.
- Jira success plus missing Slack configuration or explicit rejection: PARTIAL;
  retain the Jira reference. A corrected retry must reuse that issue. Do not
  deliberately break real credentials to test this; use mocked tests.
- Slack timeout, malformed confirmation, 5xx, or unknown provider error:
  UNCONFIRMED; stop and reconcile before retrying. PENDING also blocks resend.
- Preserve all ledger rows. Never clear a reservation to bypass uncertainty.
- Exactly-once delivery cannot be guaranteed after ambiguous network outcomes.

## Local verification completed

49 Jira/Slack tests passed with mocked providers and temporary ledgers:
`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_jira.py tests/test_slack.py`.
Coverage includes confirmed provider IDs, repeated/concurrent requests, retained
ledger results, missing configuration, explicit rejection, partial success,
timeouts, malformed confirmations, and blocked ambiguous retries. This does not
prove current live provider delivery or running-backend health.
