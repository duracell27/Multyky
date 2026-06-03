import logging
import os

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardButton, InlineKeyboardMarkup
)
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile

from bot.config import config
from bot.states import AutoMovieStates
from bot.database.movies import (
    create_movie, get_all_movie_series_names
)
from bot.utils.scraper import parse_movie_page, download_poster, get_movie_m3u8
from bot.utils.ffmpeg_runner import run_ffmpeg, get_video_info, create_thumbnail

router = Router()
logger = logging.getLogger(__name__)

ITEMS_PER_PAGE = 20


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


# ── /autoMovie ───────────────────────────────────────────────────────────────

@router.message(Command("autoMovie"))
async def cmd_auto_movie(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ Тільки для адміністраторів.")
        return
    await message.answer(
        "🎬 <b>Автозавантаження фільму</b>\n\n"
        "Надішли URL фільму з uakino.best:"
    )
    await state.set_state(AutoMovieStates.waiting_for_url)


# ── URL → парсинг ────────────────────────────────────────────────────────────

@router.message(AutoMovieStates.waiting_for_url, ~F.text.startswith("/"))
async def process_movie_url(message: Message, state: FSMContext):
    url = message.text.strip()
    if "uakino.best" not in url:
        await message.answer("❌ URL має містити uakino.best. Спробуй ще раз:")
        return

    await state.update_data(movie_url=url)
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
        available_dubbings=data["dubbings"],
    )

    lines = ["📋 <b>Знайдено:</b>\n"]
    lines.append(f"🎬 Назва: <b>{data['title'] or '—'}</b>")
    lines.append(f"🌍 EN: <b>{data['title_en'] or '—'}</b>")
    lines.append(f"📅 Рік: <b>{data['year'] or '—'}</b>")
    lines.append(f"⭐️ IMDB: <b>{data['imdb'] or '—'}</b>")
    lines.append(f"🖼 Постер: {'✅' if data['poster_url'] else '❌ не знайдено'}")
    lines.append(f"🎙 Озвучок: {len(data['dubbings'])}")

    buttons = [
        [InlineKeyboardButton(text="✅ Підтвердити", callback_data="am_meta:confirm")],
        [InlineKeyboardButton(text="✏️ Заповнити вручну", callback_data="am_meta:manual")],
    ]
    await wait_msg.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await state.set_state(AutoMovieStates.confirming_metadata)


# ── Підтвердження метаданих ───────────────────────────────────────────────────

@router.callback_query(AutoMovieStates.confirming_metadata, F.data.startswith("am_meta:"))
async def process_meta_confirm(callback: CallbackQuery, state: FSMContext):
    choice = callback.data.split(":")[1]
    data = await state.get_data()

    if choice == "confirm":
        missing = []
        if not data.get("parsed_title"):
            missing.append("title")
        if not data.get("parsed_title_en"):
            missing.append("title_en")
        if not data.get("parsed_year"):
            missing.append("year")
        if not data.get("parsed_imdb"):
            missing.append("imdb")

        await state.update_data(
            title=data.get("parsed_title"),
            title_en=data.get("parsed_title_en"),
            year=data.get("parsed_year"),
            imdb=data.get("parsed_imdb"),
            missing_fields=missing,
        )

        if missing:
            await _ask_next_missing_field(callback.message, state, missing, edit=True)
        else:
            await _show_dubbing_picker(callback.message, state, edit=True)
    else:
        await state.update_data(
            title=None, title_en=None, year=None, imdb=None,
            missing_fields=["title", "title_en", "year", "imdb"],
        )
        await callback.message.edit_text("Введіть українську назву фільму:")
        await state.set_state(AutoMovieStates.waiting_for_title_manual)

    await callback.answer()


async def _ask_next_missing_field(message, state: FSMContext, missing: list, edit: bool = False):
    field = missing[0]
    prompts = {
        "title": "Введіть українську назву фільму:",
        "title_en": "Введіть англійську назву фільму:",
        "year": "Введіть рік випуску (наприклад: <code>2016</code>):",
        "imdb": "Введіть IMDB рейтинг (наприклад: <code>7.5</code>):",
    }
    state_map = {
        "title": AutoMovieStates.waiting_for_title_manual,
        "title_en": AutoMovieStates.waiting_for_title_en_manual,
        "year": AutoMovieStates.waiting_for_year_manual,
        "imdb": AutoMovieStates.waiting_for_imdb_manual,
    }
    text = prompts[field]
    if edit:
        await message.edit_text(text)
    else:
        await message.answer(text)
    await state.set_state(state_map[field])


