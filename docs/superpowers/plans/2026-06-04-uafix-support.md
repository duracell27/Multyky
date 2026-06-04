# uafix.net Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add uafix.net as an alternative content source — all 4 auto-download commands gain a site-picker step, the scraper routes internally by domain, and `download_loop.py` passes `dubbing` when fetching m3u8.

**Architecture:** Site detection lives entirely in `scraper.py`; handlers only add a one-step site picker and relax URL validation. `parse_season_page` and `get_dubbing_options` gain an optional `season: int` parameter required by the uafix series scraper (uakino ignores it). uafix movies use `zetvideo.net` (single stream, dubbing always `"UA"`); uafix series use `ashdi.vip/serial/<id>?season=N&episode=M` URLs whose Playerjs JSON embeds all dubbings.

**Tech Stack:** Python 3.13, aiogram 3.x FSM, requests, BeautifulSoup4, re, json, urllib.parse

---

## File Map

| Action | Path |
|--------|------|
| Modify | `bot/states.py` |
| Modify | `bot/utils/scraper.py` |
| Modify | `bot/utils/download_loop.py` |
| Modify | `bot/handlers/auto_movie.py` |
| Modify | `bot/handlers/auto_anime_movie.py` |
| Modify | `bot/handlers/auto_download.py` |
| Modify | `bot/handlers/auto_anime_download.py` |
| Modify | `bot/handlers/common.py` |

---

## Task 1: Add `choosing_site` state to all 4 state groups

**Files:**
- Modify: `bot/states.py`

- [ ] **Step 1: Add `choosing_site = State()` as the first state in each of the four auto-download state groups**

In `bot/states.py`, find `class AutoMovieStates` and add `choosing_site` as the FIRST state:

```python
class AutoMovieStates(StatesGroup):
    """Стани для автоматичного завантаження фільму"""
    choosing_site = State()        # ← new
    waiting_for_url = State()
    confirming_metadata = State()
    # ... rest unchanged
```

Do the same for `AutoDownloadStates`, `AutoAnimeMovieStates`, `AutoAnimeDownloadStates` — add `choosing_site = State()` as the first state in each group.

- [ ] **Step 2: Commit**

```bash
git add bot/states.py
git commit -m "feat: add choosing_site state to auto-download state groups"
```

---

## Task 2: uafix scraper — metadata helper + movie scraper

**Files:**
- Modify: `bot/utils/scraper.py`

The current `_sync_parse_movie_page` has metadata extraction duplicated inline. Extract it into a shared helper, then add uafix movie functions.

- [ ] **Step 1: Add `_detect_site` and `_extract_dle_metadata` before `_sync_parse_movie_page`**

Read `bot/utils/scraper.py`. After the `_sync_download_poster` function (around line 400), insert these two new functions:

```python
def _detect_site(url: str) -> str:
    """Return 'uafix' if URL is from uafix.net, else 'uakino'."""
    if "uafix.net" in url:
        return "uafix"
    return "uakino"


def _extract_dle_metadata(soup: "BeautifulSoup", base_url: str) -> dict:
    """
    Extract title/title_en/year/imdb/poster_url from a DLE (DataLife Engine) page.
    Works for both uakino.best and uafix.net which share the same CMS and CSS classes.
    Returns dict with keys: title, title_en, year, imdb, poster_url (all may be None).
    """
    title = None
    solototle = soup.find(class_="solototle")
    if solototle:
        title = solototle.get_text(strip=True)
    else:
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)

    title_en = None
    orig = soup.find(class_="origintitle")
    if orig:
        title_en = orig.get_text(strip=True)

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

    poster_url = None
    film_poster = soup.find("div", class_="film-poster")
    if film_poster:
        anchor = film_poster.find("a", href=True)
        if anchor:
            href = anchor["href"]
            poster_url = href if href.startswith("http") else base_url.rstrip("/") + href

    return {
        "title": title,
        "title_en": title_en,
        "year": year,
        "imdb": imdb,
        "poster_url": poster_url,
    }
```

- [ ] **Step 2: Refactor `_sync_parse_movie_page` to use `_extract_dle_metadata`**

