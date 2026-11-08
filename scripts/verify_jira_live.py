"""Explicit live Jira smoke test. Run: python -m scripts.verify_jira_live.

Creates at most one issue for the persisted test incident; never deletes its ledger.
Only safe status codes and confirmed references are printed.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

from fastapi.testclient import TestClient
import requests

from backend.integrations.app import app
from backend.integrations.jira import configuration
from backend.main import _incidents, _lock

SNAPSHOT = Path(__file__).resolve().parents[1] / '.factoryos-jira-live.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--notify-slack', action='store_true', help='Explicitly allow the combined notify endpoint to deliver Slack too')
    args = parser.parse_args()
    if not args.notify_slack:
        raise SystemExit('Notify now also sends Slack. Obtain approval, then pass --notify-slack, or use scripts.verify_slack_incident_live to reuse the existing Jira issue.')
    base, email, token, project = configuration()
    if base != 'https://muhdaymanhaque.atlassian.net' or project != 'KAN':
        raise SystemExit('Live test requires the configured FactoryOS site and KAN project.')
    # Confirm credentials and project access before reserving a creation attempt.
    try:
        preflight = requests.get(base + '/rest/api/3/project/KAN', auth=(email, token),
                                 timeout=(5, 20), allow_redirects=False)
    except requests.RequestException:
        raise SystemExit('Jira preflight network failure; no creation attempted.') from None
    if preflight.status_code != 200:
        raise SystemExit(f'Jira project preflight HTTP {preflight.status_code}; no creation attempted.')
    client = TestClient(app)
    if SNAPSHOT.exists():
        incident = json.loads(SNAPSHOT.read_text())
        with _lock:
            _incidents[incident['incident_id']] = incident
    else:
        response = client.post('/api/telemetry', json={
            'device_id': 'JIRA-LIVE-VERIFICATION-SIMULATED', 'source_kind': 'simulator',
            'observed_at': datetime.now(timezone.utc).isoformat(), 'sequence': 1,
            'temperature_c': 29.4, 'humidity_pct': 54, 'cooling_fault': True,
            'fault_is_simulated': True,
        })
        if response.status_code != 200 or not response.json().get('incident_id'):
            raise SystemExit('Telemetry failed to create a test incident.')
        with _lock:
            incident = deepcopy(_incidents[response.json()['incident_id']])
        with SNAPSHOT.open('x') as file:
            json.dump(incident, file)
    path = f'/api/incidents/{incident["incident_id"]}/notify'
    response = client.post(path)
    if response.status_code != 200:
        raise SystemExit(f'Notify HTTP {response.status_code}: {response.json().get("detail", "failed")}')
    result = response.json()
    repeat = client.post(path)
    if repeat.status_code != 200 or not repeat.json()['already_exists'] or repeat.json()['jira_key'] != result['jira_key']:
        raise SystemExit('Duplicate prevention verification failed.')
    try:
        verify = requests.get(base + '/rest/api/3/issue/' + result['jira_key'],
                              params={'fields': 'project,issuetype,description'},
                              auth=(email, token), timeout=(5, 20), allow_redirects=False)
    except requests.RequestException:
        raise SystemExit('Issue created; read-back network failure. Keep snapshot and ledger; do not create again.') from None
    if verify.status_code != 200:
        raise SystemExit(f'Issue created; read-back HTTP {verify.status_code}. Keep snapshot and ledger.')
    body = verify.json()
    assert body['id'] == result['jira_id']
    assert body['fields']['project']['key'] == 'KAN'
    assert body['fields']['issuetype']['name'] == 'Task'
    assert 'fault_is_simulated: True' in json.dumps(body['fields']['description'])
    stored = client.get(f'/api/incidents/{incident["incident_id"]}').json()
    assert stored['integrations']['jira_key'] == result['jira_key']
    print(json.dumps({'verified': True, 'jira_key': result['jira_key'],
                      'jira_id': result['jira_id'], 'jira_url': result['jira_url'],
                      'duplicate_request_reused_issue': True}))


if __name__ == '__main__':
    main()
