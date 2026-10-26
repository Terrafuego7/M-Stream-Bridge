import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.rtp_resolver import (
    RTPResolveError, episode_ids, extract_format, select_format, valid_hls_url, validate_playback,
)


PAGE = "https://www.rtp.pt/play/p17247/e958623/ruido"
HLS = "https://streaming-vod.rtp.pt/hls/nas2.share/h264/p17247/video.mp4/index-f1.m3u8"


class Response:
    def __init__(self, body, status=200, url=None):
        self.body = body
        self.status = status
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def read(self, *_):
        return self.body


class RTPResolverTests(unittest.TestCase):
    def test_episode_url(self):
        self.assertEqual(episode_ids(PAGE), ("17247", "958623"))
        for bad in ("invalid", "https://evil.test/play/p17247/e958623",
                    "https://www.rtp.pt.evil.test/play/p17247/e958623",
                    "http://www.rtp.pt/play/p17247/e958623",
                    "https://www.rtp.pt/play/programas"):
            self.assertIsNone(episode_ids(bad))

    def test_media_validation_and_query(self):
        self.assertTrue(valid_hls_url(HLS + "?expires=123&sig=fake", "17247"))
        for bad in (
            "not a URL", HLS.replace("streaming-vod.rtp.pt", "evil.test"),
            HLS.replace("p17247", "p1525"), HLS.replace(".m3u8", ".mpd"),
            HLS.replace("/hls/", "/drm-fps/"),
            HLS.replace("/hls/", "/drm-dash/"),
            HLS.replace("streaming-vod", "streaming-ondemand"),
        ):
            self.assertFalse(valid_hls_url(bad, "17247"), bad)

    def test_selects_highest_clear_variant(self):
        formats = [{"url": HLS, "height": 1080, "tbr": 3500},
                   {"url": HLS + "?quality=low", "height": 576},
                   {"url": HLS.replace("/hls/", "/drm-fps/"), "height": 2160}]
        self.assertEqual(select_format({"formats": formats}, "17247")["height"], 1080)
        with self.assertRaises(RTPResolveError):
            select_format({"formats": formats}, "999")

    def test_extract_rejects_unexpected_result(self):
        class Result:
            returncode = 0
            stdout = json.dumps({"extractor_key": "Other", "formats": [{"url": HLS}]})
        with self.assertRaises(RTPResolveError):
            extract_format(PAGE, run=lambda *args, **kwargs: Result())

    def test_playback_requires_manifest_and_segment(self):
        calls = []
        def open_good(url, headers, timeout, stream):
            calls.append((url, stream))
            return Response(b"\x47" * 1024 if stream else b"#EXTM3U\n#EXTINF:10,\nseg.ts\n")
        validate_playback(HLS, {}, open_good)
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[-1][0].endswith("seg.ts"))
        for body, status in ((b"", 204), (b"<html>blocked</html>", 200),
                             (b"#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES\n#EXTINF:10,\nseg.ts", 200)):
            with self.assertRaises(RTPResolveError):
                validate_playback(HLS, {}, lambda *args: Response(body, status))
        with self.assertRaises(RTPResolveError):
            validate_playback(HLS, {}, lambda *args: Response(b"#EXTM3U\n#EXTINF:10,\nseg.ts", url="https://evil.test/media.m3u8"))

    def test_relative_segment_keeps_query(self):
        calls = []
        def opener(url, headers, timeout, stream):
            calls.append(url)
            return Response(b"\x47" if stream else b"#EXTM3U\n#EXTINF:10,\nseg.ts?token=fake\n")
        validate_playback(HLS + "?token=fake", {}, opener)
        self.assertTrue(calls[-1].endswith("/seg.ts?token=fake"))


if __name__ == "__main__":
    unittest.main()
