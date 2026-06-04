# Auto Anime Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `/autoAnimeMovie` and `/autoAnimeDownload` commands that mirror the existing `/autoMovie` and `/autoDownload` flows but save content as `anime_movie` / `anime_series` content types.

**Architecture:** Two new handler files (`auto_anime_movie.py`, `auto_anime_download.py`) with dedicated FSM state groups and unique `aam_` / `aad_` callback prefixes. All scraping, ffmpeg, and download-loop utilities are reused unchanged. `auto_download_jobs` gets a `content_type` field so `download_loop.py` can pick the right "done" buttons per job.

**Tech Stack:** Python 3.13, aiogram 3.x FSM, MongoDB (motor), ffmpeg, uakino.best scraper

---

## File Map

| Action | Path |
|--------|------|
| Modify | `bot/states.py` |
| Modify | `bot/database/movies.py` |
| Modify | `bot/database/auto_download_jobs.py` |
| Modify | `bot/utils/download_loop.py` |
| Create | `bot/handlers/auto_anime_movie.py` |
| Create | `bot/handlers/auto_anime_download.py` |
| Modify | `bot/handlers/__init__.py` |
| Modify | `main.py` |
| Modify | `bot/handlers/common.py` |

---

## Task 1: Add FSM State Groups

**Files:**
- Modify: `bot/states.py`

- [ ] **Step 1: Add two new state groups at the end of `bot/states.py`**

```python
class AutoAnimeMovieStates(StatesGroup):
    """Стани для автоматичного завантаження аніме-фільму"""
    waiting_for_url = State()
    confirming_metadata = State()
    waiting_for_title_manual = State()
    waiting_for_title_en_manual = State()
    waiting_for_year_manual = State()
    waiting_for_imdb_manual = State()
    choosing_dubbing = State()
    choosing_series_membership = State()
    choosing_existing_series = State()
    waiting_for_new_series_name = State()
    waiting_for_part_number = State()
    confirming_duplicate = State()
    confirming_download = State()


class AutoAnimeDownloadStates(StatesGroup):
    """Стани для автоматичного завантаження аніме-серіалу"""
    choosing_series_type = State()
    waiting_for_new_series_url = State()
    confirming_new_series_metadata = State()
    waiting_for_new_series_title = State()
    waiting_for_new_series_title_en = State()
    waiting_for_new_series_year = State()
    waiting_for_new_series_imdb = State()
    waiting_for_new_series_poster = State()
    waiting_for_existing_series_url = State()
    choosing_existing_series = State()
    waiting_for_season = State()
    waiting_for_url = State()
    choosing_dubbing = State()
    confirming = State()
```

- [ ] **Step 2: Commit**

```bash
git add bot/states.py
git commit -m "feat: add AutoAnimeMovieStates and AutoAnimeDownloadStates"
```

---

## Task 2: Add `part_number` to `create_anime_movie` and `content_type` to jobs

**Files:**
- Modify: `bot/database/movies.py` (around line 814)
- Modify: `bot/database/auto_download_jobs.py`

- [ ] **Step 1: Add `part_number` parameter to `create_anime_movie` in `bot/database/movies.py`**

Replace the function signature and body:

```python
async def create_anime_movie(
    title: str,
    title_en: str,
    year: int,
    imdb_rating: float,
    poster_file_id: str,
    video_file_id: str,
    video_type: str,
    added_by: int,
    file_size: int = 0,
    duration: int = 0,
    series_name: str = None,
    part_number: int = None,
) -> dict:
    """
    Створити новий аніме-фільм
    """
    movie_data = {
        "title": title,
        "title_en": title_en,
        "year": year,
        "imdb_rating": imdb_rating,
        "poster_file_id": poster_file_id,
        "content_type": "anime_movie",
        "video_file_id": video_file_id,
        "video_type": video_type,
        "file_size": file_size,
        "duration": duration,
        "added_by": added_by,
        "added_at": datetime.now(timezone.utc),
        "views_count": 0,
        "rating": 0,
        "ratings": [],
    }

    if series_name:
        movie_data["series_name"] = series_name
    if part_number:
        movie_data["part_number"] = part_number

    result = await db.videos.insert_one(movie_data)
    movie_data["_id"] = result.inserted_id
    return movie_data
```

- [ ] **Step 2: Add optional `content_type` field to `create_job` in `bot/database/auto_download_jobs.py`**