Replace the metadata extraction block inside `_sync_parse_movie_page` with a call to the new helper:

```python
def _sync_parse_movie_page(url: str) -> dict:
    """
    Parse a uakino.best movie page and return metadata.
    ...
    """
    resp = _fetch(url)
    soup = BeautifulSoup(resp.text, "html.parser")

    meta = _extract_dle_metadata(soup, "https://uakino.best")
    title = meta["title"]
    title_en = meta["title_en"]
    year = meta["year"]
    imdb = meta["imdb"]
    poster_url = meta["poster_url"]

    # ── Dubbings ──────────────────────────────────────────────────────────────
    ajax_div = soup.find("div", class_="playlists-ajax")
    if ajax_div and ajax_div.get("data-news_id"):
        try:
            playlist_html = _get_playlist_html(url)
            parsed = _parse_playlist_html(playlist_html)
            voices = [ep["voice"] for ep in parsed["episodes"] if ep.get("voice")]
            dubbings = voices if voices else parsed["dubbings"]
        except Exception as e:
            logger.warning(f"Could not fetch playlist for movie {url}: {e}")
            dubbings = []
    else:
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
```

- [ ] **Step 3: Add `_sync_parse_uafix_movie_page` and `_sync_get_uafix_movie_m3u8`**

Insert after `_sync_parse_movie_page`:

```python
def _sync_parse_uafix_movie_page(url: str) -> dict:
    """
    Parse a uafix.net movie page. Returns same dict shape as _sync_parse_movie_page.
    uafix movies always have a single stream (no dubbing choice), so dubbings=["UA"].
    """
    resp = _fetch(url)
    soup = BeautifulSoup(resp.text, "html.parser")
    meta = _extract_dle_metadata(soup, "https://uafix.net")
    return {**meta, "dubbings": ["UA"]}


def _sync_get_uafix_movie_m3u8(url: str) -> str:
    """
    Get m3u8 URL for a uafix.net movie.
    Flow: movie page → zetvideo.net iframe → Playerjs file → m3u8.
    """
    resp = _fetch(url)
    soup = BeautifulSoup(resp.text, "html.parser")

    iframe = soup.find("iframe", src=re.compile(r"zetvideo\.net", re.I))
    if not iframe:
        raise ValueError(f"No zetvideo.net iframe found on uafix movie page: {url}")

    zetvideo_url = _make_absolute(iframe["src"])
    resp2 = _fetch(zetvideo_url, referer=url)

    m3u8_match = re.search(
        r"""file\s*:\s*['"]((https?:)?//[^'"]+\.m3u8)['"]""",
        resp2.text,
    )
    if not m3u8_match:
        raise ValueError(f"No m3u8 URL found on zetvideo page: {zetvideo_url}")

    return _resolve_best_quality_m3u8(_make_absolute(m3u8_match.group(1)))
```

- [ ] **Step 4: Commit**

```bash
git add bot/utils/scraper.py
git commit -m "feat: add uafix movie scraper functions and extract _extract_dle_metadata helper"
```

---

## Task 3: uafix scraper — series + ashdi serial m3u8

**Files:**
- Modify: `bot/utils/scraper.py`

- [ ] **Step 1: Add `import json` and `from urllib.parse import urlparse, parse_qs` at the top of `scraper.py`**

The file currently imports: `asyncio, logging, re, functools.partial, typing.Optional, requests, BeautifulSoup`. Add:

```python
import json
from urllib.parse import urlparse, parse_qs
```

- [ ] **Step 2: Add `_sync_get_ashdi_serial_m3u8`**

Insert after `_sync_get_uafix_movie_m3u8`:

