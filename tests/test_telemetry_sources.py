"""Persistent source discovery preserves true observations after restart."""
from fastapi.testclient import TestClient
from unittest.mock import Mock

from backend import main
from backend.storage.mongo import StorageUnavailable


def test_source_discovery_works_without_process_latest_readings(monkeypatch):
    sample = {'source_kind': 'arduino_serial', 'source_id': 'RACK-STORED',
              'observed_at': '2026-01-01T00:00:00Z', 'latest': {
                  'device_id': 'RACK-STORED', 'hardware': {'observed_at': '2026-01-01T00:00:00Z',
                                                        'source_kind': 'arduino_serial'}}}
    store = Mock()
    store.sources.return_value = [sample]
    monkeypatch.setitem(main.app.state._state, 'telemetry_store', store)
    monkeypatch.setattr(main, '_latest', {})
    # No lifespan for these controller checks: the injected store is intentional.
    api = TestClient(main.app)
    result = api.get('/api/telemetry/sources')
    assert result.status_code == 200
    assert result.json()['sources'] == [sample]
    assert api.get('/api/telemetry/latest').json() == {'devices': []}
    api.close()


def test_source_discovery_disabled_is_distinct_from_database_failure(monkeypatch):
    monkeypatch.setitem(main.app.state._state, 'telemetry_store', None)
    api = TestClient(main.app)
    assert api.get('/api/telemetry/sources').json() == {'sources': [], 'storage_backend': 'disabled'}
    store = Mock()
    store.sources.side_effect = StorageUnavailable('private connection details')
    monkeypatch.setitem(main.app.state._state, 'telemetry_store', store)
    result = api.get('/api/telemetry/sources')
    assert result.status_code == 503 and 'private' not in result.text
    api.close()
