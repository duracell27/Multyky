# uafix.net Support Design

**Date:** 2026-06-04

## Goal

Add uafix.net as an alternative content source alongside uakino.best. All 4 auto-download commands (`/autoMovie`, `/autoDownload`, `/autoAnimeMovie`, `/autoAnimeDownload`) ask the user which site to use before asking for a URL. The scraper routes internally based on domain — handlers stay unchanged except for the new site-picker step and relaxed URL validation.

---

## Site Comparison

| Aspect | uakino.best | uafix.net |
|--------|-------------|-----------|
| Video host — movies | ashdi.vip/vod/<id> | zetvideo.net/vod/<id> |
| Video host — series | ashdi.vip/vod/<id> | ashdi.vip/serial/<id>?season=N&episode=M |
| Dubbing — movies | Multiple (AJAX playlist) | Single stream (no choice) |
| Dubbing — series | Via AJAX playlist | Via Playerjs JSON on ashdi serial page |
| Episode list — series | AJAX playlist endpoint | Direct `<a>` links in HTML on series page |
| Metadata (title/year/imdb/poster) | DLE HTML | DLE HTML (same engine, same selectors) |

---

## Architecture

### scraper.py

New private helpers added alongside existing uakino helpers:

**Site detection:**
```python
def _detect_site(url: str) -> str:
    # Returns "uakino" or "uafix"
    if "uafix.net" in url:
        return "uafix"
    return "uakino"
```

**uafix movie scraping:**
- `_sync_parse_uafix_movie_page(url)` — fetches page, finds `<iframe src="https://zetvideo.net/vod/<id>">`, returns same metadata dict as `_sync_parse_movie_page` with `dubbings=["UA"]` (single stream, no choice)
- `_sync_get_uafix_movie_m3u8(url)` — fetches page → iframe → zetvideo page → Playerjs `file:` → m3u8; ignores `dubbing` param

**uafix series scraping:**
- `_sync_parse_uafix_series_page(url, season, dubbing)`:
  - Fetches series page (e.g. `uafix.net/serials/rik-ta-morti/`)
  - Extracts all episode links matching `/serials/{slug}/season-{NN:02d}-episode-{MM:02d}/`
  - Filters by requested `season`
  - Fetches the first episode page → finds `ashdi.vip/serial/<id>?season=N&episode=M` iframe
  - If `dubbing == ""`: fetches that ashdi page → parses Playerjs JSON top-level titles → returns dubbing names
  - If `dubbing != ""`: for each episode URL, computes ashdi URL using same `<id>` with correct season/episode params; returns `episode_urls` (ashdi serial URLs) and `episode_numbers`
- `_sync_get_uafix_series_episode_m3u8(ashdi_serial_url, dubbing)`:
  - Fetches ashdi serial page → parses Playerjs JSON → finds dubbing by title → extracts season/episode from URL params → returns m3u8 file URL

**Updated public async functions** (route by site):

```python
async def parse_movie_page(url: str) -> dict:
    # routes to _sync_parse_movie_page or _sync_parse_uafix_movie_page

async def get_movie_m3u8(url: str, dubbing: str) -> str:
    # routes to _sync_get_movie_m3u8 or _sync_get_uafix_movie_m3u8

async def parse_season_page(url: str, dubbing: str, season: int = None) -> dict:
    # uakino: current behavior (season ignored)
    # uafix: _sync_parse_uafix_series_page(url, season, dubbing)

async def get_m3u8_url(episode_url: str, dubbing: str = None) -> str:
    # ashdi.vip/vod/<id>: current behavior (dubbing ignored)
    # ashdi.vip/serial/<id>?...: parse JSON, use dubbing to find stream

async def get_dubbing_options(url: str, season: int = None) -> list[str]:
    # uakino: current behavior
    # uafix: calls parse_season_page(url, "", season) to get dubbing names
```

### download_loop.py

One change: pass `dubbing` to `get_m3u8_url`:
```python
m3u8_url = await get_m3u8_url(episode_url, dubbing=job.get("dubbing"))
```
Needed for uafix series (ashdi serial JSON requires dubbing to select the right stream).

### States — 4 new `choosing_site` states

Add to each existing state group:
- `AutoMovieStates.choosing_site`
- `AutoDownloadStates.choosing_site`
- `AutoAnimeMovieStates.choosing_site`
- `AutoAnimeDownloadStates.choosing_site`

### Handlers — 4 files modified

Each command handler gains a site-picker step:

```
/autoMovie
  → "З якого сайту завантажити?"
     [🎬 uakino.best]  [🌐 uafix.net]
  → state: choosing_site

am_site:{uakino|uafix} callback
  → update_data(site="uakino"|"uafix")
  → "Надішли URL фільму з {site}:"
  → state: waiting_for_url
```

URL validation changes from:
```python
if "uakino.best" not in url:  # ❌
```
to:
```python
if "uakino.best" not in url and "uafix.net" not in url:  # ✅
```

For series handlers: pass `season` to `parse_season_page` and `get_dubbing_options`:
```python
result = await parse_season_page(url, dubbing, season=data.get("season"))
```

### admin_panel (common.py)

Update descriptions to mention both sites:
```
/autoMovie - Завантажити фільм (uakino.best / uafix.net)
/autoDownload - Завантажити серіал (uakino.best / uafix.net)
```

---

## Data Flow — uafix.net Movie

```
/autoMovie → pick site=uafix → send URL
→ parse_movie_page(url)         # _sync_parse_uafix_movie_page
  → fetch page → zetvideo iframe
  → dubbings=["UA"]
→ confirm metadata
→ _show_dubbing_picker → "UA" auto-selected (single dubbing)
→ confirm → download
→ get_movie_m3u8(url, "UA")     # _sync_get_uafix_movie_m3u8
  → fetch page → zetvideo → Playerjs file → m3u8
→ run_ffmpeg → upload → DB
```

## Data Flow — uafix.net Series

```
/autoDownload → pick site=uafix → send URL (series page)
→ new series flow: parse_movie_page(url) for metadata
→ ask season number
→ get_dubbing_options(url, season=N)   # parse_season_page(url, "", N)
  → fetch series page → get episode URLs for season N
  → fetch first episode page → ashdi serial URL
  → fetch ashdi serial → parse JSON → return dubbing names
→ user picks dubbing
→ parse_season_page(url, dubbing, season=N)
  → episode_urls = [ashdi serial URLs with season=N&episode=M for each M]
  → episode_numbers = [actual episode numbers from URL slugs]
→ confirm + download
→ in download_loop: get_m3u8_url(ashdi_serial_url, dubbing=dubbing)
  → fetch ashdi → parse JSON → find dubbing → return m3u8
```

---

## Error Handling

- If uafix series page has no episode links for the requested season → error message to admin
- If zetvideo page has no Playerjs `file:` → error message
- If ashdi serial JSON does not contain requested dubbing → list available dubbings in error

---

## Out of Scope

- uafix.net anime categories (same code paths as regular cartoons, no separate handling needed)
- Quality selection for zetvideo (single stream, no master playlist variants)
- Caching ashdi serial pages across episodes (one request per episode is acceptable)
