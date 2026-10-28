import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from core.x_resolver import (
    XResolveError, Resource, PublicFetcher, post_page, parse_post, media_variants,
    validate_hls, validate_mp4, resolve_post, _playlist,
)

PAGE = "https://x.com/SpaceX/status/2104560708969259344"
HLS = "https://video.twimg.com/amplify_video/test/pl/master.m3u8?tag=12&v=1"
MP4 = "https://video.twimg.com/amplify_video/test/vid/1920x1080/video.mp4?tag=12"
MEDIA = {"type": "video", "original_info": {"height": 1080},
         "video_info": {"variants": [
             {"content_type": "application/x-mpegURL", "url": HLS},
             {"content_type": "video/mp4", "bitrate": 2000000, "url": MP4}]}}
MASTER = """#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",URI="audio.m3u8?sig=synthetic",DEFAULT=YES
#EXT-X-STREAM-INF:BANDWIDTH=500000,RESOLUTION=640x360,AUDIO="a"
low.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2000000,RESOLUTION=1920x1080,AUDIO="a"
high.m3u8?sig=synthetic
"""
TRACK = """#EXTM3U
#EXTINF:5,
segment.mp4?sig=synthetic
#EXT-X-ENDLIST
"""


def page_html(post_id="2104560708969259344", author="SpaceX", media=None, reply_media=None):
    result = {"rest_id": post_id, "__typename": "Tweet", "core": {"user_results": {
        "result": {"core": {"screen_name": author}}}},
        "details": {"full_text": "A public video post"}, "media_entities2": [MEDIA] if media is None else media}
    document = {"data": {"tweet_result_by_rest_id": {"rest_id": post_id, "result": result},
                         "threaded_conversation_with_injections_v2": {"replies": [{
                             "media_entities2": [reply_media or {"type": "animated_gif"}]}]}}}
    return "<script>const hydration=" + json.dumps(json.dumps(document)) + ";</script>"


