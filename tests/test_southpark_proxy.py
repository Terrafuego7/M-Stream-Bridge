import sys
from pathlib import Path
import unittest
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from core.hls_proxy import HlsProxyMixin
from test_southpark_resolver import MASTER_TEXT, TRACK


class ProxyRegressionTests(unittest.TestCase):
    def test_master_preserves_separate_audio_and_orders_video(self):
        proxy = HlsProxyMixin()
        result = proxy._rewrite_m3u8(MASTER_TEXT, "https://ns-stream.paramount.tech/h/test/")
        self.assertIn('#EXT-X-MEDIA:TYPE=AUDIO', result)
        self.assertLess(result.index("1920x1080"), result.index("640x360"))
        self.assertIn("audio.m3u8%3Fsig%3Dfake", result)
        self.assertIn("high.m3u8%3Fsig%3Dfake", result)

    def test_media_rewrites_standard_key_and_preserves_signed_segment_url(self):
        proxy = HlsProxyMixin()
        result = proxy._rewrite_m3u8(TRACK.decode(), "https://ns-stream.paramount.tech/h/test/")
        self.assertIn("METHOD=AES-128", result)
        self.assertIn("key.bin%3Fsig%3Dfake", result)
        line = next(line for line in result.splitlines() if line and not line.startswith("#"))
        original = parse_qs(urlsplit(line).query)["url"][0]
        self.assertEqual(original, "https://southpark.orchestrator.viacomcbs-tech.com/test/segment.ts?sig=fake")


if __name__ == "__main__":
    unittest.main()
