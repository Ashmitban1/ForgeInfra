from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
import requests

from test_jira import setup, notify
from backend.integrations.router import create_notification_router


@pytest.fixture
def slack_setup(setup, monkeypatch):
    client, records, _, ledger = setup
    monkeypatch.setenv('SLACK_BOT_TOKEN', 'test-slack-secret')
    monkeypatch.setenv('SLACK_CHANNEL_ID', 'C123456')
    jira = Mock(return_value={'jira_key': 'KAN-3', 'jira_id': '10003',
                             'jira_url': 'https://example.atlassian.net/browse/KAN-3'})
    monkeypatch.setattr('backend.integrations.router.create_issue', jira)
    post = Mock(return_value=Mock(status_code=200, json=lambda: {
        'ok': True, 'channel': 'C123456', 'ts': '1794107859.146339'}))
    monkeypatch.setattr('backend.integrations.slack.requests.post', post)
    return client, records, jira, post, ledger


def test_delivery_and_retry(slack_setup):
    client, records, jira, post, _ = slack_setup
    response = notify(client)
    assert response.status_code == 200
    body = response.json()
    assert body['notification_status'] == 'DELIVERED'
    assert body['slack_channel_id'] == 'C123456'
    assert body['slack_message_ts'] == '1794107859.146339'
    assert body['integrations']['slack_status'] == 'DELIVERED'
    text = post.call_args.kwargs['json']['text']
    for value in ('INC-TEST', 'RACK-TEST', 'HIGH', 'Simulated fault: True',
                  'legacy_missed_fault', 'https://example.atlassian.net/browse/KAN-3', 'Incident created:'):
        assert value in text
    assert post.call_args.kwargs['json']['mrkdwn'] is False
    assert notify(client).json()['slack_already_exists'] is True
    assert records['INC-TEST']['integrations']['slack_message_id'] == body['slack_message_ts']
    jira.assert_called_once()
    post.assert_called_once()


@pytest.mark.parametrize('missing', ['SLACK_BOT_TOKEN', 'SLACK_CHANNEL_ID'])
def test_missing_configuration_retains_jira_and_corrected_retry(slack_setup, monkeypatch, missing):
    client, records, jira, post, _ = slack_setup
    monkeypatch.delenv(missing)
    body = notify(client).json()
    assert body['notification_status'] == 'PARTIAL'
    assert body['slack_status'] == 'NOT_CONFIGURED'
    assert missing in body['slack_error']
    assert records['INC-TEST']['integrations']['jira_key'] == 'KAN-3'
    post.assert_not_called()
    monkeypatch.setenv(missing, 'C123456' if missing == 'SLACK_CHANNEL_ID' else 'test-slack-secret')
    assert notify(client).json()['slack_status'] == 'DELIVERED'
    jira.assert_called_once()
    post.assert_called_once()


@pytest.mark.parametrize('error', ['invalid_auth', 'token_revoked', 'missing_scope',
                                   'channel_not_found', 'not_in_channel', 'is_archived', 'ratelimited'])
def test_provider_rejection_partial_success_and_retry(slack_setup, error):
    client, _, jira, post, _ = slack_setup
    success = post.return_value
    post.return_value = Mock(status_code=200, json=lambda: {'ok': False, 'error': error})
    body = notify(client).json()
    assert body['notification_status'] == 'PARTIAL'
    assert body['slack_status'] == 'FAILED'
    assert 'test-slack-secret' not in str(body)
    post.return_value = success
    assert notify(client).json()['slack_status'] == 'DELIVERED'
    assert notify(client).json()['slack_already_exists'] is True
    jira.assert_called_once()
    assert post.call_count == 2


@pytest.mark.parametrize('failure', [requests.Timeout(), requests.ConnectionError()])
def test_ambiguous_network_not_retried(slack_setup, failure):
    client, _, jira, post, _ = slack_setup
    post.side_effect = failure
    assert notify(client).json()['slack_status'] == 'UNCONFIRMED'
    assert notify(client).json()['slack_status'] == 'UNCONFIRMED'
    post.assert_called_once()
    jira.assert_called_once()


@pytest.mark.parametrize('status, body', [(500, {}), (200, {}), (200, []),
    (200, {'ok': True, 'channel': 'OTHER', 'ts': '123.4'}),
    (200, {'ok': True, 'channel': 'C123456'}),
    (200, {'ok': False, 'error': 'test-slack-secret'})])