# ── Ручне заповнення полів ────────────────────────────────────────────────────

async def _handle_manual_field(message: Message, state: FSMContext, field: str, value):
    await state.update_data(**{field: value})
    data = await state.get_data()
    missing = [f for f in data.get("missing_fields", []) if f != field]
    await state.update_data(missing_fields=missing)
    if missing:
        await _ask_next_missing_field(message, state, missing)
    else:
        await _show_dubbing_picker(message, state)


@router.message(AutoMovieStates.waiting_for_title_manual, ~F.text.startswith("/"))
async def process_title_manual(message: Message, state: FSMContext):
    await _handle_manual_field(message, state, "title", message.text.strip())


@router.message(AutoMovieStates.waiting_for_title_en_manual, ~F.text.startswith("/"))
async def process_title_en_manual(message: Message, state: FSMContext):
    await _handle_manual_field(message, state, "title_en", message.text.strip())


@router.message(AutoMovieStates.waiting_for_year_manual, ~F.text.startswith("/"))
async def process_year_manual(message: Message, state: FSMContext):
    try:
        year = int(message.text.strip())
        if not (1900 <= year <= 2100):
            raise ValueError
    except ValueError:
        await message.answer("❌ Введіть коректний рік (1900-2100):")
        return
    await _handle_manual_field(message, state, "year", year)


@router.message(AutoMovieStates.waiting_for_imdb_manual, ~F.text.startswith("/"))
async def process_imdb_manual(message: Message, state: FSMContext):
    try:
        imdb = float(message.text.strip().replace(",", "."))
        if not (0 <= imdb <= 10):
            raise ValueError
    except ValueError:
        await message.answer("❌ Введіть рейтинг від 0 до 10:")
        return
    await _handle_manual_field(message, state, "imdb", imdb)


# ── Вибір озвучки ─────────────────────────────────────────────────────────────

async def _show_dubbing_picker(message, state: FSMContext, edit: bool = False):
    data = await state.get_data()
    dubbings = data.get("available_dubbings", [])

    if not dubbings:
        text = "🎙 Озвучок не знайдено. Введіть назву озвучки вручну:"
        if edit:
            await message.edit_text(text)
        else:
            await message.answer(text)
        await state.set_state(AutoMovieStates.choosing_dubbing)
        return

    buttons = [
        [InlineKeyboardButton(text=d, callback_data=f"am_dub:{i}")]
        for i, d in enumerate(dubbings)
    ]
    text = "🎙 Оберіть озвучку:"
    if edit:
        await message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    else:
        await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(AutoMovieStates.choosing_dubbing)


@router.callback_query(AutoMovieStates.choosing_dubbing, F.data.startswith("am_dub:"))
async def process_dubbing_callback(callback: CallbackQuery, state: FSMContext):
    idx = int(callback.data.split(":")[1])
    data = await state.get_data()
    dubbings = data.get("available_dubbings", [])
    dubbing = dubbings[idx] if idx < len(dubbings) else str(idx)
    await state.update_data(dubbing=dubbing)
    await _show_series_membership(callback.message, state, edit=True)
    await callback.answer()


@router.message(AutoMovieStates.choosing_dubbing, ~F.text.startswith("/"))
async def process_dubbing_text(message: Message, state: FSMContext):
    await state.update_data(dubbing=message.text.strip())
    await _show_series_membership(message, state)


# ── Серія фільмів ─────────────────────────────────────────────────────────────

async def _show_series_membership(message, state: FSMContext, edit: bool = False):
    buttons = [
        [InlineKeyboardButton(text="📁 Так, належить до серії", callback_data="am_series:yes")],
        [InlineKeyboardButton(text="🎬 Ні, самостійний фільм", callback_data="am_series:no")],
    ]
    text = "Фільм належить до серії фільмів?"
    if edit:
        await message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    else:
        await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(AutoMovieStates.choosing_series_membership)


@router.callback_query(AutoMovieStates.choosing_series_membership, F.data.startswith("am_series:"))
async def process_series_membership(callback: CallbackQuery, state: FSMContext):
    choice = callback.data.split(":")[1]
    if choice == "no":
        await state.update_data(series_name=None, part_number=None)
        await _show_download_confirm(callback.message, state, edit=True)
    else:
        await _show_series_picker(callback.message, state, page=0, edit=True)
    await callback.answer()


