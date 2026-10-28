import assert from 'node:assert/strict';
import { test } from 'node:test';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const directory = path.resolve(process.env.BRIDGE_EXTENSION_DIR || 'src/extension');
const southpark = 'https://www.southparkstudios.com/episodes/940f8z/south-park-test-season-1-ep-1';
const rtp = 'https://www.rtp.pt/play/p17247/e958623/ruido';
const xpost = 'https://x.com/SpaceX/status/2104560708969259344';
const xmaster = 'https://video.twimg.com/amplify_video/synthetic/pl/master.m3u8?tag=12&v=1';
const master = 'https://ns-stream.paramount.tech/h/synthetic/master.m3u8?mgid=fake&hdnts=fake';
let counter = 0;
async function worker(pageUrl, resolveError = false) {
  const calls = [], listeners = {}, storage = {};
  let selectedX = null;
  const event = name => ({ addListener: fn => { listeners[name] = fn; } });
  globalThis.self = { addEventListener() {}, skipWaiting() {} };
  globalThis.chrome = {
    tabs: {
      get: async id => ({ id, url: pageUrl, title: 'Test episode' }),
      query: (query, callback) => { const tabs = [{ id: 1, url: pageUrl }]; callback?.(tabs); return Promise.resolve(tabs); },
      sendMessage: async () => {}, onActivated: event('activated'), onRemoved: event('removed'), onUpdated: event('updated'),
    },
    storage: { session: { set: async values => Object.assign(storage, values), get: async () => storage, remove: async key => delete storage[key] } },
    webRequest: { onBeforeSendHeaders: event('before'), onCompleted: event('completed') },
    runtime: { onInstalled: event('installed'), onStartup: event('startup'), onMessage: event('message') },
  };
  globalThis.fetch = async (url, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : {};
    calls.push({ url, body });
    let result = { status: 'ok' };
    if (url.endsWith('/api/resolve-southpark')) result = { status: 'ok', stream_url: master,
      title: 'Test', season: 1, episode: 1, episode_id: '940f8z', height: 1080, request_headers: {} };
    if (resolveError && url.endsWith('/api/resolve-southpark')) return {
      ok: false, status: 422, json: async () => ({ status: 'error', message: 'Not available in your region.' }) };
    if (url.endsWith('/api/resolve-rtp')) result = { status: 'ok',
      stream_url: 'https://streaming-vod.rtp.pt/hls/p17247/index.m3u8', height: 1080, request_headers: {} };
    if (url.endsWith('/api/resolve-x')) result = { status: 'ok', stream_url: xmaster,
      stream_type: 'hls', title: 'SpaceX video', post_id: '2104560708969259344', video_index: 1,
      height: 2160, request_headers: {} };
    if (url.endsWith('/set-stream') && body.capture_source === 'x_resolver') {
      selectedX = { stream_url: body.stream_url, stream_type: body.stream_type, x_capture_id: body.capture_id };
      result = { status: 'ok', stream: selectedX };
    }
    if (url.endsWith('/api/current-stream') && selectedX) result = { status: 'ok', has_stream: true, stream: selectedX };
    if (url.endsWith('/stream.m3u8')) return { ok: true, status: 200,
      text: async () => '#EXTM3U\n#EXTINF:3,\nhttp://127.0.0.1:7000/proxy-segment?url=synthetic\n#EXT-X-ENDLIST' };
    if (url.includes('/proxy-segment?')) return { ok: true, status: 200, arrayBuffer: async () => new Uint8Array([0, 0, 1, 2]).buffer };
    return { ok: true, status: 200, json: async () => result };
  };
  await import(pathToFileURL(path.join(directory, 'service_worker.js')).href + '?test=' + (++counter));
  async function meta() {
    await new Promise(resolve => listeners.message({ type: 'bridge_ext_page_meta', page_url: pageUrl,
      title: 'Test episode', title_candidates: [], is_top_frame: true }, { frameId: 0, tab: { id: 1, url: pageUrl } }, resolve));
    for (let i = 0; i < 10; i++) await new Promise(resolve => setTimeout(resolve, 0));
  }
  return { calls, listeners, meta, storage };
}

