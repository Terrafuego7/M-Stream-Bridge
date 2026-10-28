const stages = new Set(['detection', 'resolver', 'selection', 'proxy', 'proxy_manifest', 'proxy_segment',
  'proxy_direct', 'waiting_for_tab', 'proxy_checked', 'selected', 'player_loading', 'player_playing',
  'player_error', 'audio_requested', 'audio_ready', 'audio_error', 'diagnostic']);
const codes = new Set(['ok', 'http_error', 'invalid_response', 'invalid_or_different_video', 'not_ready',
  'not_selected', 'different_stream', 'active_stream_changed', 'server_update_required', 'unexpected_resource',
  'invalid_manifest', 'empty_manifest', 'empty_media', 'invalid_mp4', 'too_many_playlists', 'timeout',
  'network_error', 'capture_changed', 'open_post', 'fragment_selected', 'hls_network', 'hls_media',
  'native_media', 'autoplay_blocked', 'unsupported_hls', 'no_video_element', 'proxy_required',
  'player_setup', 'audio_extract_failed', 'x_fragment_selected']);

export function xDiagnosticReport({ local = {}, server = {}, extensionVersion, serverVersion }) {
  const stage = local.state === 'error' || local.stage === 'waiting_for_tab'
    ? local.stage : server.stage || local.stage || 'detection';
  const report = { extension_version: /^\d+\.\d+\.\d+$/.test(extensionVersion || '') ? extensionVersion : 'source',
    server_version: /^\d+\.\d+\.\d+$/.test(serverVersion || server.server_version || '') ? serverVersion || server.server_version : 'unknown',
    stage: stages.has(stage) ? stage : 'detection', code: codes.has(local.code) ? local.code : 'ok',
    events: [] };
  if (Number.isInteger(local.http) && local.http >= 100 && local.http <= 599) report.http = local.http;
  for (const event of (server.events || []).slice(-20)) {
    if (!stages.has(event.stage) || !codes.has(event.code)) continue;
    const safe = { stage: event.stage, code: event.code };
    if (Number.isInteger(event.http) && event.http >= 100 && event.http <= 599) safe.http = event.http;
    if (Number.isInteger(event.media_error) && event.media_error >= 1 && event.media_error <= 4) safe.media_error = event.media_error;
    report.events.push(safe);
  }
  if (report.events.length && local.state !== 'error') {
    const last = report.events.at(-1);
    report.code = last.code;
    if (last.http) report.http = last.http;
  }
  return report;
}

export function xDiagnosticMessage(report) {
  if (report.code === 'fragment_selected' || report.code === 'x_fragment_selected')
    return 'X: an HLS fragment was selected. Open the post and capture its HLS master.';
  if (report.code === 'open_post') return 'X: open the post itself to capture its video.';
  if (report.stage === 'player_playing') return 'X: video is advancing in Migaku through Proxy.';
  if (report.stage === 'audio_requested') return 'X Full Mode: extracting audio; Migaku playback is unconfirmed.';
  if (report.stage === 'audio_ready') return 'X Full Mode: audio prepared; Migaku playback is unconfirmed.';
  if (report.stage.endsWith('error') || report.code !== 'ok')
    return `X stopped at ${report.stage} (${report.code}${report.http ? ', HTTP ' + report.http : ''}).`;
  if (report.stage === 'proxy_checked') return 'X proxy responds. Playback in Migaku is still unconfirmed.';
  if (report.stage === 'player_loading') return 'X: Migaku received the stream; waiting for decoded video.';
  if (report.stage === 'waiting_for_tab') return 'X resolved on server. Return to the X tab to select it.';
  return `X capture: ${report.stage}. Migaku playback is unconfirmed.`;
}
