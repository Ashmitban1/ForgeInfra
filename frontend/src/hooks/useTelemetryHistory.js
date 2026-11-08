import { useEffect, useState } from 'react';

const MAX_PER_DEVICE = 120;

// The API only exposes the latest reading per device. This records the readings this browser tab
// has actually observed while polling, so charts and the timeline never contain invented points.
export function useTelemetryHistory(devices) {
  const [history, setHistory] = useState({});

  useEffect(() => {
    if (!devices) return;
    setHistory(prev => {
      let next = prev;
      for (const device of devices) {
        const hw = device.hardware;
        if (!hw) continue;
        const key = `${hw.source_kind}:${hw.sequence}:${hw.received_at}`;
        const existing = next[device.device_id] || [];
        if (existing.some(r => r.key === key)) continue;
        const reading = {
          key,
          device_id: device.device_id,
          at: hw.received_at,
          observed_at: hw.observed_at,
          sequence: hw.sequence,
          source_kind: hw.source_kind,
          temperature_c: hw.temperature_c,
          humidity_pct: hw.humidity_pct,
          cooling_fault: hw.cooling_fault === true,
          fault_is_simulated: hw.fault_is_simulated,
          legacy_status: device.legacy_monitor?.status,
          expected_status: device.expected_status,
          mismatch: device.reliability?.mismatch === true,
          reasons: device.reliability?.reasons ?? [],
        };
        next = { ...next, [device.device_id]: [...existing, reading].slice(-MAX_PER_DEVICE) };
      }
      return next;
    });
  }, [devices]);

  return history;
}
