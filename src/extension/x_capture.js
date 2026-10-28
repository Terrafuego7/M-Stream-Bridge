// Capture only the media explicitly attached to a public X post.
import { XStageError } from './x_bridge.js';
export function xPost(value) {
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || !["x.com", "www.x.com", "twitter.com", "www.twitter.com"].includes(url.hostname)
        || url.port || url.username || url.password || url.hash) return null;
    const match = url.pathname.match(/^\/([A-Za-z0-9_]{1,15})\/status\/(\d{10,20})(?:\/video\/([1-4]))?\/?$/);
    return match ? { handle: match[1].toLowerCase(), id: match[2], videoIndex: Number(match[3] || 1) } : null;
  } catch {
    return null;
  }
}

export function validXResult(result, pageUrl) {
  const post = xPost(pageUrl);
  if (!post || result?.status !== "ok" || result.post_id !== post.id
      || result.video_index !== post.videoIndex || !["hls", "direct"].includes(result.stream_type)) return false;
  try {
    const media = new URL(result.stream_url);
    return media.protocol === "https:" && media.hostname === "video.twimg.com"
      && !media.port && !media.username && !media.password && !media.hash
      && !isXFragment(result.stream_url)
      && media.pathname.toLowerCase().endsWith(result.stream_type === "hls" ? ".m3u8" : ".mp4");
  } catch {
    return false;
  }
}

export function isXFragment(value) {
  try {
    const url = new URL(value);
    return url.hostname === 'video.twimg.com' && /^\/(?:amplify_video|ext_tw_video)\/\d+\/(?:vid|aud)\/[^/]+\/(?:\d+\/){2,}[^/]+(?:\/[^/]+)?\.(?:mp4|m4a|m4s)$/i.test(url.pathname);
  } catch { return false; }
}

export function createXCapture({ fetch, chrome, endpoint, publish, isActive }) {
  const states = new Map();
  const key = tabId => `x:${tabId}`;
  async function status(tabId, pageUrl, state, message, stage = state, code = 'ok', http = null) {
    const entry = states.get(tabId);
    if (!entry || entry.pageUrl !== pageUrl) return;
    entry.stage = stage;
    const value = { pageUrl, state, message, stage, code, http, captureId: entry.captureId,
      streamType: entry.result?.stream_type || null, at: Date.now() };
    await chrome.storage.session.set({ [key(tabId)]: value, 'x:last': value });
    console.info('[Bridge X]', { captureId: entry.captureId, stage, code, http });
  }
  async function promote(tabId, entry) {
    const tab = await chrome.tabs.get(tabId);
    if (states.get(tabId) !== entry || tab.url !== entry.pageUrl) return false;
    if (!isActive(tabId)) {
      await status(tabId, entry.pageUrl, 'waiting', 'X resolved on server. Return to the X tab to select it.', 'waiting_for_tab');
      return false;
    }
    const phase = async stage => status(tabId, entry.pageUrl, 'checking',
      stage === 'selection' ? 'Selecting X video on Bridge…' : 'Checking X through the extension and proxy…', stage);
    await phase('selection');
    if (!await publish(tabId, entry.pageUrl, entry.result, entry.captureId, entry.controller.signal, phase))
      throw new XStageError('selection', 'not_selected');
    if (states.get(tabId) !== entry) return false;
    await status(tabId, entry.pageUrl, 'proxy_checked',
      'X proxy responds. Playback in Migaku is still unconfirmed.', 'proxy_checked');
    return true;
  }
  async function rejected(tabId, entry, error) {
    if (states.get(tabId) !== entry) return;
    entry.result = null;
    const stage = error instanceof XStageError ? error.stage : entry.stage || 'resolver';
    const code = error.name === 'AbortError' ? 'timeout' : error instanceof XStageError ? error.code : 'network_error';
    await status(tabId, entry.pageUrl, 'error', `X capture stopped at ${stage} (${code}).`, stage, code, error.http || null);
  }
  async function capture(tabId, pageUrl, activate = false) {
    if (tabId < 0 || !xPost(pageUrl)) return;
    const cached = states.get(tabId);
    if (cached?.pageUrl === pageUrl) {
      if (cached.pending) return cached.pending;
      if (Date.now() - cached.at < (cached.result ? 60000 : 10000)) {
        if (activate && cached.result) {
          try { await promote(tabId, cached); }
          catch (error) { await rejected(tabId, cached, error); }
        }
        return;
      }
    }
    cached?.controller?.abort();
    const entry = { pageUrl, at: Date.now(), controller: new AbortController(), captureId: 'x-' + crypto.randomUUID() };
    states.set(tabId, entry);
    entry.pending = (async () => {
      const timeout = setTimeout(() => entry.controller.abort(), 60000);
      try {
        await status(tabId, pageUrl, 'checking', 'Checking X on the server…', 'resolver');
        const response = await fetch(endpoint, { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ page_url: pageUrl }), signal: entry.controller.signal });
        if (!response.ok) throw new XStageError('resolver', 'http_error', response.status);
        let result;
        try { result = await response.json(); }
        catch { throw new XStageError('resolver', 'invalid_response'); }
        if (!validXResult(result, pageUrl)) throw new XStageError('resolver', 'invalid_or_different_video');
        if (states.get(tabId) !== entry) return;
        entry.result = result;
        await promote(tabId, entry);
      } catch (error) {
        await rejected(tabId, entry, error);
      } finally {
        clearTimeout(timeout);
        entry.pending = null;
        entry.at = Date.now();
      }
    })();
    return entry.pending;
  }
  function forget(tabId) {
    states.get(tabId)?.controller?.abort();
    states.delete(tabId);
    void chrome.storage.session.remove(key(tabId));
  }
  async function prepare(tabId, pageUrl) {
    await capture(tabId, pageUrl, true);
    const entry = states.get(tabId);
    if (entry?.stage !== 'proxy_checked') throw new XStageError(entry?.stage || 'detection', 'not_ready');
  }
  return { capture, forget, prepare };
}
