from __future__ import annotations
from dataclasses import dataclass
import json
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from uuid import UUID
import requests
PAGE_HOSTS = frozenset({'southparkstudios.com', 'www.southparkstudios.com'})
SERVICE_HOST = 'topaz.paramount.tech'
PLAYLIST_HOST = 'ns-stream.paramount.tech'
MEDIA_HOSTS = frozenset({PLAYLIST_HOST, 'southpark.orchestrator.viacomcbs-tech.com'})
PAGE_PATH = re.compile('^/episodes/([a-z0-9]{6})/south-park-.+-season-([1-9]\\d*)-ep-([1-9]\\d*)/?$')
OPTIONAL_TEMPLATES = {'advertId', 'ssus', 'bundle', 'idfv', 'deviceType', 'gppString', 'gppSid'}
USER_AGENT = 'Mozilla/5.0'

class SouthParkError(Exception):

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code

def fail(code, message):
    raise SouthParkError(code, message)

def allowed_url(value: str, hosts) -> bool:
    try:
        p = urlsplit(value)
        return p.scheme == 'https' and p.hostname in hosts and (p.port is None) and (not p.username) and (not p.password) and (not p.fragment) and (not any((c in value for c in '\r\n\\')))
    except (TypeError, ValueError):
        return False

def episode_page(value: str) -> dict | None:
    if not allowed_url(value, PAGE_HOSTS):
        return None
    match = PAGE_PATH.fullmatch(urlsplit(value).path)
    if not match:
        return None
    return {'episode_id': match[1], 'season': int(match[2]), 'episode': int(match[3])}

def _objects(value):
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            yield item
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)

def parse_episode(html: str, page_url: str) -> dict:
    expected = episode_page(page_url)
    if not expected:
        fail('invalid_page', 'Open a South Park Studios episode page.')
    match = re.search('window\\.__DATA__\\s*=\\s*', html)
    try:
        if not match:
            raise ValueError()
        data, _ = json.JSONDecoder().raw_decode(html[match.end():].lstrip())
    except (ValueError, RecursionError):
        fail('page_changed', 'South Park episode data was not found.')
    matches = []
    for item in _objects(data):
        detail = item.get('videoDetail')
        if not isinstance(detail, dict) or detail.get('shortId') != expected['episode_id']:
            continue
        if detail.get('entityType') != 'episode' or str(detail.get('seasonNumber')) != str(expected['season']) or str(detail.get('episodeNumber')) not in {str(expected['episode']), f"{expected['episode']:02}", f"{expected['season']:02}{expected['episode']:02}"}:
            fail('episode_mismatch', 'South Park returned a different episode.')
        if detail.get('authRequired') is not False:
            fail('authentication', 'This South Park episode requires authentication.')
        if detail.get('lockedLabel') or detail.get('unavailableSlate'):
            fail('unavailable', 'This South Park episode is unavailable.')
        mgid = str(detail.get('mgid') or '')
        try:
            asset_id = str(UUID(mgid.rsplit(':', 1)[-1]))
        except ValueError:
            fail('episode_mismatch', 'South Park episode identity is invalid.')
        if not mgid.startswith('mgid:arc:episode:'):
            fail('episode_mismatch', 'South Park content is not an episode.')
        service = service_url(str(detail.get('videoServiceUrl') or ''), asset_id)
        matches.append({**expected, 'asset_id': asset_id, 'service_url': service, 'title': str(detail.get('title') or 'South Park')[:180]})
    if not matches:
        fail('episode_mismatch', 'The requested episode was not found in the page.')
    if len({(m['asset_id'], m['service_url']) for m in matches}) != 1:
        fail('episode_mismatch', 'South Park episode data is ambiguous.')
    return matches[0]

def service_url(value: str, asset_id: str) -> str:
    if not allowed_url(value, {SERVICE_HOST}):
        fail('invalid_service', 'Unexpected South Park video service.')
    p = urlsplit(value)
    if not re.fullmatch('/topaz/api/mgid:arc:episode:[A-Za-z0-9.]+:' + re.escape(asset_id) + '/mica\\.json', p.path):
        fail('episode_mismatch', 'Video service does not belong to this episode.')
    params = []
    for key, val in parse_qsl(p.query, keep_blank_values=True):
        if key == 'clientPlatform' and val == '{clientPlatform}':
            val = 'desktop'
        elif re.fullmatch('\\{[A-Za-z0-9_]+\\}', val) and key in OPTIONAL_TEMPLATES:
            continue
        if '{' in val or '}' in val:
            fail('service_template', 'Unsupported video service template.')
        params.append((key, val))
    if len([1 for key, val in params if key == 'clientPlatform' and val]) != 1:
        fail('service_template', 'Video service platform is missing or ambiguous.')
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(params), ''))