test('South Park metadata resolves full master; generic hook and ad requests cannot replace it', async () => {
  const w = await worker(southpark);
  await w.listeners.before({ tabId: 1, initiator: 'https://www.southparkstudios.com', type: 'xmlhttprequest', url: 'https://ads.example/ad.m3u8' });
  assert.equal(w.calls.length, 0);
  await w.meta();
  const set = w.calls.filter(c => c.url.endsWith('/set-stream'));
  assert.equal(set.length, 1);
  assert.equal(set[0].body.stream_url, master);
  assert.equal(set[0].body.hls_master_url, master);
  assert.equal(set[0].body.capture_source, 'southpark_resolver');
  assert.equal(w.storage['southpark:1'].state, 'ready');
  await new Promise(resolve => w.listeners.message({ type: 'bridge_ext_page_hook', url: 'https://ads.example/ad.m3u8' },
    { tab: { id: 1, url: southpark } }, resolve));
  assert.equal(w.calls.filter(c => c.url.endsWith('/set-stream')).length, 1);
});

test('X post resolves its HLS master and rejects generic ad capture', async () => {
  const w = await worker(xpost);
  await w.listeners.before({ tabId: 1, initiator: 'https://x.com', type: 'xmlhttprequest',
    url: 'https://video.twimg.com/other/master.m3u8' });
  assert.equal(w.calls.length, 0);
  await w.meta();
  assert.ok(w.calls.some(c => c.url.endsWith('/api/resolve-x')));
  const set = w.calls.filter(c => c.url.endsWith('/set-stream'));
  assert.equal(set.length, 1);
  assert.equal(set[0].body.stream_url, xmaster);
  assert.equal(set[0].body.hls_master_url, xmaster);
  assert.equal(set[0].body.stream_type, 'hls');
  assert.equal(set[0].body.capture_source, 'x_resolver');
  assert.equal(w.storage['x:1'].state, 'proxy_checked');
  assert.equal(w.storage['x:1'].stage, 'proxy_checked');
  assert.ok(!/verified|playing/i.test(w.storage['x:1'].message));
  await new Promise(resolve => w.listeners.message({ type: 'bridge_ext_page_hook', url: 'https://video.twimg.com/other.mp4' },
    { tab: { id: 1, url: xpost } }, resolve));
  assert.equal(w.calls.filter(c => c.url.endsWith('/set-stream')).length, 1);
});

test('X result validation rejects foreign, DASH and another post; accepts direct MP4', async () => {
  const { validXResult, xPost } = await import(pathToFileURL(path.join(directory, 'x_capture.js')));
  const valid = { status: 'ok', post_id: '2104560708969259344', video_index: 1,
    stream_type: 'hls', stream_url: xmaster };
  assert.ok(validXResult(valid, xpost));
  assert.equal(xPost('https://x.com/'), null);
  assert.ok(validXResult({ ...valid, stream_type: 'direct',
    stream_url: 'https://video.twimg.com/amplify_video/synthetic/video.mp4?tag=12' }, xpost));
  for (const change of [{ post_id: '2104560708969259345' }, { video_index: 2 },
    { stream_url: xmaster.replace('video.twimg.com', 'evil.test') },
    { stream_url: xmaster.replace('.m3u8', '.mpd') }, { stream_url: 'invalid' }]) {
    assert.equal(validXResult({ ...valid, ...change }, xpost), false);
  }
});

test('X homepage does not trigger the resolver', async () => {
  const w = await worker('https://x.com/');
  await w.meta();
  assert.ok(!w.calls.some(c => c.url.endsWith('/api/resolve-x')));
});

test('X timeline init MP4 cannot be promoted or stored before post metadata arrives', async () => {
  const w = await worker('https://x.com/home');
  const fragment = 'https://video.twimg.com/amplify_video/1234567890/vid/avc1/0/0/1920x1080/init.mp4?token=synthetic';
  await w.listeners.before({ tabId: 1, initiator: 'https://x.com', type: 'xmlhttprequest', method: 'GET', url: fragment, requestHeaders: [] });
  await w.listeners.completed({ tabId: 1, initiator: 'https://x.com', type: 'xmlhttprequest', method: 'GET', url: fragment,
    statusCode: 200, responseHeaders: [{ name: 'Content-Type', value: 'video/mp4' }] });
  assert.ok(!w.calls.some(c => c.url.endsWith('/set-stream') || c.url.endsWith('/capture-request')));
});

