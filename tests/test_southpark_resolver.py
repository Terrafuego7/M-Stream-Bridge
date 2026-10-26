import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from core.southpark_resolver import (
    SouthParkError, Resource, episode_page, parse_episode, service_url,
    select_source, select_tracks, _playlist, resolve_episode, PublicFetcher,
)

PAGE = "https://www.southparkstudios.com/episodes/940f8z/south-park-test-season-1-ep-1"
ASSET = "5fb8887e-ecfd-11e0-aca6-0026b9414f30"
SERVICE = f"https://topaz.paramount.tech/topaz/api/mgid:arc:episode:shared.southpark.global:{ASSET}/mica.json?clientPlatform={{clientPlatform}}&advertId={{advertisingid}}"
MASTER = f"https://ns-stream.paramount.tech/h/test/master.m3u8?mgid=mgid:arc:episode:shared.southpark.global:{ASSET}&hdnts=synthetic"
DETAIL = {"shortId": "940f8z", "seasonNumber": 1, "episodeNumber": "0101", "entityType": "episode",
          "authRequired": False, "mgid": f"mgid:arc:episode:southpark.intl:{ASSET}",
          "title": "Test", "videoServiceUrl": SERVICE}
MASTER_TEXT = '''#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="English, original",DEFAULT=YES,URI="audio.m3u8?sig=fake"
#EXT-X-STREAM-INF:BANDWIDTH=400000,RESOLUTION=640x360,AUDIO="audio"
low.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=3500000,RESOLUTION=1920x1080,AUDIO="audio"
high.m3u8?sig=fake
'''
TRACK = b'''#EXTM3U
#EXT-X-KEY:METHOD=AES-128,URI="key.bin?sig=fake"
#EXTINF:6,
https://southpark.orchestrator.viacomcbs-tech.com/test/segment.ts?sig=fake
#EXT-X-ENDLIST
'''


def html(detail):
    return "<script>window.__DATA__ = " + json.dumps({"children": [{"videoDetail": detail}]}) + ";\n</script>"