def select_source(doc: dict, asset_id: str) -> str:
    error = doc.get('error')
    if error:
        code = str(error.get('diagnostics', '')) if isinstance(error, dict) else ''
        if code == '60504':
            fail('region', 'This episode is not available in your region.')
        if code == '60101':
            fail('unavailable', 'This episode is unavailable or its rights have expired.')
        fail('service_error', 'South Park video service refused playback' + (f' ({code}).' if code.isdigit() else '.'))
    stream = doc.get('stitchedstream') or {}
    source = stream.get('source', '')
    if not allowed_url(source, {PLAYLIST_HOST}):
        fail('invalid_manifest', 'Unexpected South Park manifest host.')
    p = urlsplit(source)
    if not p.path.endswith('/master.m3u8'):
        fail('unsupported_format', 'South Park must provide an HLS master; DASH is unsupported.')
    mgids = [v for k, v in parse_qsl(p.query) if k == 'mgid']
    if len(mgids) != 1 or mgids[0].rsplit(':', 1)[-1] != asset_id:
        fail('episode_mismatch', 'The HLS manifest belongs to a different episode.')
    return source

def attributes(line: str) -> dict:
    return {m[1]: m[2][1:-1] if m[2].startswith('"') else m[2] for m in re.finditer('([A-Z0-9-]+)=("[^"]*"|[^,]*)', line.split(':', 1)[-1])}

def _media_url(base, value, playlist=False):
    url = urljoin(base, value)
    if not allowed_url(url, {PLAYLIST_HOST} if playlist else MEDIA_HOSTS):
        fail('invalid_media', 'Unexpected South Park media host.')
    if playlist and (not urlsplit(url).path.endswith('.m3u8')):
        fail('unsupported_format', 'South Park media is not HLS.')
    return url

def _playlist(body: bytes) -> str:
    text = body.decode('utf-8-sig', errors='replace').strip()
    if not text.startswith('#EXTM3U'):
        fail('invalid_manifest', 'South Park returned an empty or invalid HLS manifest.')
    for line in text.splitlines():
        if line.startswith(('#EXT-X-KEY:', '#EXT-X-SESSION-KEY:')):
            attr = attributes(line)
            if attr.get('METHOD') not in {'NONE', 'AES-128'} or attr.get('KEYFORMAT', 'identity') != 'identity':
                fail('drm', 'DRM-protected South Park playback is unsupported.')
    return text

def select_tracks(text: str, base_url: str) -> tuple[dict, list[str]]:
    lines = text.splitlines()
    variants, audio = ([], [])
    for i, line in enumerate(lines):
        if line.startswith('#EXT-X-STREAM-INF:'):
            attr = attributes(line)
            uri = next((s.strip() for s in lines[i + 1:] if s.strip() and (not s.startswith('#'))), '')
            if not uri:
                fail('invalid_manifest', 'South Park variant URI is missing.')
            resolution = re.fullmatch('(\\d+)x(\\d+)', attr.get('RESOLUTION', ''))
            variants.append({'url': _media_url(base_url, uri, True), 'audio': attr.get('AUDIO'), 'height': int(resolution[2]) if resolution else 0, 'bandwidth': int(attr.get('BANDWIDTH', '0'))})
        elif line.startswith('#EXT-X-MEDIA:'):
            attr = attributes(line)
            if attr.get('TYPE') == 'AUDIO' and attr.get('URI'):
                audio.append(attr)
    if not variants:
        fail('invalid_manifest', 'South Park master has no video variants.')
    best = max(variants, key=lambda v: (v['height'], v['bandwidth']))
    selected_audio = [a for a in audio if a.get('GROUP-ID') == best['audio']]
    if best['audio'] and (not selected_audio):
        fail('invalid_manifest', 'South Park audio track is missing.')
    selected_audio.sort(key=lambda a: a.get('DEFAULT') != 'YES')
    return (best, [_media_url(base_url, a['URI'], True) for a in selected_audio[:1]])

