"""Resolve public X post video without browser credentials or script execution."""
from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import json
import re
from urllib.parse import urljoin, urlsplit

import requests

PAGE_HOSTS = frozenset({"x.com", "www.x.com", "twitter.com", "www.twitter.com"})
MEDIA_HOSTS = frozenset({"video.twimg.com"})
POST_PATH = re.compile(r"^/([A-Za-z0-9_]{1,15})/status/(\d{10,20})(?:/video/([1-4]))?/?$")
JS_STRING = re.compile(r'"(?:\\.|[^"\\])*"')
USER_AGENT = "Mozilla/5.0"


class XResolveError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def fail(code: str, message: str):
    raise XResolveError(code, message)


def allowed_url(value: str, hosts) -> bool:
    try:
        p = urlsplit(value)
        return (p.scheme == "https" and p.hostname in hosts and p.port is None
                and not p.username and not p.password and not p.fragment
                and not any(ch in value for ch in "\r\n\\"))
    except (TypeError, ValueError):
        return False


def post_page(value: str) -> dict | None:
    if not allowed_url(value, PAGE_HOSTS):
        return None
    match = POST_PATH.fullmatch(urlsplit(value).path)
    if not match:
        return None
    return {"handle": match[1].lower(), "post_id": match[2],
            "video_index": int(match[3] or 1)}


def is_x_fragment(value: str) -> bool:
    """X CMAF init/media chunks use .mp4 too; they are not complete videos."""
    try:
        p = urlsplit(value)
        return p.hostname == 'video.twimg.com' and re.search(
            r'^/(?:amplify_video|ext_tw_video)/\d+/(?:vid|aud)/[^/]+/(?:\d+/){2,}[^/]+(?:/[^/]+)?\.(?:mp4|m4a|m4s)$',
            p.path, re.IGNORECASE) is not None
    except (TypeError, ValueError):
        return False


def is_x_media(value: str) -> bool:
    try:
        return urlsplit(value).hostname == 'video.twimg.com'
    except (TypeError, ValueError):
        return False


class _Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.inside = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.inside = False

    def handle_data(self, data):
        if self.inside and "tweet_result_by_rest_id" in data:
            self.parts.append(data)


def parse_post(html: str, page_url: str) -> dict:
    expected = post_page(page_url)
    if not expected:
        fail("invalid_page", "Open a public X video post.")
    scripts = _Scripts()
    scripts.feed(html)
    matches = []
    for script in scripts.parts:
        for quoted in JS_STRING.finditer(script):
            if "tweet_result_by_rest_id" not in quoted.group():
                continue
            try:
                document = json.loads(json.loads(quoted.group()))
                record = document["data"]["tweet_result_by_rest_id"]
                post = record["result"]
                if not isinstance(post, dict):
                    continue
                if record.get("rest_id") != expected["post_id"] or post.get("rest_id") != expected["post_id"]:
                    continue
                author = post["core"]["user_results"]["result"]["core"]["screen_name"]
                if str(author).lower() != expected["handle"]:
                    fail("post_mismatch", "X returned a different post author.")
                if post.get("__typename") not in {"Tweet", None}:
                    fail("unavailable", "This X post is unavailable.")
                video = [item for item in post.get("media_entities2", [])
                         if isinstance(item, dict) and item.get("type") == "video"]
                index = expected["video_index"] - 1
                if index >= len(video):
                    fail("no_video", "This X post has no video at the requested position.")
                if len(video) > 1 and "/video/" not in urlsplit(page_url).path:
                    fail("multiple_videos", "Open a specific video from this X post.")
                text = str(post.get("details", {}).get("full_text")
                           or post.get("legacy", {}).get("full_text") or "")
                title = re.sub(r"https?://\S+", "", text).strip()[:130] or f"Post {expected['post_id']}"
                matches.append({**expected, "title": f"{author}: {title}",
                                "media": video[index]})
            except (KeyError, TypeError, ValueError):
                continue
    if not matches:
        fail("unavailable", "This public X post did not expose playable video data.")
    if len({json.dumps(item["media"].get("video_info", {}).get("variants"), sort_keys=True)
            for item in matches}) != 1:
        fail("post_mismatch", "X returned ambiguous video data for this post.")
    return matches[0]


