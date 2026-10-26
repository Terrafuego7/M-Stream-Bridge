# South Park Studios support

## Scope and installation

Canonical code is `src/`. `scripts/build.py` stages/optimizes it into `dist/`
and injects `index.min.json`'s version. The release workflow copies
`dist/extension` into root `extension/` and bundles `dist/main.py` as
`_internal/mstream_core.exe`. The root launcher starts that executable.
Editing `extension/` alone would lose changes on the next build; editing only
`src/` would not update the running extension or packaged server.

The user confirmed Chrome loads:
`C:\Users\ottma\Documents\ChromeExtensions\M-Stream-Bridge\extension`.
This installation was updated to 3.0.8, including the compiled local server.
The previous runtime is retained in `_internal_backup_3.0.7`.

1. Start `M-Stream Bridge.exe`; check `http://127.0.0.1:7000/health` reports 3.0.8.
2. Open `chrome://extensions`, enable Developer mode, locate M-Stream Bridge,
   and click Reload. Its version must be 3.0.8. If reloading fails, use Load
   unpacked and the exact folder above; do not load `src/extension`.
3. Open/reload the [test episode](https://www.southparkstudios.com/episodes/940f8z/south-park-cartman-gets-an-anal-probe-season-1-ep-1).
   Keep the tab active. Open the popup after validation; expect
   `South Park HLS verified (1080p)` and season 1 / episode 1. Reopen the popup
   if its initial status was still resolving.
4. Open Migaku Player, execute the supplied `migaku-player-snippet.js` through
   the existing DevTools Snippets workflow, select Proxy playback and Play.
   Check both picture and sound, then seek past the first minute.
5. Repeat with [RTP Ruido](https://www.rtp.pt/play/p17247/e958623/ruido).
   RTP still requires the bundled `bin/yt-dlp-rtp-support.exe`.
6. For failures, inspect the popup, Chrome extension Errors / Service worker
   Inspect views, and `http://127.0.0.1:7000/api/logs`. Do not publish signed URLs,
   cookies or the contents of `/api/current-stream`.

## Evidence from the reference

Reviewed [southpark-downloader-ui](https://github.com/xypwn/southpark-downloader-ui)
under its [MIT license, copyright xypwn 2023](https://github.com/xypwn/southpark-downloader-ui/blob/main/LICENSE).
This implementation is independently written; no reference code was copied.

- [infoextract.go](https://github.com/xypwn/southpark-downloader-ui/blob/main/pkg/southpark/infoextract.go):
  follows the site's regional redirect, parses `window.__DATA__`, discovers
  seasons/episode lists and uses episode MGIDs and availability metadata.
- [stream.go](https://github.com/xypwn/southpark-downloader-ui/blob/main/pkg/southpark/stream.go):
  gets `handleTVEAuthRedirection.videoDetail.videoServiceUrl`, requests
  `clientPlatform=desktop`, reads `stitchedstream.source`, then selects HLS
  video, separate audio and subtitles. Error 60101 means unavailable and 60504
  means regional denial. It downloads media and muxes MP4; it does not use yt-dlp.
- [httputils.go](https://github.com/xypwn/southpark-downloader-ui/blob/main/pkg/httputils/httputils.go):
  ordinary Go HTTP client, with no special browser cookies.

The current episode embeds `Player` data and a production episode number
`0101`; the new parser does not depend on the old `VideoPlayer` component name.
It matches the short ID, season, episode and MGID before using the advertised
`topaz.paramount.tech` service. It fills the desktop template, omits unresolved
optional advertising/device placeholders, and preserves concrete query values.
It does not copy the reference's practice of dropping the entire service query.

## Failure point and implementation

The previous generic hook/webRequest flow waits for an HLS request from the
browser player. It cannot resolve the episode's public video-service JSON,
does not check its episode identity and can select an unrelated advertisement
or a child video playlist. A child playlist can lose the separate audio group.
This is the demonstrated code gap, not a claim of an observed Chrome failure:
live Chrome DevTools and Migaku UI were unavailable to this test environment.

The new path is page metadata → South Park-only service worker resolver →
`POST /api/resolve-southpark` → advertised service → validated HLS master and
video/audio → existing `POST /set-stream` → `/stream.m3u8` and `/proxy-segment`
→ Migaku Proxy playback. The existing proxy already rewrites audio and key
URIs and preserves masters with audio groups, so no playback rewrite was needed.

Only `.com` episode pages use this path. Generic hook/webRequest candidates
cannot replace the resolved episode on those tabs. Navigating away cannot
publish a stale result; pending work is deduplicated and reload gets fresh URLs.
RTP and general capture branches remain in place. Chrome permissions are unchanged.

The resolver uses bounded ordinary HTTPS requests, with User-Agent and episode
Referer; playback also receives its Origin. No browser cookies are imported.
All redirects and resource hosts are checked. Regional redirects, access errors,
locked/authenticated episodes, unknown services, mismatched episode IDs, invalid
HLS and DRM are errors. It accepts ordinary HLS AES-128 identity keys served to
the public player, but rejects SAMPLE-AES and DRM key formats. It never requests
a DRM license or changes a region/authentication parameter.

## Verification and limitations

From this machine's connection the test episode and service returned HTTP 200
without redirects; the master and video/audio playlists returned 200 and sampled
media returned 206. The master offered seven video resolutions up to 1920×1080
and separate audio. The proxy successfully decoded both video and audio with
FFmpeg for three seconds. No authentication or browser cookies were required.
These results establish initial media playback, not uninterrupted full-episode
playback. Signed URLs have a limited lifetime; they are fetched again on reload.
No fixed token lifetime is assumed, and expiry recovery is manual reload.

Automated regression tests cover invalid/foreign URLs, episode mismatch,
service templates and query preservation, HLS versus DASH, DRM rejection,
separate audio selection, keys/segments, regional errors/redirects, stale tabs,
ad suppression, generic capture and RTP. The RTP tests retain other-program,
DRM/ondemand, invalid URL and query-string cases. The live smoke test goes
through the actual HTTP resolver, set-stream and proxy, then decodes audio/video.
Chrome extension execution and Migaku UI playback still need the manual steps above.

From the project root, using the existing environment:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --test tests/test_capture_routing.mjs
$env:BRIDGE_EXTENSION_DIR='extension'
node --test tests/test_capture_routing.mjs
```

Live tests change the stream selected by the specified local server. They print
only status/resolution/decode summaries, never signed media URLs:

```powershell
$decoder='C:\Users\ottma\Videos\YDL-UI_v2.9.1.0_rtp-support-20260720\bin\ffmpeg\ffmpeg.exe'
.\.venv\Scripts\python.exe scripts\verify_stream.py southpark --ffmpeg $decoder
.\.venv\Scripts\python.exe scripts\verify_stream.py rtp --ffmpeg $decoder
```

## Rebuilding this local Windows installation

The normal release workflow uses Nuitka. The existing local installation uses
PyInstaller; the following reproduces its runtime format. Run from the project
root with the existing Python environment and local Terser package:

```powershell
.\.venv\Scripts\python.exe scripts\build.py
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onedir --windowed --name mstream_core --contents-directory . --icon dist\assets\mstream.ico --add-data 'dist\dashboard.html;.' --add-data 'dist\assets;assets' --paths dist --distpath local_build dist\main.py
Copy-Item -Path dist\extension\* -Destination extension -Recurse -Force
Copy-Item -LiteralPath dist\migaku-player-snippet.js -Destination migaku-player-snippet.js -Force
```

Stop the local server before replacing its runtime. Preserve the existing
`_internal` folder as a versioned backup, then copy `local_build/mstream_core`
to `_internal` and restart the root launcher. Do not overwrite a backup or
replace files while its executable is running. Keep `bin/yt-dlp-rtp-support.exe`
beside the root launcher for RTP. Reload Chrome's extension after every update.
