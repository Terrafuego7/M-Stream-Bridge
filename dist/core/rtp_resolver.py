from __future__ import annotations
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urljoin, urlsplit
RTP_PAGE = re.compile('^/play/(?:[^/]+/)?p(\\d+)/e(\\d+)(?:/|$)')
MAX_PLAYLIST_BYTES = 1024 * 1024

class RTPResolveError(Exception):
    pass

def episode_ids(page_url: str) -> tuple[str, str] | None:
    try:
        parsed = urlsplit(page_url)
        if parsed.scheme != 'https' or parsed.hostname not in {'rtp.pt', 'www.rtp.pt'} or parsed.port:
            return None
        match = RTP_PAGE.match(parsed.path)
        return match.groups() if match else None
    except ValueError:
        return None

def valid_hls_url(media_url: str, program_id: str) -> bool:
    try:
        parsed = urlsplit(media_url)
        return parsed.scheme == 'https' and parsed.hostname == 'streaming-vod.rtp.pt' and (not parsed.port) and parsed.path.startswith('/hls/') and (f'/p{program_id}/' in parsed.path) and parsed.path.lower().endswith('.m3u8') and (not any((part.startswith('drm') for part in parsed.path.lower().split('/')))) and (not parsed.username) and (not parsed.password)
    except ValueError:
        return False

def select_format(info: dict, program_id: str) -> dict:
    formats = [f for f in info.get('formats', []) if isinstance(f, dict) and valid_hls_url(str(f.get('url') or ''), program_id)]
    if not formats:
        raise RTPResolveError('No clear RTP HLS variant was found')
    return max(formats, key=lambda f: (int(f.get('height') or 0), int(f.get('tbr') or 0)))

def _binary_path() -> str:
    configured = os.environ.get('MSTREAM_YTDLP_PATH', '').strip()
    if configured:
        return configured
    roots = [Path(sys.executable).resolve().parent.parent, Path(__file__).resolve().parents[2]]
    for root in roots:
        candidate = root / 'bin' / 'yt-dlp-rtp-support.exe'
        if candidate.is_file():
            return str(candidate)
    raise RTPResolveError('RTP extractor binary is missing')

def extract_format(page_url: str, run=subprocess.run) -> dict:
    ids = episode_ids(page_url)
    if not ids:
        raise RTPResolveError('Invalid RTP episode URL')
    try:
        result = run([_binary_path(), '--ignore-config', '--no-update', '--no-playlist', '--skip-download', '--dump-single-json', page_url], capture_output=True, text=True, timeout=45, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise RTPResolveError('RTP extractor could not resolve this episode')
        info = json.loads(result.stdout)
        if info.get('extractor_key') != 'RTP':
            raise RTPResolveError('Unexpected extractor result')
        selected = select_format(info, ids[0])
        raw_headers = selected.get('http_headers') or {}
        headers = {key.lower(): str(value) for key, value in raw_headers.items() if key.lower() in {'user-agent', 'accept', 'accept-language'} and value}
        return {'url': selected['url'], 'headers': headers, 'title': str(info.get('title') or 'RTP Play')[:180], 'height': int(selected.get('height') or 0)}
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise RTPResolveError('RTP extractor failed') from exc

def validate_playback(media_url: str, headers: dict, opener) -> None:
    program = re.search('/p(\\d+)/', urlsplit(media_url).path)
    if not program or not valid_hls_url(media_url, program.group(1)):
        raise RTPResolveError('Invalid RTP HLS URL')
    target = media_url
    request_headers = dict(headers)
    for _ in range(2):
        with opener(target, request_headers, 20, False) as response:
            if getattr(response, 'status', 200) != 200:
                raise RTPResolveError('RTP manifest unavailable')
            playlist = response.read(MAX_PLAYLIST_BYTES + 1)
        if len(playlist) > MAX_PLAYLIST_BYTES or not playlist.lstrip().startswith(b'#EXTM3U'):
            raise RTPResolveError('RTP response is not an HLS manifest')
        text = playlist.decode('utf-8', errors='replace')
        if '#EXT-X-KEY' in text or '#EXT-X-SESSION-KEY' in text:
            raise RTPResolveError('Protected RTP HLS is unsupported')
        child = next((line.strip() for line in text.splitlines() if line.strip() and (not line.startswith('#'))), '')
        if not child:
            raise RTPResolveError('RTP manifest has no media')
        next_url = urljoin(target, child)
        if '#EXTINF:' in text:
            if urlsplit(next_url).scheme != 'https' or urlsplit(next_url).hostname != 'streaming-vod.rtp.pt':
                raise RTPResolveError('Unexpected RTP segment host')
            segment_headers = dict(request_headers)
            segment_headers['range'] = 'bytes=0-1023'
            with opener(next_url, segment_headers, 25, True) as response:
                if getattr(response, 'status', 200) not in {200, 206} or not response.read(1024):
                    raise RTPResolveError('RTP segment unavailable')
            return
        if not valid_hls_url(next_url, program.group(1)):
            raise RTPResolveError('Unexpected RTP variant URL')
        target = next_url
    raise RTPResolveError('RTP manifest has no media playlist')