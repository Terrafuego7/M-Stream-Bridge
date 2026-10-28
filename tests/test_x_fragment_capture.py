from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from core.x_resolver import is_x_fragment, media_variants
from core.capture_engine import CaptureEngineMixin
from core.hls_proxy import HlsProxyMixin
from main import BridgeProxyHandler
from utils.audio_extractor import start_extraction_async

INIT = 'https://video.twimg.com/amplify_video/1234567890/vid/avc1/0/0/1920x1080/init.mp4?token=synthetic'
PROGRESSIVE = 'https://video.twimg.com/amplify_video/1234567890/vid/avc1/1920x1080/full.mp4?tag=12'


class FragmentCaptureTests(unittest.TestCase):
    def test_exact_cmaf_paths_only(self):
        self.assertTrue(is_x_fragment(INIT))
        self.assertTrue(is_x_fragment(INIT.replace('/0/0/', '/0/3000/')))
        self.assertTrue(is_x_fragment(INIT.replace('/vid/avc1/0/0/1920x1080/', '/aud/mp4a/128000/0/0/')))
        self.assertFalse(is_x_fragment(PROGRESSIVE))
        self.assertFalse(is_x_fragment(INIT.replace('video.twimg.com', 'cdn.example.org')))
        self.assertFalse(is_x_fragment('invalid'))

    def test_capture_filters_and_manual_restore_reject_fragment(self):
        capture = CaptureEngineMixin()
        self.assertFalse(capture._is_media_capture_target(INIT))
        self.assertTrue(capture._is_probably_init_segment(INIT))
        self.assertTrue(capture._is_media_capture_target(PROGRESSIVE))
        handler = object.__new__(BridgeProxyHandler)
        self.assertFalse(handler._promote_capture_candidate({'url': INIT}, forced=True))
        self.assertEqual(media_variants({'video_info': {'variants': [
            {'content_type': 'video/mp4', 'url': INIT}]}}), ([], []))

    def test_set_stream_ignores_fragment_before_mutating_active_stream(self):
        handler = object.__new__(BridgeProxyHandler)
        handler.headers = {}
        handler._read_json_body = Mock(return_value={'stream_url': INIT, 'stream_type': 'direct', 'capture_source': 'webRequest'})
        handler._send_json = Mock()
        handler._log = Mock()
        handler._handle_set_stream()
        args = handler._send_json.call_args.args
        self.assertEqual(args[0], 202)
        self.assertEqual(args[1]['code'], 'x_fragment_skipped')
        self.assertNotIn('stream_url', args[1])

    def test_full_mode_stops_before_ffmpeg_for_stale_fragment(self):
        handler = object.__new__(BridgeProxyHandler)
        handler._snapshot_stream = Mock(return_value={'stream_url': INIT})
        handler._send_json = Mock()
        with patch('main.start_extraction_async') as extraction:
            handler._handle_extract_audio()
            extraction.assert_not_called()
        self.assertEqual(handler._send_json.call_args.args[0], 422)
        self.assertEqual(handler._send_json.call_args.args[1]['code'], 'x_fragment_selected')
        with patch('utils.audio_extractor.subprocess.Popen') as ffmpeg:
            with self.assertRaises(ValueError):
                start_extraction_async(INIT, {}, 'direct')
            ffmpeg.assert_not_called()

    def test_fragment_remains_available_as_a_playlist_resource(self):
        proxy = HlsProxyMixin()
        playlist = '#EXTM3U\n#EXT-X-MAP:URI="' + INIT + '"\n#EXTINF:3,\nsegment.m4s\n#EXT-X-ENDLIST'
        rewritten = proxy._rewrite_m3u8(playlist, 'https://video.twimg.com/test/')
        self.assertIn('/proxy-segment?url=', rewritten)
        self.assertIn('%2Fvid%2Favc1%2F0%2F0%2F', rewritten)


if __name__ == '__main__':
    unittest.main()
