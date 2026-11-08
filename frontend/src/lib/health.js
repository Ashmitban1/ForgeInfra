
// Mirrors STALE_AFTER_SECONDS in backend/reliability.py. Used only to flag when the dashboard
// has not received a reading recently; it does not change any backend decision.
export const STALE_AFTER_SECONDS = 90;

export const STATE_META = {
  fault: { label: 'Fault', icon: '▲', tone: 'fault' },
  review: { label: 'Needs review', icon: '◆', tone: 'review' },
  nominal: { label: 'Nominal', icon: '●', tone: 'ok' },
  recovered: { label: 'Now nominal', icon: '✔', tone: 'ok' },
  stale: { label: 'No recent data', icon: '○', tone: 'muted' },
};

export const REASON_LABELS = {
  legacy_missed_fault: 'Legacy monitor reported a different status than the independent check (it missed a fault).',
  stale_hardware_reading: `Hardware reading was older than ${STALE_AFTER_SECONDS}s when the API received it.`,
  future_observation_timestamp: 'Hardware observation timestamp was in the future.',
  legacy_monitor_unavailable: 'The legacy monitor could not produce a verified result; comparison is unavailable.',
};

export function deviceHealth(device, nowMs, deviceHistory = []) {
  const hw = device?.hardware ?? {};
  const observed = Date.parse(hw.observed_at);
  const ageSeconds = Number.isFinite(observed) ? (nowMs - observed) / 1000 : null;
  const reasons = device?.reliability?.reasons ?? [];
  const stale = ageSeconds === null || ageSeconds > STALE_AFTER_SECONDS || ageSeconds < -10
    || reasons.includes('stale_hardware_reading') || reasons.includes('future_observation_timestamp');
  const fault = hw.cooling_fault === true || device?.expected_status === 'WARNING';
  const comparisonAvailable = typeof device?.reliability?.mismatch === 'boolean' && device?.legacy_monitor?.status !== 'UNKNOWN';
  const review = !fault && (!comparisonAvailable || device?.reliability?.mismatch === true || reasons.length > 0);
  const level = fault ? 'fault' : review ? 'review' : 'nominal';
  const faultedEarlier = deviceHistory.some(r => r.cooling_fault || r.expected_status === 'WARNING');
  const state = stale ? 'stale' : level === 'nominal' && faultedEarlier ? 'recovered' : level;
  return { state, level, stale, ageSeconds, comparisonAvailable, mismatch: device?.reliability?.mismatch ?? null };
}

const DONE = new Set(['COMPLETE', 'COMPLETED', 'DONE', 'SUCCESS', 'SUCCEEDED', 'FINISHED', 'PASSED', 'APPROVED']);
const FAILED = new Set(['FAILED', 'ERROR', 'TIMEOUT', 'TIMED_OUT', 'INTERRUPTED', 'REJECTED', 'FAILURE']);
const RUNNING = new Set(['RUNNING', 'IN_PROGRESS', 'STARTED']);

// The v1 contract only defines PENDING. Anything else is shown verbatim and classified conservatively.
export function classifyStatus(status) {
  const s = String(status ?? '').trim().toUpperCase();
  if (!s) return 'unknown';
  if (s === 'PENDING' || s === 'QUEUED') return 'pending';
  if (s === 'STALE') return 'review';
  if (DONE.has(s)) return 'done';
  if (FAILED.has(s)) return 'failed';
  if (RUNNING.has(s)) return 'active';
  return 'unknown';
}

export function pathSteps(incident, analysis = {}) {
  const approval = analysis?.approval;
  const review = analysis?.decision_review || incident.decision_review;
  const integrations = incident.integrations || {};
  const notified = Boolean(integrations.jira_key) && integrations.slack_status === 'DELIVERED';
  return [
    { id: 'detected', label: 'Detected', state: 'done', detail: 'Incident exists in the shared backend.' },
    { id: 'nemotron', label: 'Nemotron investigation', state: classifyStatus(incident.investigation?.status), detail: incident.investigation?.status || 'PENDING' },
    { id: 'gemini', label: 'Gemini review', state: classifyStatus(review?.status), detail: review?.status || 'PENDING' },
    { id: 'approval', label: 'Human approval', state: approval ? classifyStatus(approval.status) : 'pending', detail: approval?.status || 'Inspect current approval eligibility' },
    { id: 'notify', label: 'Jira / Slack', state: notified ? 'done' : integrations.jira_key ? 'review' : 'pending', detail: notified ? 'Both providers confirmed' : integrations.jira_key ? 'Jira confirmed; Slack incomplete' : 'No provider confirmation' },
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

export function repairVerification(incident, live, candidate = incident?.investigation?.generated_repair) {
  const tests = [];
  for (const label of ['original', 'candidate']) {
    for (const test of candidate?.tests?.[label]?.cases || []) tests.push({ name: label + ': ' + test.name,
      status: test.outcome, kind: classifyStatus(test.outcome) });
  }
  let state = 'unverified';
  let detail = 'No verified generated candidate is available.';
  if (candidate) {
    const verified = candidate.verification_status === 'VERIFIED' && candidate.tests?.original?.failed > 0
      && candidate.tests?.candidate?.exit_code === 0 && candidate.tests?.candidate?.failed === 0
      && candidate.tests?.candidate?.passed > 0 && candidate.replay?.detection_gap_fixed === true;
    state = verified ? 'verified' : 'failed';
    detail = verified ? 'Candidate passed acceptance tests and fixed the detection gap in offline replay. Physical equipment health remains unverified.'
      : 'Candidate verification: ' + candidate.verification_status + '. Inspect actual test and replay evidence.';
  } else if (['QUEUED', 'RUNNING'].includes(incident?.investigation?.status)) {
    state = 'running'; detail = 'Investigation is running; a verified candidate has not been produced.';
  }
  return { state, detail, tests, liveNominal: Boolean(live) && !live.stale && live.level === 'nominal' };
}

export function describeFinding(finding) {
  if (typeof finding === 'string') return { text: finding, raw: null };
  if (finding && typeof finding === 'object') {
    const text = finding.summary ?? finding.title ?? finding.description ?? finding.message ?? null;
    return { text: typeof text === 'string' ? text : null, raw: finding };
  }
  return { text: String(finding), raw: null };
}
