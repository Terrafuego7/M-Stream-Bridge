import assert from 'node:assert/strict';
import { test } from 'node:test';
import { selectXStream } from '../src/extension/x_bridge.js';
import { xDiagnosticReport } from '../src/extension/x_diagnostics.js';

const origin = 'http://127.0.0.1:7000';
const body = { stream_url: 'https://video.twimg.com/test/master.m3u8?token=private',
  stream_type: 'hls', capture_id: 'x-12345678-synthetic' };
const json = (data, status = 200) => ({ ok: status < 400, status, json: async () => data });

function scenario({ ignored = false, different = false, proxyStatus = 200, html = false, changed = false } = {}) {
  const calls = [];
  let confirmations = 0;
  const fetch = async (url, options = {}) => {
    calls.push({ url, options });
    if (url.endsWith('/set-stream')) return json(ignored ? { status: 'ignored' } : { status: 'ok', stream: {
      stream_url: different ? 'https://video.twimg.com/old.m3u8' : body.stream_url, stream_type: 'hls' } }, ignored ? 202 : 200);
    if (url.endsWith('/api/current-stream')) return json({ stream: {
      stream_url: changed && ++confirmations > 1 ? 'https://video.twimg.com/other.m3u8' : body.stream_url,
      x_capture_id: body.capture_id } });
    if (url.endsWith('/stream.m3u8')) return { ok: proxyStatus < 400, status: proxyStatus,
      text: async () => html ? '<html>error</html>' : '#EXTM3U\n#EXTINF:3,\n' + origin + '/proxy-segment?url=synthetic' };
    if (url.includes('/proxy-segment?')) return { ok: true, status: 200, arrayBuffer: async () => new Uint8Array([0, 1, 2]).buffer };
    if (url.endsWith('/api/x-playback')) return json({ status: 'ok' });
    throw Error('Unexpected test request');
  };
  return { fetch, calls };
}

test('extension selection checks acknowledgement, active identity and actual proxy bytes', async () => {
  const s = scenario();
  assert.equal(await selectXStream({ fetch: s.fetch, origin, body }), true);
  const event = s.calls.find(c => c.url.endsWith('/api/x-playback'));
  assert.deepEqual(JSON.parse(event.options.body), { capture_id: body.capture_id, stage: 'proxy_checked', code: 'ok' });
});

for (const [name, options, code] of [
  ['HTTP 202 ignored', { ignored: true }, 'not_selected'],
  ['a different stream retained by server', { different: true }, 'different_stream'],
  ['invalid proxy manifest', { html: true }, 'invalid_manifest'],
  ['active stream changes during the probe', { changed: true }, 'active_stream_changed'],
]) test(name + ' cannot report a valid capture', async () => {
  const s = scenario(options);
  await assert.rejects(selectXStream({ fetch: s.fetch, origin, body }), error => error.code === code);
  assert.ok(!s.calls.some(c => c.url.endsWith('/api/x-playback')));
});

test('a proxy 403 is reported at its stage and is never retried', async () => {
  const s = scenario({ proxyStatus: 403 });
  await assert.rejects(selectXStream({ fetch: s.fetch, origin, body }),
    error => error.stage === 'proxy_manifest' && error.http === 403 && !error.message.includes('private'));
  assert.equal(s.calls.filter(c => c.url.endsWith('/stream.m3u8')).length, 1);
});

test('diagnostic export never includes arbitrary fields, headers or media URLs', () => {
  const result = xDiagnosticReport({ extensionVersion: '3.0.10', serverVersion: '3.0.10',
    local: { stage: 'proxy_checked', code: 'ok', pageUrl: 'private', token: 'private' },
    server: { stage: 'player_error', cookie: 'private', events: [
      { stage: 'player_error', code: 'hls_network', http: 403, url: body.stream_url, headers: { cookie: 'private' } }] } });
  assert.equal(result.stage, 'player_error');
  assert.equal(result.http, 403);
  assert.ok(!JSON.stringify(result).includes('private'));
});