```python
def _sync_get_ashdi_serial_m3u8(serial_url: str, dubbing: Optional[str]) -> str:
    """
    Fetch ashdi.vip/serial/<id>?season=N&episode=M, parse the Playerjs JSON,
    find the correct dubbing/season/episode, return m3u8 URL.

    The Playerjs JSON structure:
      [{"title":"DubName","folder":[{"title":"Сезон N","folder":[
          {"title":"Серія M","file":"m3u8_url",...}
      ]}]},...]
    """
    parsed_url = urlparse(serial_url)
    params = parse_qs(parsed_url.query)
    season_num = int(params.get("season", [1])[0])
    episode_num = int(params.get("episode", [1])[0])

    resp = _fetch(serial_url, referer="https://uafix.net/")
    text = resp.text

    json_match = re.search(r"file\s*:\s*'(\[.*?\])'", text, re.DOTALL)
    if not json_match:
        raise ValueError(f"No Playerjs JSON found on ashdi serial page: {serial_url}")

    data = json.loads(json_match.group(1))

    if dubbing:
        dub_entry = next(
            (d for d in data if d.get("title", "").strip() == dubbing), None
        )
        if dub_entry is None:
            available = [d.get("title", "").strip() for d in data]
            raise ValueError(f"Dubbing {dubbing!r} not found. Available: {available}")
    else:
        dub_entry = data[0] if data else None

    if not dub_entry:
        raise ValueError(f"No dubbing entries in ashdi serial page: {serial_url}")

    seasons_folder = dub_entry.get("folder", [])
    season_entry = next(
        (s for s in seasons_folder if re.search(rf"\b{season_num}\b", s.get("title", ""))),
        seasons_folder[0] if seasons_folder else None,
    )
    if not season_entry:
        raise ValueError(f"Season {season_num} not found for dubbing '{dubbing}'")

    episodes_folder = season_entry.get("folder", [])
    ep_entry = next(
        (e for e in episodes_folder if re.search(rf"\b{episode_num}\b", e.get("title", ""))),
        episodes_folder[0] if episodes_folder else None,
    )
    if not ep_entry:
        raise ValueError(f"Episode {episode_num} not found in season {season_num} for dubbing '{dubbing}'")

    m3u8_url = ep_entry.get("file", "")
    if not m3u8_url:
        raise ValueError(f"No file URL in episode entry for {serial_url}")

    return _resolve_best_quality_m3u8(m3u8_url)
```

- [ ] **Step 3: Update `_sync_get_m3u8_url` to accept optional dubbing and handle ashdi serial URLs**

Replace the existing `_sync_get_m3u8_url`:

```python
def _sync_get_m3u8_url(episode_url: str, dubbing: Optional[str] = None) -> str:
    """
    Fetch an episode player page and extract the HLS m3u8 URL.

    Handles two URL types:
      • ashdi.vip/serial/<id>?season=N&episode=M  — uafix.net series; dubbing required
      • ashdi.vip/vod/<id>                        — uakino.best; dubbing ignored
    Resolves master playlists to the highest-bandwidth variant.
    """
    if "ashdi.vip/serial/" in episode_url:
        return _sync_get_ashdi_serial_m3u8(episode_url, dubbing)

    resp = _fetch(episode_url, referer="https://uakino.best/")
    text = resp.text

    m3u8_match = re.search(
        r"""file\s*:\s*['"]((https?:)?//[^'"]+\.m3u8)['"]""",
        text,
    )
    if not m3u8_match:
        raise ValueError(f"No m3u8 URL found on episode page: {episode_url}")

    url = _make_absolute(m3u8_match.group(1))
    return _resolve_best_quality_m3u8(url)
```

- [ ] **Step 4: Add `_sync_parse_uafix_series_page`**

Insert after `_sync_get_ashdi_serial_m3u8`:

