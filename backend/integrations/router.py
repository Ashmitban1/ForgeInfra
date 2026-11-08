"""Notification router with a durable creation ledger and injected P1 storage."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3

from fastapi import APIRouter, HTTPException

from backend.integrations.jira import configuration, create_issue

DEFAULT_LEDGER = Path(__file__).resolve().parents[2] / '.factoryos-jira.sqlite3'


def create_notification_router(incidents: dict, storage_lock, ledger_path=DEFAULT_LEDGER) -> APIRouter:
    router = APIRouter()

    @router.post('/api/incidents/{incident_id}/notify')
    def notify(incident_id: str):
        with storage_lock:
            if incident_id not in incidents:
                raise HTTPException(404, 'Incident not found')
            incident = deepcopy(incidents[incident_id])
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
        with storage_lock:
            incidents[incident_id]['integrations'].update(result)
        return {'incident_id': incident_id, 'provider': 'jira',
                'already_exists': already_exists, **result}

    return router
