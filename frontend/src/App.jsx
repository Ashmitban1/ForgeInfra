import { useEffect, useState } from 'react';

const API = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';
export default function App() {
  const [devices, setDevices] = useState([]);
  const [incidents, setIncidents] = useState([]);
  const [state, setState] = useState('Connecting');
  async function load() {
    try {
      const responses = await Promise.all([
        fetch(`${API}/health`), fetch(`${API}/api/telemetry/latest`), fetch(`${API}/api/incidents`)
      ]);
      if (responses.some(r => !r.ok)) throw new Error('API returned an error');
      const [health, telemetry, queue] = await Promise.all(responses.map(r => r.json()));
      setState(health.status === 'ok' ? 'Online' : 'Unavailable');
      setDevices(telemetry.devices || []);
      setIncidents(queue.incidents || []);
    } catch (error) { setState(`Offline: ${error.message}`); }
  }
  useEffect(() => { load(); const id = setInterval(load, 3000); return () => clearInterval(id); }, []);
  return <main className="container">
    <header><div><span className="eyebrow">HACKUTD · FACTORYOS MVP</span><h1>Mission Control</h1><p>Real sensor inputs and information reliability</p></div><button onClick={load}>Refresh</button></header>
    <div className="status">Backend: {state} · Devices: {devices.length} · Incidents: {incidents.length}</div>
    <div className="columns">
      <section><h2>Latest telemetry</h2>{devices.length === 0 ? <p>No readings. Run the simulator or connect Arduino.</p> : devices.map(d =>
        <article key={d.device_id}><div className="heading"><strong>{d.device_id}</strong><span className={d.reliability?.mismatch?'bad':'good'}>{d.reliability?.mismatch?'Mismatch':'No mismatch'}</span></div>
        <p>{d.hardware?.temperature_c}°C · {d.hardware?.humidity_pct}% RH · Cooling fault: {String(d.hardware?.cooling_fault)} (simulated)</p>
        <p>Legacy: {d.legacy_monitor?.status} · Expected: {d.expected_status}</p>
        <small>Source: {d.hardware?.source_kind} | {d.reliability?.reasons?.join(', ') || 'No issues detected'}</small></article>)}</section>
      <section><h2>Incidents</h2>{incidents.length === 0 ? <p>No incidents yet.</p> : incidents.map(i =>
        <article key={i.incident_id}><div className="heading"><strong>{i.incident_id}</strong><span className="bad">{i.severity}</span></div>
        <p>{i.device_id} · {i.status}</p><small>Nemotron: {i.investigation?.status} · Gemini: {i.decision_review?.status} · Jira: {i.integrations?.jira_key || 'not connected'}</small></article>)}</section>
    </div>
    <footer>Prototype only: AI, Jira, Slack, Solana, and cloud integrations are not yet implemented.</footer>
  </main>;
}
