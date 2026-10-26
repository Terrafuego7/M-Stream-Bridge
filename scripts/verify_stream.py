"""Opt-in live test. Selects an episode on the running bridge; prints no signed URLs."""
import argparse
import json
import subprocess
import sys
import requests

PAGES = {
    "southpark": "https://www.southparkstudios.com/episodes/940f8z/south-park-cartman-gets-an-anal-probe-season-1-ep-1",
    "rtp": "https://www.rtp.pt/play/p17247/e958623/ruido",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", choices=PAGES)
    parser.add_argument("--base", default="http://127.0.0.1:7000")
    parser.add_argument("--page")
    parser.add_argument("--ffmpeg", required=True, help="Path to ffmpeg executable for audio/video decoding")
    args = parser.parse_args()
    base, page = args.base.rstrip("/"), args.page or PAGES[args.site]
    summary = {"site": args.site}
    health = requests.get(base + "/health", timeout=5)
    summary["server_version"] = health.json().get("version")
    response = requests.post(base + "/api/resolve-" + args.site, json={"page_url": page}, timeout=90)
    summary["resolve_http"] = response.status_code
    if not response.ok:
        summary["error"] = response.json().get("message", "Resolution failed")
        print(json.dumps(summary))
        return 1
    result = response.json()
    summary["height"] = result["height"]
    payload = {"stream_url": result["stream_url"], "hls_master_url": result["stream_url"],
               "stream_type": "hls", "page_url": page, "referer": page,
               "title": result["title"], "request_headers": result["request_headers"],
               "capture_source": args.site + "_resolver", "season": result.get("season"), "episode": result.get("episode")}
    summary["set_stream_http"] = requests.post(base + "/set-stream", json=payload, timeout=10).status_code
    playlist = requests.get(base + "/stream.m3u8", timeout=30)
    summary["manifest_http"] = playlist.status_code
    summary["hls"] = playlist.content.lstrip().startswith(b"#EXTM3U")
    summary["separate_audio"] = b"#EXT-X-MEDIA:TYPE=AUDIO" in playlist.content
    if summary["set_stream_http"] != 200 or not playlist.ok or not summary["hls"]:
        print(json.dumps(summary))
        return 1
    decoded = subprocess.run([args.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1",
                              "-i", base + "/stream.m3u8", "-map", "0:v:0", "-map", "0:a:0",
                              "-t", "3", "-f", "null", "-"], capture_output=True, text=True, timeout=90)
    progress = dict(line.split("=", 1) for line in decoded.stdout.splitlines() if "=" in line)
    summary.update({"decoder_exit": decoded.returncode, "frames": int(progress.get("frame", 0)),
                    "decoded_time": progress.get("out_time"), "decoder_errors": len(decoded.stderr.splitlines())})
    print(json.dumps(summary))
    return 0 if decoded.returncode == 0 and summary["frames"] > 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (requests.RequestException, subprocess.SubprocessError, ValueError, OSError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": "Live verification failed; no media URLs were logged."}))
        sys.exit(1)
