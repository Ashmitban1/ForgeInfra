import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { useEffect, useRef, useState } from 'react';
import { classifyStatus } from '../../lib/health.js';
import { Badge } from '../ui.jsx';

const VIEW = {
  verified: { tone: 'ok', title: 'Repair verified', color: '#3fe0a0' },
  'tests-passed': { tone: 'review', title: 'Tests passed — recovery not confirmed', color: '#ffc261' },
  running: { tone: 'info', title: 'Verification in progress', color: '#52d6ff' },
  failed: { tone: 'fault', title: 'Verification failed', color: '#ff6677' },
  unverified: { tone: 'muted', title: 'Not verified', color: '#5a6a92' },
};
const TEST_TONE = { done: 'ok', failed: 'fault', active: 'info', pending: 'muted', unknown: 'review' };

function Mark({ state, burst, reduce, color }) {
  return (
    <svg className="verify-mark" viewBox="0 0 48 48" width="48" height="48" aria-hidden="true">
      <circle cx="24" cy="24" r="21" fill="none" stroke={color} strokeWidth="2.5" opacity="0.55" />
      {burst && !reduce && (
        <motion.circle
          cx="24" cy="24" r="21" fill="none" stroke={color} strokeWidth="2"
          initial={{ scale: 1, opacity: 0.9 }} animate={{ scale: 1.7, opacity: 0 }}
          transition={{ duration: 1.2, ease: 'easeOut' }}
          style={{ transformBox: 'fill-box', transformOrigin: 'center' }}
        />
      )}
      <AnimatePresence mode="wait" initial>
        {state === 'verified' || state === 'tests-passed' ? (
          <motion.path
            key="check" d="M14 25 L21 32 L34 17" fill="none" stroke={color} strokeWidth="4" strokeLinecap="round" strokeLinejoin="round"
            initial={reduce ? false : { pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.6, ease: 'easeOut' }}
          />
        ) : state === 'failed' ? (
          <motion.path
            key="x" d="M16 16 L32 32 M32 16 L16 32" fill="none" stroke={color} strokeWidth="4" strokeLinecap="round"
            initial={reduce ? false : { pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.4 }}
          />
        ) : (
          <circle key="dot" cx="24" cy="24" r="4" fill={color} />
        )}
      </AnimatePresence>
    </svg>
  );
}

export default function RepairVerification({ verification, deviceId }) {
  const reduce = useReducedMotion();
  const view = VIEW[verification.state];
  // The burst only plays if the state becomes "verified" while this page is open.
  const prev = useRef(verification.state);
  const [burst, setBurst] = useState(false);
  useEffect(() => {
    if (prev.current !== 'verified' && verification.state === 'verified') {
      setBurst(true);
      const t = setTimeout(() => setBurst(false), 1400);
      prev.current = verification.state;
      return () => clearTimeout(t);
    }
    prev.current = verification.state;
    return undefined;
  }, [verification.state]);

  return (
    <>
      <motion.div
        className={`verify verify-${view.tone}`}
        role="status"
        key={verification.state}
        initial={reduce ? false : { opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
      >
        <Mark state={verification.state} burst={burst} reduce={reduce} color={view.color} />
        <div>
          <strong>{view.title}</strong>
          <p className="muted">{verification.detail}</p>
        </div>
      </motion.div>
      <ul className="test-list" aria-label="Backend-reported verification steps">
        {verification.tests.length === 0 ? (
          <li><span className="muted">No verification steps reported for this incident.</span></li>
        ) : verification.tests.map((t, i) => (
          <li key={i}>
            <code>{t.name}</code>
            <Badge tone={TEST_TONE[classifyStatus(t.status)]}>{String(t.status ?? 'no status')}</Badge>
          </li>
        ))}
        <li>
          <span>Live rack check{deviceId ? ` · ${deviceId}` : ''}</span>
          <Badge tone={verification.liveNominal ? 'ok' : 'muted'}>{verification.liveNominal ? 'Nominal now' : 'Not nominal / unknown'}</Badge>
        </li>
      </ul>
      <p className="note">
        Derived only from backend tool-call statuses and the latest telemetry. API v1 has no repair route, so this stays
        “Not verified” until the backend reports passing tests.
      </p>
    </>
  );
}