def media_variants(media: dict) -> tuple[list[str], list[tuple[int, str]]]:
    info = media.get("video_info") or {}
    hls, mp4 = [], []
    for variant in info.get("variants") or []:
        if not isinstance(variant, dict):
            continue
        url = variant.get("url")
        if not allowed_url(url, MEDIA_HOSTS) or is_x_fragment(url):
            continue
        path = urlsplit(url).path.lower()
        content_type = str(variant.get("content_type") or "").lower()
        if path.endswith(".m3u8") and content_type in {"application/x-mpegurl", "application/vnd.apple.mpegurl"}:
            hls.append(url)
        elif path.endswith(".mp4") and content_type == "video/mp4":
            try:
                mp4.append((int(variant.get("bitrate") or 0), url))
            except (TypeError, ValueError):
                continue
    return hls, sorted(mp4, reverse=True)


@dataclass
class Resource:
    url: str
    body: bytes
    status: int
    content_type: str


class PublicFetcher:
    """Bounded anonymous GETs with strict redirect hosts."""
    def __init__(self, page_url: str):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Referer": page_url})

    def __call__(self, url: str, hosts, limit: int, sample: bool = False) -> Resource:
        for _ in range(5):
            if not allowed_url(url, hosts):
                fail("redirect", "X redirected outside the supported post or media hosts.")
            try:
                self.session.cookies.clear()
                with self.session.get(url, timeout=(5, 20), allow_redirects=False, stream=True,
                                      headers={"Range": f"bytes=0-{limit - 1}"} if sample else {}) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        url = urljoin(url, response.headers.get("Location", ""))
                        continue
                    if response.status_code in {401, 403, 451}:
                        fail("access", "X denied access to this video without authentication or in this region.")
                    if response.status_code not in ({200, 206} if sample else {200}):
                        fail("http", f"X returned HTTP {response.status_code}.")
                    body = bytearray()
                    for chunk in response.iter_content(8192):
                        body.extend(chunk)
                        if sample and len(body) >= limit:
                            body = body[:limit]
                            break
                        if len(body) > limit:
                            fail("response_size", "X response exceeded its size limit.")
                    return Resource(url, bytes(body), response.status_code,
                                    response.headers.get("Content-Type", ""))
            except requests.RequestException:
                fail("network", "X video could not be reached.")
        fail("redirect", "Too many X redirects.")

    def close(self):
        self.session.close()


def _playlist(body: bytes) -> str:
    text = body.decode("utf-8-sig", errors="replace")
    if not text.lstrip().startswith("#EXTM3U"):
        fail("invalid_manifest", "X did not return an HLS manifest.")
    if any(line.startswith(("#EXT-X-KEY:", "#EXT-X-SESSION-KEY:"))
           for line in text.splitlines()):
        fail("drm", "Protected X HLS playback is unsupported.")
    return text


def _child(base: str, value: str, suffix: str | None = None) -> str:
    candidate = urljoin(base, value)
    if not allowed_url(candidate, MEDIA_HOSTS):
        fail("invalid_media", "X media redirected to an unexpected host.")
    if suffix and not urlsplit(candidate).path.lower().endswith(suffix):
        fail("invalid_media", "X media had an unexpected format.")
    return candidate


