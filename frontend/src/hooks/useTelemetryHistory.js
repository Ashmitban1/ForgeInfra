import { useEffect, useMemo, useState } from 'react';
import { getTelemetryHistory, getIncidentHistory } from '../api.js';
import { isDemoMode } from '../demo/fixtures.js';
import { descriptors, mergeReadings, readingOf } from '../lib/history.js';

export function useTelemetryHistory(devices, { incidents = [], sources = [], enabled = true } = {}) {
  const [history, setHistory] = useState({});
  const [error, setError] = useState(null);
  const sourceKey = JSON.stringify(descriptors(devices || [], incidents, sources));
  useEffect(() => {
    setHistory(previous => {
      const next = { ...previous };
      for (const device of devices || []) {
        const reading = readingOf(device);
        if (reading) next[device.device_id] = mergeReadings(next[device.device_id], [reading]);
      }
      return next;
    });
  }, [devices]);
  useEffect(() => {
    if (!enabled || isDemoMode()) { setError(null); return undefined; }
    const controller = new AbortController();
    const targets = JSON.parse(sourceKey);
    let timer;
    async function load() {
      const results = await Promise.allSettled(targets.map(async target => {
        const rows = await getTelemetryHistory({ ...target, limit: 1000, signal: controller.signal });
        return rows.map(row => readingOf(row.payload, row.event_id)).filter(Boolean);
      }));
      if (controller.signal.aborted) return;
      const additions = results.flatMap(result => result.status === 'fulfilled' ? result.value : []);
      setHistory(previous => {
        const next = { ...previous };
        for (const deviceId of new Set(additions.map(item => item.device_id))) {
          next[deviceId] = mergeReadings(next[deviceId], additions.filter(item => item.device_id === deviceId));
        }
        return next;
      });
      setError(results.find(result => result.status === 'rejected')?.reason || null);
      timer = setTimeout(load, 15000);
    }
    load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [sourceKey, enabled]);
  return { history, error };
}

export function useIncidentHistory(incidents = []) {
  const [state, setState] = useState({ events: [], error: null });
  const ids = useMemo(() => JSON.stringify(incidents.map(item => item.incident_id).sort().slice(0, 20)), [incidents]);
  useEffect(() => {
    if (isDemoMode()) return undefined;
    const controller = new AbortController();
    let timer;
    async function load() {
      const results = await Promise.allSettled(JSON.parse(ids).map(id => getIncidentHistory(id, { signal: controller.signal })));
      if (controller.signal.aborted) return;
      setState({ events: results.flatMap(result => result.status === 'fulfilled' ? result.value : []),
        error: results.find(result => result.status === 'rejected')?.reason || null });
      timer = setTimeout(load, 15000);
    }
    load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [ids]);
  return state;
}
