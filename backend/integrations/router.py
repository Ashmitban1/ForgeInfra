"""Notification router with a durable creation ledger and injected P1 storage."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3

from fastapi import APIRouter, HTTPException

from backend.integrations.jira import configuration, create_issue
from backend.integrations.slack import deliver

DEFAULT_LEDGER = Path(os.environ.get('FACTORYOS_NOTIFICATION_LEDGER',
                                    str(Path(__file__).resolve().parents[2] / '.factoryos-jira.sqlite3')))


def create_notification_router(incidents: dict, storage_lock, ledger_path=DEFAULT_LEDGER,
                               *, get_snapshot=None, publish_result=None) -> APIRouter:
    router = APIRouter()

    def snapshot(incident_id):
        if get_snapshot is not None:
            from backend.modernization.repository import IncidentMissing
            try:
                return get_snapshot(incident_id)
            except IncidentMissing:
                raise HTTPException(404, 'Incident not found') from None
        with storage_lock:
            if incident_id not in incidents:
                raise HTTPException(404, 'Incident not found')
            return deepcopy(incidents[incident_id])

    def publish(incident, fields):
        if publish_result is not None:
            return publish_result(incident['incident_id'], incident['created_at'], fields)
        with storage_lock:
            current = incidents.get(incident['incident_id'])
            if not current or current['created_at'] != incident['created_at']:
                raise HTTPException(409, 'Incident changed during notification; refresh before continuing')
            fields = deepcopy(fields)
            if current['integrations'].get('slack_status') == 'DELIVERED' and fields.get('slack_status') != 'DELIVERED':
                fields = {key: value for key, value in fields.items() if not key.startswith('slack_')}
            current['integrations'].update(fields)
            return deepcopy(current)

    @router.get('/api/integrations/capabilities')
    def capabilities():
        return {'jira': {'notify': True}, 'slack': {'notify': True}}

    def ensure_jira(incident):
        incident_id = incident['incident_id']
        reference = incident.get('integrations', {})
        if all(reference.get(key) for key in ('jira_key', 'jira_id', 'jira_url')):
            return {'incident_id': incident_id, 'provider': 'jira', 'already_exists': True,
                    **{key: reference[key] for key in ('jira_key', 'jira_id', 'jira_url')}}
        config = configuration()
        # created_at prevents reused volatile incident IDs from colliding after restart.
        identity = json.dumps([config[0], config[3], incident_id, incident['created_at']])
        with sqlite3.connect(ledger_path, timeout=30) as db:
            db.execute('CREATE TABLE IF NOT EXISTS jira_attempts (identity TEXT PRIMARY KEY, result TEXT)')
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT result FROM jira_attempts WHERE identity=?', (identity,)).fetchone()
            result = None
            already_exists = False
            if existing:
                if existing[0] is None:
                    raise HTTPException(409, 'A Jira attempt is pending or uncertain. Check Jira for this incident and reconcile the local ledger before retrying; no second issue was sent.')
                result = json.loads(existing[0])
                already_exists = True
            elif incident.get('integrations', {}).get('jira_key'):
                result = {k: incident['integrations'].get(k) for k in ('jira_key', 'jira_id', 'jira_url')}
                already_exists = True
                db.execute('INSERT INTO jira_attempts VALUES (?, ?)', (identity, json.dumps(result)))
            else:
                db.execute('INSERT INTO jira_attempts VALUES (?, NULL)', (identity,))
            db.commit()
            if result is None:
                try:
                    result = create_issue(incident, config)
                except HTTPException as exc:
                    # Only explicit rejections are safe to retry automatically.
                    if exc.detail.startswith(('Jira authentication failed.', 'Jira rejected', 'Jira rate limit')):
                        db.execute('DELETE FROM jira_attempts WHERE identity=?', (identity,))
                        db.commit()
                    raise
                db.execute('UPDATE jira_attempts SET result=? WHERE identity=?', (json.dumps(result), identity))
                db.commit()
        publish(incident, result)
        return {'incident_id': incident_id, 'provider': 'jira',
                'already_exists': already_exists, **result}

    @router.post('/api/incidents/{incident_id}/notify')
    def notify(incident_id: str):
        original = snapshot(incident_id)
        jira = ensure_jira(original)
        incident = snapshot(incident_id)
        if incident['created_at'] != original['created_at']:
            raise HTTPException(409, 'Incident changed during notification; refresh before continuing')
        slack = deliver(incident, jira, ledger_path)
        current = publish(incident, slack)
        integrations = current['integrations']
        slack = {**slack, **{key: value for key, value in integrations.items() if key.startswith('slack_')}}
        return {**jira, **slack,
                'notification_status': 'DELIVERED' if slack['slack_status'] == 'DELIVERED' else 'PARTIAL',
                'integrations': integrations}

    return router
