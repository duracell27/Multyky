from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.database.movies import (
    get_all_movies_list,
    get_all_series_list,
    get_series_seasons,
    get_series_episodes,
    get_episode,
    get_movie_by_title,
    get_movie_by_id,
    get_series_info_by_title,
    increment_views
)
from bot.database.users import get_or_create_user
from bot.utils import send_movie_video

router = Router()


@router.message(Command("catalog"))
async def cmd_catalog(message: Message):
    """Показати каталог мультфільмів і серіалів"""

    # Автоматично оновлюємо активність
    await get_or_create_user(message.from_user)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎬 Фільми", callback_data="catalog:movies"),
            InlineKeyboardButton(text="📺 Серіали", callback_data="catalog:series")
        ]
    ])

    await message.answer(
        "🎬 <b>Каталог мультфільмів</b>\n\n"
        "Виберіть категорію:",
        reply_markup=keyboard
    )


@router.callback_query(F.data == "catalog:movies")
async def show_movies(callback: CallbackQuery):
    """Показати список фільмів"""

    movies = await get_all_movies_list()

    if not movies:
        await callback.message.edit_text("📭 Поки що немає доданих мультфільмів.")
        await callback.answer()
        return

    # Створюємо кнопки для кожного фільму (по 1 на рядок)
    buttons = []
    for movie in movies:
        # Використовуємо ID замість назви - набагато коротше
        movie_id = str(movie["_id"])
        buttons.append([
            InlineKeyboardButton(
                text=f"🎬 {movie['title']} ({movie['year']})",
                callback_data=f"m:{movie_id}"
            )
        ])

    # Додаємо кнопку "Назад"
    buttons.append([
        InlineKeyboardButton(text="◀️ Назад", callback_data="catalog:back")
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text(
        "🎬 <b>Мультфільми:</b>\n\n"
        "Виберіть фільм для перегляду:",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data == "catalog:series")
async def show_series(callback: CallbackQuery):
    """Показати список серіалів"""

    series = await get_all_series_list()

    if not series:
        await callback.message.edit_text("📭 Поки що немає доданих серіалів.")
        await callback.answer()
        return

    # Створюємо кнопки для кожного серіалу
    buttons = []
    for show in series:
        # Використовуємо doc_id який ми додали в агрегації
        series_id = str(show["doc_id"])
        buttons.append([
            InlineKeyboardButton(
                text=f"📺 {show['title']} ({show['year']})",
                callback_data=f"s:{series_id}"
            )
        ])

    # Додаємо кнопку "Назад"
    buttons.append([
        InlineKeyboardButton(text="◀️ Назад", callback_data="catalog:back")
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text(
        "📺 <b>Серіали:</b>\n\n"
        "Виберіть серіал:",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("s:"))
async def show_seasons(callback: CallbackQuery):
    """Показати сезони серіалу"""

    series_id = callback.data.split(":", 1)[1]

    # Отримуємо інформацію про серіал за ID
    series_info = await get_movie_by_id(series_id)

    if not series_info:
        await callback.answer("❌ Серіал не знайдено", show_alert=True)
        return

    title = series_info["title"]
    seasons = await get_series_seasons(title)

    if not seasons:
        await callback.answer("❌ Не знайдено сезонів для цього серіалу", show_alert=True)
        return

    # Створюємо кнопки для кожного сезону
    buttons = []
    for season in seasons:
        buttons.append([
            InlineKeyboardButton(
                text=f"📺 Сезон {season}",
                callback_data=f"sn:{series_id}:{season}"
            )
        ])

    # Додаємо кнопку "Назад"
    buttons.append([
        InlineKeyboardButton(text="◀️ Назад до серіалів", callback_data="catalog:series")
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text(
        f"📺 <b>{title}</b>\n\n"
        "Виберіть сезон:",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("sn:"))
async def show_episodes(callback: CallbackQuery):
    """Показати серії сезону"""

    parts = callback.data.split(":", 2)
    series_id = parts[1]
    season = int(parts[2])

    # Отримуємо інформацію про серіал
    series_info = await get_movie_by_id(series_id)

    if not series_info:
        await callback.answer("❌ Серіал не знайдено", show_alert=True)
        return

    title = series_info["title"]
    episodes = await get_series_episodes(title, season)

    if not episodes:
        await callback.answer("❌ Не знайдено серій для цього сезону", show_alert=True)
        return

    # Створюємо кнопки для кожної серії
    buttons = []
    for ep in episodes:
        ep_id = str(ep["_id"])
        buttons.append([
            InlineKeyboardButton(
                text=f"▶️ Серія {ep['episode']}",
                callback_data=f"e:{ep_id}"
            )
        ])

    # Додаємо кнопку "Назад"
    buttons.append([
        InlineKeyboardButton(
            text="◀️ Назад до сезонів",
            callback_data=f"s:{series_id}"
        )
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text(
        f"📺 <b>{title}</b>\n"
        f"Сезон {season}\n\n"
        "Виберіть серію:",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("e:"))
async def send_episode(callback: CallbackQuery, bot: Bot):
    """Відправити серію користувачу"""

    episode_id = callback.data.split(":", 1)[1]

    # Отримуємо серію за ID
    episode = await get_movie_by_id(episode_id)

    if not episode:
        await callback.answer("❌ Серію не знайдено", show_alert=True)
        return

    # Збільшуємо лічильник переглядів
    await increment_views(episode_id)

    # Формуємо підпис
    caption = (
        f"📺 <b>{episode['title']}</b>\n"
        f"Сезон {episode['season']}, Серія {episode['episode']}\n\n"
        f"⭐️ IMDB: {episode['imdb_rating']}\n"
        f"📅 Рік: {episode['year']}"
    )

    # Відправляємо відео
    try:
        await send_movie_video(bot, callback.from_user.id, episode, caption)
        await callback.answer("✅ Приємного перегляду!")
    except Exception as e:
        await callback.answer(f"❌ Помилка при відправці відео: {str(e)}", show_alert=True)


@router.callback_query(F.data.startswith("m:"))
async def send_movie(callback: CallbackQuery, bot: Bot):
    """Відправити фільм користувачу"""

    movie_id = callback.data.split(":", 1)[1]

    # Отримуємо фільм за ID
    movie = await get_movie_by_id(movie_id)

    if not movie:
        await callback.answer("❌ Фільм не знайдено", show_alert=True)
        return

    # Збільшуємо лічильник переглядів
    await increment_views(movie_id)

    # Формуємо підпис
    caption = (
        f"🎬 <b>{movie['title']}</b>\n\n"
        f"⭐️ IMDB: {movie['imdb_rating']}\n"
        f"📅 Рік: {movie['year']}"
    )

    # Відправляємо відео
    try:
        await send_movie_video(bot, callback.from_user.id, movie, caption)
        await callback.answer("✅ Приємного перегляду!")
    except Exception as e:
        await callback.answer(f"❌ Помилка при відправці відео: {str(e)}", show_alert=True)


@router.callback_query(F.data == "catalog:back")
async def back_to_catalog(callback: CallbackQuery):
    """Повернутися до головного меню каталогу"""

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎬 Фільми", callback_data="catalog:movies"),
            InlineKeyboardButton(text="📺 Серіали", callback_data="catalog:series")
        ]
    ])

    await callback.message.edit_text(
        "🎬 <b>Каталог мультфільмів</b>\n\n"
        "Виберіть категорію:",
        reply_markup=keyboard
    )
    await callback.answer()