async def _show_series_picker(message, state: FSMContext, page: int, edit: bool = False):
    all_series = await get_all_movie_series_names()
    total_pages = max(1, (len(all_series) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))

    start = page * ITEMS_PER_PAGE
    items = all_series[start:start + ITEMS_PER_PAGE]

    buttons = []
    for abs_idx, name in enumerate(items, start=start):
        buttons.append([InlineKeyboardButton(
            text=f"📁 {name}",
            callback_data=f"am_pickser:{abs_idx}"
        )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"am_serpage:{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"am_serpage:{page+1}"))
    if nav:
        buttons.append(nav)

    buttons.append([InlineKeyboardButton(
        text="➕ Створити нову серію",
        callback_data="am_pickser:new"
    )])

    await state.update_data(all_series_list=all_series)
    text = "📁 <b>Виберіть серію фільмів:</b>"
    if edit:
        await message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    else:
        await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(AutoMovieStates.choosing_existing_series)


@router.callback_query(AutoMovieStates.choosing_existing_series, F.data.startswith("am_serpage:"))
async def navigate_series_pages(callback: CallbackQuery, state: FSMContext):
    page = int(callback.data.split(":")[1])
    await _show_series_picker(callback.message, state, page=page, edit=True)
    await callback.answer()


@router.callback_query(AutoMovieStates.choosing_existing_series, F.data.startswith("am_pickser:"))
async def pick_series(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":", 1)[1]

    if val == "new":
        await callback.message.edit_text("➕ Введіть назву нової серії (наприклад: <code>Шрек</code>):")
        await state.set_state(AutoMovieStates.waiting_for_new_series_name)
    else:
        idx = int(val)
        data = await state.get_data()
        all_series = data.get("all_series_list", [])
        series_name = all_series[idx] if idx < len(all_series) else None
        if not series_name:
            await callback.answer("❌ Помилка", show_alert=True)
            return
        await state.update_data(series_name=series_name)
        await callback.message.edit_text(
            f"✅ Серія: <b>{series_name}</b>\n\nВведіть номер частини (наприклад: <code>1</code>):"
        )
        await state.set_state(AutoMovieStates.waiting_for_part_number)
    await callback.answer()


@router.message(AutoMovieStates.waiting_for_new_series_name, ~F.text.startswith("/"))
async def process_new_series_name(message: Message, state: FSMContext):
    series_name = message.text.strip()
    await state.update_data(series_name=series_name)
    await message.answer(
        f"✅ Нова серія: <b>{series_name}</b>\n\nВведіть номер частини (наприклад: <code>1</code>):"
    )
    await state.set_state(AutoMovieStates.waiting_for_part_number)


@router.message(AutoMovieStates.waiting_for_part_number, ~F.text.startswith("/"))
async def process_part_number(message: Message, state: FSMContext):
    try:
        part = int(message.text.strip())
        if part < 1:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введіть ціле число більше 0:")
        return
    await state.update_data(part_number=part)
    await _show_download_confirm(message, state)


# ── Підтвердження завантаження ────────────────────────────────────────────────

async def _show_download_confirm(message, state: FSMContext, edit: bool = False):
    data = await state.get_data()
    series_info = ""
    if data.get("series_name"):
        part = data.get("part_number")
        series_info = f"\n📁 Серія: {data['series_name']}"
        if part:
            series_info += f" (частина {part})"

    text = (
        f"📋 <b>Готово до завантаження:</b>\n\n"
        f"🎬 {data.get('title')}\n"
        f"🌍 {data.get('title_en')}\n"
        f"📅 {data.get('year')} · ⭐️ {data.get('imdb')}\n"
        f"🎙 Озвучка: {data.get('dubbing')}"
        f"{series_info}\n\n"
        f"Починаємо завантаження?"
    )
    buttons = [
        [InlineKeyboardButton(text="▶️ Починаємо!", callback_data="am_confirm:yes")],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="am_confirm:no")],
    ]
    if edit:
        await message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    else:
        await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(AutoMovieStates.confirming_download)


