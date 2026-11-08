import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { useMemo } from 'react';
import { isDemoMode } from '../demo/fixtures.js';
import { classifyStatus, deviceHealth, repairVerification } from '../lib/health.js';
import { formatNumber } from '../lib/format.js';

// Mission-control scene. Every color, label and animation trigger comes from API data:
//  - rack LEDs / glow  <- deviceHealth() of the latest telemetry
//  - data packets      <- a NEW reading (sequence/received_at) observed in the latest poll
//  - stage nodes       <- incident.investigation / decision_review status, verbatim from the API
//  - state-change ring <- a device's derived health state differing from the previous poll
// With reduced motion, packets, rings and pulses are not rendered; state is shown statically.

const C = { ok: '#3fe0a0', fault: '#ff6677', review: '#ffc261', muted: '#5a6a92', info: '#52d6ff', idle: '#24325f' };
const STATE_COLOR = { fault: C.fault, review: C.review, nominal: C.ok, recovered: C.ok, stale: C.muted };
const STAGE_COLOR = { done: C.ok, active: C.info, failed: C.fault, pending: C.muted, unknown: C.review };

const W = 960;
const NODES = {
  sensors: { x: 70, y: 285 },
  api: { x: 215, y: 285 },
  legacy: { x: 375, y: 240 },
  indep: { x: 375, y: 330 },
  incident: { x: 535, y: 285 },
  nemotron: { x: 675, y: 285 },
  gemini: { x: 800, y: 285 },
  repair: { x: 915, y: 285 },
};
const EDGES = [
  ['sensors', 'api'], ['api', 'legacy'], ['api', 'indep'], ['legacy', 'incident'],
  ['indep', 'incident'], ['incident', 'nemotron'], ['nemotron', 'gemini'], ['gemini', 'repair'],
];
const NODE_R = 24;

function RackSilhouette({ device, x, width, now, history, ring, reduce }) {
  const health = deviceHealth(device, now, history);
  const hw = device.hardware ?? {};
  const color = STATE_COLOR[health.state];
  const slots = [
    { id: 'cool', color: health.stale ? C.muted : hw.cooling_fault ? C.fault : C.ok },
    { id: 'legacy', color: health.stale ? C.muted : health.mismatch ? C.fault : device.legacy_monitor?.status === 'WARNING' ? C.review : C.ok },
    { id: 'indep', color: health.stale ? C.muted : device.expected_status === 'WARNING' ? C.fault : C.ok },
    { id: 'fresh', color: health.stale ? C.review : C.ok },
    { id: 'temp', color: health.stale ? C.muted : hw.temperature_c > 35 ? C.fault : C.ok },
  ];
  const h = 150;
  const y = 28;
  return (
    <g>
      <motion.rect
        x={x} y={y} width={width} height={h} rx={9}
        fill="#0b1230" strokeWidth={1.5}
        initial={false} animate={{ stroke: color, filter: health.state === 'fault' ? `drop-shadow(0 0 10px ${color})` : 'drop-shadow(0 0 0px transparent)' }}
        transition={{ duration: 0.6 }}
        strokeDasharray={health.state === 'stale' ? '5 4' : undefined}
      />
      {health.state === 'fault' && !reduce && (
        <motion.rect
          x={x - 2} y={y - 2} width={width + 4} height={h + 4} rx={11} fill="none" stroke={color} strokeWidth={2}
          animate={{ opacity: [0.1, 0.7, 0.1] }} transition={{ repeat: Infinity, duration: 1.8, ease: 'easeInOut' }}
        />
      )}
      {slots.map((slot, i) => (
        <g key={slot.id}>
          <rect x={x + 10} y={y + 36 + i * 21} width={width - 20} height={14} rx={3} fill="#111b3d" />
          {[0, 1, 2].map(k => (
            <rect key={k} x={x + 16 + k * 7} y={y + 40 + i * 21} width={4} height={6} rx={1} fill="#1b2a55" />
          ))}
          <motion.circle
            cx={x + width - 20} cy={y + 43 + i * 21} r={4}
            initial={false} animate={{ fill: slot.color }} transition={{ duration: 0.5 }}
          />
        </g>
      ))}
      <text x={x + width / 2} y={y + 20} textAnchor="middle" fill="#e8eefb" fontSize="12" fontWeight="700" fontFamily="ui-monospace, Menlo, monospace">
        {device.device_id}
      </text>
      <text x={x + width / 2} y={y + h + 17} textAnchor="middle" fill={color} fontSize="12" fontWeight="700">
        {formatNumber(hw.temperature_c)} °C
      </text>
      <AnimatePresence>
        {ring && !reduce && (
          <motion.rect
            key={ring.id}
            x={x} y={y} width={width} height={h} rx={9} fill="none" stroke={STATE_COLOR[ring.to]} strokeWidth={3}
            initial={{ opacity: 0.95, scale: 1 }} animate={{ opacity: 0, scale: 1.12 }} exit={{ opacity: 0 }}
            transition={{ duration: 1.3, ease: 'easeOut' }}
            style={{ transformBox: 'fill-box', transformOrigin: 'center' }}
          />
        )}
      </AnimatePresence>
    </g>
  );
}

