import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { classifyStatus, describeFinding, describeToolCall } from '../../lib/health.js';
import { formatDateTime } from '../../lib/format.js';
import { Badge, StateMessage } from '../ui.jsx';

const TONE = { pending: 'muted', done: 'ok', failed: 'fault', active: 'info', unknown: 'review' };

function RawJson({ value }) {
  return (
    <details className="raw">
      <summary>Raw payload</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}

function StatusLine({ label, status }) {
  return (
    <p className="status-line">
      {label} <Badge tone={TONE[classifyStatus(status)]}>{status ?? 'missing'}</Badge>
    </p>
  );
}

export function NemotronActivity({ investigation }) {
  const inv = investigation ?? {};
  const calls = Array.isArray(inv.tool_calls) ? inv.tool_calls : [];
  const findings = Array.isArray(inv.findings) ? inv.findings : [];
  const evidence = Array.isArray(inv.evidence_ids) ? inv.evidence_ids : [];
  const pending = classifyStatus(inv.status) === 'pending';
  const running = classifyStatus(inv.status) === 'active';
  const reduce = useReducedMotion();
  return (
    <>
      <StatusLine label={`Agent ${inv.agent ?? 'unknown'} · investigation.status`} status={inv.status} />
      <h3 className="subhead">
        Tool calls ({calls.length})
        {running && <span className="live-dot" role="status"> Investigation reported as {inv.status}</span>}
      </h3>
      {calls.length === 0 ? (
        <StateMessage title={pending ? 'Investigation has not run' : 'No tool calls recorded'}>
          {pending
            ? 'Status is PENDING, so no Nemotron tool calls exist yet. The investigate route (proposed by Person 2) is not implemented in API v1.'
            : 'The API reports a non-pending status but an empty tool_calls list.'}
        </StateMessage>
      ) : (
        <ol className="tool-list">
          <AnimatePresence initial={false}>
          {calls.map((call, i) => {
            const view = describeToolCall(call, i);
            const kind = classifyStatus(view.status);
            return (
              <motion.li
                key={i}
                className={`tool tool-${kind}`}
                initial={reduce ? false : { opacity: 0, x: -16 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.3 }}
              >
                {kind === 'active' && !reduce && <span className="tool-scan" aria-hidden="true" />}
                <div className="tool-top">
                  <code>{view.name}</code>
                  {view.status && <Badge tone={TONE[classifyStatus(view.status)]}>{String(view.status)}</Badge>}
                  {view.at && <span className="muted">{formatDateTime(view.at)}</span>}
                </div>
                {view.raw && <RawJson value={view.raw} />}
              </motion.li>
            );
          })}
          </AnimatePresence>
        </ol>
      )}
      <h3 className="subhead">Findings ({findings.length})</h3>
      {findings.length === 0 ? (
        <p className="muted">No findings recorded.</p>
      ) : (
        <ul className="finding-list">
          {findings.map((finding, i) => {
            const view = describeFinding(finding);
            return (
              <li key={i}>
                {view.text && <p>{view.text}</p>}
                {view.raw && <RawJson value={view.raw} />}
              </li>
            );
          })}
        </ul>
      )}
      <h3 className="subhead">Evidence IDs ({evidence.length})</h3>
      {evidence.length === 0 ? (
        <p className="muted">None recorded.</p>
      ) : (
        <div className="chips">{evidence.map(id => <code key={String(id)} className="chip">{String(id)}</code>)}</div>
      )}
    </>
  );
}

export function GeminiRecommendation({ review }) {
  const r = review ?? {};
  const rec = r.recommendation;
  const pending = classifyStatus(r.status) === 'pending';
  return (
    <>
      <StatusLine label={`Reviewer ${r.reviewer ?? 'unknown'} · decision_review.status`} status={r.status} />
      {rec === null || rec === undefined ? (
        <StateMessage title={pending ? 'No recommendation yet' : 'No recommendation recorded'}>
          {pending
            ? 'Gemini has not produced a decision review for this incident (recommendation is null).'
            : 'The API reports a non-pending status but recommendation is null.'}
        </StateMessage>
      ) : typeof rec === 'string' ? (
        <blockquote className="recommendation">{rec}</blockquote>
      ) : (
        <>
          <dl className="facts">
            {Object.entries(rec).filter(([, v]) => ['string', 'number', 'boolean'].includes(typeof v)).map(([k, v]) => (
              <div className="fact" key={k}><dt>{k}</dt><dd>{String(v)}</dd></div>
            ))}
          </dl>
          <RawJson value={rec} />
        </>
      )}
    </>
  );
}
