import assert from 'node:assert/strict';
import { test } from 'node:test';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../src/migaku-player-snippet.js', import.meta.url), 'utf8');
const helper = source.slice(source.indexOf('  function reportXPlayback('), source.indexOf('  async function playStream('));

function player() {
  const events = [], handlers = {};
  const context = { BRIDGE_ORIGIN: 'http://127.0.0.1:7000', fetch: async (_url, options) => {
    events.push(JSON.parse(options.body)); return { ok: true }; } };
  vm.createContext(context);
  vm.runInContext(helper, context);
  const video = { paused: true, readyState: 0, currentTime: 0, videoWidth: 0,
    addEventListener: (type, handler) => { handlers[type] = handler; },
    removeEventListener: type => { delete handlers[type]; } };
  return { context, video, events, emit: type => handlers[type]?.() };
}

test('Migaku confirmation requires advancing decoded video, not a successful resolver or play call', () => {
  const p = player();
  p.context.traceXPlayback(p.video, { x_capture_id: 'x-12345678-synthetic' }, true);
  p.emit('timeupdate');
  assert.equal(p.events.length, 1);
  assert.equal(p.events[0].stage, 'player_loading');
  Object.assign(p.video, { paused: false, readyState: 3, videoWidth: 1920, currentTime: 0.5 });
  p.emit('timeupdate');
  p.emit('timeupdate');
  assert.equal(p.events.filter(e => e.stage === 'player_playing').length, 1);
});

test('non-X streams emit no telemetry and X errors contain only safe numeric codes', () => {
  const p = player();
  p.context.traceXPlayback(p.video, {}, true);
  assert.equal(p.events.length, 0);
  p.context.reportXPlayback({ x_capture_id: 'x-12345678-synthetic' }, 'player_error', 'hls_network',
    { http: 403, url: 'private', cookie: 'private' });
  assert.ok(!JSON.stringify(p.events).includes('private'));
});
