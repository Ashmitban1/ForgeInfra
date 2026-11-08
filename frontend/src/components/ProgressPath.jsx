import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { useEffect, useRef, useState } from 'react';

const STATE_VIEW = {
  done: { icon: '✔', text: 'Complete', tone: 'ok' },
  pending: { icon: '○', text: 'Pending', tone: 'muted' },
  active: { icon: '◔', text: 'In progress', tone: 'info' },
  failed: { icon: '✕', text: 'Failed', tone: 'fault' },
  unavailable: { icon: '–', text: 'Not available', tone: 'muted' },
  unknown: { icon: '?', text: 'Unrecognized status', tone: 'review' },
};

function Step({ step, index, previous, advanced, reduce }) {
  const view = STATE_VIEW[step.state] ?? STATE_VIEW.unknown;
  const connectorFilled = previous?.state === 'done';
  return (
    <li className={`path-step path-${view.tone} path-state-${step.state}`}>
      {index > 0 && (
        <span className="path-connector" aria-hidden="true">
          <motion.span
            className="path-fill"
            initial={false}
            animate={{ scaleX: connectorFilled ? 1 : 0 }}
            transition={{ duration: reduce ? 0 : 0.6, ease: 'easeOut' }}
          />
          {advanced && !reduce && (
            <motion.span
              className="path-packet"
              initial={{ left: '0%', opacity: 1 }}
              animate={{ left: '100%', opacity: [1, 1, 0] }}
              transition={{ duration: 0.9, ease: 'easeInOut' }}
            />
          )}
        </span>
      )}
      <motion.span
        className="path-node"
        aria-hidden="true"
        initial={false}
        animate={step.state === 'active' && !reduce ? { scale: [1, 1.12, 1] } : { scale: 1 }}
        transition={step.state === 'active' && !reduce ? { repeat: Infinity, duration: 1.6 } : { duration: 0.2 }}
      >
        <AnimatePresence mode="popLayout" initial={false}>
          <motion.span
            key={step.state}
            initial={reduce ? false : { scale: 0.3, opacity: 0, rotate: -40 }}
            animate={{ scale: 1, opacity: 1, rotate: 0 }}
            exit={{ opacity: 0 }}
            transition={{ type: 'spring', stiffness: 420, damping: 20 }}
          >
            {view.icon}
          </motion.span>
        </AnimatePresence>
      </motion.span>
      <div className="path-text">
        <strong>{step.label}</strong>
        <span className="path-state">{view.text}</span>
        <small className="muted">{step.detail}</small>
      </div>
    </li>
  );
}

export default function ProgressPath({ steps }) {
  const reduce = useReducedMotion();
  // A packet travels a connector only when the previous step's state really changed to 'done' between API polls.
  const prev = useRef(null);
  const [advancedIds, setAdvancedIds] = useState({});
  useEffect(() => {
    const now = Object.fromEntries(steps.map(s => [s.id, s.state]));
    if (prev.current) {
      const hits = {};
      steps.forEach((s, i) => {
        if (i > 0 && prev.current[steps[i - 1].id] !== 'done' && steps[i - 1].state === 'done') hits[s.id] = Date.now();
      });
      if (Object.keys(hits).length) {
        setAdvancedIds(hits);
        const t = setTimeout(() => setAdvancedIds({}), 1200);
        prev.current = now;
        return () => clearTimeout(t);
      }
    }
    prev.current = now;
    return undefined;
  }, [steps]);

  return (
    <ol className="path" aria-label="Incident progress">
      {steps.map((step, index) => (
        <Step
          key={step.id}
          step={step}
          index={index}
          previous={steps[index - 1]}
          advanced={Boolean(advancedIds[step.id])}
          reduce={reduce}
        />
      ))}
    </ol>
  );
}