test('RTP still uses its original resolver and HLS payload', async () => {
  const w = await worker(rtp);
  await w.meta();
  assert.ok(w.calls.some(c => c.url.endsWith('/api/resolve-rtp')));
  assert.ok(!w.calls.some(c => c.url.endsWith('/api/resolve-southpark')));
  const set = w.calls.find(c => c.url.endsWith('/set-stream'));
  assert.equal(set.body.capture_source, 'rtp_resolver');
  assert.equal(set.body.stream_url, 'https://streaming-vod.rtp.pt/hls/p17247/index.m3u8');
});

test('other sites retain generic webRequest capture', async () => {
  const w = await worker('https://example.org/watch/episode-1');
  await w.listeners.before({ tabId: 1, initiator: 'https://example.org', type: 'xmlhttprequest', method: 'GET',
    url: 'https://media.example.org/master.m3u8?sig=synthetic', requestHeaders: [] });
  assert.equal(w.calls.find(c => c.url.endsWith('/set-stream')).body.stream_url, 'https://media.example.org/master.m3u8?sig=synthetic');
  assert.ok(!w.calls.some(c => c.url.includes('/api/resolve-')));
});

test('other sites retain complete MP4 capture', async () => {
  const w = await worker('https://example.org/watch/video');
  await w.listeners.before({ tabId: 1, initiator: 'https://example.org', type: 'media', method: 'GET',
    url: 'https://media.example.org/1920x1080/full.mp4?sig=synthetic', requestHeaders: [] });
  const selected = w.calls.find(c => c.url.endsWith('/set-stream'));
  assert.equal(selected.body.stream_type, 'direct');
  assert.equal(selected.body.stream_url, 'https://media.example.org/1920x1080/full.mp4?sig=synthetic');
});

test('South Park homepage never resolves an episode', async () => {
  const w = await worker('https://www.southparkstudios.com/');
  await w.meta();
  assert.ok(!w.calls.some(c => c.url.includes('/api/resolve-')));
});

test('South Park result validation rejects foreign URLs, DASH and different episodes', async () => {
  const { validSouthParkResult } = await import(pathToFileURL(path.join(directory, 'southpark_capture.js')));
  const valid = { status: 'ok', episode_id: '940f8z', season: 1, episode: 1, stream_url: master };
  assert.ok(validSouthParkResult(valid, southpark));
  for (const change of [{ episode_id: 'xxxxxx' }, { episode: 2 }, { stream_url: 'invalid' },
    { stream_url: master.replace('ns-stream.paramount.tech', 'evil.test') },
    { stream_url: master.replace('master.m3u8', 'manifest.mpd') }]) {
    assert.equal(validSouthParkResult({ ...valid, ...change }, southpark), false);
  }
});

test('a regional denial is visible and never replaces the current stream', async () => {
  const w = await worker(southpark, true);
  await w.meta();
  assert.ok(!w.calls.some(c => c.url.endsWith('/set-stream')));
  assert.equal(w.storage['southpark:1'].state, 'error');
  assert.match(w.storage['southpark:1'].message, /region/);
});

test('navigation during resolution cannot promote the previous episode', async () => {
  const { createSouthParkCapture } = await import(pathToFileURL(path.join(directory, 'southpark_capture.js')));
  let finish, currentUrl = southpark, published = 0;
  const capture = createSouthParkCapture({
    endpoint: 'http://127.0.0.1:7000/api/resolve-southpark',
    fetch: () => new Promise(resolve => { finish = resolve; }), isActive: () => true,
    publish: async () => { published++; return true; },
    chrome: { tabs: { get: async () => ({ url: currentUrl }) }, storage: { session: { set: async () => {}, remove: async () => {} } } },
  });
  const task = capture.capture(1, southpark);
  await new Promise(resolve => setTimeout(resolve, 0));
  currentUrl = southpark.replace('ep-1', 'ep-2');
  finish({ ok: true, status: 200, json: async () => ({ status: 'ok', episode_id: '940f8z', season: 1, episode: 1, height: 1080, stream_url: master }) });
  await task;
  assert.equal(published, 0);
});