@router.callback_query(AutoMovieStates.confirming_download, F.data.startswith("am_confirm:"))
async def process_download_confirm(callback: CallbackQuery, state: FSMContext, bot: Bot):
    choice = callback.data.split(":")[1]
    if choice == "no":
        await callback.message.edit_text("❌ Скасовано.")
        await state.clear()
        await callback.answer()
        return

    data = await state.get_data()
    await callback.message.edit_text("⏳ Починаю завантаження...")
    await callback.answer()

    admin_id = callback.from_user.id
    await state.clear()

    import asyncio
    asyncio.create_task(
        _download_and_create_movie(
            bot=bot,
            admin_id=admin_id,
            url=data["movie_url"],
            dubbing=data["dubbing"],
            title=data["title"],
            title_en=data["title_en"],
            year=data["year"],
            imdb=data["imdb"],
            poster_url=data.get("poster_url"),
            series_name=data.get("series_name"),
            part_number=data.get("part_number"),
        )
    )


# ── Завантаження і збереження ─────────────────────────────────────────────────

async def _download_and_create_movie(
    bot: Bot,
    admin_id: int,
    url: str,
    dubbing: str,
    title: str,
    title_en: str,
    year: int,
    imdb: float,
    poster_url: str | None,
    series_name: str | None,
    part_number: int | None,
):
    import uuid
    uid = str(uuid.uuid4())[:8]
    poster_path = f"/tmp/{uid}_poster.jpg"
    video_path = f"/tmp/{uid}_movie.mp4"
    thumb_path = f"/tmp/{uid}_thumb.jpg"

    try:
        # 1. Download and upload poster
        poster_file_id = None
        if poster_url:
            await bot.send_message(admin_id, "🖼 Завантажую постер...")
            ok = await download_poster(poster_url, poster_path)
            if ok:
                sent_photo = await bot.send_photo(
                    config.STORAGE_CHANNEL_ID,
                    photo=FSInputFile(poster_path),
                    caption=f"poster:{title}",
                )
                poster_file_id = sent_photo.photo[-1].file_id
                await bot.send_message(admin_id, "✅ Постер завантажено!")
            else:
                await bot.send_message(
                    admin_id,
                    "⚠️ Не вдалося завантажити постер автоматично.\n"
                    "Перешли постер вручну з каналу зберігання після завершення."
                )
        else:
            await bot.send_message(
                admin_id,
                "⚠️ Постер не знайдено на сторінці.\n"
                "Перешли постер вручну з каналу зберігання після завершення."
            )

        # 2. Get m3u8 and download video
        await bot.send_message(admin_id, "📥 Отримую посилання на відео...")
        m3u8_url = await get_movie_m3u8(url, dubbing)

        await bot.send_message(admin_id, "⏳ Завантажую відео (це може зайняти кілька хвилин)...")
        await run_ffmpeg(m3u8_url, video_path)

        # 3. Get metadata and thumbnail
        duration, width, height = await get_video_info(video_path)
        has_thumb = await create_thumbnail(video_path, thumb_path)

        # 4. Upload video to storage channel
        await bot.send_message(admin_id, "📤 Вивантажую відео в канал...")
        sent_video = await bot.send_video(
            config.STORAGE_CHANNEL_ID,
            video=FSInputFile(video_path),
            caption=f"movie:{title}",
            supports_streaming=True,
            width=width or None,
            height=height or None,
            duration=duration or None,
            thumbnail=FSInputFile(thumb_path) if has_thumb else None,
        )
        video_file_id = sent_video.video.file_id
        file_size = sent_video.video.file_size or 0

        # 5. Create movie in database
        movie = await create_movie(
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
        )
        movie_id = str(movie["_id"])

        part_info = f" (частина {part_number})" if part_number else ""
        series_info = f"\n📁 Серія: {series_name}{part_info}" if series_name else ""

        broadcast_btn = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="📢 Зробити розсилку",
                callback_data=f"post_quick:movie:{movie_id}"
            )
        ]])

        await bot.send_message(
            admin_id,
            f"🎉 <b>Фільм «{title}» успішно додано!</b>\n\n"
            f"🆔 ID: <code>{movie_id}</code>"
            f"{series_info}\n\n"
            f"Хочеш зробити розсилку?",
            reply_markup=broadcast_btn,
        )

    except Exception as e:
        logger.error(f"Auto movie download failed for '{title}': {e}")
        try:
            await bot.send_message(admin_id, f"❌ Помилка: {str(e)[:300]}")
        except Exception:
            pass
    finally:
        for path in (poster_path, video_path, thumb_path):
            if os.path.exists(path):
                os.remove(path)