def test_uncertain_response_does_not_retry_or_leak(slack_setup, status, body):
    client, _, _, post, _ = slack_setup
    post.return_value = Mock(status_code=status, json=lambda: body)
    response = notify(client)
    assert response.json()['slack_status'] == 'UNCONFIRMED'
    assert 'test-slack-secret' not in response.text
    assert notify(client).json()['slack_status'] == 'UNCONFIRMED'
    post.assert_called_once()


def test_rate_limit_can_retry(slack_setup):
    client, _, jira, post, _ = slack_setup
    success = post.return_value
    post.return_value = Mock(status_code=429)
    assert notify(client).json()['slack_status'] == 'FAILED'
    post.return_value = success
    assert notify(client).json()['slack_status'] == 'DELIVERED'
    jira.assert_called_once()


def test_ledger_rehydrates_delivery(slack_setup):
    client, records, jira, post, ledger = slack_setup
    assert notify(client).json()['slack_status'] == 'DELIVERED'
    records['INC-TEST']['integrations'] = {}
    app = FastAPI()
    from threading import Lock
    app.include_router(create_notification_router(records, Lock(), ledger))
    assert notify(TestClient(app)).json()['slack_already_exists'] is True
    post.assert_called_once()
    jira.assert_called_once()


def test_concurrent_delivery_reserves_once(slack_setup):
    client, _, jira, post, _ = slack_setup
    entered, finish = Event(), Event()
    success = post.return_value
    def wait_for_other(*args, **kwargs):
        entered.set()
        assert finish.wait(5)
        return success
    post.side_effect = wait_for_other
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(notify, client)
        assert entered.wait(5)
        second = notify(client)
        assert second.json()['slack_status'] == 'PENDING'
        finish.set()
        assert first.result().json()['slack_status'] == 'DELIVERED'
    assert notify(client).json()['slack_status'] == 'DELIVERED'
    post.assert_called_once()
    jira.assert_called_once()


def test_jira_failure_never_sends_slack(slack_setup):
    from fastapi import HTTPException
    client, _, jira, post, _ = slack_setup
    jira.side_effect = HTTPException(502, 'Jira authentication failed.')
    assert notify(client).status_code == 502
    post.assert_not_called()


def test_invalid_channel_configuration(slack_setup, monkeypatch):
    client, _, jira, post, _ = slack_setup
    monkeypatch.setenv('SLACK_CHANNEL_ID', '#factoryos-incidents')
    body = notify(client).json()
    assert body['slack_status'] == 'NOT_CONFIGURED'
    assert body['jira_key'] == 'KAN-3'
    post.assert_not_called()
    jira.assert_called_once()


def test_invalid_json_confirmation(slack_setup):
    client, _, _, post, _ = slack_setup
    post.return_value.json = Mock(side_effect=ValueError())
    assert notify(client).json()['slack_status'] == 'UNCONFIRMED'
    assert notify(client).json()['slack_status'] == 'UNCONFIRMED'
    post.assert_called_once()


def test_uncertain_delivery_survives_recreation(slack_setup):
    from threading import Lock
    client, records, jira, post, ledger = slack_setup
    post.side_effect = requests.Timeout()
    assert notify(client).json()['slack_status'] == 'UNCONFIRMED'
    records['INC-TEST']['integrations'] = {}
    app = FastAPI()
    app.include_router(create_notification_router(records, Lock(), ledger))
    assert notify(TestClient(app)).json()['slack_status'] == 'UNCONFIRMED'
    jira.assert_called_once()
    post.assert_called_once()


def test_get_incident_exposes_real_delivery(slack_setup):
    client, records, _, _, _ = slack_setup
    # Same storage injection used by P1's GET route, without touching P1's source.
    @client.app.get('/api/incidents/{incident_id}')
    def get_incident(incident_id: str):
        return records[incident_id]
    assert notify(client).json()['slack_status'] == 'DELIVERED'
    integrations = client.get('/api/incidents/INC-TEST').json()['integrations']
    assert integrations['slack_channel_id'] == 'C123456'
    assert integrations['slack_message_ts'] == '1794107859.146339'
    assert integrations['slack_status'] == 'DELIVERED'
