import { ageSince } from './format.js';

// Mirrors STALE_AFTER_SECONDS in backend/reliability.py. Used only to flag when the dashboard
// has not received a reading recently; it does not change any backend decision.
export const STALE_AFTER_SECONDS = 90;

export const STATE_META = {
  fault: { label: 'Fault', icon: '▲', tone: 'fault' },
  review: { label: 'Needs review', icon: '◆', tone: 'review' },
  nominal: { label: 'Nominal', icon: '●', tone: 'ok' },
  recovered: { label: 'Recovered', icon: '✔', tone: 'ok' },
  stale: { label: 'No recent data', icon: '○', tone: 'muted' },
};

export const REASON_LABELS = {
  legacy_missed_fault: 'Legacy monitor reported a different status than the independent check (it missed a fault).',
  stale_hardware_reading: `Hardware reading was older than ${STALE_AFTER_SECONDS}s when the API received it.`,
  future_observation_timestamp: 'Hardware observation timestamp was in the future.',
};

export function deviceHealth(device, nowMs, deviceHistory = []) {
  const hw = device?.hardware ?? {};
  const ageSeconds = ageSince(hw.received_at, nowMs);
  const stale = ageSeconds === null || ageSeconds > STALE_AFTER_SECONDS;
  const reasons = device?.reliability?.reasons ?? [];
  const fault = hw.cooling_fault === true || device?.expected_status === 'WARNING';
  const review = !fault && (device?.reliability?.mismatch === true || reasons.length > 0);
  const level = fault ? 'fault' : review ? 'review' : 'nominal';
  const faultedEarlier = deviceHistory.some(r => r.cooling_fault || r.expected_status === 'WARNING');
  const state = stale ? 'stale' : level === 'nominal' && faultedEarlier ? 'recovered' : level;
  return { state, level, stale, ageSeconds, mismatch: device?.reliability?.mismatch === true };
}

const DONE = new Set(['COMPLETE', 'COMPLETED', 'DONE', 'SUCCESS', 'SUCCEEDED', 'FINISHED']);
const FAILED = new Set(['FAILED', 'ERROR', 'TIMEOUT', 'TIMED_OUT']);
const RUNNING = new Set(['RUNNING', 'IN_PROGRESS', 'STARTED']);

// The v1 contract only defines PENDING. Anything else is shown verbatim and classified conservatively.
export function classifyStatus(status) {
  const s = String(status ?? '').trim().toUpperCase();
  if (!s) return 'unknown';
  if (s === 'PENDING') return 'pending';
  if (DONE.has(s)) return 'done';
  if (FAILED.has(s)) return 'failed';
  if (RUNNING.has(s)) return 'active';
  return 'unknown';
}

export function pathSteps(incident) {
  const integrations = incident?.integrations ?? {};
  const hasTicket = Boolean(integrations.jira_key || integrations.slack_message_id);
  return [
    {
      id: 'detected',
      label: 'Detected',
      state: 'done',
      detail: 'Incident record exists in the API.',
    },
    {
      id: 'nemotron',
      label: 'Nemotron investigation',
      state: classifyStatus(incident?.investigation?.status),
      detail: `investigation.status = ${incident?.investigation?.status ?? 'missing'}`,
    },
    {
      id: 'gemini',
      label: 'Gemini review',
      state: classifyStatus(incident?.decision_review?.status),
      detail: `decision_review.status = ${incident?.decision_review?.status ?? 'missing'}`,
    },
    {
      id: 'approval',
      label: 'Human approval',
      state: 'unavailable',
      detail: 'Approval route is not implemented in API v1.',
    },
    {
      id: 'notify',
      label: 'Jira / Slack',
      state: hasTicket ? 'done' : 'pending',
      detail: hasTicket ? 'At least one provider ID is recorded.' : 'No Jira key or Slack message ID recorded.',
    },
  ];
}

export function describeToolCall(call, index) {
  if (typeof call === 'string') return { name: call, status: null, at: null, raw: null };
  if (call && typeof call === 'object') {
    const name = call.name ?? call.tool ?? call.tool_name ?? call.function ?? `Tool call ${index + 1}`;
    return {
      name: String(name),
      status: call.status ?? null,
      at: call.called_at ?? call.started_at ?? call.timestamp ?? null,
      raw: call,
    };
  }
  return { name: String(call), status: null, at: null, raw: null };
}

const TEST_CALL = /test|regress|verif/i;

// API v1 has no per-incident acceptance-test result contract. Tool-call completion
// proves execution only, never test success or a repaired physical system.
export function repairVerification(incident, live) {
  const calls = Array.isArray(incident?.investigation?.tool_calls) ? incident.investigation.tool_calls : [];
  const tests = calls
    .map(describeToolCall)
    .filter(c => TEST_CALL.test(c.name))
    .map(c => ({ name: c.name, status: c.status, kind: classifyStatus(c.status) }));
  const failed = tests.some(t => t.kind === 'failed');
  const running = tests.some(t => t.kind === 'active');
  const liveNominal = Boolean(live) && !live.stale && live.level === 'nominal';
  let state = 'unverified';
  let detail = 'No per-incident acceptance-test evidence is available. Repair verification is not connected in API v1.';
  if (failed) {
    state = 'failed';
    detail = 'A verification tool execution failed. No repair success is inferred.';
  } else if (running) {
    state = 'running';
    detail = 'A verification tool execution is running. Test outcomes are not yet established.';
  } else if (tests.some(t => t.kind === 'done')) {
    detail = 'A test tool finished, but completion alone does not establish passing acceptance tests. Repair remains unverified.';
  }
  return { state, detail, tests, liveNominal };
}

export function describeFinding(finding) {
  if (typeof finding === 'string') return { text: finding, raw: null };
  if (finding && typeof finding === 'object') {
    const text = finding.summary ?? finding.title ?? finding.description ?? finding.message ?? null;
    return { text: typeof text === 'string' ? text : null, raw: finding };
  }
  return { text: String(finding), raw: null };
}
