import test from 'node:test';
import assert from 'node:assert/strict';
import { rackLayout, shortDeviceLabel } from '../src/lib/dataHallLayout.js';

const longId = 'SLACK-E2E-daeb88008fd6498596795e18f905b1a2';
const measure = text => Array.from(text).length * 7.5;

test('short rack IDs are unchanged; long labels retain a recognizable prefix and suffix', () => {
  assert.equal(shortDeviceLabel('RACK-01', 104), 'RACK-01');
  assert.equal(shortDeviceLabel(longId, 108), 'SLACK-E2E-…1a2');
  assert.equal(longId, 'SLACK-E2E-daeb88008fd6498596795e18f905b1a2');
});

test('truncation respects available SVG width, including wide glyphs and narrow bounds', () => {
  const wide = text => Array.from(text).reduce((sum, c) => sum + (c === 'W' ? 13 : 8), 0);
  for (const id of [longId, 'W'.repeat(200), '😀'.repeat(100), '温度传感器'.repeat(30)]) {
    for (const width of [0, 8, 24, 60, 104]) {
      assert.ok(wide(shortDeviceLabel(id, width, wide)) <= width);
    }
  }
});

test('rack widths remain readable with empty, single, multiple and overflow device counts', () => {
  for (const count of [0, 1, 2, 4, 8, 12]) {
    const layout = rackLayout(count);
    assert.equal(layout.count, Math.min(count, 8));
    assert.equal(layout.width, 128);
    assert.ok(Number.isFinite(layout.startX));
    assert.ok(layout.sceneWidth >= 960);
    for (let i = 0; i < layout.count; i++) {
      const x = layout.startX + i * (layout.width + layout.gap);
      assert.ok(x >= 40);
      assert.ok(x + layout.width <= layout.sceneWidth - 40);
      assert.ok(measure(shortDeviceLabel(longId, layout.width - 20)) <= layout.width - 20);
    }
  }
});
