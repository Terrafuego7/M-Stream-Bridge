// X-only checks at the extension origin. Never include upstream URLs in errors.
export class XStageError extends Error {
  constructor(stage, code, http = null) {
    super(`X capture stopped at ${stage} (${code}).`);
    this.stage = stage;
    this.code = code;
    this.http = http;
  }
}

async function jsonResponse(response, stage) {
  if (!response.ok) throw new XStageError(stage, 'http_error', response.status);
  try { return await response.json(); }
  catch { throw new XStageError(stage, 'invalid_response', response.status); }
}

async function sample(response) {
  if (!response.body?.getReader) return new Uint8Array(await response.arrayBuffer());
  const reader = response.body.getReader();
  try { return (await reader.read()).value || new Uint8Array(); }
  finally { await reader.cancel().catch(() => {}); }
}

function localResource(value, base, origin) {
  const url = new URL(value, base);
  if (url.origin !== origin || url.pathname !== '/proxy-segment')
    throw new XStageError('proxy_manifest', 'unexpected_resource');
  return url.href;
}

export async function checkXProxy({ fetch, origin, streamType, signal }) {
  let address = origin + (streamType === 'hls' ? '/stream.m3u8' : '/stream-direct');
  if (streamType === 'direct') {
    const response = await fetch(address, { headers: { Range: 'bytes=0-1023' }, cache: 'no-store', signal });
    if (!response.ok) throw new XStageError('proxy_direct', 'http_error', response.status);
    const bytes = await sample(response);
    if (String.fromCharCode(...bytes.slice(4, 8)) !== 'ftyp') throw new XStageError('proxy_direct', 'invalid_mp4');
    return;
  }
  for (let depth = 0; depth < 3; depth++) {
    const response = await fetch(address, { cache: 'no-store', signal });
    if (!response.ok) throw new XStageError('proxy_manifest', 'http_error', response.status);
    const text = await response.text();
    if (text.length > 1024 * 1024 || !text.trimStart().startsWith('#EXTM3U'))
      throw new XStageError('proxy_manifest', 'invalid_manifest');
    const lines = text.split(/\r?\n/);
    const first = lines.find(line => line.trim() && !line.startsWith('#'));
    if (!first) throw new XStageError('proxy_manifest', 'empty_manifest');
    const next = localResource(first.trim(), address, origin);
    if (text.includes('#EXTINF:')) {
      const response = await fetch(next, { headers: { Range: 'bytes=0-1023' }, cache: 'no-store', signal });
      if (!response.ok) throw new XStageError('proxy_segment', 'http_error', response.status);
      const bytes = await sample(response);
      if (!bytes.length || /^\s*(?:<|\{)/.test(new TextDecoder().decode(bytes.slice(0, 32))))
        throw new XStageError('proxy_segment', 'empty_media');
      return;
    }
    address = next;
  }
  throw new XStageError('proxy_manifest', 'too_many_playlists');
}

export async function selectXStream({ fetch, origin, body, signal, phase = async () => {} }) {
  await phase('selection');
  const response = await fetch(origin + '/set-stream', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal });
  const selected = await jsonResponse(response, 'selection');
  if (response.status !== 200 || selected.status !== 'ok') throw new XStageError('selection', 'not_selected', response.status);
  if (selected.stream?.stream_url !== body.stream_url || selected.stream?.stream_type !== body.stream_type)
    throw new XStageError('selection', 'different_stream');
  const confirm = async () => {
    const active = await jsonResponse(await fetch(origin + '/api/current-stream', { cache: 'no-store', signal }), 'selection');
    if (active.stream?.stream_url !== body.stream_url) throw new XStageError('selection', 'active_stream_changed');
    if (active.stream?.x_capture_id !== body.capture_id) throw new XStageError('selection', 'server_update_required');
  };
  await confirm();
  await phase('proxy');
  await checkXProxy({ fetch, origin, streamType: body.stream_type, signal });
  await confirm();
  const trace = await fetch(origin + '/api/x-playback', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, signal,
    body: JSON.stringify({ capture_id: body.capture_id, stage: 'proxy_checked', code: 'ok' }) });
  if (!trace.ok) throw new XStageError('diagnostic', 'server_update_required', trace.status);
  return true;
}
