import { useEffect, useState } from 'react';
import { getSystemMetrics, getTelemetryHistory, getTelemetrySummary } from '../api.js';
import { usePolling } from '../hooks/usePolling.js';
import { isDemoMode } from '../demo/fixtures.js';
import { Panel } from './ui.jsx';
import { formatNumber, formatTime } from '../lib/format.js';

function HostTrend({ rows, metric, label }) {
  const points = rows.map(row => ({ at: row.observed_at, value: row.payload?.[metric]?.utilization_pct }))
    .filter(point => Number.isFinite(point.value) && Number.isFinite(Date.parse(point.at)))
    .sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  if (points.length < 2) return <p className="muted">{label}: fewer than two stored observations.</p>;
  const first = Date.parse(points[0].at);
  const span = Date.parse(points.at(-1).at) - first || 1;
  const path = points.map(point => (5 + (Date.parse(point.at) - first) / span * 290) + ',' + (65 - point.value / 100 * 60)).join(' ');
  return <figure className="host-trend"><svg viewBox="0 0 300 70" role="img" aria-label={label + ', ' + points.length + ' stored observations'}>
    <polyline fill="none" stroke="currentColor" strokeWidth="2" points={path} />
  </svg><figcaption>{label} · {formatTime(points[0].at)} – {formatTime(points.at(-1).at)}</figcaption></figure>;
}

export default function SystemHealth({ backend, selectedDevice }) {
  const metrics = usePolling(signal => isDemoMode() ? Promise.resolve(null) : getSystemMetrics(signal), { intervalMs: 15000 });
  const [hostHistory, setHostHistory] = useState({ rows: [], error: null });
  const hostId = metrics.data?.source?.host_id;
  useEffect(() => {
    if (!hostId || isDemoMode() || backend?.telemetryStorage?.status === 'DISABLED') return undefined;
    const controller = new AbortController();
    let timer;
    async function load() {
      try {
        const rows = await getTelemetryHistory({ sourceKind: 'host_system', sourceId: hostId, signal: controller.signal });
        if (!controller.signal.aborted) setHostHistory({ rows, error: null });
      } catch (error) { if (!controller.signal.aborted) setHostHistory(previous => ({ ...previous, error })); }
      if (!controller.signal.aborted) timer = setTimeout(load, 30000);
    }
    load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [hostId, backend?.telemetryStorage?.status]);
  const [summary, setSummary] = useState({ buckets: [], error: null });
  const sourceKind = selectedDevice?.hardware?.source_kind;
  const sourceId = selectedDevice?.device_id;
  useEffect(() => {
    setSummary({ buckets: [], error: null });
    if (!sourceKind || !sourceId || isDemoMode() || backend?.telemetryStorage?.status === 'DISABLED') return undefined;
    const controller = new AbortController();
    let timer;
    async function load() {
      try {
        const buckets = await getTelemetrySummary({ sourceKind, sourceId, signal: controller.signal });
        if (!controller.signal.aborted) setSummary({ buckets, error: null });
      } catch (error) { if (!controller.signal.aborted) setSummary(previous => ({ ...previous, error })); }
      if (!controller.signal.aborted) timer = setTimeout(load, 30000);
    }
    load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [sourceKind, sourceId, backend?.telemetryStorage?.status]);
  const samples = summary.buckets.reduce((total, bucket) => total + bucket.sample_count, 0);
  const average = samples ? summary.buckets.reduce((total, bucket) => total + (bucket.temperature_c_avg || 0) * bucket.sample_count, 0) / samples : null;
  return <div className="split system-panels">
    <Panel title="Backend host CPU / RAM" eyebrow="Host system · not rack hardware" headingId="host-health-h">
      {isDemoMode() ? <p className="note">Host measurements are not mixed into demo fixtures.</p> : <>
        <p className="muted">Host: {metrics.data?.source?.host_id || '—'} · {metrics.data?.status || 'Loading'}</p>
        <dl className="facts"><div className="fact"><dt>CPU utilization</dt><dd>{formatNumber(metrics.data?.cpu?.utilization_pct)}%</dd></div><div className="fact"><dt>RAM utilization</dt><dd>{formatNumber(metrics.data?.memory?.utilization_pct)}%</dd></div></dl>
        <HostTrend rows={hostHistory.rows} metric="cpu" label="Backend host CPU history" />
        <HostTrend rows={hostHistory.rows} metric="memory" label="Backend host RAM history" />
        {hostHistory.error && <p className="inline-error" role="alert">{hostHistory.error.message}</p>}
        {metrics.error && <p className="inline-error" role="alert">{metrics.error.message}</p>}
        <p className="note">Measurements describe the machine running FastAPI. They do not measure Arduino rack CPU/RAM.</p>
      </>}
    </Panel>
    <Panel title="Stored telemetry analytics" eyebrow={sourceId || 'Select a rack'} headingId="analytics-h">
      <dl className="facts"><div className="fact"><dt>Samples in last hour</dt><dd>{samples}</dd></div><div className="fact"><dt>Mean temperature</dt><dd>{formatNumber(average)} °C</dd></div><div className="fact"><dt>Fault observations</dt><dd>{summary.buckets.reduce((total, bucket) => total + (bucket.fault_count || 0), 0)}</dd></div></dl>
      {summary.error && <p className="inline-error" role="alert">{summary.error.message}</p>}
      <p className="note">Aggregated from Tiger Data in five-minute buckets. Missing history is not a healthy reading.</p>
    </Panel>
  </div>;
}
