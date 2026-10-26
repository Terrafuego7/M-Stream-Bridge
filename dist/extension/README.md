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
the stream host `streaming-vod.rtp.pt` and the episode title.
`http://127.0.0.1:7000/stream.m3u8` must begin with `#EXTM3U`; its first
`/proxy-segment` URL must return media bytes. Run the Migaku Player snippet and
select Proxy playback. Extension errors appear under **Service worker → Inspect
views** on `chrome://extensions`; server errors appear at `/api/logs`.

## South Park Studios (server 3.0.8 or newer)

Open this episode, not the homepage:
`https://www.southparkstudios.com/episodes/940f8z/south-park-cartman-gets-an-anal-probe-season-1-ep-1`.
Reload the extension in `chrome://extensions`, then reload the episode and keep
its tab active until the popup says **South Park HLS verified (1080p)**. Reopen
the popup if it was opened while validation was running. Open Migaku Player,
run the supplied `migaku-player-snippet.js`, and select **Proxy** playback.

The local server reads the episode's advertised public video service and
validates the HLS master, best video, default audio, public HLS key and initial
segments. It preserves the master so audio is not lost. The extension ignores
generic media/ad captures only on these South Park episode pages. No new Chrome
permissions or browser cookies are needed. It does not require yt-dlp for South Park.

Only English `.com/episodes/…/south-park-…-season-N-ep-N` pages are supported.
Regional redirects, unavailable/authenticated episodes, DASH and DRM are rejected
with a popup error; no region or authentication workaround is attempted.
Ordinary AES-128 HLS identity keys are supported by the existing proxy.
Signed media URLs expire: reload the episode to obtain a fresh URL, then reload
Proxy playback. Do not share signed URLs or current-stream API responses.

Source files live in `src/extension`; the build stages them in `dist/extension`.
Chrome loads the release copy in the root `extension` folder. Updating only
`src` or only `dist` is insufficient. See `SOUTHPARK_SUPPORT.md` in the project
root for the investigation, build commands and reproducible live tests.
