"""Opt-in FFmpeg test of the production Full Mode HLS audio path."""
from pathlib import Path
import os
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from utils import audio_extractor as audio

FFMPEG = os.environ.get('BRIDGE_TEST_FFMPEG')


@unittest.skipUnless(FFMPEG and Path(FFMPEG).is_file(), 'Set BRIDGE_TEST_FFMPEG for the real Full Mode decode test')
class XFullModeTests(unittest.TestCase):
    def test_audio_rendition_is_found_when_type_attribute_is_not_first(self):
        with TemporaryDirectory(prefix='mstream-x-audio-') as folder:
            root = Path(folder)
            generated = subprocess.run([FFMPEG, '-hide_banner', '-loglevel', 'error', '-y',
                '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', '2',
                '-c:a', 'aac', '-f', 'hls', '-hls_time', '1', '-hls_segment_type', 'fmp4',
                '-hls_playlist_type', 'vod', '-hls_fmp4_init_filename', 'init.mp4',
                '-hls_segment_filename', str(root / 'audio%d.m4s'), str(root / 'audio.m3u8')],
                capture_output=True, timeout=20, cwd=root)
            self.assertEqual(generated.returncode, 0)
            master = b'''#EXTM3U
#EXT-X-MEDIA:GROUP-ID="audio",NAME="original",TYPE=AUDIO,DEFAULT=YES,URI="audio.m3u8?token=synthetic"
#EXT-X-STREAM-INF:BANDWIDTH=1000000,RESOLUTION=1920x1080,AUDIO="audio"
video.m3u8
'''
            calls = []
            class Response:
                status_code = 200
                headers = {'Content-Type': 'application/octet-stream'}
                def __init__(self, content): self.content = content
            class Session:
                def get(self, url, **kwargs):
                    calls.append(url)
                    name = Path(urlsplit(url).path).name
                    if name == 'master.m3u8': return Response(master)
                    if name == 'video.m3u8': raise AssertionError('Full Mode selected video-only HLS instead of its audio rendition')
                    return Response((root / name).read_bytes())
            output = root / 'extracted.mp4'
            with patch.object(audio.cffi_requests, 'Session', return_value=Session()), \
                 patch.object(audio, 'get_ffmpeg_path', return_value=Path(FFMPEG)), \
                 patch.object(audio, '_extract_status', 'extracting'), \
                 patch.object(audio, '_extract_process', None):
                audio._extract_hls('https://video.twimg.com/fixture/master.m3u8', {}, output)
                self.assertEqual(audio._extract_status, 'done')
            decoded = subprocess.run([FFMPEG, '-hide_banner', '-loglevel', 'error', '-i', str(output),
                                      '-map', '0:a:0', '-t', '1', '-f', 'null', '-'],
                                     capture_output=True, timeout=20)
            self.assertEqual(decoded.returncode, 0)
            self.assertTrue(any('audio.m3u8?token=synthetic' in url for url in calls))


if __name__ == '__main__':
    unittest.main()