class SouthParkTests(unittest.TestCase):
    def assert_code(self, code, function, *args):
        with self.assertRaises(SouthParkError) as error:
            function(*args)
        self.assertEqual(error.exception.code, code)

    def test_episode_scope_and_query(self):
        self.assertEqual(episode_page(PAGE + "?tracking=fake")["episode_id"], "940f8z")
        for url in ("invalid", "https://www.southparkstudios.com/", PAGE.replace("/episodes/", "/video-clips/"),
                    PAGE.replace("www.southparkstudios.com", "evil.test"),
                    PAGE.replace(".com/", ".com.evil.test/"), PAGE.replace("https:", "http:"),
                    PAGE.replace("https://", "https://user:password@"), PAGE + "#fragment"):
            self.assertIsNone(episode_page(url), url)

    def test_page_identity_and_production_number(self):
        result = parse_episode(html(DETAIL), PAGE)
        self.assertEqual((result["season"], result["episode"]), (1, 1))
        other = {**DETAIL, "shortId": "xxxxxx"}
        combined = "window.__DATA__=" + json.dumps([{"videoDetail": other}, {"videoDetail": DETAIL}]) + ";"
        self.assertEqual(parse_episode(combined, PAGE)["asset_id"], ASSET)
        self.assert_code("episode_mismatch", parse_episode, html(other), PAGE)
        self.assert_code("episode_mismatch", parse_episode, html({**DETAIL, "episodeNumber": "0102"}), PAGE)
        self.assert_code("page_changed", parse_episode, "<html>No JSON</html>", PAGE)
        self.assert_code("authentication", parse_episode, html({**DETAIL, "authRequired": True}), PAGE)

    def test_service_template_preserves_concrete_query(self):
        result = service_url(SERVICE + "&custom=keep%2Bthis", ASSET)
        self.assertIn("clientPlatform=desktop", result)
        self.assertIn("custom=keep%2Bthis", result)
        self.assertNotIn("advertId", result)
        self.assert_code("invalid_service", service_url, SERVICE.replace("topaz.paramount.tech", "evil.test"), ASSET)
        self.assert_code("episode_mismatch", service_url, SERVICE.replace(ASSET, "00000000-0000-0000-0000-000000000000"), ASSET)
        self.assert_code("service_template", service_url, SERVICE + "&auth={auth}", ASSET)

    def test_select_hls_preserves_signature_and_episode(self):
        self.assertEqual(select_source({"stitchedstream": {"source": MASTER}}, ASSET), MASTER)
        for bad in (MASTER.replace("ns-stream.paramount.tech", "evil.test"),
                    MASTER.replace("master.m3u8", "manifest.mpd"), MASTER.replace(ASSET, "other-episode")):
            with self.assertRaises(SouthParkError):
                select_source({"stitchedstream": {"source": bad}}, ASSET)
        self.assert_code("region", select_source, {"error": {"diagnostics": "60504"}}, ASSET)
        self.assert_code("unavailable", select_source, {"error": {"diagnostics": "60101"}}, ASSET)

    def test_video_and_separate_audio(self):
        best, audio = select_tracks(MASTER_TEXT, MASTER)
        self.assertEqual(best["height"], 1080)
        self.assertTrue(best["url"].endswith("high.m3u8?sig=fake"))
        self.assertEqual(audio, ["https://ns-stream.paramount.tech/h/test/audio.m3u8?sig=fake"])
        self.assert_code("invalid_manifest", select_tracks, MASTER_TEXT.replace('GROUP-ID="audio"', 'GROUP-ID="missing"'), MASTER)

    def test_drm_rejected_standard_hls_allowed(self):
        self.assertIn("AES-128", _playlist(TRACK))
        self.assert_code("drm", _playlist, TRACK.replace(b"AES-128", b"SAMPLE-AES"))
        self.assert_code("drm", _playlist, TRACK.replace(b"METHOD=AES-128", b'METHOD=AES-128,KEYFORMAT="com.apple.streamingkeydelivery"'))
        for bad in (b"", b"<html>denied</html>", b"<MPD/>"):
            self.assert_code("invalid_manifest", _playlist, bad)

    def test_resolution_validates_audio_video_key_and_segments(self):
        calls = []
        def fetch(url, hosts, limit, sample=False):
            calls.append(url)
            if url == PAGE:
                return Resource(url, html(DETAIL).encode())
            if "mica.json" in url:
                return Resource(url, json.dumps({"stitchedstream": {"source": MASTER}}).encode())
            if url == MASTER:
                return Resource(url, MASTER_TEXT.encode())
            if "key.bin" in url:
                return Resource(url, bytes(16))
            if "segment.ts" in url:
                return Resource(url, bytes(1024), "video/MP2T")
            return Resource(url, TRACK)
        result = resolve_episode(PAGE, fetch)
        self.assertEqual(result["stream_url"], MASTER)
        self.assertEqual(result["height"], 1080)
        self.assertTrue(any("audio.m3u8" in u for u in calls))
        self.assertEqual(sum("segment.ts" in u for u in calls), 2)
        self.assertNotIn("cookie", result["request_headers"])

    def test_region_error_never_requests_media(self):
        calls = []
        def fetch(url, *args):
            calls.append(url)
            return Resource(url, html(DETAIL).encode() if url == PAGE else b'{"error":{"diagnostics":"60504"}}')
        self.assert_code("region", resolve_episode, PAGE, fetch)
        self.assertEqual(len(calls), 2)

    def test_redirect_never_changes_region(self):
        class Response:
            status_code = 302
            headers = {"Location": PAGE.replace("southparkstudios.com", "southpark.de")}
            def __enter__(self): return self
            def __exit__(self, *_): pass
        class Session:
            calls = 0
            def get(self, *args, **kwargs):
                self.calls += 1
                return Response()
            def close(self): pass
        fetch = PublicFetcher(PAGE)
        fetch.session.close()
        fetch.session = Session()
        self.assert_code("redirect", fetch, PAGE, {"www.southparkstudios.com"}, 1000)
        self.assertEqual(fetch.session.calls, 1)


if __name__ == "__main__":
    unittest.main()
