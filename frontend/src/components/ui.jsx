import { animate, motion, useMotionValue, useMotionValueEvent, useReducedMotion } from 'motion/react';
import { useEffect, useState } from 'react';
import { DASH, formatNumber } from '../lib/format.js';

// Tweens to each new API value; renders the value immediately with reduced motion.
export function AnimatedNumber({ value, digits = 1 }) {
  const reduce = useReducedMotion();
  const mv = useMotionValue(typeof value === 'number' ? value : 0);
  const [text, setText] = useState(() => formatNumber(value, digits));
  useMotionValueEvent(mv, 'change', v => setText(v.toFixed(digits)));
  useEffect(() => {
    if (typeof value !== 'number' || !Number.isFinite(value)) { setText(DASH); return undefined; }
    if (reduce) { mv.set(value); setText(value.toFixed(digits)); return undefined; }
    const controls = animate(mv, value, { duration: 0.7, ease: 'easeOut' });
    return () => controls.stop();
  }, [value, digits, reduce, mv]);
  return <>{text}</>;
}

export function Panel({ title, eyebrow, actions, children, className = '', sample = false, headingId, ...rest }) {
  return (
    <motion.section
      className={`panel ${sample ? 'panel-sample' : ''} ${className}`}
      aria-labelledby={headingId}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
      {...rest}
    >
      <header className="panel-head">
        <div>
          {eyebrow && <span className="eyebrow">{eyebrow}</span>}
          <h2 id={headingId}>{title}</h2>
        </div>
        <div className="panel-actions">
          {sample && <SampleBadge>{typeof sample === 'string' ? sample : undefined}</SampleBadge>}
          {actions}
        </div>
      </header>
      {children}
    </motion.section>
  );
}

export function Badge({ tone = 'muted', icon, children }) {
  return (
    <span className={`badge badge-${tone}`}>
      {icon && <span aria-hidden="true">{icon}</span>}
      {children}
    </span>
  );
}

export function SampleBadge({ children = 'Sample — not from API' }) {
  return <span className="badge badge-sample">{children}</span>;
}

export function StateMessage({ kind = 'empty', title, children, action }) {
  const role = kind === 'error' ? 'alert' : 'status';
  return (
    <div className={`state state-${kind}`} role={role}>
      {kind === 'loading' && <span className="spinner" aria-hidden="true" />}
      <div>
        <strong>{title}</strong>
        {children && <p>{children}</p>}
      </div>
      {action}
    </div>
  );
}

export function SkeletonRows({ rows = 3 }) {
  return (
    <div className="skeletons" aria-hidden="true">
      {Array.from({ length: rows }, (_, i) => <span key={i} className="skeleton" />)}
    </div>
  );
}

export function Fact({ label, children, mono = false }) {
  return (
    <div className="fact">
      <dt>{label}</dt>
      <dd className={mono ? 'mono' : ''}>{children}</dd>
    </div>
  );
}