```python
async def create_job(
    series_id: str,
    series_title: str,
    season: int,
    dubbing: str,
    episode_urls: list[str],
    admin_id: int,
    content_type: str = "series",
) -> str:
    doc = {
        "series_id": series_id,
        "series_title": series_title,
        "season": season,
        "dubbing": dubbing,
        "episode_urls": episode_urls,
        "total_episodes": len(episode_urls),
        "current_episode": 0,
        "status": "running",
        "admin_id": admin_id,
        "content_type": content_type,
        "created_at": datetime.now(timezone.utc),
    }
    result = await db.auto_download_jobs.insert_one(doc)
    return str(result.inserted_id)
```

- [ ] **Step 3: Commit**

```bash
git add bot/database/movies.py bot/database/auto_download_jobs.py
git commit -m "feat: add part_number to create_anime_movie, add content_type to jobs"
```

---

## Task 3: Update `download_loop.py` to use `content_type` for done buttons

**Files:**
- Modify: `bot/utils/download_loop.py`

The loop reads `content_type` from the job document and chooses the right callback prefixes for the "done" message buttons. Existing regular-series jobs without `content_type` default to `"series"`.

- [ ] **Step 1: Replace the final done-message block in `_run_loop` (after `set_job_status`)**

Find this section at the end of `_run_loop`:

```python
    await set_job_status(job_id, "done")

    bot_info = await bot.get_me()
    view_url = f"https://t.me/{bot_info.username}?start=s_{series_id}"

    done_markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Зробити розсилку", callback_data=f"post_quick:series:{series_id}")],
        [InlineKeyboardButton(text="📺 Переглянути серіал", url=view_url)],
        [InlineKeyboardButton(text="➕ Додати ще серіал", callback_data="ad_add_new:series"),
         InlineKeyboardButton(text="🎬 Додати фільм", callback_data="am_add_new:movie")],
    ])

    await bot.send_message(
        admin_id,
        f"🎉 <b>Готово!</b> Всі {total} серій сезону {season} "
        f"серіалу «{series_title}» успішно завантажено!",
        reply_markup=done_markup,
    )
```

Replace with:

```python
    await set_job_status(job_id, "done")

    bot_info = await bot.get_me()
    is_anime = job.get("content_type") == "anime_series"
    view_prefix = "as_" if is_anime else "s_"
    post_type = "anime_series" if is_anime else "series"
    add_series_cb = "aad_add_new:series" if is_anime else "ad_add_new:series"
    add_movie_cb = "aam_add_new:movie" if is_anime else "am_add_new:movie"
    add_movie_label = "🎬 Додати аніме-фільм" if is_anime else "🎬 Додати фільм"
    add_series_label = "➕ Ще аніме-серіал" if is_anime else "➕ Додати ще серіал"

    view_url = f"https://t.me/{bot_info.username}?start={view_prefix}{series_id}"

    done_markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Зробити розсилку", callback_data=f"post_quick:{post_type}:{series_id}")],
        [InlineKeyboardButton(text="📺 Переглянути серіал", url=view_url)],
        [InlineKeyboardButton(text=add_series_label, callback_data=add_series_cb),
         InlineKeyboardButton(text=add_movie_label, callback_data=add_movie_cb)],
    ])

    await bot.send_message(
        admin_id,
        f"🎉 <b>Готово!</b> Всі {total} серій сезону {season} "
        f"серіалу «{series_title}» успішно завантажено!",
        reply_markup=done_markup,
    )
```

- [ ] **Step 2: Commit**

```bash
git add bot/utils/download_loop.py
git commit -m "feat: use content_type from job for done-message buttons in download_loop"
```

---

## Task 4: Create `auto_anime_movie.py`

**Files:**
- Create: `bot/handlers/auto_anime_movie.py`

This is a full handler file. Differences from `auto_movie.py`:
- State group: `AutoAnimeMovieStates`
- DB call: `create_anime_movie` (no `part_number` removed — it IS included)
- Series names: `get_all_anime_movie_series_names`
- Duplicate check: `find_movie_by_titles(..., content_type="anime_movie")`
- All callback prefixes: `aam_*` instead of `am_*`
- Deep link: `am_{movie_id}` (this prefix already maps to anime movie in `common.py`)
- Done buttons: `aam_add_new:movie` and `aad_add_new:series`
- Command: `/autoAnimeMovie`

- [ ] **Step 1: Create `bot/handlers/auto_anime_movie.py`**

The file is a copy of `bot/handlers/auto_movie.py` with these substitutions applied:

