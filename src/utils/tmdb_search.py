# ==M-Stream Bridge==
# @name        M-Stream Bridge
# @version     __VERSION__
# @author      Zielzy
# @description Local bridge for non-DRM browser streams and Migaku Player.
# @homepage    https://github.com/Zielzy/M-Stream-Bridge
# ==/M-Stream Bridge==
"""
TMDB Search Query Helpers for Multi-Search Metadata Resolution.
"""

from __future__ import annotations
from core.config import get_tmdb_endpoint

import re
from typing import Any

import requests


def generate_tmdb_queries(title: str) -> list[str]:
    """
    Generate a list of search queries with increasing fuzziness.

    Prioritizes exact match, then stripped year, then stripped subtitles.
    """
    t = (title or "").strip()
    if not t:
        return []

    queries: list[str] = [t]

    # 1. Strip trailing year (e.g. "The Epoch Of Miyu 2026" -> "The Epoch Of Miyu")
    no_year = re.sub(r"\s+(?:19|20)\d{2}$", "", t).strip()
    if no_year and no_year not in queries:
        queries.append(no_year)

    # 2. Strip subtitles using strictly spaced colon or dash
    # (e.g. "Sword Art Online - Alicization" -> "Sword Art Online")
    # This prevents breaking titles like "Re:ZERO" or "86-Eighty Six"
    base_title = re.split(r"\s+[:\-]\s+", no_year or t)[0].strip()
    if base_title and base_title not in queries:
        queries.append(base_title)

    return queries


def tmdb_search(
    session: requests.Session,
    api_key: str | None,
    queries: list[str],
) -> list[dict[str, Any]]:
    """
    Search TMDB using a list of fallback queries.

    Returns the first valid movie/tv results array it finds.
    """
    for q in queries:
        if not q:
            continue
        try:
            url, params = get_tmdb_endpoint("search/multi")
            req_params = dict(params)
            req_params.update({"query": q, "include_adult": "false"})
            if api_key and "api_key" not in req_params:
                req_params["api_key"] = api_key
            resp = session.get(
                url,
                params=req_params,
                timeout=10,
            )
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                valid = [item for item in results if isinstance(item, dict) and item.get("media_type") in ("movie", "tv")]
                if valid:
                    return valid
        except Exception:
            continue

    return []

