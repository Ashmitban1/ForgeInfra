export const DASH = '—';

function parse(iso) {
  const ms = Date.parse(iso);
  return Number.isFinite(ms) ? ms : null;
}

export function formatTime(iso) {
  const ms = parse(iso);
  return ms === null ? DASH : new Date(ms).toLocaleTimeString([], { hour12: false });
}

export function formatDateTime(iso) {
  const ms = parse(iso);
  return ms === null ? DASH : new Date(ms).toLocaleString([], { hour12: false });
}

export function formatAge(seconds) {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return DASH;
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

export function ageSince(iso, nowMs) {
  const ms = parse(iso);
  return ms === null ? null : Math.max(0, (nowMs - ms) / 1000);
}

export function formatNumber(value, digits = 1) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : DASH;
}

export function safeHttpUrl(value) {
  if (typeof value !== 'string') return null;
  try {
    const url = new URL(value);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null;
  } catch {
    return null;
  }
}
