"""Prepare one Slack incident delivery using the existing live-test Jira reference.

Default only prints a safe preview. After approval, run with --send.
No new Jira ticket is allowed; missing references stop the script.
"""
import argparse
import json
import os
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient

from backend.integrations.app import app
from backend.integrations.router import DEFAULT_LEDGER
from backend.main import _incidents, _lock

SNAPSHOT = Path(__file__).resolve().parents[1] / '.factoryos-jira-live.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--send', action='store_true', help='Send only after explicit human approval')
    args = parser.parse_args()
    if not SNAPSHOT.exists() or not DEFAULT_LEDGER.exists():
        raise SystemExit('Existing incident snapshot and Jira ledger required; no requests sent.')
    incident = json.loads(SNAPSHOT.read_text())
    expected_url = 'https://muhdaymanhaque.atlassian.net/browse/KAN-4'
    identity = json.dumps(['https://muhdaymanhaque.atlassian.net', 'KAN',
                           incident['incident_id'], incident['created_at']])
    with sqlite3.connect(f'file:{DEFAULT_LEDGER}?mode=ro', uri=True) as db:
        row = db.execute('SELECT result FROM jira_attempts WHERE identity=?', (identity,)).fetchone()
    if not row or not row[0]:
        raise SystemExit('No confirmed existing Jira result; no requests sent.')
    jira = json.loads(row[0])
    if jira.get('jira_url') != expected_url or not jira.get('jira_id'):
        raise SystemExit('Expected confirmed KAN-4 reference is unavailable; no requests sent.')
    channel = os.getenv('SLACK_CHANNEL_ID', '').strip()
    if channel != 'C0CFUREPTGS' or not os.getenv('SLACK_BOT_TOKEN', '').strip():
        raise SystemExit('Verified Slack channel and bot configuration required; no requests sent.')
    incident['integrations'].update(jira)
    print(json.dumps({'incident_id': incident['incident_id'], 'device': incident['device_id'],
                      'severity': incident['severity'], 'created_at': incident['created_at'],
                      'simulated_fault': incident['hardware']['fault_is_simulated'],
                      'mismatch_evidence': incident['reliability']['reasons'],
                      'jira_url': expected_url, 'channel': channel, 'sending': args.send}))
    if not args.send:
        return
    with _lock:
        if incident['incident_id'] in _incidents:
            raise SystemExit('Incident ID already in use in this process; no requests sent.')
        _incidents[incident['incident_id']] = incident
    response = TestClient(app).post(f'/api/incidents/{incident["incident_id"]}/notify')
    if response.status_code != 200:
        raise SystemExit(f'Notify HTTP {response.status_code}; no retries attempted.')
    result = response.json()
    print(json.dumps({key: result.get(key) for key in
                      ('incident_id', 'jira_key', 'jira_url', 'slack_status', 'slack_channel_id',
                       'slack_message_ts', 'slack_error', 'slack_already_exists', 'notification_status')}))
    if result.get('slack_status') != 'DELIVERED':
        raise SystemExit('Slack not confirmed; no retries attempted. Reconcile any ambiguous outcome.')


if __name__ == '__main__':
    main()
