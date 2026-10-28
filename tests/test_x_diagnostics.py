from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from core.x_diagnostics import new_trace, record, valid_capture_id
from core.state import current_stream
from main import BridgeProxyHandler


class XDiagnosticTests(unittest.TestCase):
    def test_only_allowlisted_fields_are_retained(self):
        trace = new_trace('x-12345678-synthetic')
        trace = record(trace, {'stage': 'player_error', 'code': 'hls_network', 'http': 403,
                               'url': 'private', 'cookie': 'private', 'title': 'private'})
        self.assertNotIn('private', repr(trace))
        self.assertEqual(trace['events'][-1]['http'], 403)
        self.assertFalse(valid_capture_id('https://example.org/private'))

    def test_server_check_never_means_player_playing(self):
        trace = record(new_trace('x-12345678-synthetic'), {'stage': 'proxy_checked', 'code': 'ok'})
        self.assertEqual(trace['stage'], 'proxy_checked')
        with self.assertRaises(ValueError):
            record(trace, {'stage': 'verified', 'code': 'ok'})
        trace = record(trace, {'stage': 'player_playing', 'code': 'ok'})
        trace = record(trace, {'stage': 'proxy_checked', 'code': 'ok'})
        self.assertEqual(trace['stage'], 'player_playing')

    def test_stale_player_cannot_confirm_a_different_active_capture(self):
        trace = new_trace('x-12345678-current')
        handler = object.__new__(BridgeProxyHandler)
        handler._read_json_body = Mock(return_value={'capture_id': 'x-12345678-old', 'stage': 'player_playing', 'code': 'ok'})
        handler._send_json = Mock()
        with patch.dict(current_stream, {'stream_url': 'https://video.twimg.com/test/master.m3u8', 'x_diagnostic': trace}, clear=True):
            handler._handle_x_playback()
            self.assertEqual(handler._send_json.call_args.args[0], 409)
            self.assertEqual(current_stream['x_diagnostic']['stage'], 'selected')


if __name__ == '__main__':
    unittest.main()
