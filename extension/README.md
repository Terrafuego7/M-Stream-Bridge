# M-Stream Bridge Extension

This folder is the Chrome extension folder used with Load unpacked.

## Install

1. Open `chrome://extensions`.
2. Enable Developer mode.
3. Click Load unpacked.
4. Select this `extension` folder.
5. Start the local server with `M-Stream Bridge.exe`.

For RTP Play, the matching server build must include `bin/yt-dlp-rtp-support.exe`
beside the launcher. The extension loaded in Chrome must be this release's
`extension` folder. Reload it after updating the files.

## What It Does

The extension captures browser media request events and page metadata, then sends them to the local server at `http://127.0.0.1:7000`.

Stream selection, title cleanup, Jimaku matching, and subtitle handling run in the local server package.

## RTP Play

On an episode page such as `https://www.rtp.pt/play/p17247/e958623/ruido`,
the extension asks the local server to resolve the episode. The server uses
yt-dlp's RTP extractor, accepts only a clear HLS variant for the same program,
and checks the manifest and first media segment before sending the URL through
`/set-stream`. URLs found in unrelated HTML blocks, DASH manifests, and DRM
paths are not sent to Migaku Player. The server obtains a fresh URL on page
load; reload the episode if RTP expires a URL while the player is open.

To verify: open the episode in Chrome, open the extension popup, and confirm it
shows an HLS stream. `http://127.0.0.1:7000/api/current-stream` should show
`capture_source: rtp_resolver` and the stream host `streaming-vod.rtp.pt`.
`http://127.0.0.1:7000/stream.m3u8` must begin with `#EXTM3U`; its first
`/proxy-segment` URL must return media bytes. Run the Migaku Player snippet and
select Proxy playback. Extension errors appear under **Service worker → Inspect
views** on `chrome://extensions`; server errors appear at `/api/logs`.
