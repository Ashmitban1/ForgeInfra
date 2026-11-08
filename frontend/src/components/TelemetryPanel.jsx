import { formatDateTime, formatNumber } from '../lib/format.js';
import Sparkline from './Sparkline.jsx';
import { Badge, Fact } from './ui.jsx';

export default function TelemetryPanel({ device, readings }) {
  const hw = device.hardware ?? {};
  const fault = hw.cooling_fault === true;
  return (
    <div className="telemetry">
      <div className="metric-row">
        <div className="metric">
          <span className="metric-label">Temperature</span>
          <span className="metric-value">{formatNumber(hw.temperature_c)}<small> °C</small></span>
        </div>
        <div className="metric">
          <span className="metric-label">Humidity</span>
          <span className="metric-value">{formatNumber(hw.humidity_pct, 0)}<small> % RH</small></span>
        </div>
        <div className="metric">
          <span className="metric-label">Cooling fault</span>
          <span className="metric-value metric-badge">
            <Badge tone={fault ? 'fault' : 'ok'} icon={fault ? '▲' : '●'}>{fault ? 'Reported' : 'None reported'}</Badge>
            {hw.fault_is_simulated && <Badge tone="sample">Simulated flag</Badge>}
          </span>
        </div>
      </div>
      <dl className="facts">
        <Fact label="Device" mono>{device.device_id}</Fact>
        <Fact label="Source kind" mono>{hw.source_kind ?? '—'}</Fact>
        <Fact label="Sequence" mono>{hw.sequence ?? '—'}</Fact>
        <Fact label="Observed at">{formatDateTime(hw.observed_at)}</Fact>
        <Fact label="Received at">{formatDateTime(hw.received_at)}</Fact>
      </dl>
      <h3 className="subhead">Temperature observed in this tab</h3>
      <Sparkline readings={readings} />
    </div>
  );
}
