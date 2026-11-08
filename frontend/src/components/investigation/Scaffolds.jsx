import { safeHttpUrl } from '../../lib/format.js';
import { Badge } from '../ui.jsx';

// Illustrative layout content only. Nothing here comes from the API and no repair or test has run.
const SAMPLE_DIFF = [
  { kind: 'ctx', text: '--- a/example/legacy_monitor.py   (SAMPLE FILE NAME)' },
  { kind: 'ctx', text: '+++ b/example/legacy_monitor.py' },
  { kind: 'ctx', text: ' def check_status(reading):' },
  { kind: 'del', text: '-    return "WARNING" if reading.temperature_c > 35 else "NORMAL"' },
  { kind: 'add', text: '+    return "WARNING" if reading.cooling_fault or reading.temperature_c > 35 else "NORMAL"' },
];

const SAMPLE_TESTS = [
  'test_cooling_fault_raises_warning',
  'test_high_temperature_still_warns',
  'test_healthy_reading_stays_normal',
];

const DIFF_MARK = { add: '+', del: '−', ctx: ' ' };

export function SampleDiff() {
  return (
    <>
      <p className="note">
        Layout placeholder. Awaiting a repair-proposal route (<code>POST /api/incidents/{'{id}'}/repair</code>, proposed
        by Person 2, not implemented). This is not a real patch.
      </p>
      <div className="diff" role="group" aria-label="Sample code diff, not from API">
        {SAMPLE_DIFF.map((line, i) => (
          <div key={i} className={`diff-line diff-${line.kind}`}>
            <span className="diff-mark" aria-hidden="true">{DIFF_MARK[line.kind]}</span>
            <code>{line.kind === 'ctx' ? line.text : line.text.slice(1)}</code>
            {line.kind !== 'ctx' && <span className="sr-only">{line.kind === 'add' ? ' (added line)' : ' (removed line)'}</span>}
          </div>
        ))}
      </div>
    </>
  );
}

export function SampleTests() {
  return (
    <>
      <p className="note">
        Layout placeholder. No regression tests have been run for this incident, so every row is shown as not run.
      </p>
      <ul className="test-list">
        {SAMPLE_TESTS.map(name => (
          <li key={name}>
            <code>{name}</code>
            <Badge tone="muted">Not run (sample)</Badge>
          </li>
        ))}
      </ul>
    </>
  );
}

export function ApprovalActions() {
  return (
    <>
      <p className="note" id="approval-note">
        Approval is disabled until <code>POST /api/repairs/{'{id}'}/approve</code> exists (proposed, not implemented) and a
        repair has passing tests. Nothing is merged or deployed from this screen.
      </p>
      <div className="actions">
        <button type="button" className="btn btn-primary" disabled aria-describedby="approval-note">Approve repair</button>
        <button type="button" className="btn" disabled aria-describedby="approval-note">Reject</button>
      </div>
    </>
  );
}

function IntegrationValue({ value, href }) {
  if (value === null || value === undefined || value === '') return <span className="muted">Not recorded (null)</span>;
  const url = safeHttpUrl(href ?? value);
  return url ? <a href={url} target="_blank" rel="noreferrer noopener">{String(value)}</a> : <code>{String(value)}</code>;
}

export function IntegrationResults({ integrations }) {
  const i = integrations ?? {};
  const rows = [
    ['Jira issue key', i.jira_key, i.jira_url],
    ['Slack delivery', i.slack_status, null],
    ['Slack channel', i.slack_channel_id, null],
    ['Slack message timestamp', i.slack_message_ts ?? i.slack_message_id, null],
    ['GitHub PR', i.github_pr_url, null],
    ['Solana tx signature', i.solana_tx_signature, null],
  ];
  return (
    <>
      <dl className="facts facts-wide">
        {rows.map(([label, value, href]) => (
          <div className="fact" key={label}>
            <dt>{label}</dt>
            <dd><IntegrationValue value={value} href={href} /></dd>
          </div>
        ))}
      </dl>
      <p className="note">Values stay null until a real provider call returns an ID. The dashboard never fabricates them.</p>
    </>
  );
}
