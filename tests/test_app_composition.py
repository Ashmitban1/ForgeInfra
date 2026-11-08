"""Fresh startup and canonical notification publication contracts."""
from datetime import datetime, timezone
import json
import os
import subprocess
import sys

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import mongomock
import pytest

from backend import main
from backend.integrations.router import create_notification_router
from backend.storage.mongo import MongoIncidentStore


@pytest.mark.parametrize('module', ['backend.app', 'backend.modernization.app', 'backend.integrations.app'])
def test_entrypoints_have_complete_routes_without_duplicate_registration(module):
    code = '''
import importlib, json, sys, warnings
app = importlib.import_module(sys.argv[1]).app
assert all(importlib.import_module(name).app is app for name in
           ('backend.app', 'backend.integrations.app', 'backend.modernization.app'))
with warnings.catch_warnings(record=True) as captured:
    schema = app.openapi()
assert not any('Duplicate Operation ID' in str(item.message) for item in captured)
routes = [(method.upper(), path) for path, operations in schema['paths'].items() for method in operations]
assert not any(path.startswith('/__test__') for _, path in routes)
required = [('POST','/api/telemetry'), ('POST','/api/incidents/{incident_id}/investigate'),
            ('POST','/api/incidents/{incident_id}/review'), ('POST','/api/incidents/{incident_id}/approval'),
            ('POST','/api/incidents/{incident_id}/notify'), ('GET','/api/integrations/capabilities')]
assert all(route in routes for route in required)
assert len(routes) == len(set(routes)), routes
assert app is importlib.import_module('backend.app').app
print(json.dumps({'complete':True}))
'''
    env = dict(os.environ, MONGODB_URI='', TIGERDATA_DATABASE_URL='', NVIDIA_API_KEY='', GEMINI_API_KEY='')
    result = subprocess.run([sys.executable, '-c', code, module], env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['complete']


def test_notification_is_persisted_and_audited_before_response(tmp_path, monkeypatch):
    for name in ('_incidents', '_latest', '_latest_sequence', '_history', '_fingerprints', '_approval_acks'):
        monkeypatch.setattr(main, name, {})
    monkeypatch.setattr(main, '_next_incident_number', 1)
    mongo = mongomock.MongoClient()
    store = MongoIncidentStore(mongo, 'notifications')
    monkeypatch.setattr(main, 'store_from_environment', lambda: store)
    monkeypatch.setattr(main, 'tiger_from_environment', lambda: None)
    monkeypatch.setattr('backend.integrations.router.configuration', lambda: ('https://example.atlassian.net', 'test', 'secret', 'OPS'))
    monkeypatch.setattr('backend.integrations.router.create_issue', lambda incident, config: {
        'jira_key': 'OPS-1', 'jira_id': '1', 'jira_url': 'https://example.atlassian.net/browse/OPS-1'})
    monkeypatch.setattr('backend.integrations.router.deliver', lambda *args: {
        'slack_status': 'DELIVERED', 'slack_message_id': '123.4', 'slack_message_ts': '123.4', 'slack_channel_id': 'C123'})
    with TestClient(main.app) as api:
        response = api.post('/api/telemetry', json={
            'device_id': 'SIM-NOTIFICATION', 'source_kind': 'simulator',
            'observed_at': datetime.now(timezone.utc).isoformat(), 'sequence': 1,
            'temperature_c': 29.4, 'humidity_pct': 54, 'cooling_fault': True,
        })
        iid = response.json()['incident_id']
        router_app = FastAPI()
        router_app.include_router(create_notification_router(
            {}, main._lock, tmp_path / 'ledger.sqlite3', get_snapshot=main.get_incident_snapshot,
            publish_result=main.publish_notification,
        ))
        with TestClient(router_app) as notifications:
            result = notifications.post(f'/api/incidents/{iid}/notify')
            assert result.status_code == 200, result.text
            assert result.json()['notification_status'] == 'DELIVERED'
            current = store.incidents.find_one({'_id': iid})
            assert current['integrations']['jira_key'] == 'OPS-1'
            assert current['integrations']['slack_status'] == 'DELIVERED'
            assert store.events.count_documents({'kind': 'notification'}) == 2
            assert notifications.post(f'/api/incidents/{iid}/notify').status_code == 200
            assert store.events.count_documents({'kind': 'notification'}) == 2
        before = main.get_incident_snapshot(iid)
        with pytest.raises(HTTPException) as error:
            main.publish_notification(iid, 'wrong-incarnation', {'jira_key': 'WRONG'})
        assert error.value.status_code == 409
        assert main.get_incident_snapshot(iid) == before
        main.publish_notification(iid, before['created_at'], {'slack_status': 'FAILED', 'approval': {'version': 99}})
        assert main.get_incident_snapshot(iid)['integrations']['slack_status'] == 'DELIVERED'
        assert 'approval' not in main.get_incident_snapshot(iid)
