import { useState } from 'react';
import { formatNumber, formatTime } from '../lib/format.js';

const W = 360;
const H = 110;
const PAD = { l: 38, r: 12, t: 12, b: 22 };

export default function Sparkline({ readings }) {
  const [hover, setHover] = useState(null);
  const points = readings.filter(r => Number.isFinite(r.temperature_c) && Number.isFinite(Date.parse(r.at)));

  if (points.length < 2) {
    return (
      <p className="muted spark-empty" role="status">
        {points.length === 0 ? 'No stored readings are available for this window.' : 'One observation is available.'} The chart uses actual stored and current observations.
      </p>
    );
  }

  const times = points.map(p => Date.parse(p.at));
  const t0 = times[0];
  const span = times[times.length - 1] - t0 || 1;
  const dataMin = Math.min(...points.map(p => p.temperature_c));
  const dataMax = Math.max(...points.map(p => p.temperature_c));
  let lo = dataMin;
  let hi = dataMax;
  if (hi - lo < 2) { const mid = (hi + lo) / 2; lo = mid - 1; hi = mid + 1; }
  const x = i => PAD.l + ((times[i] - t0) / span) * (W - PAD.l - PAD.r);
  const y = v => PAD.t + (1 - (v - lo) / (hi - lo)) * (H - PAD.t - PAD.b);
  const path = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(p.temperature_c).toFixed(1)}`).join(' ');
  const activeIndex = Math.min(hover ?? points.length - 1, points.length - 1);
  const active = points[activeIndex];
  const last = points.length - 1;

  const onPointer = event => {
    const box = event.currentTarget.getBoundingClientRect();
    const px = ((event.clientX - box.left) / box.width) * W;
    let best = 0;
    for (let i = 1; i < points.length; i++) if (Math.abs(x(i) - px) < Math.abs(x(best) - px)) best = i;
    setHover(best);
  };
  const onKey = event => {
    if (event.key === 'ArrowLeft') { event.preventDefault(); setHover(Math.max(0, activeIndex - 1)); }
    if (event.key === 'ArrowRight') { event.preventDefault(); setHover(Math.min(last, activeIndex + 1)); }
    if (event.key === 'Escape') setHover(null);
  };

  return (
    <figure className="spark">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`Stored and current temperature readings, ${points.length} points ranging from ${formatNumber(dataMin)} to ${formatNumber(dataMax)} degrees Celsius. Use arrow keys to inspect points.`}
        tabIndex={0}
        onKeyDown={onKey}
        onBlur={() => setHover(null)}
        onPointerMove={onPointer}
        onPointerLeave={() => setHover(null)}
      >
        {[lo, hi].map(v => (
          <g key={v}>
            <line className="spark-grid" x1={PAD.l} x2={W - PAD.r} y1={y(v)} y2={y(v)} />
            <text className="spark-axis" x={PAD.l - 6} y={y(v) + 3} textAnchor="end">{formatNumber(v)}</text>
          </g>
        ))}
        <text className="spark-axis" x={PAD.l} y={H - 5}>{formatTime(points[0].at)}</text>
        <text className="spark-axis" x={W - PAD.r} y={H - 5} textAnchor="end">{formatTime(points[last].at)}</text>
        <path className="spark-line" d={path} />
        {points.map((p, i) => p.cooling_fault && (
          <circle key={p.key} className="spark-fault" cx={x(i)} cy={y(p.temperature_c)} r="4.5" />
        ))}
        <circle className="spark-end" cx={x(last)} cy={y(points[last].temperature_c)} r="4.5" />
        {hover !== null && (
          <g>
            <line className="spark-cross" x1={x(activeIndex)} x2={x(activeIndex)} y1={PAD.t} y2={H - PAD.b} />
            <circle className="spark-active" cx={x(activeIndex)} cy={y(active.temperature_c)} r="5" />
          </g>
        )}
      </svg>
      <figcaption>
        <span className="mono">
          {formatNumber(active.temperature_c)} °C · {formatTime(active.at)}
          {active.cooling_fault ? ' · cooling fault reported' : ''}
        </span>
        <span className="muted">
          <span className="legend-dot legend-fault" aria-hidden="true" /> Red markers: readings with cooling_fault = true
        </span>
      </figcaption>
      <details className="spark-table">
        <summary>Table view (last {Math.min(10, points.length)})</summary>
        <table>
          <thead><tr><th scope="col">Received</th><th scope="col">°C</th><th scope="col">% RH</th><th scope="col">Cooling fault</th></tr></thead>
          <tbody>
            {points.slice(-10).reverse().map(p => (
              <tr key={p.key}>
                <td>{formatTime(p.at)}</td><td>{formatNumber(p.temperature_c)}</td>
                <td>{formatNumber(p.humidity_pct, 0)}</td><td>{p.cooling_fault ? 'Yes' : 'No'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
