import test from 'node:test';
import assert from 'node:assert/strict';
import { parseRoute, missionHref, workspaceHref, investigateHref } from '../src/router.js';
import { repairVerification } from '../src/lib/health.js';
import { phases, personas } from '../src/components/landing/content.js';

test('bare entry and product anchors open overview; original operational URLs survive', () => {
  assert.equal(parseRoute('').name, 'landing');
  assert.deepEqual(parseRoute('#architecture'), { name: 'landing', section: 'architecture' });
  assert.equal(parseRoute('#/').name, 'mission');
  assert.equal(parseRoute('#/mission').name, 'mission');
  assert.deepEqual(parseRoute('#/investigate/INC%2FA'), { name: 'investigate', incidentId: 'INC/A' });
});

test('all persona routes map to actual operational workspaces with shared incident IDs', () => {
  for (const persona of personas) {
    const route = parseRoute(workspaceHref(persona.route, 'INC-002'));
    assert.equal(route.name, persona.route);
    if (['engineering', 'investigate'].includes(persona.route)) assert.equal(route.incidentId, 'INC-002');
  }
  assert.equal(parseRoute(missionHref).name, 'mission');
  assert.equal(parseRoute(investigateHref('INC-002')).incidentId, 'INC-002');
});

test('finished test tools and nominal telemetry cannot establish repair verification', () => {
  const incident = { investigation: { tool_calls: [{ name: 'run_regression_tests', status: 'SUCCESS' }] } };
  const result = repairVerification(incident, { stale: false, level: 'nominal' });
  assert.equal(result.state, 'unverified');
  assert.equal(result.liveNominal, true);
  assert.equal(result.tests.length, 0, 'Tool completion supplies no candidate acceptance results');
});

test('verification uses candidate evidence and investigation state, not tool-call labels', () => {
  assert.equal(repairVerification({}, null).state, 'unverified');
  assert.equal(repairVerification({ investigation: { tool_calls: [{ name: 'test_candidate', status: 'FAILED' }] } }, null).state, 'unverified');
  assert.equal(repairVerification({ investigation: { status: 'RUNNING' } }, null).state, 'running');
  const incomplete = { verification_status: 'FAILED', tests: { candidate: { failed: 1 } } };
  assert.equal(repairVerification({}, null, incomplete).state, 'failed');
});

test('architecture reflects connected APIs without claiming production code or deployment', () => {
  assert.equal(phases.length, 5);
  assert.equal(phases[2].status, 'Connected through backend APIs');
  assert.match(phases[1].note, /not Northmark/);
  assert.match(phases[3].note, /manually authored/);
  assert.match(phases[4].note, /without waiting/);
});
