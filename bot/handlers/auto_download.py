import logging
import os
import uuid

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
)
from aiogram.fsm.context import FSMContext

from bot.config import config
from bot.states import AutoDownloadStates
from bot.database.movies import (
    get_all_series_list, get_movie_by_id,
    create_series, find_movie_by_titles
)
from bot.database.auto_download_jobs import (
    create_job, set_job_status, get_job
)
from bot.utils.scraper import get_dubbing_options, parse_season_page, parse_movie_page, download_poster
from bot.utils.download_loop import start_job, cancel_job
from bot.handlers.admin import get_forwarded_chat_id

router = Router()
logger = logging.getLogger(__name__)

ITEMS_PER_PAGE = 20


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


# ── Кнопки після завершення ───────────────────────────────────────────────────

@router.callback_query(F.data == "ad_add_new:series")
async def process_ad_add_new(callback: CallbackQuery, state: FSMContext):
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


# ── /autoDownload ────────────────────────────────────────────────────────────

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


@router.callback_query(AutoDownloadStates.choosing_site, F.data.startswith("ad_site:"))
async def process_series_site_choice(callback: CallbackQuery, state: FSMContext):
    site = callback.data.split(":")[1]
    await state.update_data(site=site)
    site_name = "uakino.best" if site == "uakino" else "uafix.net"
    buttons = [
        [InlineKeyboardButton(text="➕ Новий серіал", callback_data="ad_series_type:new")],
        [InlineKeyboardButton(text="📺 Існуючий серіал", callback_data="ad_series_type:existing")],
    ]
    await callback.message.edit_text(
        f"🤖 <b>Автозавантаження серій</b> ({site_name})\n\n"
        f"Додати серії до нового чи існуючого серіалу?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await state.set_state(AutoDownloadStates.choosing_series_type)
    await callback.answer()


# ── Вибір типу серіалу ───────────────────────────────────────────────────────

@router.callback_query(AutoDownloadStates.choosing_series_type, F.data.startswith("ad_series_type:"))
async def process_series_type(callback: CallbackQuery, state: FSMContext):
    choice = callback.data.split(":", 1)[1]
    data = await state.get_data()
    site = data.get("site", "uakino")
    site_name = "uakino.best" if site == "uakino" else "uafix.net"
    if choice == "new":
        await callback.message.edit_text(
            f"➕ <b>Новий серіал</b>\n\nНадішли URL серіалу з {site_name}:"
        )
        await state.set_state(AutoDownloadStates.waiting_for_new_series_url)
    else:
        await callback.message.edit_text(
            f"📺 <b>Існуючий серіал</b>\n\nНадішли URL сезону з {site_name} — "
            "я розпізнаю серіал автоматично:"
        )
        await state.set_state(AutoDownloadStates.waiting_for_existing_series_url)
    await callback.answer()


# ── Новий серіал: URL → парсинг ──────────────────────────────────────────────

@router.message(AutoDownloadStates.waiting_for_new_series_url, ~F.text.startswith("/"))
async def process_new_series_url(message: Message, state: FSMContext):
    url = message.text.strip()
    data = await state.get_data()
    site = data.get("site", "uakino")
    allowed = "uakino.best" if site == "uakino" else "uafix.net"
    if allowed not in url:
        await message.answer(f"❌ URL має містити {allowed}. Спробуй ще раз:")
        return

    await state.update_data(series_page_url=url)
    wait_msg = await message.answer("⏳ Парсю сторінку...")

    try:
        data = await parse_movie_page(url)
    except Exception as e:
        await wait_msg.edit_text(f"❌ Помилка парсингу: {e}\n\nСпробуй ще раз:")
        return

    await state.update_data(
        parsed_title=data["title"],
        parsed_title_en=data["title_en"],
        parsed_year=data["year"],
        parsed_imdb=data["imdb"],
        poster_url=data["poster_url"],
    )

    lines = ["📋 <b>Знайдено:</b>\n"]
    lines.append(f"🎬 Назва: <b>{data['title'] or '—'}</b>")
    lines.append(f"🌍 EN: <b>{data['title_en'] or '—'}</b>")
    lines.append(f"📅 Рік: <b>{data['year'] or '—'}</b>")
    lines.append(f"⭐️ IMDB: <b>{data['imdb'] or '—'}</b>")
    lines.append(f"🖼 Постер: {'✅' if data['poster_url'] else '❌ не знайдено'}")

    buttons = [
        [InlineKeyboardButton(text="✅ Підтвердити", callback_data="ads_meta:confirm")],
        [InlineKeyboardButton(text="✏️ Заповнити вручну", callback_data="ads_meta:manual")],
    ]
    await wait_msg.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await state.set_state(AutoDownloadStates.confirming_new_series_metadata)


# ── Новий серіал: підтвердження metadata ─────────────────────────────────────

@router.callback_query(AutoDownloadStates.confirming_new_series_metadata, F.data.startswith("ads_meta:"))
async def process_new_series_meta_confirm(callback: CallbackQuery, state: FSMContext):
    choice = callback.data.split(":")[1]
    data = await state.get_data()

    if choice == "confirm":
        missing = [f for f in ("parsed_title", "parsed_title_en", "parsed_year", "parsed_imdb")
                   if not data.get(f)]
        await state.update_data(
            new_title=data.get("parsed_title"),
            new_title_en=data.get("parsed_title_en"),
            new_year=data.get("parsed_year"),
            new_imdb=data.get("parsed_imdb"),
            missing_fields=missing,
        )
        if missing:
            await _ask_next_missing_series_field(callback.message, state, missing, edit=True)
        else:
            await _proceed_after_meta(callback.message, state, edit=True)
    else:
        await state.update_data(
            new_title=None, new_title_en=None, new_year=None, new_imdb=None,
            missing_fields=["parsed_title", "parsed_title_en", "parsed_year", "parsed_imdb"],
        )
        await callback.message.edit_text("Введіть українську назву серіалу:")
        await state.set_state(AutoDownloadStates.waiting_for_new_series_title)
    await callback.answer()


async def _ask_next_missing_series_field(message, state: FSMContext, missing: list, edit: bool = False):
    field = missing[0]
    prompts = {
        "parsed_title": "Введіть українську назву серіалу:",
        "parsed_title_en": "Введіть англійську назву серіалу:",
        "parsed_year": "Введіть рік випуску (наприклад: <code>2010</code>):",
        "parsed_imdb": "Введіть IMDB рейтинг (наприклад: <code>7.5</code>):",
    }
    state_map = {
        "parsed_title": AutoDownloadStates.waiting_for_new_series_title,
        "parsed_title_en": AutoDownloadStates.waiting_for_new_series_title_en,
        "parsed_year": AutoDownloadStates.waiting_for_new_series_year,
        "parsed_imdb": AutoDownloadStates.waiting_for_new_series_imdb,
    }
    if edit:
        await message.edit_text(prompts[field])
    else:
        await message.answer(prompts[field])
    await state.set_state(state_map[field])


async def _handle_new_series_manual_field(message: Message, state: FSMContext, field: str, value):
    await state.update_data(**{field: value,
                                "new_title" if field == "parsed_title" else
                                "new_title_en" if field == "parsed_title_en" else
                                "new_year" if field == "parsed_year" else
                                "new_imdb": value})
    data = await state.get_data()
    missing = [f for f in data.get("missing_fields", []) if f != field]
    await state.update_data(missing_fields=missing)
    if missing:
        await _ask_next_missing_series_field(message, state, missing)
    else:
        await _proceed_after_meta(message, state)


# ── Новий серіал: ручні поля ─────────────────────────────────────────────────

@router.message(AutoDownloadStates.waiting_for_new_series_title, ~F.text.startswith("/"))
async def process_new_title(message: Message, state: FSMContext):
    await state.update_data(new_title=message.text.strip())
    data = await state.get_data()
    missing = [f for f in data.get("missing_fields", []) if f != "parsed_title"]
    await state.update_data(missing_fields=missing)
    if missing:
        await _ask_next_missing_series_field(message, state, missing)
    else:
        await _proceed_after_meta(message, state)


@router.message(AutoDownloadStates.waiting_for_new_series_title_en, ~F.text.startswith("/"))
async def process_new_title_en(message: Message, state: FSMContext):
    await state.update_data(new_title_en=message.text.strip())
    data = await state.get_data()
    missing = [f for f in data.get("missing_fields", []) if f != "parsed_title_en"]
    await state.update_data(missing_fields=missing)
    if missing:
        await _ask_next_missing_series_field(message, state, missing)
    else:
        await _proceed_after_meta(message, state)


@router.message(AutoDownloadStates.waiting_for_new_series_year, ~F.text.startswith("/"))
async def process_new_year(message: Message, state: FSMContext):
    try:
        year = int(message.text.strip())
        if not (1900 <= year <= 2100):
            raise ValueError
    except ValueError:
        await message.answer("❌ Введіть коректний рік (1900-2100):")
        return
    await state.update_data(new_year=year)
    data = await state.get_data()
    missing = [f for f in data.get("missing_fields", []) if f != "parsed_year"]
    await state.update_data(missing_fields=missing)
    if missing:
        await _ask_next_missing_series_field(message, state, missing)
    else:
        await _proceed_after_meta(message, state)


@router.message(AutoDownloadStates.waiting_for_new_series_imdb, ~F.text.startswith("/"))
async def process_new_imdb(message: Message, state: FSMContext):
    try:
        imdb = float(message.text.strip().replace(",", "."))
        if not (0 <= imdb <= 10):
            raise ValueError
    except ValueError:
        await message.answer("❌ Введіть рейтинг від 0 до 10:")
        return
    await state.update_data(new_imdb=imdb)
    data = await state.get_data()
    missing = [f for f in data.get("missing_fields", []) if f != "parsed_imdb"]
    await state.update_data(missing_fields=missing)
    if missing:
        await _ask_next_missing_series_field(message, state, missing)
    else:
        await _proceed_after_meta(message, state)


async def _proceed_after_meta(message, state: FSMContext, edit: bool = False):
    """After all metadata is collected — handle poster then ask season."""
    data = await state.get_data()
    if data.get("poster_url"):
        text = (
            f"🖼 Знайдено постер на сторінці. Завантажити його автоматично\n"
            f"чи перешлеш свій з каналу зберігання?"
        )
        buttons = [
            [InlineKeyboardButton(text="⬇️ Завантажити автоматично", callback_data="ads_poster:auto")],
            [InlineKeyboardButton(text="📤 Перешлю свій", callback_data="ads_poster:manual")],
        ]
        if edit:
            await message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        else:
            await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await state.set_state(AutoDownloadStates.waiting_for_new_series_poster)
    else:
        text = "🖼 Постер не знайдено. Перешли постер (фото) з каналу зберігання:"
        if edit:
            await message.edit_text(text)
        else:
            await message.answer(text)
        await state.set_state(AutoDownloadStates.waiting_for_new_series_poster)


# ── Новий серіал: постер ─────────────────────────────────────────────────────

@router.callback_query(AutoDownloadStates.waiting_for_new_series_poster, F.data.startswith("ads_poster:"))
async def process_poster_choice(callback: CallbackQuery, state: FSMContext, bot: Bot):
    choice = callback.data.split(":")[1]
    if choice == "manual":
        await callback.message.edit_text("📤 Перешли постер (фото) з каналу зберігання:")
        await callback.answer()
        return

    # auto download poster
    data = await state.get_data()
    poster_url = data["poster_url"]
    uid = str(uuid.uuid4())[:8]
    poster_path = f"/tmp/{uid}_series_poster.jpg"

    await callback.message.edit_text("⏳ Завантажую постер...")
    ok = await download_poster(poster_url, poster_path)
    if not ok:
        await callback.message.edit_text(
            "❌ Не вдалося завантажити постер. Перешли вручну з каналу зберігання:"
        )
        await callback.answer()
        return

    try:
        sent = await bot.send_photo(
            config.STORAGE_CHANNEL_ID,
            photo=FSInputFile(poster_path),
            caption=f"poster:{data.get('new_title', '')}",
        )
        poster_file_id = sent.photo[-1].file_id
    finally:
        if os.path.exists(poster_path):
            os.remove(poster_path)

    await _create_series_and_ask_season(callback.message, state, poster_file_id, callback.from_user.id)
    await callback.answer()


@router.message(AutoDownloadStates.waiting_for_new_series_poster, F.photo)
async def process_new_poster(message: Message, state: FSMContext):
    if get_forwarded_chat_id(message) != config.STORAGE_CHANNEL_ID:
        await message.answer("❌ Постер має бути пересланий з каналу зберігання!")
        return
    poster_file_id = message.photo[-1].file_id
    await _create_series_and_ask_season(message, state, poster_file_id, message.from_user.id)


@router.message(AutoDownloadStates.waiting_for_new_series_poster, ~F.text.startswith("/"))
async def process_new_poster_invalid(message: Message, state: FSMContext):
    await message.answer("❌ Надішліть фото постера з каналу зберігання.")


async def _create_series_and_ask_season(message, state: FSMContext, poster_file_id: str, user_id: int):
    data = await state.get_data()
    series = await create_series(
        title=data["new_title"],
        title_en=data["new_title_en"],
        year=data["new_year"],
        imdb_rating=data["new_imdb"],
        poster_file_id=poster_file_id,
        added_by=user_id,
    )
    series_id = str(series["_id"])
    await state.update_data(
        series_id=series_id,
        series_title=data["new_title"],
        season_url=data.get("series_page_url"),  # reuse parsed URL as default season URL
    )
    await message.answer(
        f"✅ <b>Серіал створено!</b>\n"
        f"📺 {data['new_title']}\n"
        f"🆔 <code>{series_id}</code>\n\n"
        f"Введіть номер сезону:"
    )
    await state.set_state(AutoDownloadStates.waiting_for_season)


# ── Існуючий серіал: URL → пошук ─────────────────────────────────────────────

@router.message(AutoDownloadStates.waiting_for_existing_series_url, ~F.text.startswith("/"))
async def process_existing_series_url(message: Message, state: FSMContext):
    url = message.text.strip()
    data = await state.get_data()
    site = data.get("site", "uakino")
    allowed = "uakino.best" if site == "uakino" else "uafix.net"
    if allowed not in url:
        await message.answer(f"❌ URL має містити {allowed}. Спробуй ще раз:")
        return

    await state.update_data(season_url=url)
    wait_msg = await message.answer("⏳ Розпізнаю серіал...")

    try:
        page_data = await parse_movie_page(url)
    except Exception as e:
        await wait_msg.edit_text(f"❌ Помилка парсингу: {e}")
        return

    title = page_data.get("title")
    title_en = page_data.get("title_en")

    if title or title_en:
        existing = await find_movie_by_titles(title, title_en, content_type="series")
        if existing:
            series_id = str(existing["_id"])
            await state.update_data(series_id=series_id, series_title=existing["title"])
            buttons = [
                [InlineKeyboardButton(text="✅ Так, це він", callback_data=f"ads_existing:confirm:{series_id}")],
                [InlineKeyboardButton(text="📋 Показати список", callback_data="ads_existing:list")],
            ]
            await wait_msg.edit_text(
                f"🔍 Знайдено в базі:\n\n"
                f"📺 <b>{existing['title']}</b>"
                + (f" / {existing.get('title_en')}" if existing.get("title_en") else "")
                + f"\n📅 {existing.get('year')} · ⭐️ {existing.get('imdb_rating')}\n\n"
                f"Це той серіал?",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
            )
            await state.set_state(AutoDownloadStates.choosing_existing_series)
            return

    # Not found — show list as fallback
    await wait_msg.edit_text(
        f"🔍 Серіал не знайдено в базі по назві «{title or title_en}».\n"
        f"Обери зі списку:"
    )
    await _show_existing_series(wait_msg, state, page=0, edit=True)


@router.callback_query(AutoDownloadStates.choosing_existing_series, F.data.startswith("ads_existing:"))
async def process_existing_confirm(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":", 2)
    action = parts[1]

    if action == "confirm":
        await callback.message.edit_text(
            f"✅ Серіал підтверджено!\n\nВведіть номер сезону:"
        )
        await state.set_state(AutoDownloadStates.waiting_for_season)
    else:
        await _show_existing_series(callback.message, state, page=0, edit=True)
    await callback.answer()


# ── Існуючий серіал: список (fallback) ───────────────────────────────────────

async def _show_existing_series(message, state: FSMContext, page: int, edit: bool = False):
    series_list = await get_all_series_list(include_hidden=True)
    total_pages = max(1, (len(series_list) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))

    start = page * ITEMS_PER_PAGE
    items = series_list[start:start + ITEMS_PER_PAGE]

    buttons = []
    for s in items:
        sid = str(s["_id"])
        buttons.append([InlineKeyboardButton(
            text=f"📺 {s['title']}",
            callback_data=f"ad_pick_series:{sid}"
        )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"ad_series_page:{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"ad_series_page:{page+1}"))
    if nav:
        buttons.append(nav)

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = f"📺 <b>Виберіть серіал:</b>"
    if edit:
        await message.edit_text(text, reply_markup=keyboard)
    else:
        await message.answer(text, reply_markup=keyboard)

    await state.set_state(AutoDownloadStates.choosing_existing_series)


@router.callback_query(AutoDownloadStates.choosing_existing_series, F.data.startswith("ad_series_page:"))
async def navigate_series_pages(callback: CallbackQuery, state: FSMContext):
    page = int(callback.data.split(":")[1])
    await _show_existing_series(callback.message, state, page=page, edit=True)
    await callback.answer()


@router.callback_query(AutoDownloadStates.choosing_existing_series, F.data.startswith("ad_pick_series:"))
async def pick_existing_series(callback: CallbackQuery, state: FSMContext):
    series_id = callback.data.split(":", 1)[1]
    series = await get_movie_by_id(series_id)
    if not series:
        await callback.answer("❌ Серіал не знайдено", show_alert=True)
        return

    await state.update_data(series_id=series_id, series_title=series["title"])
    await callback.message.edit_text(
        f"✅ <b>{series['title']}</b>\n"
        f"🆔 <code>{series_id}</code>\n\n"
        f"Введіть номер сезону:"
    )
    await state.set_state(AutoDownloadStates.waiting_for_season)
    await callback.answer()


# ── Сезон і URL ──────────────────────────────────────────────────────────────

@router.message(AutoDownloadStates.waiting_for_season, ~F.text.startswith("/"))
async def process_season(message: Message, state: FSMContext):
    try:
        season = int(message.text.strip())
        if season < 1:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введіть ціле число більше 0:")
        return

    await state.update_data(season=season)
    data = await state.get_data()

    # If URL was already parsed (new series or existing series via URL), skip URL step
    if data.get("season_url"):
        wait_msg = await message.answer("⏳ Парсю сторінку...")
        try:
            dubbings = await get_dubbing_options(data["season_url"], season=season)
        except Exception as e:
            await wait_msg.edit_text(f"❌ Не вдалося завантажити сторінку: {e}")
            return
        await _show_dubbing_picker(wait_msg, state, dubbings, edit=True)
    else:
        site = data.get("site", "uakino")
        site_name = "uakino.best" if site == "uakino" else "uafix.net"
        await message.answer(
            f"✅ Сезон: <b>{season}</b>\n\n"
            f"Надішліть URL сезону з {site_name}:"
        )
        await state.set_state(AutoDownloadStates.waiting_for_url)


@router.message(AutoDownloadStates.waiting_for_url, ~F.text.startswith("/"))
async def process_url(message: Message, state: FSMContext):
    url = message.text.strip()
    data = await state.get_data()
    site = data.get("site", "uakino")
    allowed = "uakino.best" if site == "uakino" else "uafix.net"
    if allowed not in url:
        await message.answer(f"❌ URL має містити {allowed}. Спробуйте ще раз:")
        return

    await state.update_data(season_url=url)
    wait_msg = await message.answer("⏳ Парсю сторінку...")

    try:
        dubbings = await get_dubbing_options(url, season=data.get("season"))
    except Exception as e:
        await wait_msg.edit_text(f"❌ Не вдалося завантажити сторінку: {e}")
        return

    await _show_dubbing_picker(wait_msg, state, dubbings, edit=True)


async def _show_dubbing_picker(message, state: FSMContext, dubbings: list, edit: bool = True):
    if not dubbings:
        text = "⚠️ Озвучок не знайдено. Введіть назву озвучки вручну:"
        if edit:
            await message.edit_text(text)
        else:
            await message.answer(text)
        await state.set_state(AutoDownloadStates.choosing_dubbing)
        return

    await state.update_data(available_dubbings=dubbings)
    buttons = [
        [InlineKeyboardButton(text=d, callback_data=f"ad_dubbing:{i}")]
        for i, d in enumerate(dubbings)
    ]
    if edit:
        await message.edit_text("🎙 Оберіть озвучку:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    else:
        await message.answer("🎙 Оберіть озвучку:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(AutoDownloadStates.choosing_dubbing)


# ── Вибір озвучки ────────────────────────────────────────────────────────────

@router.callback_query(AutoDownloadStates.choosing_dubbing, F.data.startswith("ad_dubbing:"))
async def process_dubbing_callback(callback: CallbackQuery, state: FSMContext):
    idx = int(callback.data.split(":")[1])
    data = await state.get_data()
    dubbings = data.get("available_dubbings", [])
    dubbing = dubbings[idx] if idx < len(dubbings) else str(idx)

    await _confirm_dubbing(callback.message, state, dubbing, edit=True)
    await callback.answer()


@router.message(AutoDownloadStates.choosing_dubbing, ~F.text.startswith("/"))
async def process_dubbing_text(message: Message, state: FSMContext):
    await _confirm_dubbing(message, state, message.text.strip(), edit=False)


async def _confirm_dubbing(message, state: FSMContext, dubbing: str, edit: bool):
    data = await state.get_data()
    url = data["season_url"]

    wait_text = "⏳ Рахую серії..."
    if edit:
        await message.edit_text(wait_text)
    else:
        msg = await message.answer(wait_text)
        message = msg

    try:
        result = await parse_season_page(url, dubbing, season=data.get("season"))
    except Exception as e:
        await message.edit_text(f"❌ Помилка парсингу: {e}")
        return

    episode_urls = result["episode_urls"]
    episode_numbers = result.get("episode_numbers") or list(range(1, len(episode_urls) + 1))
    if not episode_urls:
        await message.edit_text(
            f"⚠️ Серій для озвучки «{dubbing}» не знайдено. "
            f"Спробуйте іншу озвучку або перевірте URL."
        )
        return

    await state.update_data(
        dubbing=dubbing,
        episode_urls=episode_urls,
        episode_numbers=episode_numbers,
        total_episodes=len(episode_urls),
    )

    season = data["season"]
    series_title = data["series_title"]
    total = len(episode_urls)

    # Build episode list summary and detect gaps
    nums_sorted = sorted(episode_numbers)
    full_range = set(range(nums_sorted[0], nums_sorted[-1] + 1))
    missing = sorted(full_range - set(nums_sorted))

    ep_list = ", ".join(str(n) for n in nums_sorted)
    if len(ep_list) > 200:
        ep_list = ep_list[:197] + "..."

    info_lines = [
        f"📋 <b>Готово до завантаження:</b>\n",
        f"📺 {series_title}",
        f"📅 Сезон: {season}",
        f"🎙 Озвучка: {dubbing}",
        f"📼 Серій на сайті: {total} (№ {nums_sorted[0]}–{nums_sorted[-1]})",
        f"📝 Номери: {ep_list}",
    ]
    if missing:
        missing_str = ", ".join(str(n) for n in missing[:20])
        if len(missing) > 20:
            missing_str += f" (+{len(missing) - 20} ін.)"
        info_lines.append(f"⚠️ Пропущені на сайті: {missing_str}")
    info_lines.append("\nПочинаємо завантаження?")

    buttons = [
        [InlineKeyboardButton(text="▶️ Починаємо!", callback_data="ad_confirm:yes")],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="ad_confirm:no")],
    ]
    await message.edit_text(
        "\n".join(info_lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await state.set_state(AutoDownloadStates.confirming)


# ── Підтвердження і запуск ───────────────────────────────────────────────────

@router.callback_query(AutoDownloadStates.confirming, F.data.startswith("ad_confirm:"))
async def process_confirm(callback: CallbackQuery, state: FSMContext, bot: Bot):
    choice = callback.data.split(":")[1]
    if choice == "no":
        await callback.message.edit_text("❌ Скасовано.")
        await state.clear()
        await callback.answer()
        return

    data = await state.get_data()
    job_id = await create_job(
        series_id=data["series_id"],
        series_title=data["series_title"],
        season=data["season"],
        dubbing=data["dubbing"],
        episode_urls=data["episode_urls"],
        episode_numbers=data.get("episode_numbers"),
        admin_id=callback.from_user.id,
        content_type=data.get("content_type", "series"),
    )

    await state.clear()
    await callback.message.edit_text(
        f"🚀 Завантаження розпочато!\n\n"
        f"Буде завантажено {data['total_episodes']} серій.\n"
        f"Я повідомлятиму після кожної серії.\n\n"
        f"Щоб зупинити: /cancelDownload"
    )
    await start_job(bot, job_id)
    await callback.answer()


# ── Наступний сезон ──────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("next_season:"))
async def start_next_season(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔️", show_alert=True)
        return

    parts = callback.data.split(":")
    series_id, next_season, content_type = parts[1], int(parts[2]), parts[3]

    series = await get_movie_by_id(series_id)
    series_title = series.get("title", "?") if series else "?"

    await state.set_data({
        "series_id": series_id,
        "series_title": series_title,
        "season": next_season,
        "content_type": content_type,
    })
    await callback.message.answer(
        f"▶️ <b>Наступний сезон</b>\n\n"
        f"📺 {series_title}\n"
        f"📅 Сезон: {next_season}\n\n"
        f"Надішліть URL сезону {next_season} з uakino.best або uafix.net:"
    )
    await state.set_state(AutoDownloadStates.waiting_for_next_season_url)
    await callback.answer()


@router.message(AutoDownloadStates.waiting_for_next_season_url, ~F.text.startswith("/"))
async def process_next_season_url(message: Message, state: FSMContext):
    url = message.text.strip()
    if "uakino.best" not in url and "uafix.net" not in url:
        await message.answer("❌ URL має містити uakino.best або uafix.net. Спробуйте ще раз:")
        return

    site = "uafix" if "uafix.net" in url else "uakino"
    data = await state.get_data()
    season = data["season"]
    season_param = season if site == "uafix" else None

    await state.update_data(season_url=url, site=site)
    wait_msg = await message.answer("⏳ Парсю сторінку...")
    try:
        dubbings = await get_dubbing_options(url, season=season_param)
    except Exception as e:
        await wait_msg.edit_text(f"❌ Не вдалося завантажити сторінку: {e}")
        return

    await _show_dubbing_picker(wait_msg, state, dubbings, edit=True)


# ── /cancelDownload ──────────────────────────────────────────────────────────

@router.message(Command("cancelDownload"))
async def cmd_cancel_download(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ Тільки для адміністраторів.")
        return

    from bot.database.auto_download_jobs import get_running_jobs
    all_running = await get_running_jobs()
    my_jobs = [j for j in all_running if j["admin_id"] == message.from_user.id]

    if not my_jobs:
        await message.answer("Немає активних завантажень.")
        return

    for job in my_jobs:
        await cancel_job(str(job["_id"]))

    await message.answer(
        f"⏹ Зупинка після поточної серії... "
        f"({len(my_jobs)} завантажень)"
    )


# ── Resume callbacks (sent on startup) ───────────────────────────────────────

@router.callback_query(F.data.startswith("ad_resume:"))
async def handle_resume(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔️", show_alert=True)
        return
    job_id = callback.data.split(":", 1)[1]
    try:
        job = await get_job(job_id)
    except Exception:
        await callback.answer("Завдання не знайдено", show_alert=True)
        return
    if not job:
        await callback.answer("Завдання не знайдено", show_alert=True)
        return
    await set_job_status(job_id, "running")
    await callback.message.edit_text(
        f"▶️ Продовжую завантаження «{job['series_title']}» "
        f"з серії {job['current_episode'] + 1}..."
    )
    await start_job(bot, job_id)
    await callback.answer()


@router.callback_query(F.data.startswith("ad_resume_cancel:"))
async def handle_resume_cancel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔️", show_alert=True)
        return
    job_id = callback.data.split(":", 1)[1]
    try:
        await set_job_status(job_id, "paused")
    except Exception:
        await callback.answer("Помилка", show_alert=True)
        return
    await callback.message.edit_text("❌ Завантаження скасовано.")
    await callback.answer()