function stageView(status) {
  const kind = classifyStatus(status);
  return { kind, color: STAGE_COLOR[kind], label: status ?? 'missing' };
}

function Node({ id, label, sub, color, active, reduce }) {
  const { x, y } = NODES[id];
  return (
    <g>
      {active && !reduce && (
        <motion.circle
          cx={x} cy={y} r={NODE_R} fill="none" stroke={color} strokeWidth={1.5}
          style={{ transformBox: 'fill-box', transformOrigin: 'center' }}
          animate={{ scale: [1, 1.45], opacity: [0.7, 0] }}
          transition={{ repeat: Infinity, duration: 1.8, ease: 'easeOut' }}
        />
      )}
      <motion.circle
        cx={x} cy={y} r={NODE_R} fill="#0b1230" strokeWidth={2}
        initial={false} animate={{ stroke: color }} transition={{ duration: 0.5 }}
      />
      <motion.circle cx={x} cy={y} r={7} initial={false} animate={{ fill: color }} transition={{ duration: 0.5 }} />
      <text x={x} y={y + NODE_R + 17} textAnchor="middle" fill="#e8eefb" fontSize="12" fontWeight="700">{label}</text>
      <text x={x} y={y + NODE_R + 32} textAnchor="middle" fill="#93a1c0" fontSize="11">{sub}</text>
    </g>
  );
}

