"""
Scraper for uakino.best — extracts dubbing options, episode URLs, and m3u8 streams.

Flow:
  1. Fetch the season page to get news_id and dle_edittime.
  2. POST to /engine/ajax/playlists.php — returns HTML fragment with
     dubbing tabs (.playlists-lists li[data-id]) and
     episode rows (.playlists-videos li[data-id, data-voice, data-file]).
  3. For each episode the data-file attribute is a protocol-relative URL to
     ashdi.vip (//ashdi.vip/vod/<id>). Fetch that page and extract the
     m3u8 URL from the Playerjs initialisation script.
"""

import asyncio
import re
from functools import partial
from typing import Optional

import requests
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

_PLAYLIST_ENDPOINT = "https://uakino.best/engine/ajax/playlists.php"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_absolute(url: str) -> str:
    """Convert protocol-relative URL (//host/path) to https://host/path."""
    if url.startswith("//"):
        return "https:" + url
    return url


def _fetch(url: str, *, method: str = "GET", data: Optional[dict] = None,
           referer: Optional[str] = None) -> requests.Response:
    headers = dict(_HEADERS)
    if referer:
        headers["Referer"] = referer
    if method == "POST":
        headers["X-Requested-With"] = "XMLHttpRequest"
        headers["Accept"] = "application/json, text/javascript, */*; q=0.01"
        resp = requests.post(url, headers=headers, data=data, timeout=30)
    else:
        resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp


def _get_playlist_html(page_url: str) -> str:
    """
    Fetch the season page, then call the AJAX playlist endpoint.
    Returns the raw HTML fragment with dubbing tabs and episode list.
    """
    resp = _fetch(page_url)
    text = resp.text

    # Extract news_id from the playlists-ajax div
    news_id_match = re.search(r'data-news_id=["\'](\d+)["\']', text)
    if not news_id_match:
        raise ValueError(f"Cannot find data-news_id on page: {page_url}")
    news_id = news_id_match.group(1)

    # Extract dle_edittime (cache-buster required by the endpoint)
    edittime_match = re.search(r'dle_edittime\s*=\s*["\']?(\d+)', text)
    if not edittime_match:
        raise ValueError(f"Cannot find dle_edittime on page: {page_url}")
    edittime = edittime_match.group(1)

    payload = {"news_id": news_id, "xfield": "playlist", "ti": edittime}
    ajax_resp = _fetch(_PLAYLIST_ENDPOINT, method="POST", data=payload, referer=page_url)

    try:
        json_data = ajax_resp.json()
    except Exception as exc:
        raise ValueError(f"Playlist AJAX did not return JSON: {exc}") from exc

    if not json_data.get("success"):
        raise ValueError(f"Playlist AJAX returned failure: {json_data.get('message')}")

    return json_data["response"]


def _parse_playlist_html(html: str) -> dict:
    """
    Parse the playlist HTML fragment and return:
      {
        "dubbings": [str, ...],          # dubbing names in order
        "dubbing_ids": {name: data_id},  # e.g. {"DniproFilm": "0_0"}
        "episodes": [                    # all episode li elements info
          {"voice": str, "file": str, "data_id": str, "title": str},
          ...
        ]
      }
    """
    soup = BeautifulSoup(html, "html.parser")

    # Dubbing tabs live in .playlists-lists .playlists-items li[data-id]
    dubbing_names: list[str] = []
    dubbing_ids: dict[str, str] = {}

    lists_div = soup.find("div", class_="playlists-lists")
    if lists_div:
        for li in lists_div.find_all("li"):
            data_id = li.get("data-id")
            if not data_id:
                continue  # "Рейтинг озвучень" and similar decorative items
            name_text = li.get_text(strip=True)
            # Strip episode count in parentheses: "DniproFilm (1-2)" → "DniproFilm"
            name = re.sub(r"\s*\(\d+[–\-]\d+\)\s*$", "", name_text).strip()
            if not name:
                name = name_text
            dubbing_names.append(name)
            dubbing_ids[name] = data_id

    # Episode rows live in .playlists-videos .playlists-items li
    episodes: list[dict] = []
    videos_div = soup.find("div", class_="playlists-videos")
    if videos_div:
        for li in videos_div.find_all("li"):
            data_file = li.get("data-file")
            data_id = li.get("data-id")
            data_voice = li.get("data-voice", "")
            if not data_file:
                continue
            episodes.append({
                "voice": data_voice,
                "file": _make_absolute(data_file),
                "data_id": data_id,
                "title": li.get_text(strip=True),
            })

    return {
        "dubbings": dubbing_names,
        "dubbing_ids": dubbing_ids,
        "episodes": episodes,
    }


def _sync_get_dubbing_options(url: str) -> list[str]:
    html = _get_playlist_html(url)
    parsed = _parse_playlist_html(html)
    return parsed["dubbings"]


def _sync_parse_season_page(url: str, dubbing: str) -> dict:
    html = _get_playlist_html(url)
    parsed = _parse_playlist_html(html)

    dubbings = parsed["dubbings"]
    episodes = parsed["episodes"]

    # Match episodes for the requested dubbing
    # Strategy: match by data-voice field (exact), then fallback to dubbing_ids
    episode_urls: list[str] = []

    # Try matching by voice name first
    matched_by_voice = [ep["file"] for ep in episodes if ep["voice"] == dubbing]
    if matched_by_voice:
        episode_urls = matched_by_voice
    else:
        # Fallback: match by data_id
        target_id = parsed["dubbing_ids"].get(dubbing)
        if target_id:
            episode_urls = [ep["file"] for ep in episodes if ep["data_id"] == target_id]

    if not episode_urls and dubbing not in (parsed["dubbing_ids"] or {}):
        raise ValueError(
            f"Dubbing {dubbing!r} not found. Available: {dubbings}"
        )

    return {"dubbings": dubbings, "episode_urls": episode_urls}


def _sync_get_m3u8_url(episode_url: str) -> str:
    """
    Fetch an ashdi.vip episode page and extract the m3u8 URL from the
    Playerjs({..., file:'<url>.m3u8', ...}) script block.
    """
    resp = _fetch(episode_url, referer="https://uakino.best/")
    text = resp.text

    # Pattern: file:'<url>.m3u8'  (single or double quotes)
    m3u8_match = re.search(
        r"""file\s*:\s*['"]((https?:)?//[^'"]+\.m3u8)['"]""",
        text,
    )
    if not m3u8_match:
        raise ValueError(f"No m3u8 URL found on episode page: {episode_url}")

    url = m3u8_match.group(1)
    return _make_absolute(url)


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------

async def get_dubbing_options(url: str) -> list[str]:
    """Return the list of dubbing names available on the season page."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_sync_get_dubbing_options, url))


async def parse_season_page(url: str, dubbing: str) -> dict:
    """
    Return {"dubbings": [str], "episode_urls": [str]}.
    episode_urls are ordered episode player URLs for the chosen dubbing.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_sync_parse_season_page, url, dubbing))


async def get_m3u8_url(episode_url: str) -> str:
    """Fetch the episode player page and extract the HLS m3u8 URL."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_sync_get_m3u8_url, episode_url))
