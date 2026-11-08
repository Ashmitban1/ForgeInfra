import { motion } from 'motion/react';
import { REASON_LABELS } from '../lib/health.js';
import { formatAge, formatDateTime, formatNumber } from '../lib/format.js';
import { Badge } from './ui.jsx';

function statusBadge(status) {
  if (status === 'WARNING') return <Badge tone="fault" icon="▲">WARNING</Badge>;
  if (status === 'NORMAL') return <Badge tone="ok" icon="●">NORMAL</Badge>;
  return <Badge tone="muted">{status ?? '—'}</Badge>;
}

// `source` is either a /api/telemetry/latest device or a /api/incidents/{id} incident; both share these fields.
export default function MismatchEvidence({ source }) {
  const hw = source.hardware ?? {};
  const legacy = source.legacy_monitor ?? {};
  const rel = source.reliability ?? {};
  const reasons = rel.reasons ?? [];
  const placeholder = /placeholder/i.test(legacy.source_revision ?? '');
  const unavailable = typeof rel.mismatch !== 'boolean' || legacy.status === 'UNKNOWN';

  return (
    <div className="evidence">
      <motion.p
        key={`${rel.mismatch}-${legacy.status}-${source.expected_status}`}
        className={`verdict ${unavailable ? 'verdict-review' : rel.mismatch ? 'verdict-fault' : 'verdict-ok'}`}
        initial={{ opacity: 0, x: -8 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 0.25 }}
      >
        <span aria-hidden="true">{rel.mismatch ? '▲' : '●'}</span>
        {unavailable ? 'Comparison unavailable: the legacy monitor has no verified decision. Independent alerts remain active.' : rel.mismatch
          ? `Source mismatch: legacy monitor says ${legacy.status}, independent check expects ${source.expected_status}.`
          : `No source mismatch: legacy monitor and independent check both say ${source.expected_status ?? '—'}.`}
      </motion.p>

      <div className="compare">
        <div className="compare-col">
          <h3>Hardware evidence</h3>
          <p className="mono">{formatNumber(hw.temperature_c)} °C · {formatNumber(hw.humidity_pct, 0)} % RH</p>
          <p>Cooling fault: <b>{hw.cooling_fault ? 'reported' : 'not reported'}</b>{hw.fault_is_simulated ? ' (simulated flag)' : ''}</p>
          <p className="muted">Source <span className="mono">{hw.source_kind ?? '—'}</span>. A source label is not authenticated proof.</p>
        </div>
        <div className="compare-col">
          <h3>Legacy monitor</h3>
          <p>{statusBadge(legacy.status)}</p>
          {legacy.health && <p className="muted">Monitor health: {legacy.health} · execution: {legacy.execution_status}</p>}
          <p className="muted">Revision <span className="mono">{legacy.source_revision ?? '—'}</span></p>
          {placeholder && <p className="caveat">Placeholder function, not genuine reverse engineering (API contract).</p>}
          <p className="muted">Sampled {formatDateTime(legacy.sampled_at)}</p>
        </div>
        <div className="compare-col">
          <h3>Independent check</h3>
          <p>{statusBadge(source.expected_status)}</p>
          <p className="muted">Deterministic backend rule; does not depend on AI availability.</p>
        </div>
      </div>

      <dl className="facts">
        <div className="fact"><dt>Evidence quality</dt><dd><Badge tone={rel.evidence_quality === 'CURRENT' ? 'ok' : 'review'}>{rel.evidence_quality ?? '—'}</Badge></dd></div>
        <div className="fact"><dt>Age when received</dt><dd>{formatAge(rel.observation_age_seconds)}</dd></div>
      </dl>

      <h3 className="subhead">Reasons reported by the API</h3>
      {reasons.length === 0 ? (
        <p className="muted">No reliability reasons reported.</p>
      ) : (
        <ul className="reasons">
          {reasons.map(code => (
            <li key={code}>
              <code>{code}</code>
              <span>{REASON_LABELS[code] ?? 'Reason code not documented in the dashboard.'}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
