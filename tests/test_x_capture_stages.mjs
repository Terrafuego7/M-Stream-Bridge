import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createXCapture } from '../src/extension/x_capture.js';

const page = 'https://x.com/SpaceX/status/2104560708969259344';
const result = { status: 'ok', post_id: '2104560708969259344', video_index: 1,
  stream_type: 'hls', stream_url: 'https://video.twimg.com/test/master.m3u8?token=private', height: 1080 };

test('switching to Migaku before resolution finishes never reports a selected stream', async () => {
  const saved = {};
  let active = true, finish, published = 0;
  const capture = createXCapture({
    endpoint: 'http://127.0.0.1:7000/api/resolve-x',
    fetch: () => new Promise(resolve => { finish = resolve; }),
    isActive: () => active, publish: async () => { published++; return true; },
    chrome: { tabs: { get: async () => ({ url: page }) }, storage: { session: {
      set: async values => Object.assign(saved, values), remove: async () => {} } } },
  });
  const pending = capture.capture(1, page);
  await new Promise(resolve => setTimeout(resolve, 0));
  active = false;
  finish({ ok: true, status: 200, json: async () => result });
  await pending;
  assert.equal(published, 0);
  assert.notEqual(saved['x:1'].state, 'ready');
  assert.equal(saved['x:1'].stage, 'waiting_for_tab');
  active = true;
  await capture.capture(1, page, true);
  assert.equal(published, 1);
  assert.equal(saved['x:1'].stage, 'proxy_checked');
});

test('opening Migaku waits for an already pending resolution and selection', async () => {
  const saved = {};
  let finish, select, prepared = false;
  const capture = createXCapture({
    endpoint: 'http://127.0.0.1:7000/api/resolve-x',
    fetch: () => new Promise(resolve => { finish = resolve; }), isActive: () => true,
    publish: () => new Promise(resolve => { select = resolve; }),
    chrome: { tabs: { get: async () => ({ url: page }) }, storage: { session: {
      set: async values => Object.assign(saved, values), remove: async () => {} } } },
  });
  const pending = capture.capture(1, page);
  const opening = capture.prepare(1, page).then(() => { prepared = true; });
  await new Promise(resolve => setTimeout(resolve, 0));
  finish({ ok: true, status: 200, json: async () => result });
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(prepared, false);
  select(true);
  await Promise.all([pending, opening]);
  assert.equal(prepared, true);
  assert.equal(saved['x:1'].stage, 'proxy_checked');
});

test('network exceptions cannot put private URLs or tokens into popup diagnostics', async () => {
  const saved = {};
  const capture = createXCapture({
    endpoint: 'http://127.0.0.1:7000/api/resolve-x',
    fetch: async () => { throw Error('https://video.twimg.com/private?cookie=private'); },
    publish: async () => true, isActive: () => true,
    chrome: { tabs: { get: async () => ({ url: page }) }, storage: { session: {
      set: async values => Object.assign(saved, values), remove: async () => {} } } },
  });
  await capture.capture(1, page);
  assert.equal(saved['x:1'].code, 'network_error');
  assert.ok(!JSON.stringify(saved).includes('private'));
});