def _attributes(line: str) -> dict:
    return {m[1]: m[2][1:-1] if m[2].startswith('"') else m[2]
            for m in re.finditer(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)', line.split(":", 1)[-1])}


def validate_hls(url: str, fetch) -> int:
    master = fetch(url, MEDIA_HOSTS, 1024 * 1024)
    text = _playlist(master.body)
    lines = text.splitlines()
    variants, audio = [], []
    for index, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF:"):
            attrs = _attributes(line)
            child = next((v.strip() for v in lines[index + 1:] if v.strip() and not v.startswith("#")), "")
            if not child:
                fail("invalid_manifest", "X HLS variant is missing.")
            resolution = re.fullmatch(r"(\d+)x(\d+)", attrs.get("RESOLUTION", ""))
            variants.append((int(resolution[2]) if resolution else 0,
                             int(attrs.get("BANDWIDTH") or 0), _child(master.url, child, ".m3u8"),
                             attrs.get("AUDIO")))
        elif line.startswith("#EXT-X-MEDIA:"):
            attrs = _attributes(line)
            if attrs.get("TYPE") == "AUDIO" and attrs.get("URI"):
                audio.append(attrs)
    if variants:
        best = max(variants)
        validate_media_playlist(best[2], fetch)
        if best[3]:
            tracks = [a for a in audio if a.get("GROUP-ID") == best[3]]
            if not tracks:
                fail("invalid_manifest", "X HLS audio track is missing.")
            tracks.sort(key=lambda a: a.get("DEFAULT") != "YES")
            validate_media_playlist(_child(master.url, tracks[0]["URI"], ".m3u8"), fetch)
        return best[0]
    validate_media_playlist(master.url, fetch, initial=text)
    return 0


def validate_media_playlist(url: str, fetch, initial: str | None = None):
    if initial is None:
        resource = fetch(url, MEDIA_HOSTS, 1024 * 1024)
        text = _playlist(resource.body)
        url = resource.url
    else:
        text = initial
    if "#EXTINF:" not in text:
        fail("invalid_manifest", "X HLS media playlist contains no segments.")
    for line in text.splitlines():
        if line.startswith("#EXT-X-MAP:"):
            init = _attributes(line).get("URI")
            if not init or not fetch(_child(url, init), MEDIA_HOSTS, 1024, True).body:
                fail("empty_media", "X HLS initialization segment is empty.")
    first = next((line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")), "")
    if not first:
        fail("invalid_manifest", "X HLS segment is missing.")
    segment = fetch(_child(url, first), MEDIA_HOSTS, 1024, True)
    if not segment.body or segment.body.lstrip().lower().startswith((b"<html", b"<!doctype", b"{")):
        fail("empty_media", "X returned no playable HLS media bytes.")


def validate_mp4(url: str, fetch):
    resource = fetch(url, MEDIA_HOSTS, 64 * 1024, True)
    if len(resource.body) < 12 or resource.body[4:8] != b"ftyp":
        fail("invalid_media", "X did not return an MP4 video.")
    if "video/mp4" not in resource.content_type.lower():
        fail("invalid_media", "X returned an unexpected video content type.")
    if any(marker in resource.body for marker in (b"pssh", b"sinf", b"schm", b"encv", b"enca")):
        fail("drm", "Encrypted X MP4 playback is unsupported.")


def resolve_post(page_url: str, fetch=None) -> dict:
    expected = post_page(page_url)
    if not expected:
        fail("invalid_page", "Open a public X video post.")
    owned = fetch is None
    fetch = fetch or PublicFetcher(page_url)
    try:
        page = fetch(page_url, PAGE_HOSTS, 4 * 1024 * 1024)
        if post_page(page.url) != expected:
            fail("post_mismatch", "X redirected to a different post.")
        post = parse_post(page.body.decode("utf-8", errors="replace"), page.url)
        hls, mp4 = media_variants(post["media"])
        if hls:
            source, stream_type = hls[0], "hls"
            height = validate_hls(source, fetch)
        elif mp4:
            source, stream_type = mp4[0][1], "direct"
            validate_mp4(source, fetch)
            height = int(post["media"].get("original_info", {}).get("height") or 0)
        else:
            fail("no_video", "This X post has no supported public HLS or MP4 variant.")
        return {"status": "ok", "validation_scope": "server_resources", "stream_url": source, "stream_type": stream_type,
                "title": post["title"], "post_id": expected["post_id"],
                "video_index": expected["video_index"], "height": height,
                "request_headers": {"user-agent": USER_AGENT, "referer": page.url,
                                    "origin": "https://x.com"}}
    finally:
        if owned:
            fetch.close()