```python
def _sync_parse_uafix_series_page(url: str, season: int, dubbing: str) -> dict:
    """
    Parse a uafix.net series page (e.g. https://uafix.net/serials/rik-ta-morti/).

    When dubbing == "":
      Returns {"dubbings": [...], "episode_urls": [], "episode_numbers": []}.
      Fetches the first episode of `season` to read available dubbings from ashdi JSON.

    When dubbing != "":
      Returns {"dubbings": [], "episode_urls": [...ashdi serial URLs...], "episode_numbers": [...]}.
      episode_urls are ashdi.vip/serial/<id>?season=N&episode=M for each episode.
    """
    resp = _fetch(url)
    soup = BeautifulSoup(resp.text, "html.parser")

    # Collect all episode page URLs for the requested season
    season_pat = re.compile(
        r"season-(\d+)-episode-(\d+)", re.I
    )
    seen_eps: dict[int, str] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.startswith("http"):
            href = "https://uafix.net" + href if href.startswith("/") else href
        m = season_pat.search(href)
        if m and int(m.group(1)) == season:
            ep_num = int(m.group(2))
            if ep_num not in seen_eps:
                seen_eps[ep_num] = href

    if not seen_eps:
        raise ValueError(f"No episodes found for season {season} on page: {url}")

    sorted_eps = sorted(seen_eps.items())  # [(ep_num, page_url), ...]

    # Fetch the first episode page to get the ashdi serial ID
    first_ep_page = sorted_eps[0][1]
    resp2 = _fetch(first_ep_page)
    soup2 = BeautifulSoup(resp2.text, "html.parser")
    iframe = soup2.find("iframe", src=re.compile(r"ashdi\.vip/serial/", re.I))
    if not iframe:
        raise ValueError(f"No ashdi serial iframe on episode page: {first_ep_page}")

    ashdi_src = _make_absolute(iframe["src"])
    sid_match = re.search(r"ashdi\.vip/serial/(\d+)", ashdi_src)
    if not sid_match:
        raise ValueError(f"Cannot extract serial ID from: {ashdi_src}")
    serial_id = sid_match.group(1)

    episode_numbers = [ep_num for ep_num, _ in sorted_eps]

    if not dubbing:
        # Fetch dubbing list from the ashdi JSON
        first_ashdi = f"https://ashdi.vip/serial/{serial_id}?season={season}&episode={episode_numbers[0]}"
        resp3 = _fetch(first_ashdi, referer=url)
        json_match = re.search(r"file\s*:\s*'(\[.*?\])'", resp3.text, re.DOTALL)
        if not json_match:
            raise ValueError(f"No Playerjs JSON on ashdi serial page: {first_ashdi}")
        data = json.loads(json_match.group(1))
        dubbings = [d.get("title", "").strip() for d in data if d.get("title", "").strip()]
        return {"dubbings": dubbings, "episode_urls": [], "episode_numbers": []}

    episode_urls = [
        f"https://ashdi.vip/serial/{serial_id}?season={season}&episode={ep_num}"
        for ep_num in episode_numbers
    ]
    return {"dubbings": [], "episode_urls": episode_urls, "episode_numbers": episode_numbers}
```

- [ ] **Step 5: Commit**

```bash
git add bot/utils/scraper.py
git commit -m "feat: add uafix series scraper and ashdi serial m3u8 extraction"
```

---

## Task 4: Update public scraper API for site routing

**Files:**
- Modify: `bot/utils/scraper.py`

- [ ] **Step 1: Replace the public async API section (bottom of `scraper.py`)**

Replace the entire `# Public async API` section with:

```python
# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------

async def get_dubbing_options(url: str, season: int = None) -> list[str]:
    """Return dubbing names for the given URL.
    For uafix.net series, `season` is required to fetch the first episode."""
    result = await parse_season_page(url, dubbing="", season=season)
    return result["dubbings"]


async def parse_season_page(url: str, dubbing: str, season: int = None) -> dict:
    """
    Return {"dubbings": [str], "episode_urls": [str], "episode_numbers": [int]}.
    Pass dubbing="" to retrieve only the dubbings list.
    For uafix.net series, pass season=N to filter episodes.
    """
    loop = asyncio.get_running_loop()
    if _detect_site(url) == "uafix":
        if season is None:
            raise ValueError("season is required for uafix.net series")
        return await loop.run_in_executor(
            None, partial(_sync_parse_uafix_series_page, url, season, dubbing)
        )
    return await loop.run_in_executor(None, partial(_sync_parse_season_page, url, dubbing))


async def get_m3u8_url(episode_url: str, dubbing: Optional[str] = None) -> str:
    """Fetch the episode player page and extract the HLS m3u8 URL.
    For uafix.net ashdi serial URLs, dubbing is required to pick the right stream."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, partial(_sync_get_m3u8_url, episode_url, dubbing)
    )


async def parse_movie_page(url: str) -> dict:
    """
    Parse a movie/series page. Returns {title, title_en, year, imdb, poster_url, dubbings}.
    Routes to uafix or uakino implementation based on domain.
    """
    loop = asyncio.get_running_loop()
    if _detect_site(url) == "uafix":
        return await loop.run_in_executor(None, partial(_sync_parse_uafix_movie_page, url))
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
    For uafix.net, dubbing is ignored (single stream).
    """
    loop = asyncio.get_running_loop()
    if _detect_site(url) == "uafix":
        return await loop.run_in_executor(None, partial(_sync_get_uafix_movie_m3u8, url))
    return await loop.run_in_executor(
        None, partial(_sync_get_movie_m3u8, url, dubbing)
    )
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('bot/utils/scraper.py').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add bot/utils/scraper.py
git commit -m "feat: update public scraper API for uafix/uakino routing"
```

