import { useMemo, useState } from 'react';
import DataHall from '../components/DataHall.jsx';
import EventTimeline, { buildEvents } from '../components/EventTimeline.jsx';
import { useHealthTransitions, useReadingPulses } from '../hooks/useLiveEvents.js';
import IncidentList from '../components/IncidentList.jsx';
import MismatchEvidence from '../components/MismatchEvidence.jsx';
import RackCard from '../components/RackCard.jsx';
import TelemetryPanel from '../components/TelemetryPanel.jsx';
import { Panel, SkeletonRows, StateMessage } from '../components/ui.jsx';
import { deviceHealth } from '../lib/health.js';
import SystemHealth from '../components/SystemHealth.jsx';

function Kpi({ label, value, tone = 'info', hint }) {
  return (
    <div className={`kpi kpi-${tone}`}>
      <span className="kpi-label">{label}</span>
      <span className="kpi-value">{value}</span>
      {hint && <span className="kpi-hint">{hint}</span>}
    </div>
  );
}

function TelemetryGate({ state, children }) {
  const { data, error, loading, refresh } = state;
  if (loading) return <SkeletonRows rows={3} />;
  if (error && !data) {
    return (
      <StateMessage
        kind="error"
        title="Could not load telemetry"
        action={<button type="button" className="btn" onClick={refresh}>Retry</button>}
      >
        {error.message}
      </StateMessage>
    );
  }
  if (!data.length) {
    return (
      <StateMessage title="No devices reporting yet">
        Start the backend, then run <code>python hardware/simulator.py --mode normal</code> or connect the Arduino gateway.
      </StateMessage>
    );
  }
  return (
    <>
      {error && <p className="inline-error" role="alert">Refresh failed ({error.message}). Showing last data.</p>}
      {children(data)}
    </>
  );
}

export default function MissionControl({ telemetry, incidents, history, now, backend, persistedEvents = [], oversight = false }) {
  const [selectedId, setSelectedId] = useState(null);
  const devices = useMemo(() => telemetry.data ?? [], [telemetry.data]);

  const healthById = useMemo(
    () => Object.fromEntries(devices.map(d => [d.device_id, deviceHealth(d, now, history[d.device_id])])),
    [devices, now, history],
  );
  const selected =
    devices.find(d => d.device_id === selectedId) ??
    devices.find(d => healthById[d.device_id]?.mismatch || healthById[d.device_id]?.level === 'fault') ??
    devices[0];

  const { pulses, dismiss } = useReadingPulses(telemetry.data);
  const transitions = useHealthTransitions(telemetry.data, history, now);
  const events = useMemo(() => buildEvents(incidents.data, history, persistedEvents), [incidents.data, history, persistedEvents]);
  const openIncidents = (incidents.data ?? []).filter(i => i.status === 'OPEN').length;
  const faulted = devices.filter(d => healthById[d.device_id]?.level === 'fault').length;
  const mismatched = devices.filter(d => healthById[d.device_id]?.mismatch).length;
  const ready = Boolean(telemetry.data);
  const noValue = telemetry.error ? '—' : '…';
  const timelineUnavailable = !telemetry.data && !incidents.data && !(telemetry.loading || incidents.loading);

  const incidentPanel = (
    <Panel title="Live incidents" eyebrow="Polling every 3s" headingId="inc-h">
      <IncidentList state={incidents} />
    </Panel>
  );

  return (
    <div className={`page ${oversight ? 'page-oversight' : ''}`}>
      {oversight && incidentPanel}
      {!oversight && <div className="page-title">
        <span className="eyebrow">Mission Control</span>
        <h1>Data-center reliability</h1>
        <p className="muted">
          Compares hardware telemetry against the legacy monitor. Operational values come from the API; Demo mode uses explicitly labeled fixtures.
        </p>
      </div>}

      <div className="kpis" aria-label="Summary">
        <Kpi label="Known racks" value={ready ? devices.length : noValue} hint={ready ? devices.filter(device => !healthById[device.device_id]?.stale).length + ' with fresh observations' : ''} />
        <Kpi label="Cooling / expected faults" value={ready ? faulted : noValue} tone={!ready ? 'muted' : faulted ? 'fault' : 'ok'} />
        <Kpi label="Source mismatches" value={ready ? mismatched : noValue} tone={!ready ? 'muted' : mismatched ? 'fault' : 'ok'} hint={devices.some(device => !healthById[device.device_id]?.comparisonAvailable) ? devices.filter(device => !healthById[device.device_id]?.comparisonAvailable).length + ' comparisons unavailable' : 'legacy ≠ independent'} />
        <Kpi
          label="Open incidents"
          value={incidents.data ? openIncidents : incidents.error ? '—' : '…'}
          tone={!incidents.data ? 'muted' : openIncidents ? 'review' : 'ok'}
        />
      </div>
      <SystemHealth backend={backend} selectedDevice={selected} />

      <Panel title="Data hall" eyebrow="Racks and incident pipeline" headingId="hall-h" className="panel-hall">
        <DataHall
          devices={devices}
          history={history}
          now={now}
          incidents={incidents.data}
          telemetryError={Boolean(telemetry.error)}
          transitions={transitions}
          pulses={pulses}
          onPulseDone={dismiss}
          loading={telemetry.loading}
        />
      </Panel>

      <div className="grid-main">
        <div className="col">
          <Panel title="Server rack health" eyebrow="Live" headingId="racks-h">
            <TelemetryGate state={telemetry}>
              {list => (
                <>
                  <div className="rack-grid">
                    {list.map(device => (
                      <RackCard
                        key={device.device_id}
                        device={device}
                        history={history[device.device_id] ?? []}
                        now={now}
                        selected={device.device_id === selected?.device_id}
                        onSelect={setSelectedId}
                      />
                    ))}
                  </div>
                  <p className="note">
                    Racks come from current telemetry or persisted source/incident records. Stored observations retain their original timestamps.
                  </p>
                </>
              )}
            </TelemetryGate>
          </Panel>

          <div className="split">
            <Panel
              title={selected ? `Current telemetry · ${selected.device_id}` : 'Current telemetry'}
              eyebrow="Latest reading"
              headingId="tele-h"
            >
              <TelemetryGate state={telemetry}>
                {() => selected && <TelemetryPanel device={selected} readings={history[selected.device_id] ?? []} />}
              </TelemetryGate>
            </Panel>
            <Panel
              title={selected ? `Source mismatch evidence · ${selected.device_id}` : 'Source mismatch evidence'}
              eyebrow="Legacy vs independent"
              headingId="evidence-h"
            >
              <TelemetryGate state={telemetry}>
                {() => selected && <MismatchEvidence source={selected} />}
              </TelemetryGate>
            </Panel>
          </div>
        </div>

        <div className="col">
          {!oversight && incidentPanel}
          <Panel title="Event timeline" eyebrow="Newest first" headingId="events-h">
            {timelineUnavailable ? (
              <StateMessage kind="error" title="Timeline unavailable">
                No incident or telemetry data could be loaded from the API.
              </StateMessage>
            ) : incidents.loading || telemetry.loading ? (
              <SkeletonRows rows={4} />
            ) : (
              <EventTimeline events={events} />
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}
