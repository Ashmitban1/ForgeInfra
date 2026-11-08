import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { useEffect, useRef, useState } from 'react';
import { deviceHealth, STATE_META } from '../lib/health.js';
import { formatAge, formatNumber } from '../lib/format.js';
import { AnimatedNumber, Badge } from './ui.jsx';

function Fan({ running }) {
  const reduce = useReducedMotion();
  const spin = running && !reduce;
  return (
    <motion.svg
      className="fan"
      viewBox="0 0 24 24"
      width="26"
      height="26"
      aria-hidden="true"
      animate={spin ? { rotate: [0, 360] } : { rotate: 0 }}
      transition={spin ? { repeat: Infinity, ease: 'linear', duration: 2.4 } : { duration: 0.4 }}
    >
      <circle cx="12" cy="12" r="10.5" fill="none" stroke="currentColor" strokeWidth="1" opacity="0.5" />
      <g fill="currentColor">
        <path d="M12 12 C9 8 9.5 3.5 12 3 C14.5 3.5 14.8 8 12 12Z" />
        <path d="M12 12 C16 9 20.5 9.5 21 12 C20.5 14.5 16 14.8 12 12Z" />
        <path d="M12 12 C15 16 14.5 20.5 12 21 C9.5 20.5 9.2 16 12 12Z" />
        <path d="M12 12 C8 15 3.5 14.5 3 12 C3.5 9.5 8 9.2 12 12Z" />
      </g>
      <circle cx="12" cy="12" r="1.8" fill="#070b1a" />
    </motion.svg>
  );
}

function Unit({ tone, label, value, children }) {
  return (
    <div className={`unit unit-${tone}`}>
      {children}
      <span className="unit-label">{label}</span>
      <span className="unit-value">{value}</span>
      <span className="led" aria-hidden="true" />
    </div>
  );
}

function statusTone(status, stale) {
  if (stale) return 'muted';
  return status === 'WARNING' ? 'fault' : status === 'NORMAL' ? 'ok' : 'muted';
}

export default function RackCard({ device, history, now, selected, onSelect }) {
  const reduce = useReducedMotion();
  const hw = device.hardware ?? {};
  const health = deviceHealth(device, now, history);
  const meta = STATE_META[health.state];
  const coolingFault = hw.cooling_fault === true;
  const legacy = device.legacy_monitor?.status;
  const expected = device.expected_status;
  const alarming = health.state === 'fault' && !reduce;

  // Flash when the derived state really changes between polls (never on first render).
  const prevState = useRef(health.state);
  const [flash, setFlash] = useState(null);
  useEffect(() => {
    if (prevState.current !== health.state) {
      setFlash({ id: Date.now(), from: prevState.current, to: health.state });
      prevState.current = health.state;
    }
  }, [health.state]);

  const summary = [
    `${device.device_id}: ${meta.label}`,
    `${formatNumber(hw.temperature_c)} °C`,
    coolingFault ? 'cooling fault reported' : 'no cooling fault reported',
    !health.comparisonAvailable ? 'comparison unavailable' : health.mismatch ? 'legacy monitor mismatch' : 'no source mismatch',
  ].join(', ');

  return (
    <motion.button
      type="button"
      layout
      className={`rack rack-${health.state} ${selected ? 'is-selected' : ''}`}
      aria-pressed={selected}
      aria-label={summary}
      onClick={() => onSelect(device.device_id)}
      initial={{ opacity: 0, scale: 0.97 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.3 }}
    >
      {alarming && (
        <motion.span
          className="rack-pulse"
          aria-hidden="true"
          animate={{ opacity: [0.15, 0.6, 0.15] }}
          transition={{ repeat: Infinity, duration: 1.8, ease: 'easeInOut' }}
        />
      )}
      <AnimatePresence>
        {flash && !reduce && (
          <motion.span
            key={flash.id}
            className={`rack-flash rack-flash-${flash.to}`}
            aria-hidden="true"
            initial={{ opacity: 0.85, scaleX: flash.to === 'recovered' ? 0 : 1 }}
            animate={{ opacity: 0, scaleX: 1 }}
            transition={{ duration: flash.to === 'recovered' ? 1.4 : 1.1, ease: 'easeOut' }}
            onAnimationComplete={() => setFlash(null)}
          />
        )}
      </AnimatePresence>
      <div className="rack-top">
        <strong className="mono">{device.device_id}</strong>
        <AnimatePresence mode="wait" initial={false}>
          <motion.span
            key={health.state}
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 4 }}
            transition={{ duration: 0.18 }}
          >
            <Badge tone={meta.tone} icon={meta.icon}>{meta.label}</Badge>
          </motion.span>
        </AnimatePresence>
      </div>
      <div className="rack-frame">
        <Unit tone={health.stale ? 'muted' : coolingFault ? 'fault' : 'ok'} label="Cooling" value={coolingFault ? 'Fault reported' : 'No fault reported'}>
          <Fan running={!coolingFault && !health.stale} />
        </Unit>
        <Unit
          tone={health.stale ? 'muted' : health.mismatch ? 'fault' : statusTone(legacy, false)}
          label="Legacy monitor"
          value={`${legacy ?? '—'}${health.mismatch ? ' · mismatch' : ''}`}
        />
        <Unit tone={statusTone(expected, health.stale)} label="Independent check" value={expected ?? '—'} />
        <Unit
          tone={health.stale ? 'review' : 'ok'}
          label="Last reading"
          value={health.ageSeconds === null ? '—' : `${formatAge(health.ageSeconds)} ago`}
        />
      </div>
      <div className="rack-foot">
        <span><b><AnimatedNumber value={hw.temperature_c} /></b> °C</span>
        <span><b>{formatNumber(hw.humidity_pct, 0)}</b> % RH</span>
        <span className="muted">{hw.source_kind ?? '—'}{hw.fault_is_simulated ? ' · simulated fault flag' : ''}</span>
      </div>
      {health.state === 'recovered' && (
        <p className="rack-note">Latest reading is nominal after a fault observed in this session.</p>
      )}
      {health.state === 'stale' && (
        <p className="rack-note">No new reading for over 90s. Values shown are the last received.</p>
      )}
    </motion.button>
  );
}
