import { safeHttpUrl } from '../../lib/format.js';

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