---

## Task 5: Update `download_loop.py` to pass dubbing

**Files:**
- Modify: `bot/utils/download_loop.py`

- [ ] **Step 1: Change the `get_m3u8_url` call to include `dubbing`**

Find line (approximately):
```python
m3u8_url = await get_m3u8_url(episode_url)
```

Replace with:
```python
m3u8_url = await get_m3u8_url(episode_url, dubbing=job.get("dubbing"))
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('bot/utils/download_loop.py').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add bot/utils/download_loop.py
git commit -m "feat: pass dubbing to get_m3u8_url in download loop (required for uafix series)"
```

---

## Task 6: Update `auto_movie.py` and `auto_anime_movie.py` — site picker

**Files:**
- Modify: `bot/handlers/auto_movie.py`
- Modify: `bot/handlers/auto_anime_movie.py`

Both files receive identical structural changes; only state group name and command name differ.

### Changes for `auto_movie.py`

- [ ] **Step 1: Replace `cmd_auto_movie` to show site picker**

```python
@router.message(Command("autoMovie"))
async def cmd_auto_movie(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ Тільки для адміністраторів.")
        return
    buttons = [
        [InlineKeyboardButton(text="🎬 uakino.best", callback_data="am_site:uakino")],
        [InlineKeyboardButton(text="🌐 uafix.net", callback_data="am_site:uafix")],
    ]
    await message.answer(
        "🎬 <b>Автозавантаження фільму</b>\n\nЗ якого сайту завантажити?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await state.set_state(AutoMovieStates.choosing_site)
```

- [ ] **Step 2: Add site picker callback handler (insert after `cmd_auto_movie`)**

```python
@router.callback_query(AutoMovieStates.choosing_site, F.data.startswith("am_site:"))
async def process_site_choice(callback: CallbackQuery, state: FSMContext):
    site = callback.data.split(":")[1]
    await state.update_data(site=site)
    site_name = "uakino.best" if site == "uakino" else "uafix.net"
    await callback.message.edit_text(
        f"🎬 <b>Автозавантаження фільму</b>\n\nНадішли URL фільму з {site_name}:"
    )
    await state.set_state(AutoMovieStates.waiting_for_url)
    await callback.answer()
```

- [ ] **Step 3: Update URL validation in `process_movie_url`**

Replace:
```python
    if "uakino.best" not in url:
        await message.answer("❌ URL має містити uakino.best. Спробуй ще раз:")
        return
```
With:
```python
    data = await state.get_data()
    site = data.get("site", "uakino")
    allowed = "uakino.best" if site == "uakino" else "uafix.net"
    if allowed not in url:
        await message.answer(f"❌ URL має містити {allowed}. Спробуй ще раз:")
        return
```

- [ ] **Step 4: Update the "Додати ще фільм" `am_add_new:movie` callback to show site picker too**

Find `process_add_new` (the `@router.callback_query(F.data.startswith("am_add_new:"))` handler). In the `kind == "movie"` branch, replace:
```python
        await callback.message.answer(
            "🎬 <b>Автозавантаження фільму</b>\n\nНадішли URL фільму з uakino.best:"
        )
        await state.set_state(AutoMovieStates.waiting_for_url)
```
With:
```python
        buttons = [
            [InlineKeyboardButton(text="🎬 uakino.best", callback_data="am_site:uakino")],
            [InlineKeyboardButton(text="🌐 uafix.net", callback_data="am_site:uafix")],
        ]
        await callback.message.answer(
            "🎬 <b>Автозавантаження фільму</b>\n\nЗ якого сайту завантажити?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
        await state.set_state(AutoMovieStates.choosing_site)
```

