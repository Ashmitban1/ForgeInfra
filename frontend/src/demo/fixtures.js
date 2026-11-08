// HARDCODED DEMO DATA. Used only when the user turns on Demo mode; never mixed with real API responses.
import { ApiError } from '../api.js';

const DEMO_KEY = 'factoryos-demo-mode';

try {
  const param = new URLSearchParams(window.location.search).get('demo');
  if (param === '1' || param === '0') {
    window.localStorage.setItem(DEMO_KEY, param);
    window.history.replaceState(null, '', window.location.pathname + window.location.hash);
  }
} catch { /* storage unavailable */ }

export const isDemoMode = () => {
  try { return window.localStorage.getItem(DEMO_KEY) === '1'; } catch { return false; }
};

export function setDemoMode(on) {
  try { window.localStorage.setItem(DEMO_KEY, on ? '1' : '0'); } catch { /* storage unavailable */ }
  window.location.reload();
}

const iso = ms => new Date(ms).toISOString();
const delay = () => new Promise(resolve => setTimeout(resolve, 150));

function device(id, now, { temp, humidity, fault, legacy, ageSec, sequenceOffset = 0 }) {
  const received = now - ageSec * 1000;
  const expected = fault || temp > 35 ? 'WARNING' : 'NORMAL';
  const mismatch = legacy !== expected;
  return {
    schema_version: '1.0',
    device_id: id,
    hardware: {
      temperature_c: temp, humidity_pct: humidity, cooling_fault: fault, fault_is_simulated: true,
      source_kind: 'simulator', observed_at: iso(received - 5), received_at: iso(received),
      sequence: Math.floor(now / 3000) + sequenceOffset,
    },
    legacy_monitor: { status: legacy, source_revision: 'demo-legacy-placeholder-v1', sampled_at: iso(received - 5) },
    expected_status: expected,
    reliability: {
      mismatch,
      reasons: mismatch ? ['legacy_missed_fault'] : [],
      evidence_quality: mismatch ? 'PARTIAL' : 'CURRENT',
      observation_age_seconds: 0.01,
    },
  };
}

export function demoTelemetry(now = Date.now()) {
  const wave = Math.sin(now / 9000);
  // RACK-02 shows a 20s fault in every 60s so the Recovered state can be seen.
  const rack2Fault = (now / 1000) % 60 < 20;
  return [
    device('RACK-01', now, { temp: +(29.4 + wave * 0.6).toFixed(1), humidity: 54, fault: true, legacy: 'NORMAL', ageSec: 2 }),
    device('RACK-02', now, { temp: +(24.1 + wave * 0.4).toFixed(1), humidity: 47, fault: rack2Fault, legacy: 'NORMAL', ageSec: 1, sequenceOffset: 1 }),
    device('RACK-03', now, { temp: 36.8, humidity: 51, fault: false, legacy: 'WARNING', ageSec: 4, sequenceOffset: 2 }),
    device('RACK-04', now, { temp: 23.2, humidity: 44, fault: false, legacy: 'NORMAL', ageSec: 140, sequenceOffset: 3 }),
  ];
}

// DEMO ONLY: INC-002 advances through investigation stages on a 90s loop so the progression animations
// can be seen without the Person 2 agent routes. This is scripted sample data, not backend behavior.
function demoStage(now) {
  const t = (now / 1000) % 90;
  if (t < 25) return { inv: 'PENDING', gem: 'PENDING', calls: 0 };
  if (t < 45) return { inv: 'RUNNING', gem: 'PENDING', calls: 1 + Math.floor((t - 25) / 7) };
  if (t < 65) return { inv: 'COMPLETED', gem: 'RUNNING', calls: 3 };
  return { inv: 'COMPLETED', gem: 'COMPLETED', calls: 3 };
}
const DEMO_CALLS = [
  { name: 'read_telemetry_window', args: { device_id: 'RACK-03', minutes: 10 } },
  { name: 'inspect_legacy_source', args: { function: 'check_status' } },
  { name: 'run_baseline_tests' },
];

export function demoIncidents(now = Date.now()) {
  const stage = demoStage(now);
  const base = telemetryFor('RACK-01', now);
  const second = telemetryFor('RACK-03', now);
  return [
    {
      schema_version: '1.0', incident_id: 'INC-COOLING-001', device_id: 'RACK-01',
      created_at: iso(now - 12 * 60 * 1000), updated_at: iso(now - 2000), status: 'OPEN', severity: 'HIGH',
      investigation: {
        status: 'COMPLETED', agent: 'nvidia-nemotron',
        tool_calls: [
          { name: 'read_telemetry_window', status: 'SUCCESS', called_at: iso(now - 11 * 60 * 1000), args: { device_id: 'RACK-01', minutes: 10 } },
          { name: 'inspect_legacy_source', status: 'SUCCESS', called_at: iso(now - 10.5 * 60 * 1000), args: { function: 'check_status' } },
          { name: 'run_baseline_tests', status: 'SUCCESS', called_at: iso(now - 10 * 60 * 1000) },
        ],
        findings: [
          'DEMO: Legacy monitor only inspects temperature and ignores the cooling-fault input.',
          { summary: 'DEMO: Fault reproduced with a 29.4 °C reading and cooling_fault = true.', confidence: 0.92 },
        ],
        evidence_ids: ['DEMO-EV-001', 'DEMO-EV-002'],
      },
      decision_review: {
        status: 'COMPLETED', reviewer: 'gemini',
        recommendation: {
          summary: 'DEMO: Approve a minimal patch that also warns when cooling_fault is true.',
          risk: 'low',
          rationale: 'Change is isolated to one condition and covered by regression tests.',
        },
      },
      integrations: {
        jira_key: 'DEMO-1', jira_url: 'https://example.com/browse/DEMO-1', slack_message_id: 'DEMO-1730000000.000100',
        github_pr_url: null, solana_tx_signature: null,
      },
      ...base,
    },
    {
      schema_version: '1.0', incident_id: 'INC-COOLING-002', device_id: 'RACK-03',
      created_at: iso(now - 90 * 1000), updated_at: iso(now - 4000), status: 'OPEN', severity: 'HIGH',
      investigation: {
        status: stage.inv, agent: 'nvidia-nemotron',
        tool_calls: DEMO_CALLS.slice(0, stage.calls).map((c, i) => ({
          ...c, called_at: iso(now - (stage.calls - i) * 5000),
          status: stage.inv === 'RUNNING' && i === stage.calls - 1 ? 'RUNNING' : 'SUCCESS',
        })),
        findings: stage.inv === 'COMPLETED' ? ['DEMO: Over-temperature reading was flagged by the legacy monitor.'] : [],
        evidence_ids: [],
      },
      decision_review: {
        status: stage.gem, reviewer: 'gemini',
        recommendation: stage.gem === 'COMPLETED' ? { summary: 'DEMO: No code change needed; investigate rack airflow.', risk: 'low' } : null,
      },
      integrations: { jira_key: null, jira_url: null, slack_message_id: null, github_pr_url: null, solana_tx_signature: null },
      ...second,
    },
  ];
}

function telemetryFor(id, now) {
  const { schema_version, device_id, ...rest } = demoTelemetry(now).find(d => d.device_id === id);
  return { ...rest, schema_version, device_id };
}

export async function demoGetTelemetry() { await delay(); return demoTelemetry(); }
export async function demoGetIncidents() { await delay(); return demoIncidents(); }
export async function demoGetIncident(id) {
  await delay();
  const found = demoIncidents().find(i => i.incident_id === id);
  if (!found) throw new ApiError('Incident not found', { kind: 'not_found', status: 404 });
  return found;
}
