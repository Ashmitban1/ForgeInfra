export const sampleKey = (deviceId, hw) => [deviceId, hw.source_kind, hw.sequence, hw.observed_at].join(':');
export function readingOf(sample, eventId) {
  const hw = sample?.hardware;
  if (!hw || !sample.device_id || !Number.isFinite(Date.parse(hw.observed_at))) return null;
  return { key: sampleKey(sample.device_id, hw), event_id: eventId, device_id: sample.device_id,
    at: hw.observed_at, observed_at: hw.observed_at, received_at: hw.received_at, sequence: hw.sequence,
    source_kind: hw.source_kind, temperature_c: hw.temperature_c, humidity_pct: hw.humidity_pct,
    cooling_fault: hw.cooling_fault, fault_is_simulated: hw.fault_is_simulated,
    legacy_status: sample.legacy_monitor?.status, expected_status: sample.expected_status,
    mismatch: sample.reliability?.mismatch ?? null, reasons: sample.reliability?.reasons || [] };
}
export function mergeReadings(previous = [], additions = [], limit = 1000) {
  const map = new Map(previous.map(item => [item.key, item]));
  for (const item of additions) if (item) map.set(item.key, { ...map.get(item.key), ...item });
  return [...map.values()].sort((a, b) => Date.parse(a.observed_at) - Date.parse(b.observed_at)).slice(-limit);
}
export function rackSources(devices = [], incidents = [], sources = []) {
  const map = new Map();
  for (const source of sources) {
    if (source.source_kind !== 'host_system' && source.latest?.hardware) {
      const device = source.latest;
      const before = map.get(device.device_id);
      if (!before || Date.parse(device.hardware.observed_at) > Date.parse(before.hardware.observed_at))
        map.set(device.device_id, { ...device, historical: true });
    }
  }
  for (const incident of incidents) {
    const before = map.get(incident.device_id);
    if (incident.hardware && (!before || Date.parse(incident.hardware.observed_at) > Date.parse(before.hardware.observed_at)))
      map.set(incident.device_id, { ...incident, historical: true });
  }
  for (const device of devices) map.set(device.device_id, { ...device, historical: false });
  return [...map.values()];
}
export function descriptors(devices = [], incidents = [], sources = []) {
  const map = new Map();
  for (const device of [...devices, ...incidents]) {
    if (device.hardware) map.set(device.hardware.source_kind + ':' + device.device_id,
      { sourceKind: device.hardware.source_kind, sourceId: device.device_id });
  }
  for (const source of sources) if (source.source_kind !== 'host_system') map.set(source.source_kind + ':' + source.source_id,
    { sourceKind: source.source_kind, sourceId: source.source_id });
  return [...map.values()];
}
