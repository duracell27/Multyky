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
import logging
import re
from functools import partial
from typing import Optional

logger = logging.getLogger(__name__)

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


def _extract_episode_number(title: str) -> Optional[int]:
    """Try to extract a real episode number from a playlist title string.

    Handles formats like: 'Серія 36', '36 серія', 'Episode 5', '12.', '12', etc.
    Returns None if no number can be reliably extracted.
    """
    if not title:
        return None
    # "Серія 36" / "серія 36" / "Episode 36"
    m = re.search(r'(?:серія|series|episode)\s*(\d+)', title, re.I)
    if m:
        return int(m.group(1))
    # "36 серія" / "36 series"
    m = re.search(r'(\d+)\s*(?:серія|series|episode)', title, re.I)
    if m:
        return int(m.group(1))
    # Bare number, possibly with a dot: "36" / "36."
    m = re.fullmatch(r'\s*(\d+)\.?\s*', title)
    if m:
        return int(m.group(1))
    return None


def _sync_parse_season_page(url: str, dubbing: str) -> dict:
    html = _get_playlist_html(url)
    parsed = _parse_playlist_html(html)

    dubbings = parsed["dubbings"]
    episodes = parsed["episodes"]

    # Empty dubbing string means caller only wants the dubbings list (no episode filtering).
    if not dubbing:
        return {"dubbings": dubbings, "episode_urls": [], "episode_numbers": []}

    # Match episodes for the requested dubbing
    # Strategy: match by data-voice field (exact), then fallback to dubbing_ids
    matched: list[dict] = []

    matched_by_voice = [ep for ep in episodes if ep["voice"] == dubbing]
    if matched_by_voice:
        matched = matched_by_voice
    else:
        target_id = parsed["dubbing_ids"].get(dubbing)
        if target_id:
            matched = [ep for ep in episodes if ep["data_id"] == target_id]

    if not matched and dubbing not in parsed["dubbing_ids"]:
        raise ValueError(
            f"Dubbing {dubbing!r} not found. Available: {dubbings}"
        )

    if not matched:
        raise ValueError(
            f"Dubbing '{dubbing}' found on page but returned 0 episodes. "
            f"Available dubbings: {dubbings}"
        )

    episode_urls = [ep["file"] for ep in matched]

    # Extract real episode numbers from titles; fall back to 1-based sequential
    raw_numbers = [_extract_episode_number(ep.get("title", "")) for ep in matched]
    if all(n is not None for n in raw_numbers):
        episode_numbers = raw_numbers
    else:
        episode_numbers = list(range(1, len(matched) + 1))

    return {"dubbings": dubbings, "episode_urls": episode_urls, "episode_numbers": episode_numbers}


def _resolve_best_quality_m3u8(master_url: str) -> str:
    """
    If master_url is an HLS master playlist, return the variant URL with the
    highest BANDWIDTH value. Otherwise return master_url unchanged.
    """
    try:
        resp = _fetch(master_url)
        content = resp.text
    except Exception:
        return master_url

    if "#EXT-X-STREAM-INF" not in content:
        return master_url  # already a media playlist, not a master

    best_bw = -1
    best_url = None
    lines = content.splitlines()
    base = master_url.rsplit("/", 1)[0]

    for i, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF"):
            continue
        bw_match = re.search(r"BANDWIDTH=(\d+)", line)
        if not bw_match:
            continue
        bw = int(bw_match.group(1))
        if bw > best_bw and i + 1 < len(lines):
            variant = lines[i + 1].strip()
            if variant and not variant.startswith("#"):
                if not variant.startswith("http"):
                    variant = base + "/" + variant
                best_bw = bw
                best_url = variant

    if best_url:
        logger.info(f"Selected best quality variant (bandwidth={best_bw}): {best_url}")
        return best_url
    return master_url