class XResolverTests(unittest.TestCase):
    def assert_code(self, code, func, *args):
        with self.assertRaises(XResolveError) as caught:
            func(*args)
        self.assertEqual(caught.exception.code, code)

    def test_page_scope_query_and_video_index(self):
        self.assertEqual(post_page(PAGE + "?s=20")["post_id"], "2104560708969259344")
        self.assertEqual(post_page(PAGE + "/video/2")["video_index"], 2)
        for value in ("invalid", "https://x.com/", PAGE.replace("/status/", "/media/"),
                      PAGE.replace("x.com", "x.com.evil.test"), PAGE.replace("https", "http"),
                      PAGE.replace("https://", "https://user:pass@"), PAGE + "#fragment",
                      "https://x.com/i/broadcasts/1234567890123456789"):
            self.assertIsNone(post_page(value), value)

    def test_post_identity_and_reply_are_not_confused(self):
        post = parse_post(page_html(reply_media={**MEDIA, "video_info": {"variants": [
            {"content_type": "video/mp4", "url": "https://video.twimg.com/reply.mp4"}]}}), PAGE)
        self.assertEqual(post["media"]["video_info"]["variants"][0]["url"], HLS)
        self.assert_code("post_mismatch", parse_post, page_html(author="Other"), PAGE)
        self.assert_code("unavailable", parse_post, page_html(post_id="9999999999999999999"), PAGE)
        self.assert_code("no_video", parse_post, page_html(media=[]), PAGE)

    def test_multiple_videos_require_specific_index(self):
        self.assert_code("multiple_videos", parse_post, page_html(media=[MEDIA, MEDIA]), PAGE)
        self.assertEqual(parse_post(page_html(media=[MEDIA, MEDIA]), PAGE + "/video/2")["video_index"], 2)
        self.assert_code("no_video", parse_post, page_html(media=[MEDIA]), PAGE + "/video/2")

    def test_variant_selection_rejects_foreign_dash_and_bad_types(self):
        hls, mp4 = media_variants({"video_info": {"variants": [
            {"content_type": "application/x-mpegURL", "url": HLS},
            {"content_type": "video/mp4", "bitrate": 2000000, "url": MP4},
            {"content_type": "video/mp4", "bitrate": 1000, "url": MP4.replace("1920x1080", "320x180")},
            {"content_type": "application/dash+xml", "url": HLS.replace(".m3u8", ".mpd")},
            {"content_type": "video/mp4", "url": MP4.replace("video.twimg.com", "evil.test")}]}})
        self.assertEqual(hls, [HLS])
        self.assertEqual(mp4[0][1], MP4)
        self.assertEqual(len(mp4), 2)

    def test_hls_validates_best_video_audio_and_signed_queries(self):
        calls = []
        def fetch(url, hosts, limit, sample=False):
            calls.append(url)
            body = MASTER.encode() if url == HLS else TRACK.encode() if url.endswith("m3u8?sig=synthetic") else b"\0" * 1024
            return Resource(url, body, 206 if sample else 200, "video/mp4")
        self.assertEqual(validate_hls(HLS, fetch), 1080)
        self.assertTrue(any("high.m3u8?sig=synthetic" in url for url in calls))
        self.assertTrue(any("audio.m3u8?sig=synthetic" in url for url in calls))
        self.assertEqual(sum("segment.mp4?sig=synthetic" in url for url in calls), 2)

    def test_drm_and_invalid_manifest_rejected(self):
        self.assert_code("drm", _playlist, b"#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI=\"license\"\n")
        self.assert_code("invalid_manifest", _playlist, b"<html>denied</html>")
        self.assert_code("invalid_manifest", _playlist, b"")

    def test_mp4_signature_and_content_type(self):
        def fetch(url, *args):
            return Resource(url, b"\x00\x00\x00\x18ftypisom" + bytes(100), 206, "video/mp4")
        validate_mp4(MP4, fetch)
        def encrypted(url, *args):
            return Resource(url, b"\x00\x00\x00\x18ftypisom" + b"pssh" + bytes(100), 206, "video/mp4")
        self.assert_code("drm", validate_mp4, MP4, encrypted)
        def bad(url, *args):
            return Resource(url, b"<html>denied</html>", 200, "text/html")
        self.assert_code("invalid_media", validate_mp4, MP4, bad)

    def test_full_resolution_prefers_hls_and_mp4_only_fallback(self):
        def fetch(url, hosts, limit, sample=False):
            if url == PAGE:
                return Resource(url, page_html().encode(), 200, "text/html")
            if url == HLS:
                return Resource(url, MASTER.encode(), 200, "application/x-mpegURL")
            if url.endswith("m3u8?sig=synthetic"):
                return Resource(url, TRACK.encode(), 200, "application/x-mpegURL")
            return Resource(url, bytes(1024), 206, "video/mp4")
        resolved = resolve_post(PAGE, fetch)
        self.assertEqual((resolved["post_id"], resolved["stream_type"], resolved["height"]),
                         ("2104560708969259344", "hls", 1080))
        self.assertEqual(resolved["stream_url"], HLS)
        self.assertNotIn("cookie", resolved["request_headers"])
        def mp4_fetch(url, hosts, limit, sample=False):
            if url == PAGE:
                doc = page_html(media=[{**MEDIA, "video_info": {"variants": [
                    {"content_type": "video/mp4", "bitrate": 2000000, "url": MP4}]}}])
                return Resource(url, doc.encode(), 200, "text/html")
            return Resource(url, b"\0\0\0\x18ftypisom" + bytes(100), 206, "video/mp4")
        self.assertEqual(resolve_post(PAGE, mp4_fetch)["stream_type"], "direct")

    def test_redirect_stays_within_public_hosts(self):
        class Response:
            status_code = 302
            headers = {"Location": "https://evil.test/video.mp4"}
            def __enter__(self): return self
            def __exit__(self, *_): pass
        class Session:
            calls = 0
            class cookies:
                @staticmethod
                def clear(): pass
            def get(self, *args, **kwargs):
                self.calls += 1
                return Response()
            def close(self): pass
        fetch = PublicFetcher(PAGE)
        fetch.session.close()
        fetch.session = Session()
        self.assert_code("redirect", fetch, PAGE, {"x.com"}, 1000)
        self.assertEqual(fetch.session.calls, 1)


if __name__ == "__main__":
    unittest.main()
