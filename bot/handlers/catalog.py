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
from bot.database.users import get_or_create_user, add_to_watch_history
from bot.utils import send_movie_video

router = Router()


@router.message(Command("catalog"))
async def cmd_catalog(message: Message):
    """Показати каталог мультфільмів і серіалів"""

    # Автоматично оновлюємо активність
    await get_or_create_user(message.from_user)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎬 Мультфільми", callback_data="catalog:movies"),
            InlineKeyboardButton(text="📺 Мультсеріали", callback_data="catalog:series")
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
                text=f"🎬 {movie['title']} ({movie['year']}) ⭐️ {movie['imdb_rating']}",
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
                text=f"📺 {show['title']} ({show['year']}) ⭐️ {show['imdb_rating']}",
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
    """Показати сезони серіалу з пагінацією"""

    parts = callback.data.split(":")
    series_id = parts[1]
    page = int(parts[2]) if len(parts) > 2 else 0

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

    # Пагінація: 5 сезонів на сторінку
    SEASONS_PER_PAGE = 5
    total_pages = (len(seasons) + SEASONS_PER_PAGE - 1) // SEASONS_PER_PAGE
    page = max(0, min(page, total_pages - 1))  # Обмежуємо page в межах

    start_idx = page * SEASONS_PER_PAGE
    end_idx = start_idx + SEASONS_PER_PAGE
    seasons_page = seasons[start_idx:end_idx]

    # Створюємо кнопки для сезонів на поточній сторінці
    buttons = []
    for season in seasons_page:
        buttons.append([
            InlineKeyboardButton(
                text=f"📺 Сезон {season}",
                callback_data=f"sn:{series_id}:{season}:0"
            )
        ])

    # Кнопки навігації
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"s:{series_id}:{page-1}"
        ))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(
            text="Далі ▶️",
            callback_data=f"s:{series_id}:{page+1}"
        ))

    if nav_buttons:
        buttons.append(nav_buttons)

    # Кнопка повернення до списку серіалів
    buttons.append([
        InlineKeyboardButton(text="◀️ Назад до мультсеріалів", callback_data="catalog:series")
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    page_info = f"Сторінка {page + 1}/{total_pages}" if total_pages > 1 else ""

    await callback.message.edit_text(
        f"📺 <b>{title}</b>\n\n"
        f"Виберіть сезон:\n"
        f"{page_info}",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("sn:"))
async def show_episodes(callback: CallbackQuery):
    """Показати серії сезону з пагінацією"""

    parts = callback.data.split(":")
    series_id = parts[1]
    season = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0

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

    # Пагінація: 10 серій на сторінку
    EPISODES_PER_PAGE = 10
    total_pages = (len(episodes) + EPISODES_PER_PAGE - 1) // EPISODES_PER_PAGE
    page = max(0, min(page, total_pages - 1))  # Обмежуємо page в межах

    start_idx = page * EPISODES_PER_PAGE
    end_idx = start_idx + EPISODES_PER_PAGE
    episodes_page = episodes[start_idx:end_idx]

    # Створюємо кнопки для серій на поточній сторінці
    buttons = []
    for ep in episodes_page:
        ep_id = str(ep["_id"])
        buttons.append([
            InlineKeyboardButton(
                text=f"▶️ Серія {ep['episode']}",
                callback_data=f"e:{ep_id}"
            )
        ])

    # Кнопки навігації
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"sn:{series_id}:{season}:{page-1}"
        ))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(
            text="Далі ▶️",
            callback_data=f"sn:{series_id}:{season}:{page+1}"
        ))

    if nav_buttons:
        buttons.append(nav_buttons)

    # Кнопка повернення до списку сезонів
    buttons.append([
        InlineKeyboardButton(
            text="◀️ Назад до сезонів",
            callback_data=f"s:{series_id}:0"
        )
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    page_info = f"Сторінка {page + 1}/{total_pages}" if total_pages > 1 else ""

    await callback.message.edit_text(
        f"📺 <b>{title}</b>\n"
        f"Сезон {season}\n\n"
        f"Виберіть серію:\n"
        f"{page_info}",
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

    # Збільшуємо лічільник переглядів
    await increment_views(episode_id)

    # Додаємо в історію перегляду
    await add_to_watch_history(callback.from_user.id, episode_id, episode)

    # Формуємо підпис
    caption = (
        f"📺 <b>{episode['title']}</b>\n"
        f"Сезон {episode['season']}, Серія {episode['episode']}\n\n"
        f"📺 <a href='https://t.me/multyky_ua_bot'>Мультики 🇺🇦 | Мультфільми Українською</a>"
    )

    # Відправляємо відео
    try:
        sent_message = await send_movie_video(bot, callback.from_user.id, episode, caption)

        # Шукаємо наступну серію
        title = episode['title']
        current_season = episode['season']
        current_episode = episode['episode']

        # Спробуємо знайти наступну серію в поточному сезоні
        all_episodes = await get_series_episodes(title, current_season)
        next_episode_in_season = None

        for ep in all_episodes:
            if ep['episode'] == current_episode + 1:
                next_episode_in_season = ep
                break

        # Створюємо кнопку для наступної серії
        buttons = []
        if next_episode_in_season:
            # Є наступна серія в поточному сезоні
            next_ep_id = str(next_episode_in_season["_id"])
            buttons.append([
                InlineKeyboardButton(
                    text=f"▶️ Наступна серія {current_episode + 1}",
                    callback_data=f"e:{next_ep_id}"
                )
            ])
        else:
            # Перевіряємо чи є наступний сезон
            all_seasons = await get_series_seasons(title)
            if current_season + 1 in all_seasons:
                # Є наступний сезон, шукаємо першу серію
                next_season_episodes = await get_series_episodes(title, current_season + 1)
                if next_season_episodes:
                    first_episode = next_season_episodes[0]
                    first_ep_id = str(first_episode["_id"])
                    buttons.append([
                        InlineKeyboardButton(
                            text=f"▶️ Сезон {current_season + 1}, Серія 1",
                            callback_data=f"e:{first_ep_id}"
                        )
                    ])

        # Якщо є кнопка наступної серії - редагуємо повідомлення
        if buttons:
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            await bot.edit_message_caption(
                chat_id=callback.from_user.id,
                message_id=sent_message.message_id,
                caption=caption,
                reply_markup=keyboard
            )

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

    # Збільшуємо лічільник переглядів
    await increment_views(movie_id)

    # Додаємо в історію перегляду
    await add_to_watch_history(callback.from_user.id, movie_id, movie)

    # Формуємо підпис
    caption = (
        f"🎬 <b>{movie['title']}</b>\n\n"
        f"📺 <a href='https://t.me/multyky_ua_bot'>Мультики 🇺🇦 | Мультфільми Українською</a>"
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
            InlineKeyboardButton(text="🎬 Мультфільми", callback_data="catalog:movies"),
            InlineKeyboardButton(text="📺 Мультсеріали", callback_data="catalog:series")
        ]
    ])

    await callback.message.edit_text(
        "🎬 <b>Каталог мультфільмів</b>\n\n"
        "Виберіть категорію:",
        reply_markup=keyboard
    )
    await callback.answer()
