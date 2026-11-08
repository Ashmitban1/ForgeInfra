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
  assert.match(result.detail, /completion alone/);
});

test('execution failures and active jobs are distinct from absent verification evidence', () => {
  assert.equal(repairVerification({}, null).state, 'unverified');
  assert.equal(repairVerification({ investigation: { tool_calls: [{ name: 'test_candidate', status: 'FAILED' }] } }, null).state, 'failed');
  assert.equal(repairVerification({ investigation: { tool_calls: [{ name: 'test_candidate', status: 'RUNNING' }] } }, null).state, 'running');
});

test('architecture keeps intended model integration and current storage limits explicit', () => {
  assert.equal(phases.length, 5);
  assert.equal(phases[2].status, 'Awaiting integration');
  assert.match(phases[1].note, /in memory/);
  assert.match(phases[3].note, /manually authored/);
  assert.match(phases[4].note, /without waiting/);
});
