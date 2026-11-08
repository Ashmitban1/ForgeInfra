"""Explicit local UI acceptance server: scripted providers, disposable storage.

Run: PYTHONPATH=.:tests .venv/bin/python -m uvicorn ui_backend:app --port 8002
All provider functions below are test doubles. No cloud credentials are used.
"""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import tempfile

for key in ('MONGODB_URI', 'TIGERDATA_DATABASE_URL', 'NVIDIA_API_KEY', 'GEMINI_API_KEY',
            'JIRA_API_TOKEN', 'SLACK_BOT_TOKEN', 'SLACK_CHANNEL_ID'):
    os.environ[key] = ''

from fastapi import Response
import mongomock
from backend.integrations import router as notifications

temporary = tempfile.TemporaryDirectory(prefix='factoryos-ui-acceptance-')
root = Path(temporary.name)
original_router = notifications.create_notification_router
notifications.create_notification_router = lambda *args, **kwargs: original_router(
    *args, **kwargs, ledger_path=root / 'notifications.sqlite3')

from backend import main, legacy_runtime
from backend import app as application
from backend.modernization import app as services
from backend.modernization.approval_auth import token_digest
from backend.storage.mongo import MongoIncidentStore
from backend.schemas.incident import TelemetryEvent
from backend.agents import tools as agent_tools
from backend.agents.nemotron import NemotronConfig
from backend.agents.gemini import GeminiConfig


def helper(name, relative):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parent / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

agents = helper('ui_scripted_agents', 'agents/conftest.py')
proof = helper('ui_scripted_approval', 'modernization/test_approval_api.py')
client = mongomock.MongoClient()
main.store_from_environment = lambda: MongoIncidentStore(client, 'ui_acceptance')
counts = {'nvidia_clients': 0, 'jira': 0, 'slack': 0}


class TelemetryStore:
    def __init__(self): self.rows = []
    def initialize(self): pass
    def queue_host(self, metrics): pass
    def queue_arduino(self, receipt):
        hw = receipt['hardware']
        self.rows.append({'event_id': str(hw['sequence']), 'observed_at': hw['observed_at'],
                          'received_at': hw['received_at'], 'status': 'OK', 'payload': receipt})
    def flush(self): return True
    def health(self): return {'backend': 'tigerdata', 'status': 'OK', 'pending_samples': 0, 'error': None}
    def sources(self):
        return [{'source_kind': 'simulator', 'source_id': 'RACK-UI', 'latest': self.rows[-1]['payload']}] if self.rows else []
    def history(self, kind, source, start, end, limit): return self.rows[-limit:] if source == 'RACK-UI' else []
    def summary(self, kind, source, start, end, bucket):
        return [{'sample_count': len(self.rows), 'temperature_c_avg': 29.4,
                 'fault_count': sum(row['payload']['hardware']['cooling_fault'] for row in self.rows)}]

telemetry = TelemetryStore()
main.tiger_from_environment = lambda: telemetry
os.environ['FACTORYOS_APPROVERS_JSON'] = json.dumps({'alice': token_digest(proof.ALICE_TOKEN)})
services.service.output_root = root / 'repairs'
services.investigation_service.output_root = root / 'investigations'
services.review_service.output_root = root / 'reviews'


def provider(config):
    counts['nvidia_clients'] += 1
    return agents.ScriptedClient(config, 'patch')

services.investigation_service.client_factory = provider
services.investigation_service.config_factory = lambda: NemotronConfig(api_key='scripted-ui-nvidia-key', max_rounds=4, max_tool_calls=6)
services.review_service.client_factory = proof.ScriptedReviewer
services.review_service.config_factory = lambda: GeminiConfig(api_key='scripted-ui-google-key')
agent_tools.execute_incident_repair = proof.scripted_verifier
notifications.configuration = lambda: ('https://example.atlassian.net', 'test@example.test', 'unit-only', 'OPS')


def jira(*args):
    counts['jira'] += 1
    return {'jira_key': 'OPS-UI-1', 'jira_id': '1', 'jira_url': 'https://example.atlassian.net/browse/OPS-UI-1'}


def slack(*args):
    counts['slack'] += 1
    return {'slack_status': 'DELIVERED', 'slack_channel_id': 'C123', 'slack_message_id': '123.4', 'slack_message_ts': '123.4'}

notifications.create_issue = jira
# Use the real Slack ledger with only the final provider operation substituted.
from backend.integrations import slack as slack_module
slack_module.post_message = lambda *args: slack(*args)
os.environ['SLACK_BOT_TOKEN'] = 'scripted-ui-slack-key'
os.environ['SLACK_CHANNEL_ID'] = 'C123'
app = application.app
original_lifespan = app.router.lifespan_context


@asynccontextmanager
async def lifespan(app):
    async with original_lifespan(app):
        for sequence in (1, 2):
            sample = TelemetryEvent(device_id='RACK-UI', source_kind='simulator', sequence=sequence,
                observed_at=datetime.now(timezone.utc)-timedelta(seconds=4-sequence),
                temperature_c=29.4, humidity_pct=54, cooling_fault=True, fault_is_simulated=True)
            main.receive_telemetry(sample, Response())
        main._latest.clear()  # Startup discovery must recover stored sources without inventing live readings.
        yield

app.router.lifespan_context = lifespan


@app.get('/__test__/stats')
def stats():
    return {**counts, 'decisions': sum(len(row.get('approval', {}).get('decisions', [])) for row in main._incidents.values()),
            'incidents': len(main._incidents)}


@app.post('/__test__/monitor-failure')
def monitor_failure():
    def failed(event): raise RuntimeError('scripted test failure')
    legacy_runtime.run_legacy_monitor = failed
    return {'enabled': True}