@dataclass
class Resource:
    url: str
    body: bytes
    content_type: str = ''

class PublicFetcher:

    def __init__(self, page_url):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': USER_AGENT, 'Referer': page_url})

    def __call__(self, url, hosts, limit, sample=False):
        for _ in range(5):
            if not allowed_url(url, hosts):
                fail('redirect', 'South Park redirected outside the supported site or media hosts.')
            try:
                with self.session.get(url, timeout=(5, 20), allow_redirects=False, stream=True, headers={'Range': 'bytes=0-1023'} if sample else {}) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        url = urljoin(url, response.headers.get('Location', ''))
                        continue
                    if response.status_code in {401, 403, 451}:
                        fail('access', 'South Park denied access or restricts this content by region.')
                    if response.status_code not in ({200, 206} if sample else {200}):
                        fail('http', f'South Park returned HTTP {response.status_code}.')
                    data = bytearray()
                    for chunk in response.iter_content(8192):
                        data.extend(chunk)
                        if sample and len(data) >= limit:
                            data = data[:limit]
                            break
                        if len(data) > limit:
                            fail('response_size', 'South Park response exceeded its size limit.')
                    return Resource(url, bytes(data), response.headers.get('Content-Type', ''))
            except requests.RequestException:
                fail('network', 'South Park could not be reached.')
        fail('redirect', 'Too many South Park redirects.')

    def close(self):
        self.session.close()

def validate_track(url, fetch):
    resource = fetch(url, {PLAYLIST_HOST}, 1024 * 1024)
    text = _playlist(resource.body)
    if '#EXTINF:' not in text:
        fail('invalid_manifest', 'South Park media playlist has no segments.')
    keys = []
    for line in text.splitlines():
        if line.startswith('#EXT-X-KEY:'):
            attr = attributes(line)
            if attr.get('METHOD') == 'AES-128':
                if not attr.get('URI'):
                    fail('invalid_key', 'South Park HLS key URI is missing.')
                keys.append(_media_url(resource.url, attr['URI']))
        elif line.startswith('#EXT-X-MAP:'):
            attr = attributes(line)
            init = fetch(_media_url(resource.url, attr.get('URI', '')), MEDIA_HOSTS, 1024, True)
            if not init.body:
                fail('empty_media', 'South Park initialization segment is empty.')
    for key in dict.fromkeys(keys[:1]):
        if len(fetch(key, MEDIA_HOSTS, 32).body) != 16:
            fail('invalid_key', 'South Park HLS key is unavailable.')
    first = next((s.strip() for s in text.splitlines() if s.strip() and (not s.startswith('#'))), '')
    segment = fetch(_media_url(resource.url, first), MEDIA_HOSTS, 1024, True)
    if not segment.body or segment.body.lstrip().lower().startswith((b'<html', b'<!doctype', b'{')):
        fail('empty_media', 'South Park returned no playable media bytes.')

def resolve_episode(page_url: str, fetch=None) -> dict:
    if not episode_page(page_url):
        fail('invalid_page', 'Open a South Park Studios episode page.')
    owned = fetch is None
    fetch = fetch or PublicFetcher(page_url)
    try:
        page = fetch(page_url, PAGE_HOSTS, 4 * 1024 * 1024)
        if episode_page(page.url) != episode_page(page_url):
            fail('episode_mismatch', 'South Park redirected to a different episode.')
        episode = parse_episode(page.body.decode('utf-8', errors='replace'), page.url)
        response = fetch(episode['service_url'], {SERVICE_HOST}, 2 * 1024 * 1024)
        try:
            doc = json.loads(response.body)
            if not isinstance(doc, dict):
                raise ValueError()
        except ValueError:
            fail('service_error', 'South Park returned an invalid video service response.')
        source = select_source(doc, episode['asset_id'])
        master = fetch(source, {PLAYLIST_HOST}, 1024 * 1024)
        text = _playlist(master.body)
        best, audio = select_tracks(text, master.url)
        validate_track(best['url'], fetch)
        for track in audio:
            validate_track(track, fetch)
        return {'status': 'ok', 'stream_url': source, 'title': episode['title'], 'episode_id': episode['episode_id'], 'season': episode['season'], 'episode': episode['episode'], 'height': best['height'], 'request_headers': {'user-agent': USER_AGENT, 'referer': page.url, 'origin': 'https://' + urlsplit(page.url).netloc}}
    finally:
        if owned:
            fetch.close()