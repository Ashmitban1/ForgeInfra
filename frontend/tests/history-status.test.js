import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readingOf, mergeReadings, rackSources } from '../src/lib/history.js';
import { deviceHealth, pathSteps, repairVerification, classifyStatus } from '../src/lib/health.js';
const now = Date.parse('2026-11-08T12:00:00Z');
function sample(at, sequence = 1, mismatch = true) {
  return { device_id: 'RACK-1', hardware: { source_kind: 'arduino_serial', sequence, observed_at: at,
    received_at: '2026-11-08T12:00:00Z', temperature_c: 29.4, cooling_fault: true, fault_is_simulated: true },
  legacy_monitor: { status: mismatch === null ? 'UNKNOWN' : 'NORMAL' }, expected_status: 'WARNING', reliability: { mismatch, reasons: [] } };
}
test('stored/live samples deduplicate without changing observation times or null comparison', () => {
  const old = readingOf(sample('2026-11-08T11:59:00Z', 1, null), 'stored-id');
  const fresh = readingOf(sample('2026-11-08T12:00:00Z', 2));
  const merged = mergeReadings([fresh], [old, fresh]);
  assert.equal(merged.length, 2); assert.equal(merged[0].event_id, 'stored-id');
  assert.equal(merged[0].mismatch, null); assert.equal(merged[0].at, '2026-11-08T11:59:00Z');
});
test('restart discovery chooses newest stored source and excludes host metrics', () => {
  const recent = sample('2026-11-08T11:59:00Z');
  const old = sample('2026-11-08T11:00:00Z'); old.hardware.source_kind = 'simulator';
  const racks = rackSources([], [], [{ source_kind: 'arduino_serial', latest: recent }, { source_kind: 'simulator', latest: old }, { source_kind: 'host_system', latest: { device_id: 'host' } }]);
  assert.equal(racks.length, 1); assert.equal(racks[0].hardware.source_kind, 'arduino_serial'); assert.equal(racks[0].historical, true);
});
test('old observation stays stale despite recent receipt; unknown monitor has no comparison', () => {
  assert.equal(deviceHealth(sample('2026-11-08T11:00:00Z'), now).stale, true);
  assert.equal(deviceHealth(sample('2026-11-08T12:01:00Z'), now).stale, true);
  const unknown = deviceHealth(sample('2026-11-08T12:00:00Z', 1, null), now);
  assert.equal(unknown.mismatch, null); assert.equal(unknown.comparisonAvailable, false);
});
test('human and notification progress use current server state, not AI approval placeholders', () => {
  const incident = { investigation: { status: 'COMPLETED', approval_status: 'PENDING' }, integrations: { jira_key: 'OPS-1', slack_status: 'FAILED' } };
  const steps = pathSteps(incident, { approval: { status: 'APPROVED' }, decision_review: { status: 'STALE' } });
  assert.equal(steps.find(s => s.id === 'approval').state, 'done');
  assert.equal(steps.find(s => s.id === 'gemini').state, 'review');
  assert.equal(steps.find(s => s.id === 'notify').state, 'review');
  assert.equal(classifyStatus('QUEUED'), 'pending'); assert.equal(classifyStatus('INTERRUPTED'), 'failed');
});
test('tool success cannot establish a verified software candidate', () => {
  const incident = { investigation: { status: 'COMPLETED', tool_calls: [{ tool: 'verify_monitor_patch', status: 'SUCCESS' }] } };
  assert.equal(repairVerification(incident, null).state, 'unverified');
  const candidate = { verification_status: 'VERIFIED', tests: { original: { failed: 1 }, candidate: { passed: 5, failed: 0, exit_code: 0 } }, replay: { detection_gap_fixed: true } };
  assert.equal(repairVerification(incident, null, candidate).state, 'verified');
  candidate.replay = null;
  assert.notEqual(repairVerification(incident, null, candidate).state, 'verified');
});
