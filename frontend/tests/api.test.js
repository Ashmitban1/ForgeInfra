import { test, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { submitInvestigation, decideApproval, getInvestigationPatch, getTelemetryHistory, getIncidentHistory, request, ApiError } from '../src/api.js';
const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; delete globalThis.window; });
test('submits one investigation with escaped identity and stable retry key', async () => {
  let call;
  globalThis.fetch = async (...args) => { call = args; return new Response(JSON.stringify({ job_id: 'investigation-job-1', status: 'QUEUED' }), { status: 202 }); };
  const result = await submitInvestigation('INC /1', { idempotencyKey: 'action-1' });
  assert.equal(result.job_id, 'investigation-job-1');
  assert.ok(call[0].endsWith('/api/incidents/INC%20%2F1/investigate'));
  assert.equal(call[1].method, 'POST');
  assert.equal(call[1].headers['Idempotency-Key'], 'action-1');
});
test('approval sends reviewer authorization and exact package without client identity', async () => {
  let options;
  globalThis.fetch = async (url, init) => { options = init; return new Response('{"status":"APPROVED"}'); };
  const body = { decision: 'APPROVE', package_revision: 'sha256:package', candidate_revision: 'sha256:candidate', comment: 'Reviewed' };
  await decideApproval('INC-1', body, { token: 'unit-reviewer', idempotencyKey: 'approval-1' });
  assert.equal(options.headers.Authorization, 'Bearer unit-reviewer');
  assert.deepEqual(JSON.parse(options.body), body);
});
test('structured conflicts retain blocking reasons and validation errors are readable', async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: { message: 'Package changed', reasons: ['stale'] } }), { status: 409 });
  await assert.rejects(request('/test'), error => error instanceof ApiError && error.message === 'Package changed' && error.reasons[0] === 'stale');
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: [{ loc: ['body', 'decision'], msg: 'Invalid' }] }), { status: 422 });
  await assert.rejects(request('/test'), /body.decision: Invalid/);
});
test('plain text diff does not require JSON; history translates source parameters', async () => {
  globalThis.fetch = async url => url.includes('/patch') ? new Response('--- original\n+++ candidate') : new Response('{"samples":[]}');
  assert.equal(await getInvestigationPatch('job-1'), '--- original\n+++ candidate');
  let url;
  globalThis.fetch = async path => { url = path; return new Response('{"samples":[]}'); };
  await getTelemetryHistory({ sourceKind: 'arduino_serial', sourceId: 'RACK-01', limit: 5 });
  assert.ok(url.includes('source_kind=arduino_serial&source_id=RACK-01'));
});
test('demo mutations never invoke the backend; aborts remain aborts', async () => {
  globalThis.window = { localStorage: { getItem: () => '1' } };
  globalThis.fetch = async () => { throw new Error('must not call'); };
  await assert.rejects(submitInvestigation('DEMO'), error => error.kind === 'demo');
  assert.deepEqual(await getIncidentHistory('DEMO'), []);
  delete globalThis.window;
  globalThis.fetch = async () => { throw new DOMException('Aborted', 'AbortError'); };
  await assert.rejects(request('/test'), error => error.name === 'AbortError');
});