| Find | Replace |
|------|---------|
| `AutoMovieStates` | `AutoAnimeMovieStates` |
| `create_movie` | `create_anime_movie` |
| `get_all_movie_series_names` | `get_all_anime_movie_series_names` |
| `find_movie_by_titles(` | `find_movie_by_titles(` *(keep, add `content_type="anime_movie"` arg — see below)* |
| `content_type="movie"` *(implicit default)* | `content_type="anime_movie"` |
| `am_meta:` | `aam_meta:` |
| `am_dub:` | `aam_dub:` |
| `am_series:` | `aam_series:` |
| `am_pickser:` | `aam_pickser:` |
| `am_serpage:` | `aam_serpage:` |
| `am_confirm:` | `aam_confirm:` |
| `am_dup:` | `aam_dup:` |
| `am_add_new:` | `aam_add_new:` |
| `Command("autoMovie")` | `Command("autoAnimeMovie")` |
| `🎬 <b>Автозавантаження фільму</b>` | `🎌 <b>Автозавантаження аніме-фільму</b>` |
| `Фільм належить до серії фільмів?` | `Аніме-фільм належить до серії?` |
| `🎬 Ні, самостійний фільм` | `🎌 Ні, самостійний фільм` |
| `📁 <b>Виберіть серію фільмів:</b>` | `📁 <b>Виберіть серію аніме-фільмів:</b>` |
| `Фільм вже є в базі!` | `Аніме-фільм вже є в базі!` |
| `view_url = f"https://t.me/{bot_info.username}?start=m_{movie_id}"` | `view_url = f"https://t.me/{bot_info.username}?start=am_{movie_id}"` |
| `post_quick:movie:{movie_id}` | `post_quick:anime_movie:{movie_id}` |
| `"➕ Додати ще фільм", callback_data="am_add_new:movie"` | `"➕ Ще аніме-фільм", callback_data="aam_add_new:movie"` |
| `"📺 Додати серіал", callback_data="am_add_new:series"` | `"📺 Додати аніме-серіал", callback_data="aad_add_new:series"` |
| `_download_and_create_movie` | `_download_and_create_anime_movie` |
| `caption=f"movie:{title}"` | `caption=f"anime_movie:{title}"` |

Additionally, change the `_download_and_create_anime_movie` call to use `create_anime_movie` and the `find_movie_by_titles` call to pass `content_type="anime_movie"`:

```python
# In _show_dubbing_picker:
existing = await find_movie_by_titles(
    data.get("title"), data.get("title_en"), content_type="anime_movie"
)

# In _download_and_create_anime_movie, step 5:
movie = await create_anime_movie(
    title=title,
    title_en=title_en,
    year=year,
    imdb_rating=imdb,
    poster_file_id=poster_file_id or "",
    video_file_id=video_file_id,
    video_type="video",
    added_by=admin_id,
    file_size=file_size,
    duration=duration,
    series_name=series_name,
    part_number=part_number,
)
```

- [ ] **Step 2: Commit**

```bash
git add bot/handlers/auto_anime_movie.py
git commit -m "feat: add auto_anime_movie handler (/autoAnimeMovie)"
```

---

## Task 5: Create `auto_anime_download.py`

**Files:**
- Create: `bot/handlers/auto_anime_download.py`

This file is identical to `bot/handlers/auto_download.py` with the following substitutions:

| Find | Replace |
|------|---------|
| `AutoDownloadStates` | `AutoAnimeDownloadStates` |
| `create_series` | `create_anime_series` |
| `get_all_series_list` | `get_all_anime_series_list` |
| `find_movie_by_titles(title, title_en, content_type="series")` | `find_movie_by_titles(title, title_en, content_type="anime_series")` |
| `ad_series_type:` | `aad_series_type:` |
| `ads_meta:` | `aads_meta:` |
| `ads_poster:` | `aads_poster:` |
| `ads_existing:` | `aads_existing:` |
| `ad_series_page:` | `aad_series_page:` |
| `ad_pick_series:` | `aad_pick_series:` |
| `ad_dubbing:` | `aad_dubbing:` |
| `ad_confirm:` | `aad_confirm:` |
| `ad_add_new:` | `aad_add_new:` |
| `ad_resume:` | `aad_resume:` |
| `ad_resume_cancel:` | `aad_resume_cancel:` |
| `Command("autoDownload")` | `Command("autoAnimeDownload")` |
| `Command("cancelDownload")` | `Command("cancelAnimeDownload")` |
| `🤖 <b>Автозавантаження серій</b>` | `🎌 <b>Автозавантаження аніме-серіалу</b>` |
| `➕ Новий серіал` | `➕ Новий аніме-серіал` |
| `📺 Існуючий серіал` | `📺 Існуючий аніме-серіал` |
| `➕ <b>Новий серіал</b>` | `➕ <b>Новий аніме-серіал</b>` |
| `📺 <b>Існуючий серіал</b>` | `📺 <b>Існуючий аніме-серіал</b>` |
| `"am_add_new:movie"` *(in process_ad_add_new)* | `"aam_add_new:movie"` |

