import { useEffect, useRef, useState } from 'react';
import { deviceHealth } from '../lib/health.js';

// Everything here is derived by diffing consecutive API responses. Nothing is scheduled or invented:
// if the backend does not change, no event is produced.

const MAX_EVENTS = 40;

// Emits a "pulse" for every reading the API reports that this tab has not seen before
// (new hardware.sequence / received_at). The first poll only seeds the baseline, so a page load
// never replays old readings as if they were live.
export function useReadingPulses(devices) {
  const seen = useRef(null);
  const counter = useRef(0);
  const [pulses, setPulses] = useState([]);

  useEffect(() => {
    if (!devices) return;
    const baseline = seen.current === null;
    if (baseline) seen.current = new Map();
    const fresh = [];
    for (const d of devices) {
      const hw = d.hardware;
      if (!hw) continue;
      const key = `${hw.source_kind}:${hw.sequence}:${hw.received_at}`;
      if (seen.current.get(d.device_id) === key) continue;
      seen.current.set(d.device_id, key);
      if (baseline || d.historical) continue;
      fresh.push({
        id: ++counter.current,
        deviceId: d.device_id,
        mismatch: d.reliability?.mismatch === true,
        fault: hw.cooling_fault === true || d.expected_status === 'WARNING',
      });
    }
    if (fresh.length) setPulses(prev => [...prev, ...fresh].slice(-8));
  }, [devices]);

  const dismiss = id => setPulses(prev => prev.filter(p => p.id !== id));
  return { pulses, dismiss };
}

// Emits an event whenever a device's derived health state differs from the previous poll.
export function useHealthTransitions(devices, history, now) {
  const last = useRef(null);
  const counter = useRef(0);
  const [transitions, setTransitions] = useState([]);

  useEffect(() => {
    if (!devices) return;
    const next = {};
    const fresh = [];
    for (const d of devices) {
      const state = deviceHealth(d, now, history[d.device_id]).state;
      next[d.device_id] = state;
      const before = last.current?.[d.device_id];
      if (last.current && before && before !== state) {
        fresh.push({ id: ++counter.current, deviceId: d.device_id, from: before, to: state, at: Date.now() });
      }
    }
    last.current = next;
    if (fresh.length) setTransitions(prev => [...fresh, ...prev].slice(0, MAX_EVENTS));
  }, [devices, history, now]);

  return transitions;
}

// Returns the ids of list items whose `signature` changed since the previous render
// (e.g. an incident whose investigation status moved). Used to flash only real progressions.
export function useChangedKeys(items, getKey, getSignature) {
  const prev = useRef(null);
  const [changed, setChanged] = useState({});

  useEffect(() => {
    if (!items) return;
    const sigs = {};
    const delta = {};
    for (const item of items) {
      const k = getKey(item);
      sigs[k] = getSignature(item);
      if (prev.current && prev.current[k] !== undefined && prev.current[k] !== sigs[k]) delta[k] = Date.now();
    }
    prev.current = sigs;
    if (Object.keys(delta).length) setChanged(c => ({ ...c, ...delta }));
    // getKey/getSignature are stable module-level functions at call sites
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items]);

  return changed;
}