export default function DataHall({ devices, history, now, incidents, telemetryError, transitions, pulses, onPulseDone, loading }) {
  const reduce = useReducedMotion();
  const demo = isDemoMode();

  const healths = useMemo(
    () => devices.map(d => deviceHealth(d, now, history[d.device_id])),
    [devices, now, history],
  );
  const anyFresh = healths.some(h => !h.stale);
  const faulted = healths.filter(h => h.level === 'fault').length;
  const mismatched = healths.filter(h => h.mismatch).length;

  const open = (incidents ?? []).filter(i => i.status === 'OPEN');
  const focus = [...open].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))[0] ?? null;
  const nemo = stageView(focus?.investigation?.status);
  const gem = stageView(focus?.decision_review?.status);
  const focusIdx = focus ? devices.findIndex(d => d.device_id === focus.device_id) : -1;
  const verification = focus ? repairVerification(focus, focusIdx >= 0 ? healths[focusIdx] : null) : null;
  const VERIFY_VIEW = {
    verified: { color: C.ok, sub: 'Verified' }, 'tests-passed': { color: C.review, sub: 'Tests passed' },
    failed: { color: C.fault, sub: 'Failed' }, running: { color: C.info, sub: 'Running' },
    unverified: { color: C.muted, sub: 'Not verified' },
  };
  const verifyView = verification ? VERIFY_VIEW[verification.state] : { color: C.muted, sub: 'No incident' };

  const nodeState = {
    sensors: { color: telemetryError && !devices.length ? C.fault : anyFresh ? C.ok : C.muted, sub: `${devices.length} device${devices.length === 1 ? '' : 's'}`, label: 'Hardware feed' },
    api: { color: telemetryError ? (devices.length ? C.review : C.fault) : loading ? C.muted : C.ok, sub: telemetryError ? 'Unreachable' : loading ? 'Connecting' : 'Receiving', label: 'FactoryOS API' },
    legacy: { color: mismatched ? C.fault : anyFresh ? C.ok : C.muted, sub: mismatched ? `${mismatched} mismatch` : 'Agrees', label: 'Legacy monitor' },
    indep: { color: faulted ? C.fault : anyFresh ? C.ok : C.muted, sub: faulted ? `${faulted} fault${faulted === 1 ? '' : 's'}` : 'Nominal', label: 'Independent check' },
    incident: { color: open.length ? C.review : incidents ? C.ok : C.muted, sub: incidents ? `${open.length} open` : '—', label: 'Incident' },
    nemotron: { color: focus ? nemo.color : C.muted, sub: focus ? nemo.label : '—', label: 'Nemotron' },
    gemini: { color: focus ? gem.color : C.muted, sub: focus ? gem.label : '—', label: 'Gemini review' },
    repair: { color: verifyView.color, sub: verifyView.sub, label: 'Repair' },
  };
  const activeNodes = new Set(
    [nemo.kind === 'active' && focus ? 'nemotron' : null, gem.kind === 'active' && focus ? 'gemini' : null,
      verification?.state === 'running' ? 'repair' : null].filter(Boolean),
  );

  const visible = devices.slice(0, 8);
  const gap = 14;
  const rackW = Math.min(118, (W - 80 - gap * (visible.length - 1)) / Math.max(visible.length, 1));
  const total = visible.length * rackW + (visible.length - 1) * gap;
  const startX = (W - total) / 2;

  const rings = {};
  for (const t of transitions) {
    if (now - t.at < 1400 && !rings[t.deviceId]) rings[t.deviceId] = t;
  }

  const edgeColor = ([from, to]) => {
    const target = nodeState[to].color;
    return nodeState[from].color === C.muted || target === C.muted ? C.idle : target;
  };

  const summary = `Data hall. ${devices.length} racks reporting, ${faulted} with faults, ${mismatched} legacy monitor mismatches, ` +
    `${open.length} open incidents. Nemotron ${focus ? nemo.label : 'idle'}, Gemini ${focus ? gem.label : 'idle'}, repair ${verifyView.sub}.`;

  const nodePos = id => NODES[id];

  return (
    <div className="hall">
      <div className="hall-tags">
        {demo ? <span className="badge badge-sample">Demo data — not from the backend</span> : <span className="badge badge-info">Live from API</span>}
        <span className="muted hall-hint">Packets appear only when a new reading arrives. Pipeline stages show backend status verbatim.</span>
      </div>
      <div className="hall-scroll">
        <svg className="hall-svg" viewBox={`0 0 ${W} 400`} role="img" aria-label={summary}>
          <defs>
            <linearGradient id="floor" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor="#52d6ff" stopOpacity="0.07" />
              <stop offset="1" stopColor="#52d6ff" stopOpacity="0" />
            </linearGradient>
          </defs>
          <rect x="0" y="0" width={W} height="215" fill="url(#floor)" rx="12" />
          {visible.length === 0 && (
            <text x={W / 2} y="110" textAnchor="middle" fill="#93a1c0" fontSize="14">
              {loading ? 'Connecting to the data hall…' : 'No racks have reported telemetry yet.'}
            </text>
          )}
          {visible.map((device, i) => (
            <RackSilhouette
              key={device.device_id} device={device} x={startX + i * (rackW + gap)} width={rackW}
              now={now} history={history[device.device_id]} ring={rings[device.device_id]} reduce={reduce}
            />
          ))}
          {devices.length > visible.length && (
            <text x={W - 20} y="205" textAnchor="end" fill="#93a1c0" fontSize="11">+{devices.length - visible.length} more racks below</text>
          )}

          {EDGES.map(edge => {
            const a = nodePos(edge[0]);
            const b = nodePos(edge[1]);
            const color = edgeColor(edge);
            const flowing = color !== C.idle && !reduce && (activeNodes.has(edge[1]) || (edge[0] === 'sensors' && anyFresh && !telemetryError));
            return (
              <g key={edge.join('-')}>
                <motion.line
                  x1={a.x + NODE_R} y1={a.y} x2={b.x - NODE_R} y2={b.y}
                  strokeWidth={2} initial={false} animate={{ stroke: color }} transition={{ duration: 0.6 }}
                />
                {flowing && (
                  <motion.line
                    x1={a.x + NODE_R} y1={a.y} x2={b.x - NODE_R} y2={b.y}
                    stroke="#0b1230" strokeWidth={2} strokeDasharray="6 10"
                    animate={{ strokeDashoffset: [0, -32] }} transition={{ repeat: Infinity, duration: 1.4, ease: 'linear' }}
                    opacity={0.55}
                  />
                )}
              </g>
            );
          })}

          {Object.keys(NODES).map(id => (
            <Node key={id} id={id} {...nodeState[id]} active={activeNodes.has(id)} reduce={reduce} />
          ))}

          {!reduce && pulses.map(p => {
            const path = id => nodePos(id);
            const s = path('sensors'); const a = path('api'); const l = path('legacy'); const e = path('indep'); const inc = path('incident');
            const legacyColor = p.mismatch ? C.fault : C.ok;
            const indepColor = p.fault ? C.fault : C.ok;
            const toIncident = p.mismatch;
            const times = toIncident ? [0, 0.3, 0.6, 1] : [0, 0.4, 1];
            return (
              <g key={p.id} aria-hidden="true">
                <motion.circle
                  r={5} fill={legacyColor} initial={{ cx: s.x, cy: s.y, opacity: 0 }}
                  animate={{ cx: toIncident ? [s.x, a.x, l.x, inc.x] : [s.x, a.x, l.x], cy: toIncident ? [s.y, a.y, l.y, inc.y] : [s.y, a.y, l.y], opacity: toIncident ? [0, 1, 1, 0] : [0, 1, 0] }}
                  transition={{ duration: 2.2, ease: 'easeInOut', times }}
                  onAnimationComplete={() => onPulseDone(p.id)}
                />
                <motion.circle
                  r={5} fill={indepColor} initial={{ cx: s.x, cy: s.y, opacity: 0 }}
                  animate={{ cx: [s.x, a.x, e.x], cy: [s.y, a.y, e.y], opacity: [0, 1, 0] }}
                  transition={{ duration: 2.2, ease: 'easeInOut', times: [0, 0.4, 1] }}
                />
              </g>
            );
          })}
        </svg>
      </div>
      <p className="hall-swipe muted">Swipe sideways to see the full pipeline.</p>
      <ul className="hall-legend" aria-label="Legend">
        <li><i style={{ background: C.ok }} />Nominal / complete</li>
        <li><i style={{ background: C.fault }} />Fault / mismatch / failed</li>
        <li><i style={{ background: C.review }} />Needs review</li>
        <li><i style={{ background: C.info }} />In progress</li>
        <li><i style={{ background: C.muted }} />Pending / no data</li>
      </ul>
    </div>
  );
}
