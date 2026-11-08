"""Slack delivery with a durable reservation; ambiguous attempts require reconciliation."""
import json
import os
import re
import sqlite3

import requests


class SlackFailure(Exception):
    def __init__(self, message: str, uncertain: bool = False):
        self.message = message
        self.uncertain = uncertain


def post_message(incident: dict, jira: dict, token: str, channel: str) -> dict:
    hardware = incident.get('hardware', {})
    evidence = incident.get('reliability', {})
    # Disable mrkdwn parsing so device IDs/evidence cannot trigger mentions.
    text = '\n'.join([
        f'FactoryOS incident {incident["incident_id"]}',
        f'Device / rack: {incident["device_id"]}',
        f'Severity: {incident.get("severity", "unknown")}',
        f'Incident created: {incident.get("created_at")}',
        f'Observed: {hardware.get("observed_at")}',
        f'Temperature C: {hardware.get("temperature_c")}; humidity %: {hardware.get("humidity_pct")}',
        f'Cooling fault: {hardware.get("cooling_fault")}',
        f'Simulated fault: {hardware.get("fault_is_simulated", "unknown")}; source: {hardware.get("source_kind", "unknown")}',
        f'Reliability mismatch: {evidence.get("mismatch", "unknown")}',
        'Mismatch evidence: ' + ', '.join(evidence.get('reasons', [])),
        f'Jira: {jira["jira_url"]}',
    ])
    try:
        response = requests.post('https://slack.com/api/chat.postMessage',
                                 headers={'Authorization': 'Bearer ' + token},
                                 json={'channel': channel, 'text': text, 'mrkdwn': False,
                                       'parse': 'none', 'unfurl_links': False, 'unfurl_media': False},
                                 timeout=(5, 20), allow_redirects=False)
    except requests.RequestException:
        raise SlackFailure('Slack network failure; delivery is unconfirmed. Reconcile before retrying.', True) from None
    if response.status_code == 429:
        raise SlackFailure('Slack rate limited the request. Wait before retrying.')
    if response.status_code != 200:
        raise SlackFailure('Slack did not confirm delivery. Reconcile before retrying.', True)
    try:
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError()
    except ValueError:
        raise SlackFailure('Slack returned an invalid response. Reconcile before retrying.', True) from None
    if body.get('ok') is not True:
        # Only known explicit rejections permit another attempt. Never echo arbitrary errors.
        fixes = {
            'invalid_auth': 'Check SLACK_BOT_TOKEN and reinstall the app if needed.',
            'not_authed': 'Configure SLACK_BOT_TOKEN.',
            'token_revoked': 'Replace the revoked SLACK_BOT_TOKEN.',
            'account_inactive': 'Restore the bot account or reinstall the app.',
            'missing_scope': 'Grant chat:write and reinstall the Slack app.',
            'not_in_channel': 'Invite the bot to the configured channel.',
            'channel_not_found': 'Check SLACK_CHANNEL_ID and bot channel access.',
            'is_archived': 'Choose an active Slack channel.',
            'restricted_action': 'Check workspace restrictions on bot posting.',
            'no_permission': 'Check bot posting permissions in the channel.',
            'ratelimited': 'Wait for Slack rate limits before retrying.',
            'msg_too_long': 'Shorten incident evidence before retrying.',
        }
        error = body.get('error')
        fix = fixes.get(error) if isinstance(error, str) else None
        if fix:
            raise SlackFailure('Slack rejected delivery: ' + fix)
        raise SlackFailure('Slack returned an unconfirmed outcome. Reconcile before retrying.', True)
    ts = body.get('ts')
    if body.get('channel') != channel or not isinstance(ts, str) or not re.fullmatch(r'\d+\.\d+', ts):
        raise SlackFailure('Slack confirmation lacks a valid channel/timestamp. Reconcile before retrying.', True)
    return {'slack_status': 'DELIVERED', 'slack_channel_id': channel,
            'slack_message_ts': ts, 'slack_message_id': ts, 'slack_error': None}


def deliver(incident: dict, jira: dict, ledger_path) -> dict:
    identity = json.dumps([incident['incident_id'], incident['created_at'], jira['jira_url']])
    with sqlite3.connect(ledger_path, timeout=30) as db:
        db.execute('CREATE TABLE IF NOT EXISTS slack_attempts (identity TEXT PRIMARY KEY, result TEXT NOT NULL)')
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT result FROM slack_attempts WHERE identity=?', (identity,)).fetchone()
        if row:
            previous = json.loads(row[0])
            if previous['slack_status'] in ('DELIVERED', 'PENDING', 'UNCONFIRMED'):
                return {**previous, 'slack_already_exists': previous['slack_status'] == 'DELIVERED'}
        reference = incident.get('integrations', {})
        if reference.get('slack_message_id') or reference.get('slack_message_ts'):
            result = {key: reference.get(key) for key in
                      ('slack_channel_id', 'slack_message_ts', 'slack_message_id')}
            if not result['slack_message_ts']:
                result['slack_message_ts'] = result['slack_message_id']
            result.update(slack_status='DELIVERED' if result['slack_channel_id'] else 'UNCONFIRMED',
                          slack_error=None if result['slack_channel_id'] else 'Existing Slack reference lacks channel; reconcile before retrying.')
            db.execute('INSERT OR REPLACE INTO slack_attempts VALUES (?, ?)', (identity, json.dumps(result)))
            db.commit()
            return {**result, 'slack_already_exists': result['slack_status'] == 'DELIVERED'}
        token = os.getenv('SLACK_BOT_TOKEN', '').strip()
        channel = os.getenv('SLACK_CHANNEL_ID', '').strip()
        missing = [name for name, value in [('SLACK_BOT_TOKEN', token), ('SLACK_CHANNEL_ID', channel)] if not value]
        if missing:
            return {'slack_status': 'NOT_CONFIGURED', 'slack_error': 'Configure backend variables: ' + ', '.join(missing),
                    'slack_already_exists': False}
        if not re.fullmatch(r'[CG][A-Z0-9]+', channel):
            return {'slack_status': 'NOT_CONFIGURED', 'slack_error': 'SLACK_CHANNEL_ID must be a channel ID, not a name or URL.',
                    'slack_already_exists': False}
        pending = {'slack_status': 'PENDING', 'slack_channel_id': channel,
                   'slack_error': 'Slack delivery pending or interrupted. Reconcile before retrying.'}
        db.execute('INSERT OR REPLACE INTO slack_attempts VALUES (?, ?)', (identity, json.dumps(pending)))
        db.commit()
        try:
            result = post_message(incident, jira, token, channel)
        except SlackFailure as exc:
            result = {'slack_status': 'UNCONFIRMED' if exc.uncertain else 'FAILED',
                      'slack_channel_id': channel, 'slack_error': exc.message}
        db.execute('UPDATE slack_attempts SET result=? WHERE identity=?', (json.dumps(result), identity))
        db.commit()
        return {**result, 'slack_already_exists': False}
