from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
import requests

from backend.integrations.router import create_notification_router


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.delenv('SLACK_BOT_TOKEN', raising=False)
    monkeypatch.delenv('SLACK_CHANNEL_ID', raising=False)
    for name, value in {'JIRA_BASE_URL': 'https://example.atlassian.net',
                        'JIRA_EMAIL': 'test@example.com', 'JIRA_API_TOKEN': 'secret-test-token',
                        'JIRA_PROJECT_KEY': 'KAN'}.items():
        monkeypatch.setenv(name, value)
    incident = {'incident_id': 'INC-TEST', 'device_id': 'RACK-TEST',
                'created_at': datetime.now(timezone.utc).isoformat(), 'updated_at': 'now',
                'severity': 'HIGH', 'hardware': {'temperature_c': 29.4, 'humidity_pct': 54,
                'fault_is_simulated': True, 'source_kind': 'simulator'},
                'reliability': {'reasons': ['legacy_missed_fault']},
                'integrations': {'jira_key': None, 'jira_url': None}}
    records = {'INC-TEST': incident}
    app = FastAPI()
    ledger = tmp_path / 'ledger.sqlite3'
    app.include_router(create_notification_router(records, Lock(), ledger))
    post = Mock(return_value=Mock(status_code=201, json=lambda: {'key': 'KAN-3', 'id': '10003'}))
    monkeypatch.setattr('backend.integrations.jira.requests.post', post)
    return TestClient(app), records, post, ledger


def notify(client):
    return client.post('/api/incidents/INC-TEST/notify')


def test_success_and_retry(setup):
    client, records, post, _ = setup
    response = notify(client)
    assert response.status_code == 200
    assert response.json()['jira_key'] == 'KAN-3'
    assert response.json()['jira_url'] == 'https://example.atlassian.net/browse/KAN-3'
    assert records['INC-TEST']['integrations']['jira_id'] == '10003'
    fields = post.call_args.kwargs['json']['fields']
    assert fields['project']['key'] == 'KAN'
    assert fields['issuetype']['name'] == 'Task'
    assert fields['description']['type'] == 'doc'
    assert 'fault_is_simulated: True' in str(fields)
    assert notify(client).json()['already_exists'] is True
    post.assert_called_once()


def test_existing_issue(setup):
    client, records, post, _ = setup
    records['INC-TEST']['integrations'].update(jira_key='KAN-9', jira_id='9', jira_url='https://example.atlassian.net/browse/KAN-9')
    assert notify(client).json()['jira_key'] == 'KAN-9'
    post.assert_not_called()


def test_missing_incident(setup):
    client, _, post, _ = setup
    assert client.post('/api/incidents/missing/notify').status_code == 404
    post.assert_not_called()


def test_missing_credentials(setup, monkeypatch):
    client, _, post, _ = setup
    monkeypatch.delenv('JIRA_API_TOKEN')
    response = notify(client)
    assert response.status_code == 503
    assert 'JIRA_API_TOKEN' in response.json()['detail']
    post.assert_not_called()


@pytest.mark.parametrize('status', [400, 401, 403, 404, 422, 429])
def test_explicit_rejection_can_retry(setup, status):
    client, _, post, _ = setup
    post.return_value.status_code = status
    response = notify(client)
    assert response.status_code in (502, 503)
    assert 'secret-test-token' not in response.text
    post.return_value.status_code = 201
    assert notify(client).status_code == 200
    assert notify(client).json()['already_exists'] is True
    assert post.call_count == 2


@pytest.mark.parametrize('failure', [requests.Timeout(), requests.ConnectionError()])
def test_uncertain_network_failure_blocks_retry(setup, failure):
    client, _, post, _ = setup
    post.side_effect = failure
    assert notify(client).status_code == 502
    assert notify(client).status_code == 409
    post.assert_called_once()


@pytest.mark.parametrize('status, body', [(500, {}), (201, {}), (201, {'key': 'evil', 'id': '3'})])
def test_uncertain_confirmation_blocks_retry(setup, status, body):
    client, _, post, _ = setup
    post.return_value = Mock(status_code=status, json=lambda: body)
    assert notify(client).status_code == 502
    assert notify(client).status_code == 409
    post.assert_called_once()


def test_ledger_survives_router_recreation(setup):
    client, records, post, ledger = setup
    assert notify(client).status_code == 200
    records['INC-TEST']['integrations'] = {}
    app = FastAPI()
    app.include_router(create_notification_router(records, Lock(), ledger))
    assert notify(TestClient(app)).json()['already_exists'] is True
    post.assert_called_once()


def test_concurrent_requests_do_not_duplicate(setup):
    client, _, post, _ = setup
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: notify(client), range(2)))
    assert all(r.status_code in (200, 409) for r in responses)
    post.assert_called_once()


def test_capability_is_available_without_exposing_configuration(setup):
    client, _, post, _ = setup
    response = client.get('/api/integrations/capabilities')
    assert response.json() == {'jira': {'notify': True}, 'slack': {'notify': True}}
    post.assert_not_called()


def test_existing_reference_works_without_credentials(setup, monkeypatch):
    client, records, post, _ = setup
    records['INC-TEST']['integrations'].update(
        jira_key='KAN-9', jira_id='9', jira_url='https://example.atlassian.net/browse/KAN-9')
    monkeypatch.delenv('JIRA_API_TOKEN')
    assert notify(client).json()['already_exists'] is True
    post.assert_not_called()


@pytest.mark.parametrize('base', ['http://example.atlassian.net', 'https://[invalid',
                                  'https://example.atlassian.net.evil.com',
                                  'https://example.atlassian.net:abc'])
def test_invalid_base_url_is_actionable(setup, monkeypatch, base):
    client, _, post, _ = setup
    monkeypatch.setenv('JIRA_BASE_URL', base)
    assert notify(client).status_code == 503
    post.assert_not_called()
