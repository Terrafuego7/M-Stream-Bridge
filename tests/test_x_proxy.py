from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from core.hls_proxy import HlsProxyMixin


class Proxy(HlsProxyMixin):
    snapshot = {"stream_url": "https://video.twimg.com/test/master.m3u8",
                "page_url": "https://x.com/SpaceX/status/2104560708969259344",
                "referer": "https://x.com/SpaceX/status/2104560708969259344",
                "request_headers": {"cookie": "private=test", "user-agent": "Mozilla/5.0"}}

    def _snapshot_stream(self, **kwargs): return self.snapshot
    def _find_hls_headers_for_url(self, url, snapshot): return (self.snapshot["request_headers"], "exact")
    def _sanitize_forward_headers(self, headers): return dict(headers)
    def _extract_client_replay_headers(self): return {}
    def _apply_identity_headers(self, headers, snapshot): return dict(headers)
    def _normalize_header_map_key(self, url): return url
    def _log_throttled(self, *args, **kwargs): pass


class XProxyTests(unittest.TestCase):
    def test_x_hls_does_not_forward_cookie(self):
        proxy = Proxy()
        headers = proxy._build_hls_upstream_headers(proxy.snapshot["stream_url"])
        self.assertNotIn("cookie", headers)
        self.assertEqual(headers["user-agent"], "Mozilla/5.0")

    def test_x_direct_does_not_forward_cookie(self):
        proxy = Proxy()
        proxy.snapshot = {**Proxy.snapshot, "stream_url": "https://video.twimg.com/test/video.mp4"}
        headers = proxy._build_direct_upstream_headers()
        self.assertNotIn("cookie", headers)


if __name__ == "__main__":
    unittest.main()