def _sync_get_m3u8_url(episode_url: str) -> str:
    """
    Fetch an ashdi.vip episode page and extract the m3u8 URL from the
    Playerjs({..., file:'<url>.m3u8', ...}) script block.
    Resolves master playlists to the highest-bandwidth variant.
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

    url = _make_absolute(m3u8_match.group(1))
    return _resolve_best_quality_m3u8(url)


def _sync_parse_movie_page(url: str) -> dict:
    """
    Parse a uakino.best movie page and return metadata.

    Returns dict with keys: title, title_en, year, imdb, poster_url, dubbings.
    Any field can be None if not found on the page.

    Two page variants are handled:
      • AJAX playlist variant  — has a <div class="playlists-ajax" data-news_id="...">
        block; dubbing list comes from the playlist endpoint (same as series pages).
        Each episode in the playlist is one dubbing of the movie.
      • Direct iframe variant  — has a plain <iframe src="https://ashdi.vip/vod/...">
        block; the tab label ("UA #1", etc.) is treated as the single dubbing.
    """
    resp = _fetch(url)
    soup = BeautifulSoup(resp.text, "html.parser")

    # ── Ukrainian title ───────────────────────────────────────────────────
    title = None
    solototle = soup.find(class_="solototle")
    if solototle:
        title = solototle.get_text(strip=True)
    else:
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)

    # ── English / original title ──────────────────────────────────────────
    title_en = None
    orig = soup.find(class_="origintitle")
    if orig:
        title_en = orig.get_text(strip=True)

    # ── Year — from the .film-info section ────────────────────────────────
    year = None
    film_info = soup.find(class_="film-info")
    if film_info:
        for item in film_info.find_all("div", class_="fi-item"):
            label = item.find("div", class_="fi-label")
            desc = item.find("div", class_="fi-desc")
            if label and desc and "Рік" in label.get_text():
                m = re.search(r"\d{4}", desc.get_text(strip=True))
                if m:
                    year = int(m.group(0))
                break

    # ── IMDB rating — fi-item whose label contains the imdb-mini image ────
    imdb = None
    if film_info:
        for item in film_info.find_all("div", class_="fi-item"):
            label = item.find("div", class_="fi-label")
            desc = item.find("div", class_="fi-desc")
            if label and label.find("img", src=re.compile(r"imdb", re.I)):
                if desc:
                    m = re.search(r"([0-9]+\.[0-9]+)", desc.get_text(strip=True))
                    if m:
                        try:
                            imdb = float(m.group(1))
                        except ValueError:
                            pass
                break

    # ── Poster — full-resolution URL from the .film-poster anchor ─────────
    poster_url = None
    film_poster = soup.find("div", class_="film-poster")
    if film_poster:
        anchor = film_poster.find("a", href=True)
        if anchor:
            href = anchor["href"]
            poster_url = href if href.startswith("http") else "https://uakino.best" + href

    # ── Dubbings ──────────────────────────────────────────────────────────
    # Check which player variant the page uses.
    ajax_div = soup.find("div", class_="playlists-ajax")
    if ajax_div and ajax_div.get("data-news_id"):
        # AJAX variant: reuse existing playlist helpers.
        # Each "episode" in the playlist is one dubbing of the movie.
        try:
            playlist_html = _get_playlist_html(url)
            parsed = _parse_playlist_html(playlist_html)
            # For movies the dubbing name lives in episode["voice"]
            voices = [ep["voice"] for ep in parsed["episodes"] if ep.get("voice")]
            dubbings = voices if voices else parsed["dubbings"]
        except Exception as e:
            logger.warning(f"Could not fetch playlist for movie {url}: {e}")
            dubbings = []
    else:
        # Direct iframe variant: collect non-Trailer tab labels.
        dubbings = []
        players_section = soup.find("div", class_="players-section")
        if players_section:
            tabs_ul = players_section.find("ul", class_="tabs")
            if tabs_ul:
                for li in tabs_ul.find_all("li"):
                    text_val = li.get_text(strip=True)
                    if text_val and "Трейлер" not in text_val:
                        dubbings.append(text_val)

    return {
        "title": title,
        "title_en": title_en,
        "year": year,
        "imdb": imdb,
        "poster_url": poster_url,
        "dubbings": dubbings,
    }


def _sync_download_poster(poster_url: str, output_path: str) -> bool:
    """Download a poster image to output_path. Returns True on success."""
    try:
        resp = _fetch(poster_url)
        with open(output_path, "wb") as f:
            f.write(resp.content)
        return True
    except Exception as e:
        logger.warning(f"Failed to download poster from {poster_url}: {e}")
        return False


def _sync_get_movie_m3u8(url: str, dubbing: str) -> str:
    """
    For a movie page, get the m3u8 URL for the selected dubbing.

    Handles two page variants:
      • AJAX playlist variant — fetches the playlist and maps dubbing → ashdi URL.
      • Direct iframe variant — ignores dubbing (only one stream) and reads the
        ashdi iframe src directly from the page HTML.
    """
    resp = _fetch(url)
    soup = BeautifulSoup(resp.text, "html.parser")

    # Determine which variant we're dealing with
    ajax_div = soup.find("div", class_="playlists-ajax")
    if ajax_div and ajax_div.get("data-news_id"):
        # AJAX variant — same logic as series pages but per-dubbing
        playlist_html = _get_playlist_html(url)
        parsed = _parse_playlist_html(playlist_html)
        episodes = parsed["episodes"]

        # Match by voice name (exact)
        matched = [ep["file"] for ep in episodes if ep["voice"] == dubbing]
        if not matched:
            # Fallback: match by data_id
            target_id = parsed["dubbing_ids"].get(dubbing)
            if target_id:
                matched = [ep["file"] for ep in episodes if ep["data_id"] == target_id]

        if not matched:
            voices = [ep["voice"] for ep in episodes if ep.get("voice")]
            raise ValueError(
                f"Dubbing {dubbing!r} not found. Available: {voices or parsed['dubbings']}"
            )

        episode_url = matched[0]
    else:
        # Direct iframe variant — there is only one ashdi player on the page
        iframe = soup.find("iframe", src=re.compile(r"ashdi\.vip", re.I))
        if not iframe:
            raise ValueError(f"No ashdi.vip iframe found on movie page: {url}")
        episode_url = iframe["src"]

    return _sync_get_m3u8_url(episode_url)


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------

async def get_dubbing_options(url: str) -> list[str]:
    """Return the list of dubbing names available on the season page.

    Delegates to parse_season_page with an empty dubbing to avoid a
    redundant HTTP round-trip when the caller later calls parse_season_page.
    """
    result = await parse_season_page(url, dubbing="")
    return result["dubbings"]


async def parse_season_page(url: str, dubbing: str) -> dict:
    """
    Return {"dubbings": [str], "episode_urls": [str]}.
    episode_urls are ordered episode player URLs for the chosen dubbing.
    Pass dubbing="" to retrieve only the dubbings list without episode filtering.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_sync_parse_season_page, url, dubbing))


async def get_m3u8_url(episode_url: str) -> str:
    """Fetch the episode player page and extract the HLS m3u8 URL."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_sync_get_m3u8_url, episode_url))


async def parse_movie_page(url: str) -> dict:
    """
    Parse a uakino.best movie page.
    Returns {title, title_en, year, imdb, poster_url, dubbings}.
    Any field may be None if not found.
    Handles both direct-iframe and AJAX-playlist page variants.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_sync_parse_movie_page, url))


async def download_poster(poster_url: str, output_path: str) -> bool:
    """Download poster image to output_path. Returns True on success."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, partial(_sync_download_poster, poster_url, output_path)
    )


async def get_movie_m3u8(url: str, dubbing: str) -> str:
    """
    Get m3u8 URL for the given dubbing from a movie page.
    Handles both direct-iframe and AJAX-playlist page variants.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, partial(_sync_get_movie_m3u8, url, dubbing)
    )
