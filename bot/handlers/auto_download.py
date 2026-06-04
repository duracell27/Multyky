import logging
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardButton, InlineKeyboardMarkup
)
from aiogram.fsm.context import FSMContext

from bot.config import config
from bot.states import AutoDownloadStates
from bot.database.movies import (
    get_all_series_list, get_movie_by_id,
    create_series
)
from bot.database.auto_download_jobs import (
    create_job, set_job_status, get_job
)
from bot.utils.scraper import get_dubbing_options, parse_season_page
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
        [InlineKeyboardButton(text="➕ Новий серіал", callback_data="ad_series_type:new")],
        [InlineKeyboardButton(text="📺 Існуючий серіал", callback_data="ad_series_type:existing")],
    ]
    await callback.message.answer(
        "🤖 <b>Автозавантаження серій</b>\n\n"
        "Додати серії до нового чи існуючого серіалу?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await state.set_state(AutoDownloadStates.choosing_series_type)
    await callback.answer()


# ── /autoDownload ────────────────────────────────────────────────────────────

@router.message(Command("autoDownload"))
async def cmd_auto_download(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ Тільки для адміністраторів.")
        return

    buttons = [
        [InlineKeyboardButton(text="➕ Новий серіал", callback_data="ad_series_type:new")],
        [InlineKeyboardButton(text="📺 Існуючий серіал", callback_data="ad_series_type:existing")],
    ]
    await message.answer(
        "🤖 <b>Автозавантаження серій</b>\n\n"
        "Додати серії до нового чи існуючого серіалу?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await state.set_state(AutoDownloadStates.choosing_series_type)


# ── Вибір типу серіалу ───────────────────────────────────────────────────────

@router.callback_query(AutoDownloadStates.choosing_series_type, F.data.startswith("ad_series_type:"))
async def process_series_type(callback: CallbackQuery, state: FSMContext):
    choice = callback.data.split(":", 1)[1]
    if choice == "new":
        await callback.message.edit_text(
            "➕ <b>Новий серіал</b>\n\nВведіть українську назву серіалу:"
        )
        await state.set_state(AutoDownloadStates.waiting_for_new_series_title)
    else:
        await _show_existing_series(callback.message, state, page=0, edit=True)
    await callback.answer()


# ── Новий серіал: збір даних ─────────────────────────────────────────────────

@router.message(AutoDownloadStates.waiting_for_new_series_title, ~F.text.startswith("/"))
async def process_new_title(message: Message, state: FSMContext):
    await state.update_data(new_title=message.text.strip())
    await message.answer("Введіть англійську назву:")
    await state.set_state(AutoDownloadStates.waiting_for_new_series_title_en)


@router.message(AutoDownloadStates.waiting_for_new_series_title_en, ~F.text.startswith("/"))
async def process_new_title_en(message: Message, state: FSMContext):
    await state.update_data(new_title_en=message.text.strip())
    await message.answer("Введіть рік випуску (наприклад: <code>2010</code>):")
    await state.set_state(AutoDownloadStates.waiting_for_new_series_year)


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
    await message.answer("Введіть IMDB рейтинг (наприклад: <code>7.5</code>):")
    await state.set_state(AutoDownloadStates.waiting_for_new_series_imdb)


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
    await message.answer("Перешліть постер (фото) з каналу зберігання:")
    await state.set_state(AutoDownloadStates.waiting_for_new_series_poster)


@router.message(AutoDownloadStates.waiting_for_new_series_poster, F.photo)
async def process_new_poster(message: Message, state: FSMContext):
    if get_forwarded_chat_id(message) != config.STORAGE_CHANNEL_ID:
        await message.answer("❌ Постер має бути пересланий з каналу зберігання!")
        return

    poster_file_id = message.photo[-1].file_id
    data = await state.get_data()

    series = await create_series(
        title=data["new_title"],
        title_en=data["new_title_en"],
        year=data["new_year"],
        imdb_rating=data["new_imdb"],
        poster_file_id=poster_file_id,
        added_by=message.from_user.id,
    )
    series_id = str(series["_id"])

    await state.update_data(series_id=series_id, series_title=data["new_title"])
    await message.answer(
        f"✅ Серіал створено!\n"
        f"<b>{data['new_title']}</b>\n"
        f"🆔 <code>{series_id}</code>\n\n"
        f"Введіть номер сезону:"
    )
    await state.set_state(AutoDownloadStates.waiting_for_season)


@router.message(AutoDownloadStates.waiting_for_new_series_poster, ~F.text.startswith("/"))
async def process_new_poster_invalid(message: Message, state: FSMContext):
    await message.answer("❌ Надішліть фото постера з каналу зберігання.")


# ── Існуючий серіал: список ──────────────────────────────────────────────────

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
    await message.answer(
        f"✅ Сезон: <b>{season}</b>\n\n"
        f"Надішліть URL сезону з uakino.best:"
    )
    await state.set_state(AutoDownloadStates.waiting_for_url)


@router.message(AutoDownloadStates.waiting_for_url, ~F.text.startswith("/"))
async def process_url(message: Message, state: FSMContext):
    url = message.text.strip()
    if "uakino.best" not in url:
        await message.answer("❌ URL має містити uakino.best. Спробуйте ще раз:")
        return

    await state.update_data(season_url=url)
    wait_msg = await message.answer("⏳ Парсю сторінку...")

    try:
        dubbings = await get_dubbing_options(url)
    except Exception as e:
        await wait_msg.edit_text(f"❌ Не вдалося завантажити сторінку: {e}")
        return

    if not dubbings:
        await wait_msg.edit_text(
            "⚠️ Озвучок не знайдено. Можливо, сторінка має незнайому структуру.\n"
            "Введіть назву озвучки вручну:"
        )
        await state.set_state(AutoDownloadStates.choosing_dubbing)
        return

    await state.update_data(available_dubbings=dubbings)
    buttons = [
        [InlineKeyboardButton(text=d, callback_data=f"ad_dubbing:{i}")]
        for i, d in enumerate(dubbings)
    ]
    await wait_msg.edit_text(
        "🎙 Оберіть озвучку:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
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
        result = await parse_season_page(url, dubbing)
    except Exception as e:
        await message.edit_text(f"❌ Помилка парсингу: {e}")
        return

    episode_urls = result["episode_urls"]
    if not episode_urls:
        await message.edit_text(
            f"⚠️ Серій для озвучки «{dubbing}» не знайдено. "
            f"Спробуйте іншу озвучку або перевірте URL."
        )
        return

    await state.update_data(
        dubbing=dubbing,
        episode_urls=episode_urls,
        total_episodes=len(episode_urls),
    )

    buttons = [
        [InlineKeyboardButton(text="▶️ Починаємо!", callback_data="ad_confirm:yes")],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="ad_confirm:no")],
    ]
    season = data["season"]
    series_title = data["series_title"]
    await message.edit_text(
        f"📋 <b>Готово до завантаження:</b>\n\n"
        f"📺 {series_title}\n"
        f"📅 Сезон: {season}\n"
        f"🎙 Озвучка: {dubbing}\n"
        f"📼 Серій: {len(episode_urls)}\n\n"
        f"Починаємо завантаження?",
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
        admin_id=callback.from_user.id,
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
