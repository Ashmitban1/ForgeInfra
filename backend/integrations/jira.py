"""Jira Cloud adapter. Never return upstream bodies, which may contain secrets."""
import os
import re
from urllib.parse import urlsplit

import requests
from fastapi import HTTPException


def configuration() -> tuple[str, str, str, str]:
    names = ('JIRA_BASE_URL', 'JIRA_EMAIL', 'JIRA_API_TOKEN', 'JIRA_PROJECT_KEY')
    values = tuple(os.getenv(name, '').strip() for name in names)
    missing = [name for name, value in zip(names, values) if not value]
    if missing:
        raise HTTPException(503, 'Configure backend variables: ' + ', '.join(missing))
    base, email, token, project = values
    try:
        url = urlsplit(base)
    except ValueError:
        raise HTTPException(503, 'JIRA_BASE_URL must be an HTTPS Atlassian Cloud site URL.') from None
    if (url.scheme != 'https' or not url.hostname or
            not url.hostname.endswith('.atlassian.net') or url.username or
            url.password or url.netloc != url.hostname or url.path not in ('', '/') or url.query or url.fragment):
        raise HTTPException(503, 'JIRA_BASE_URL must be an HTTPS Atlassian Cloud site URL.')
    if not re.fullmatch(r'[A-Z][A-Z0-9_]*', project):
        raise HTTPException(503, 'JIRA_PROJECT_KEY must be a Jira project key such as KAN.')
    return base.rstrip('/'), email, token, project


def create_issue(incident: dict, config: tuple) -> dict:
    base, email, token, project = config
    hardware = incident.get('hardware', {})
    lines = [f'FactoryOS incident: {incident["incident_id"]}',
             f'Device / rack: {incident["device_id"]}',
             f'Severity: {incident.get("severity")}',
             f'Created: {incident.get("created_at")}',
             f'Updated: {incident.get("updated_at")}',
             *[f'{key}: {hardware.get(key)}' for key in
               ('temperature_c', 'humidity_pct', 'observed_at', 'received_at',
                'cooling_fault', 'fault_is_simulated', 'source_kind')],
             f'Expected status: {incident.get("expected_status")}',
             f'Legacy status: {incident.get("legacy_monitor", {}).get("status")}',
             f'Reliability mismatch: {incident.get("reliability", {}).get("mismatch")}',
             f'Evidence quality: {incident.get("reliability", {}).get("evidence_quality")}',
             'Mismatch reasons: ' + ', '.join(incident.get('reliability', {}).get('reasons', []))]
    payload = {'fields': {
        'project': {'key': project}, 'issuetype': {'name': 'Task'},
        'summary': f'FactoryOS {incident["incident_id"]}: {incident["device_id"]}'[:255],
        'description': {'type': 'doc', 'version': 1, 'content': [
            {'type': 'paragraph', 'content': [{'type': 'text', 'text': line}]}
            for line in lines]},
    }}
    try:
        response = requests.post(base + '/rest/api/3/issue', json=payload,
                                 auth=(email, token), timeout=(5, 20),
                                 headers={'Accept': 'application/json'}, allow_redirects=False)
    except requests.RequestException:
        raise HTTPException(502, 'Jira network failure; creation outcome is uncertain. Reconcile this attempt before retrying.') from None
    if response.status_code == 401:
        raise HTTPException(502, 'Jira authentication failed. Check JIRA_EMAIL and JIRA_API_TOKEN.')
    if response.status_code in (400, 403, 404, 422):
        raise HTTPException(502, 'Jira rejected the project or issue fields. Check KAN access, Create Issues permission, Task availability, and required fields.')
    if response.status_code == 429:
        raise HTTPException(503, 'Jira rate limit reached. Wait before retrying.')
    if response.status_code != 201:
        raise HTTPException(502, 'Jira did not confirm creation. Reconcile this attempt before retrying.')
    try:
        body = response.json()
        key, issue_id = body['key'], body['id']
        if not isinstance(key, str) or not re.fullmatch(re.escape(project) + r'-[0-9]+', key):
            raise ValueError()
        if not isinstance(issue_id, str) or not issue_id.isdigit():
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise HTTPException(502, 'Jira returned an invalid confirmation. Reconcile this attempt before retrying.') from None
    return {'jira_key': key, 'jira_id': issue_id, 'jira_url': base + '/browse/' + key}
