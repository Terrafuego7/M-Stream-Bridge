"""Allowlisted X capture diagnostics; no titles, post/media URLs or headers."""
import re
import time

STAGES = {"selected", "proxy_checked", "player_loading", "player_playing", "player_error",
          "audio_requested", "audio_ready", "audio_error"}
CODES = {"ok", "hls_network", "hls_media", "native_media", "autoplay_blocked",
         "unsupported_hls", "no_video_element", "proxy_required", "player_setup",
         "audio_extract_failed", "x_fragment_selected"}


def valid_capture_id(value):
    return isinstance(value, str) and re.fullmatch(r"x-[a-z0-9-]{8,64}", value) is not None


def new_trace(capture_id):
    return record({"capture_id": capture_id, "events": []}, {"stage": "selected", "code": "ok"})


def record(trace, event):
    stage, code = event.get("stage"), event.get("code", "ok")
    if stage not in STAGES or code not in CODES:
        raise ValueError("Unsupported diagnostic event")
    safe = {"stage": stage, "code": code, "at": int(time.time() * 1000)}
    for key, low, high in (("http", 100, 599), ("media_error", 1, 4)):
        value = event.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high:
            safe[key] = value
    events = (trace.get("events", []) + [safe])[-20:]
    # A late extension probe must not hide a player error or confirmed playback.
    current = trace.get("stage")
    effective = current if stage == "proxy_checked" and current in {"player_loading", "player_playing", "player_error"} else stage
    return {"capture_id": trace["capture_id"], "stage": effective, "events": events}