### Changes for `auto_anime_movie.py`

- [ ] **Step 5: Apply identical changes to `auto_anime_movie.py`** substituting:
  - `AutoAnimeMovieStates` instead of `AutoMovieStates`
  - `aam_site:` instead of `am_site:`
  - `🎌` instead of `🎬` in text labels
  - `aam_add_new:` callback in the "Додати ще" handler

- [ ] **Step 6: Verify syntax of both files**

```bash
python3 -c "
import ast
for f in ['bot/handlers/auto_movie.py', 'bot/handlers/auto_anime_movie.py']:
    ast.parse(open(f).read())
    print(f'OK: {f}')
"
```
Expected: two `OK` lines.

- [ ] **Step 7: Commit**

```bash
git add bot/handlers/auto_movie.py bot/handlers/auto_anime_movie.py
git commit -m "feat: add site picker to /autoMovie and /autoAnimeMovie"
```

---

## Task 7: Update `auto_download.py` and `auto_anime_download.py` — site picker + season

**Files:**
- Modify: `bot/handlers/auto_download.py`
- Modify: `bot/handlers/auto_anime_download.py`

### Changes for `auto_download.py`

- [ ] **Step 1: Replace `cmd_auto_download` to show site picker first**

```python
@router.message(Command("autoDownload"))
async def cmd_auto_download(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ Тільки для адміністраторів.")
        return
    buttons = [
        [InlineKeyboardButton(text="🎬 uakino.best", callback_data="ad_site:uakino")],
        [InlineKeyboardButton(text="🌐 uafix.net", callback_data="ad_site:uafix")],
    ]
    await message.answer(
        "🤖 <b>Автозавантаження серій</b>\n\nЗ якого сайту завантажити?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await state.set_state(AutoDownloadStates.choosing_site)
```

- [ ] **Step 2: Add site picker callback handler (insert after `cmd_auto_download`)**

```python
@router.callback_query(AutoDownloadStates.choosing_site, F.data.startswith("ad_site:"))
async def process_site_choice(callback: CallbackQuery, state: FSMContext):
    site = callback.data.split(":")[1]
    await state.update_data(site=site)
    buttons = [
        [InlineKeyboardButton(text="➕ Новий серіал", callback_data="ad_series_type:new")],
        [InlineKeyboardButton(text="📺 Існуючий серіал", callback_data="ad_series_type:existing")],
    ]
    site_name = "uakino.best" if site == "uakino" else "uafix.net"
    await callback.message.edit_text(
        f"🤖 <b>Автозавантаження серій</b> ({site_name})\n\n"
        f"Додати серії до нового чи існуючого серіалу?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await state.set_state(AutoDownloadStates.choosing_series_type)
    await callback.answer()
```

- [ ] **Step 3: Update URL validation in all URL-accepting handlers**

There are 3 URL-accepting message handlers in `auto_download.py`:
- `process_new_series_url` (state `waiting_for_new_series_url`)
- `process_existing_series_url` (state `waiting_for_existing_series_url`)
- `process_url` (state `waiting_for_url`)

In each, replace the uakino-only check with a site-aware check:

```python
    data = await state.get_data()
    site = data.get("site", "uakino")
    allowed = "uakino.best" if site == "uakino" else "uafix.net"
    if allowed not in url:
        await message.answer(f"❌ URL має містити {allowed}. Спробуй ще раз:")
        return
```

Also update the prompt strings in `process_series_type` that mention "uakino.best":

```python
    data = await state.get_data()
    site = data.get("site", "uakino")
    site_name = "uakino.best" if site == "uakino" else "uafix.net"
    if choice == "new":
        await callback.message.edit_text(
            f"➕ <b>Новий серіал</b>\n\nНадішли URL серіалу з {site_name}:"
        )
        ...
    else:
        await callback.message.edit_text(
            f"📺 <b>Існуючий серіал</b>\n\nНадішли URL сезону з {site_name} — "
            "я розпізнаю серіал автоматично:"
        )
```