Also change `create_job` call to pass `content_type="anime_series"`:

```python
job_id = await create_job(
    series_id=data["series_id"],
    series_title=data["series_title"],
    season=data["season"],
    dubbing=data["dubbing"],
    episode_urls=data["episode_urls"],
    admin_id=callback.from_user.id,
    content_type="anime_series",
)
```

And update the `process_ad_add_new` handler (now `process_aad_add_new`) to start `AutoAnimeDownloadStates`:

```python
@router.callback_query(F.data == "aad_add_new:series")
async def process_aad_add_new(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔️ Тільки для адміністраторів.", show_alert=True)
        return
    await state.clear()
    buttons = [
        [InlineKeyboardButton(text="➕ Новий аніме-серіал", callback_data="aad_series_type:new")],
        [InlineKeyboardButton(text="📺 Існуючий аніме-серіал", callback_data="aad_series_type:existing")],
    ]
    await callback.message.answer(
        "🎌 <b>Автозавантаження аніме-серіалу</b>\n\n"
        "Додати серії до нового чи існуючого серіалу?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await state.set_state(AutoAnimeDownloadStates.choosing_series_type)
    await callback.answer()
```

- [ ] **Step 1: Create `bot/handlers/auto_anime_download.py`** applying all substitutions above.

- [ ] **Step 2: Commit**

```bash
git add bot/handlers/auto_anime_download.py
git commit -m "feat: add auto_anime_download handler (/autoAnimeDownload)"
```

---

## Task 6: Wire Up — Register Routers, Commands, Admin Panel

**Files:**
- Modify: `bot/handlers/__init__.py`
- Modify: `main.py`
- Modify: `bot/handlers/common.py`

- [ ] **Step 1: Update `bot/handlers/__init__.py`**

```python
from bot.handlers.common import router as common_router
from bot.handlers.admin import router as admin_router
from bot.handlers.catalog import router as catalog_router
from bot.handlers.broadcast import router as broadcast_router
from bot.handlers.auto_download import router as auto_download_router
from bot.handlers.auto_movie import router as auto_movie_router
from bot.handlers.auto_anime_movie import router as auto_anime_movie_router
from bot.handlers.auto_anime_download import router as auto_anime_download_router

__all__ = [
    "common_router", "admin_router", "catalog_router",
    "broadcast_router", "auto_download_router", "auto_movie_router",
    "auto_anime_movie_router", "auto_anime_download_router",
]
```

- [ ] **Step 2: Register routers in `main.py`**

Change the import line:
```python
from bot.handlers import (
    common_router, admin_router, catalog_router,
    broadcast_router, auto_download_router, auto_movie_router,
    auto_anime_movie_router, auto_anime_download_router,
)
```

Add two router includes after the existing ones:
```python
    dp.include_router(auto_download_router)
    dp.include_router(auto_movie_router)
    dp.include_router(auto_anime_movie_router)
    dp.include_router(auto_anime_download_router)
```

- [ ] **Step 3: Add anime commands to admin command menu in `main.py`**

```python
    admin_commands = commands + [
        BotCommand(command="autoMovie", description="Завантажити фільм з uakino.best"),
        BotCommand(command="autoDownload", description="Автозавантаження серій з uakino.best"),
        BotCommand(command="cancelDownload", description="Зупинити активне завантаження"),
        BotCommand(command="autoAnimeMovie", description="Завантажити аніме-фільм з uakino.best"),
        BotCommand(command="autoAnimeDownload", description="Автозавантаження аніме-серіалу з uakino.best"),
        BotCommand(command="cancelAnimeDownload", description="Зупинити аніме-завантаження"),
    ]
```

- [ ] **Step 4: Update admin panel text in `bot/handlers/common.py`**

Replace the `<b>Аніме:</b>` block:

```python
        "<b>Аніме:</b>\n"
        "/addAnimeMovie - Додати аніме-фільм\n"
        "/addAnimeBatch - Додати аніме-серіал\n"
        "/autoAnimeMovie - Авто: аніме-фільм з uakino.best\n"
        "/autoAnimeDownload - Авто: аніме-серіал з uakino.best\n"
        "/cancelAnimeDownload - Зупинити аніме-завантаження\n\n"
```

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/__init__.py main.py bot/handlers/common.py
git commit -m "feat: wire up anime auto-download routers and admin commands"
```
