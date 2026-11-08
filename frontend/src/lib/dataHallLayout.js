export const PIPELINE_WIDTH = 960;
export const MAX_VISIBLE_RACKS = 8;

// Keep text readable as devices arrive; the SVG viewport scrolls when necessary.
export function rackLayout(deviceCount) {
  const count = Math.min(MAX_VISIBLE_RACKS, Math.max(0, deviceCount));
  const width = 128;
  const gap = 24;
  const total = count ? count * width + (count - 1) * gap : 0;
  const sceneWidth = Math.max(PIPELINE_WIDTH, total + 80);
  return { count, width, gap, sceneWidth, startX: (sceneWidth - total) / 2 };
}

// Widths are SVG user units. The component supplies actual SVG font measurements.
// Prefix + ellipsis + a three-character suffix preserves recognizable identity.
export function shortDeviceLabel(id, maxWidth, measure = text => Array.from(text).length * 7.5) {
  const full = String(id ?? '');
  if (measure(full) <= maxWidth) return full;
  const chars = Array.from(full);
  const suffix = chars.slice(-3).join('');
  for (let length = Math.min(10, chars.length - 4); length >= 1; length--) {
    const candidate = chars.slice(0, length).join('') + '…' + suffix;
    if (measure(candidate) <= maxWidth) return candidate;
  }
  for (let length = Math.min(3, chars.length); length >= 0; length--) {
    const candidate = '…' + chars.slice(chars.length - length).join('');
    if (measure(candidate) <= maxWidth) return candidate;
  }
  return '';
}
