// South Park-only resolution. Generic capture and RTP remain separate.
export function southParkEpisode(value) {
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || !["southparkstudios.com", "www.southparkstudios.com"].includes(url.hostname)
        || url.port || url.username || url.password || url.hash) return null;
    const match = url.pathname.match(/^\/episodes\/([a-z0-9]{6})\/south-park-.+-season-([1-9]\d*)-ep-([1-9]\d*)\/?$/);
    return match ? { id: match[1], season: Number(match[2]), episode: Number(match[3]) } : null;
  } catch {
    return null;
  }
}

export function validSouthParkResult(result, pageUrl) {
  const episode = southParkEpisode(pageUrl);
  if (!episode || result?.status !== "ok" || result.episode_id !== episode.id
      || result.season !== episode.season || result.episode !== episode.episode) return false;
  try {
    const media = new URL(result.stream_url);
    return media.protocol === "https:" && media.hostname === "ns-stream.paramount.tech"
      && !media.port && !media.username && !media.password && !media.hash
      && media.pathname.endsWith("/master.m3u8");
  } catch {
    return false;
  }
}

export function createSouthParkCapture({ fetch, chrome, endpoint, publish, isActive }) {
  const states = new Map();
  const statusKey = tabId => `southpark:${tabId}`;
  async function status(tabId, pageUrl, state, message) {
    await chrome.storage.session.set({ [statusKey(tabId)]: { pageUrl, state, message } });
  }
  async function promote(tabId, entry) {
    const tab = await chrome.tabs.get(tabId);
    if (states.get(tabId) !== entry || tab.url !== entry.pageUrl || !isActive(tabId)) return;
    if (!await publish(tabId, entry.pageUrl, entry.result)) throw new Error("Bridge rejected the stream.");
  }
  async function capture(tabId, pageUrl, activate = false) {
    if (tabId < 0 || !southParkEpisode(pageUrl)) return;
    const cached = states.get(tabId);
    if (cached?.pageUrl === pageUrl) {
      if (cached.pending) return cached.pending;
      if (Date.now() - cached.at < (cached.result ? 60000 : 10000)) {
        if (activate && cached.result) {
          try { await promote(tabId, cached); } catch { await status(tabId, pageUrl, "error", "Bridge could not select this episode. Reload the page."); }
        }
        return;
      }
    }
    cached?.controller?.abort();
    const entry = { pageUrl, at: Date.now(), controller: new AbortController() };
    states.set(tabId, entry);
    entry.pending = (async () => {
      const timeout = setTimeout(() => entry.controller.abort(), 60000);
      try {
        await status(tabId, pageUrl, "resolving", "Checking South Park video and audio…");
        const response = await fetch(endpoint, { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ page_url: pageUrl }), signal: entry.controller.signal });
        if (response.status === 404) throw new Error("Update and restart the Bridge server to use South Park.");
        const result = await response.json();
        if (!response.ok) throw new Error(result.message || "South Park is unavailable.");
        if (!validSouthParkResult(result, pageUrl)) throw new Error("South Park returned an invalid or different episode.");
        if (states.get(tabId) !== entry) return;
        entry.result = result;
        await promote(tabId, entry);
        await status(tabId, pageUrl, "ready", `South Park HLS verified (${result.height}p). Use Proxy playback.`);
      } catch (error) {
        if (states.get(tabId) === entry) {
          entry.result = null;
          await status(tabId, pageUrl, "error", error.name === "AbortError"
            ? "South Park check timed out. Reload the episode to retry."
            : String(error.message || "South Park could not be reached.").slice(0, 200));
        }
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
    void chrome.storage.session.remove(statusKey(tabId));
  }
  return { capture, forget };
}