And in `process_season` the "ask for URL" branch:
```python
        await message.answer(
            f"✅ Сезон: <b>{season}</b>\n\n"
            f"Надішліть URL сезону з {site_name}:"
        )
```
(compute `site_name` from `data.get("site", "uakino")` before the if-block)

- [ ] **Step 4: Pass `season` to `get_dubbing_options` and `parse_season_page`**

In `process_season`, where `get_dubbing_options` is called:
```python
    dubbings = await get_dubbing_options(data["season_url"], season=season)
```

In `_confirm_dubbing`, where `parse_season_page` is called:
```python
    result = await parse_season_page(url, dubbing, season=data.get("season"))
```

In `process_url`, where `get_dubbing_options` is called:
```python
    dubbings = await get_dubbing_options(url, season=data.get("season"))
```

- [ ] **Step 5: Update the `process_aad_add_new` / `process_ad_add_new` "add new series" callback to show site picker**

Find the `@router.callback_query(F.data == "ad_add_new:series")` handler (`process_ad_add_new`). Replace its body with:

```python
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔️ Тільки для адміністраторів.", show_alert=True)
        return
    await state.clear()
    buttons = [
        [InlineKeyboardButton(text="🎬 uakino.best", callback_data="ad_site:uakino")],
        [InlineKeyboardButton(text="🌐 uafix.net", callback_data="ad_site:uafix")],
    ]
    await callback.message.answer(
        "🤖 <b>Автозавантаження серій</b>\n\nЗ якого сайту завантажити?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await state.set_state(AutoDownloadStates.choosing_site)
    await callback.answer()
```

### Changes for `auto_anime_download.py`

- [ ] **Step 6: Apply identical changes** substituting:
  - `AutoAnimeDownloadStates` instead of `AutoDownloadStates`
  - `aad_site:` instead of `ad_site:`
  - `🎌` instead of `🤖` label prefix
  - `aad_add_new:series` callback reference

- [ ] **Step 7: Verify syntax**

```bash
python3 -c "
import ast
for f in ['bot/handlers/auto_download.py', 'bot/handlers/auto_anime_download.py']:
    ast.parse(open(f).read())
    print(f'OK: {f}')
"
```
Expected: two `OK` lines.

- [ ] **Step 8: Commit**

```bash
git add bot/handlers/auto_download.py bot/handlers/auto_anime_download.py
git commit -m "feat: add site picker and season pass to /autoDownload and /autoAnimeDownload"
```

---

## Task 8: Update admin panel descriptions

**Files:**
- Modify: `bot/handlers/common.py`

- [ ] **Step 1: Update the "Автозавантаження" block in `btn_admin`**

Find the block (around line 1673):
```python
        "🤖 <b>Автозавантаження:</b>\n"
        "/autoMovie - Завантажити фільм з uakino.best\n"
        "/autoDownload - Завантажити серіал з uakino.best\n"
        "/cancelDownload - Зупинити завантаження\n"
        "/autoAnimeMovie - Завантажити аніме-фільм з uakino.best\n"
        "/autoAnimeDownload - Завантажити аніме-серіал з uakino.best\n"
        "/cancelAnimeDownload - Зупинити аніме-завантаження\n\n"
```

Replace with:
```python
        "🤖 <b>Автозавантаження:</b>\n"
        "/autoMovie - Фільм (uakino.best / uafix.net)\n"
        "/autoDownload - Серіал (uakino.best / uafix.net)\n"
        "/cancelDownload - Зупинити завантаження\n"
        "/autoAnimeMovie - Аніме-фільм (uakino.best / uafix.net)\n"
        "/autoAnimeDownload - Аніме-серіал (uakino.best / uafix.net)\n"
        "/cancelAnimeDownload - Зупинити аніме-завантаження\n\n"
```

- [ ] **Step 2: Verify syntax and commit**

```bash
python3 -c "import ast; ast.parse(open('bot/handlers/common.py').read()); print('OK')"
git add bot/handlers/common.py
git commit -m "feat: update admin panel to mention both uakino.best and uafix.net"
```
