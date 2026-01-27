from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from datetime import datetime

from bot.database.movies import (
    get_all_movies_list,
    get_all_series_list,
    get_series_seasons,
    get_series_episodes,
    get_episode,
    get_movie_by_title,
    get_movie_by_id,
    get_series_info_by_title,
    increment_views,
    toggle_like,
    toggle_dislike,
    get_user_vote,
    get_grouped_movies,
    get_movies_by_series_name,
    calculate_series_average_rating,
    # Аніме функції
    get_all_anime_movies_list,
    get_all_anime_series_list,
    get_grouped_anime_movies,
    get_anime_movies_by_series_name,
    get_anime_movies_only_count,
    get_anime_series_only_count
)
from bot.database.users import (
    get_or_create_user,
    add_to_watch_history,
    add_to_watch_later,
    remove_from_watch_later,
    is_in_watch_later,
    mark_movie_as_watched,
    unmark_movie_as_watched,
    is_movie_watched
)
from bot.utils import send_movie_video
from bot.config import config

router = Router()


async def create_content_poster_buttons(content_id: str, user_id: int) -> InlineKeyboardMarkup:
    """Створити кнопки для постера з візуальною індикацією стану (для фільмів і серіалів)"""
    # Перевіряємо чи користувач лайкнув/дизлайкнув
    user_vote = await get_user_vote(content_id, user_id)

    # Перевіряємо чи контент в черзі перегляду
    in_queue = await is_in_watch_later(user_id, content_id)

    # Формуємо текст кнопок
    like_text = "👍 ✅" if user_vote == "like" else "👍"
    dislike_text = "👎 ✅" if user_vote == "dislike" else "👎"
    watchlater_text = "📌 ✅" if in_queue else "📌"

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=like_text, callback_data=f"like:{content_id}"),
            InlineKeyboardButton(text=dislike_text, callback_data=f"dislike:{content_id}"),
            InlineKeyboardButton(text=watchlater_text, callback_data=f"watchlater:{content_id}")
        ]
    ])


# Для зворотної сумісності
async def create_series_poster_buttons(series_id: str, user_id: int) -> InlineKeyboardMarkup:
    """Створити кнопки для постера серіалу (використовує загальну функцію)"""
    return await create_content_poster_buttons(series_id, user_id)


@router.message(Command("catalog"))
async def cmd_catalog(message: Message, state: FSMContext, bot: Bot):
    """Показати каталог мультфільмів і серіалів"""

    # Очищаємо стан (наприклад, якщо користувач був у пошуку)
    await state.clear()

    # Автоматично оновлюємо активність
    await get_or_create_user(message.from_user, bot)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎬 Мультфільми", callback_data="catalog:movies"),
            InlineKeyboardButton(text="📺 Мультсеріали", callback_data="catalog:series")
        ],
        [
            InlineKeyboardButton(text="🎌 Аніме", callback_data="catalog:anime")
        ]
    ])

    await message.answer(
        "🎬 <b>Каталог</b>\n\n"
        "Виберіть категорію:",
        reply_markup=keyboard
    )


@router.callback_query(F.data.startswith("catalog:movies:new:"))
async def show_movies_new(callback: CallbackQuery):
    """Показати новинки (фільми 2025 року)"""

    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[NEWMOVIES] Викликано обробник новинок! callback_data: {callback.data}")

    # Отримуємо номер сторінки з callback_data
    parts = callback.data.split(":")
    page = int(parts[3]) if len(parts) > 3 else 0
    logger.info(f"[NEWMOVIES] Сторінка: {page}")

    # Адміни бачать всі фільми, включаючи приховані
    is_admin = callback.from_user.id in config.ADMIN_IDS

    # Отримуємо всі фільми
    grouped_data = await get_grouped_movies(include_hidden=is_admin)
    grouped = grouped_data["grouped"]
    standalone = grouped_data["standalone"]

    # Збираємо всі фільми (і з груп, і окремі)
    all_movies = []
    for series_name, movies in grouped.items():
        all_movies.extend(movies)
    all_movies.extend(standalone)

    # DEBUG: Виводимо інформацію про фільми
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Всього фільмів: {len(all_movies)}")
    years = [m.get('year') for m in all_movies]
    logger.info(f"Роки фільмів: {sorted(set(years))}")

    # Фільтруємо тільки фільми 2025 року
    new_movies = [m for m in all_movies if m.get('year') == 2025]
    logger.info(f"Фільмів 2025 року: {len(new_movies)}")
    if new_movies:
        logger.info(f"Назви новинок: {[m.get('title') for m in new_movies]}")

    if not new_movies:
        await callback.answer("❌ Новинок 2025 року поки немає", show_alert=True)
        return

    # Сортуємо за рейтингом IMDb (від найвищого до найнижчого)
    new_movies.sort(key=lambda x: x.get('imdb_rating', 0), reverse=True)

    # Пагінація: 15 фільмів на сторінку
    ITEMS_PER_PAGE = 15
    total_pages = (len(new_movies) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    page = max(0, min(page, total_pages - 1))

    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    movies_page = new_movies[start_idx:end_idx]

    # Створюємо кнопки
    buttons = []
    for movie in movies_page:
        movie_id = str(movie["_id"])

        # Перевіряємо чи фільм переглянутий
        is_watched = await is_movie_watched(callback.from_user.id, movie_id)
        watched_emoji = "👁 " if is_watched else ""

        buttons.append([
            InlineKeyboardButton(
                text=f"{watched_emoji}🎬 {movie['title']} ({movie['year']}) ⭐️ {movie['imdb_rating']}",
                callback_data=f"m:{movie_id}"
            )
        ])

    # Кнопки навігації
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"catalog:movies:new:{page-1}"
        ))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(
            text="Далі ▶️",
            callback_data=f"catalog:movies:new:{page+1}"
        ))

    if nav_buttons:
        buttons.append(nav_buttons)

    # Додаємо кнопку "Назад до каталогу"
    buttons.append([
        InlineKeyboardButton(text="◀️ Назад до каталогу", callback_data="catalog:movies")
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    page_info = f"\n<i>Сторінка {page + 1}/{total_pages}</i>" if total_pages > 1 else ""

    await callback.message.edit_text(
        f"🆕 <b>Новинки 2025:</b>\n\n"
        f"Всього фільмів: {len(new_movies)}\n\n"
        f"Виберіть фільм для перегляду:{page_info}",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("catalog:movies:top:"))
async def show_movies_top(callback: CallbackQuery):
    """Показати топ фільмів за рейтингом IMDb"""

    # Отримуємо номер сторінки з callback_data
    parts = callback.data.split(":")
    page = int(parts[3]) if len(parts) > 3 else 0

    # Адміни бачать всі фільми, включаючи приховані
    is_admin = callback.from_user.id in config.ADMIN_IDS

    # Отримуємо всі фільми
    grouped_data = await get_grouped_movies(include_hidden=is_admin)
    grouped = grouped_data["grouped"]
    standalone = grouped_data["standalone"]

    # Збираємо всі фільми (і з груп, і окремі)
    all_movies = []
    for series_name, movies in grouped.items():
        all_movies.extend(movies)
    all_movies.extend(standalone)

    if not all_movies:
        await callback.answer("❌ Немає фільмів", show_alert=True)
        return

    # Сортуємо за рейтингом IMDb (від найвищого до найнижчого)
    all_movies.sort(key=lambda x: x.get('imdb_rating', 0), reverse=True)

    # Пагінація: 15 фільмів на сторінку
    ITEMS_PER_PAGE = 15
    total_pages = (len(all_movies) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    page = max(0, min(page, total_pages - 1))

    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    movies_page = all_movies[start_idx:end_idx]

    # Створюємо кнопки
    buttons = []
    for movie in movies_page:
        movie_id = str(movie["_id"])

        # Перевіряємо чи фільм переглянутий
        is_watched = await is_movie_watched(callback.from_user.id, movie_id)
        watched_emoji = "👁 " if is_watched else ""

        buttons.append([
            InlineKeyboardButton(
                text=f"{watched_emoji}🎬 {movie['title']} ({movie['year']}) ⭐️ {movie['imdb_rating']}",
                callback_data=f"m:{movie_id}"
            )
        ])

    # Кнопки навігації
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"catalog:movies:top:{page-1}"
        ))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(
            text="Далі ▶️",
            callback_data=f"catalog:movies:top:{page+1}"
        ))

    if nav_buttons:
        buttons.append(nav_buttons)

    # Додаємо кнопку "Назад до каталогу"
    buttons.append([
        InlineKeyboardButton(text="◀️ Назад до каталогу", callback_data="catalog:movies")
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    page_info = f"\n<i>Сторінка {page + 1}/{total_pages}</i>" if total_pages > 1 else ""

    await callback.message.edit_text(
        f"🏆 <b>Топ фільмів за рейтингом IMDb:</b>\n\n"
        f"Всього фільмів: {len(all_movies)}\n\n"
        f"Виберіть фільм для перегляду:{page_info}",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("catalog:movies"))
async def show_movies(callback: CallbackQuery):
    """Показати список фільмів (згруповані за серіями)"""

    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[SHOWMOVIES] Отримано callback: {callback.data}")

    # Отримуємо номер сторінки з callback_data
    parts = callback.data.split(":")

    logger.info(f"[SHOWMOVIES] Обробляємо як звичайний каталог")
    page = int(parts[2]) if len(parts) > 2 else 0

    # Адміни бачать всі фільми, включаючи приховані
    is_admin = callback.from_user.id in config.ADMIN_IDS
    grouped_data = await get_grouped_movies(include_hidden=is_admin)
    grouped = grouped_data["grouped"]
    standalone = grouped_data["standalone"]

    if not grouped and not standalone:
        await callback.message.edit_text("📭 Поки що немає доданих мультфільмів.")
        await callback.answer()
        return

    # Створюємо список всіх елементів (групи + окремі фільми)
    all_items = []

    # Спочатку додаємо групи (серії фільмів)
    for series_name in sorted(grouped.keys()):
        movies_in_series = grouped[series_name]
        count = len(movies_in_series)
        avg_rating = await calculate_series_average_rating(movies_in_series)
        all_items.append({
            "type": "series",
            "name": series_name,
            "count": count,
            "avg_rating": avg_rating
        })

    # Потім окремі фільми
    for movie in standalone:
        all_items.append({
            "type": "movie",
            "movie": movie
        })

    # Пагінація: 15 елементів на сторінку
    ITEMS_PER_PAGE = 15
    total_pages = (len(all_items) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    page = max(0, min(page, total_pages - 1))

    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    items_page = all_items[start_idx:end_idx]

    # Створюємо кнопки
    buttons = []

    for item in items_page:
        if item["type"] == "series":
            # Група фільмів
            count = item["count"]
            avg_rating = item["avg_rating"]
            buttons.append([
                InlineKeyboardButton(
                    text=f"📁 {item['name']} ({count} {'фільм' if count == 1 else 'фільми' if count < 5 else 'фільмів'}) ⭐️ {avg_rating}",
                    callback_data=f"series_movies:{item['name']}"
                )
            ])
        else:
            # Окремий фільм
            movie = item["movie"]
            movie_id = str(movie["_id"])

            # Перевіряємо чи фільм переглянутий
            is_watched = await is_movie_watched(callback.from_user.id, movie_id)
            watched_emoji = "👁 " if is_watched else ""

            buttons.append([
                InlineKeyboardButton(
                    text=f"{watched_emoji}🎬 {movie['title']} ({movie['year']}) ⭐️ {movie['imdb_rating']}",
                    callback_data=f"m:{movie_id}"
                )
            ])

    # Кнопки навігації
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"catalog:movies:{page-1}"
        ))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(
            text="Далі ▶️",
            callback_data=f"catalog:movies:{page+1}"
        ))

    if nav_buttons:
        buttons.append(nav_buttons)

    # Збираємо всі фільми (і з груп, і окремі) для підрахунку новинок
    all_movies = []
    for series_name, movies in grouped.items():
        all_movies.extend(movies)
    all_movies.extend(standalone)

    # DEBUG: Виводимо інформацію про фільми в основному каталозі
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[CATALOG] Всього фільмів: {len(all_movies)}")
    logger.info(f"[CATALOG] З груп: {sum(len(movies) for movies in grouped.values())}, Окремих: {len(standalone)}")
    years = [m.get('year') for m in all_movies]
    logger.info(f"[CATALOG] Роки фільмів: {sorted(set(years))}")

    # Підраховуємо кількість новинок (фільми 2025 року)
    new_movies_2025 = [m for m in all_movies if m.get('year') == 2025]
    new_movies_count = len(new_movies_2025)
    logger.info(f"[CATALOG] Фільмів 2025 року: {new_movies_count}")
    if new_movies_2025:
        logger.info(f"[CATALOG] Назви: {[m.get('title') for m in new_movies_2025]}")

    # Додаємо кнопки "Новинки" і "Топ" на початку
    filter_buttons = []
    if new_movies_count > 0:
        filter_buttons.append(
            InlineKeyboardButton(text=f"🆕 Новинки ({new_movies_count})", callback_data="catalog:movies:new:0")
        )
    filter_buttons.append(
        InlineKeyboardButton(text="🏆 Топ", callback_data="catalog:movies:top:0")
    )

    # Вставляємо кнопки фільтрів на початок списку кнопок
    if filter_buttons:
        buttons.insert(0, filter_buttons)

    # Додаємо кнопку "Назад до каталогу"
    buttons.append([
        InlineKeyboardButton(text="◀️ Назад", callback_data="catalog:back")
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    page_info = f"\n<i>Сторінка {page + 1}/{total_pages}</i>" if total_pages > 1 else ""

    await callback.message.edit_text(
        f"🎬 <b>Мультфільми:</b>\n\n"
        f"Виберіть серію або фільм для перегляду:{page_info}",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("series_movies:"))
async def show_series_movies(callback: CallbackQuery):
    """Показати фільми в серії"""

    series_name = callback.data.split(":", 1)[1]

    # Адміни бачать всі фільми, включаючи приховані
    is_admin = callback.from_user.id in config.ADMIN_IDS
    movies = await get_movies_by_series_name(series_name, include_hidden=is_admin)

    if not movies:
        await callback.answer("❌ Фільми не знайдено", show_alert=True)
        return

    # Створюємо кнопки для фільмів в серії
    buttons = []
    for movie in movies:
        movie_id = str(movie["_id"])

        # Перевіряємо чи фільм переглянутий
        is_watched = await is_movie_watched(callback.from_user.id, movie_id)
        watched_emoji = "👁 " if is_watched else ""

        buttons.append([
            InlineKeyboardButton(
                text=f"{watched_emoji}🎬 {movie['title']} ({movie['year']}) ⭐️ {movie['imdb_rating']}",
                callback_data=f"m:{movie_id}"
            )
        ])

    # Додаємо кнопку "Назад"
    buttons.append([
        InlineKeyboardButton(text="◀️ Назад до каталогу", callback_data="catalog:movies")
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text(
        f"📁 <b>{series_name}</b>\n\n"
        f"Всього фільмів: {len(movies)}\n\n"
        "Виберіть фільм для перегляду:",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("catalog:series:new:"))
async def show_series_new(callback: CallbackQuery):
    """Показати новинки серіалів (2025 року)"""

    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[NEWSERIES] Викликано обробник новинок серіалів! callback_data: {callback.data}")

    # Отримуємо номер сторінки з callback_data
    parts = callback.data.split(":")
    page = int(parts[3]) if len(parts) > 3 else 0
    logger.info(f"[NEWSERIES] Сторінка: {page}")

    # Адміни бачать всі серіали, включаючи приховані
    is_admin = callback.from_user.id in config.ADMIN_IDS
    all_series = await get_all_series_list(include_hidden=is_admin)

    # Фільтруємо тільки серіали 2025 року
    new_series = [s for s in all_series if s.get('year') == 2025]
    logger.info(f"Серіалів 2025 року: {len(new_series)}")
    if new_series:
        logger.info(f"Назви новинок: {[s.get('title') for s in new_series]}")

    if not new_series:
        await callback.answer("❌ Новинок серіалів 2025 року поки немає", show_alert=True)
        return

    # Сортуємо за рейтингом IMDb (від найвищого до найнижчого)
    new_series.sort(key=lambda x: x.get('imdb_rating', 0), reverse=True)

    # Пагінація: 15 серіалів на сторінку
    ITEMS_PER_PAGE = 15
    total_pages = (len(new_series) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    page = max(0, min(page, total_pages - 1))

    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    series_page = new_series[start_idx:end_idx]

    # Створюємо кнопки
    buttons = []
    for show in series_page:
        series_id = str(show["_id"])
        buttons.append([
            InlineKeyboardButton(
                text=f"📺 {show['title']} ({show['year']}) ⭐️ {show['imdb_rating']}",
                callback_data=f"s:{series_id}"
            )
        ])

    # Кнопки навігації
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"catalog:series:new:{page-1}"
        ))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(
            text="Далі ▶️",
            callback_data=f"catalog:series:new:{page+1}"
        ))

    if nav_buttons:
        buttons.append(nav_buttons)

    # Додаємо кнопку "Назад до каталогу"
    buttons.append([
        InlineKeyboardButton(text="◀️ Назад до каталогу", callback_data="catalog:series")
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    page_info = f"\n<i>Сторінка {page + 1}/{total_pages}</i>" if total_pages > 1 else ""

    await callback.message.edit_text(
        f"🆕 <b>Новинки серіалів 2025:</b>\n\n"
        f"Всього серіалів: {len(new_series)}\n\n"
        f"Виберіть серіал для перегляду:{page_info}",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("catalog:series:top:"))
async def show_series_top(callback: CallbackQuery):
    """Показати топ серіалів за рейтингом IMDb"""

    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[TOPSERIES] Викликано обробник топ серіалів! callback_data: {callback.data}")

    # Отримуємо номер сторінки з callback_data
    parts = callback.data.split(":")
    page = int(parts[3]) if len(parts) > 3 else 0

    # Адміни бачать всі серіали, включаючи приховані
    is_admin = callback.from_user.id in config.ADMIN_IDS
    all_series = await get_all_series_list(include_hidden=is_admin)

    if not all_series:
        await callback.answer("❌ Немає серіалів", show_alert=True)
        return

    # Сортуємо за рейтингом IMDb (від найвищого до найнижчого)
    all_series.sort(key=lambda x: x.get('imdb_rating', 0), reverse=True)

    # Пагінація: 15 серіалів на сторінку
    ITEMS_PER_PAGE = 15
    total_pages = (len(all_series) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    page = max(0, min(page, total_pages - 1))

    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    series_page = all_series[start_idx:end_idx]

    # Створюємо кнопки
    buttons = []
    for show in series_page:
        series_id = str(show["_id"])
        buttons.append([
            InlineKeyboardButton(
                text=f"📺 {show['title']} ({show['year']}) ⭐️ {show['imdb_rating']}",
                callback_data=f"s:{series_id}"
            )
        ])

    # Кнопки навігації
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"catalog:series:top:{page-1}"
        ))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(
            text="Далі ▶️",
            callback_data=f"catalog:series:top:{page+1}"
        ))

    if nav_buttons:
        buttons.append(nav_buttons)

    # Додаємо кнопку "Назад до каталогу"
    buttons.append([
        InlineKeyboardButton(text="◀️ Назад до каталогу", callback_data="catalog:series")
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    page_info = f"\n<i>Сторінка {page + 1}/{total_pages}</i>" if total_pages > 1 else ""

    await callback.message.edit_text(
        f"🏆 <b>Топ серіалів за рейтингом IMDb:</b>\n\n"
        f"Всього серіалів: {len(all_series)}\n\n"
        f"Виберіть серіал для перегляду:{page_info}",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data == "catalog:series")
async def show_series(callback: CallbackQuery):
    """Показати список серіалів"""

    # Адміни бачать всі серіали, включаючи приховані
    is_admin = callback.from_user.id in config.ADMIN_IDS
    series = await get_all_series_list(include_hidden=is_admin)

    if not series:
        await callback.message.edit_text("📭 Поки що немає доданих серіалів.")
        await callback.answer()
        return

    # Підраховуємо кількість новинок (серіали 2025 року)
    new_series_2025 = [s for s in series if s.get('year') == 2025]
    new_series_count = len(new_series_2025)

    # Створюємо кнопки для кожного серіалу
    buttons = []

    # Додаємо кнопки "Новинки" і "Топ" на початку
    filter_buttons = []
    if new_series_count > 0:
        filter_buttons.append(
            InlineKeyboardButton(text=f"🆕 Новинки ({new_series_count})", callback_data="catalog:series:new:0")
        )
    filter_buttons.append(
        InlineKeyboardButton(text="🏆 Топ", callback_data="catalog:series:top:0")
    )

    # Вставляємо кнопки фільтрів на початок списку кнопок
    if filter_buttons:
        buttons.append(filter_buttons)

    for show in series:
        # В новій структурі використовуємо _id
        series_id = str(show["_id"])
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
async def show_seasons(callback: CallbackQuery, bot: Bot):
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
    seasons = await get_series_seasons(series_id)

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

    # Якщо це перший вхід (page == 0), відправляємо постер окремо, а кнопки в наступному повідомленні
    if page == 0:
        rating = series_info.get('rating', 0)
        views = series_info.get('views_count', 0)

        poster_caption = (
            f"📺 <b>{series_info['title']}</b>\n\n"
            f"📅 Рік: {series_info['year']}\n"
            f"⭐️ IMDB: {series_info['imdb_rating']}\n"
            f"⭐️ Рейтинг: {rating}\n"
            f"👁 Перегляди: {views}"
        )

        try:
            # Створюємо кнопки для постера з візуальною індикацією стану
            poster_buttons = await create_series_poster_buttons(series_id, callback.from_user.id)

            # Відправляємо постер з кнопками
            await bot.send_photo(
                chat_id=callback.from_user.id,
                photo=series_info['poster_file_id'],
                caption=poster_caption,
                reply_markup=poster_buttons
            )
            # Видаляємо старе повідомлення з каталогом
            await callback.message.delete()
            # Відправляємо окреме текстове повідомлення з кнопками
            await bot.send_message(
                chat_id=callback.from_user.id,
                text=f"Виберіть сезон:\n{page_info}" if page_info else "Виберіть сезон:",
                reply_markup=keyboard
            )
        except Exception as e:
            # Якщо не вдалося відправити постер - показуємо текстом
            await callback.message.edit_text(
                f"📺 <b>{title}</b>\n\n"
                f"Виберіть сезон:\n"
                f"{page_info}",
                reply_markup=keyboard
            )
    else:
        # Для інших сторінок просто редагуємо текст
        await callback.message.edit_text(
            f"Виберіть сезон:\n{page_info}" if page_info else "Виберіть сезон:",
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
        # В новій структурі передаємо series_id:season:episode
        buttons.append([
            InlineKeyboardButton(
                text=f"▶️ Серія {ep['episode']}",
                callback_data=f"e:{series_id}:{season}:{ep['episode']}"
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

    # Редагуємо текстове повідомлення
    text = f"Сезон {season}\n\nВиберіть серію:"
    if page_info:
        text += f"\n{page_info}"

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("e:"))
async def send_episode(callback: CallbackQuery, bot: Bot):
    """Відправити серію користувачу"""

    parts = callback.data.split(":")
    series_id = parts[1]
    season = int(parts[2])
    episode_num = int(parts[3])

    # Отримуємо серію
    episode = await get_episode(series_id, season, episode_num)

    if not episode:
        await callback.answer("❌ Серію не знайдено", show_alert=True)
        return

    # Отримуємо інформацію про серіал
    series_info = await get_movie_by_id(series_id)
    if not series_info:
        await callback.answer("❌ Серіал не знайдено", show_alert=True)
        return

    # Збільшуємо лічільник переглядів серіалу (не рахуємо адмінів)
    await increment_views(series_id, callback.from_user.id)

    # Додаємо в історію перегляду (зберігаємо епізод з інформацією про сезон)
    episode_data = {
        "title": series_info.get("title"),
        "content_type": "series",
        "season": episode["season"],
        "episode": episode["episode"]
    }
    await add_to_watch_history(callback.from_user.id, series_id, episode_data)

    # Формуємо підпис для відео
    caption = (
        f"📺 <b>{episode['series_title']}</b>\n"
        f"Сезон {episode['season']}, Серія {episode['episode']}\n\n"
        f"📺 <a href='https://t.me/multyky_ua_bot'>Мультики 🇺🇦 | Мультфільми Українською</a>"
    )

    # Відправляємо відео
    try:
        sent_message = await send_movie_video(bot, callback.from_user.id, episode, caption)

        # Шукаємо наступну серію
        current_season = episode['season']
        current_episode = episode['episode']

        # Перевіряємо чи є наступна серія в поточному сезоні
        next_episode = await get_episode(series_id, current_season, current_episode + 1)

        # Створюємо кнопку для наступної серії
        buttons = []
        if next_episode:
            # Є наступна серія в поточному сезоні
            buttons.append([
                InlineKeyboardButton(
                    text=f"▶️ Наступна серія {current_episode + 1}",
                    callback_data=f"e:{series_id}:{current_season}:{current_episode + 1}"
                )
            ])
        else:
            # Перевіряємо чи є наступний сезон
            all_seasons = await get_series_seasons(series_id)
            if current_season + 1 in all_seasons:
                # Перевіряємо чи є перша серія наступного сезону
                first_episode = await get_episode(series_id, current_season + 1, 1)
                if first_episode:
                    buttons.append([
                        InlineKeyboardButton(
                            text=f"▶️ Сезон {current_season + 1}, Серія 1",
                            callback_data=f"e:{series_id}:{current_season + 1}:1"
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
        import logging
        logger = logging.getLogger(__name__)

        # Базове логування
        logger.error(f"Не вдалося відправити '{series_info.get('title')}' S{season}E{episode_num}: {str(e)}")

        # Для адмінів відправляємо детальну інформацію
        if callback.from_user.id in config.ADMIN_IDS:
            error_msg = (
                f"❌ <b>Помилка при відправці відео</b>\n\n"
                f"📺 Серіал: <b>{series_info.get('title')}</b>\n"
                f"📹 Сезон {season}, Серія {episode_num}\n"
                f"🆔 ID: <code>{series_id}</code>\n"
                f"❗️ Помилка: {str(e)}\n\n"
                f"💡 <i>Видаліть і додайте серію знову через /admin</i>"
            )
            await bot.send_message(
                chat_id=callback.from_user.id,
                text=error_msg
            )
            await callback.answer("❌ Помилка! Деталі вище ⬆️")
        else:
            await callback.answer("❌ Помилка при відправці відео", show_alert=True)


@router.callback_query(F.data.startswith("m:"))
async def send_movie(callback: CallbackQuery, bot: Bot):
    """Відправити фільм користувачу"""

    movie_id = callback.data.split(":", 1)[1]

    # Отримуємо фільм за ID
    movie = await get_movie_by_id(movie_id)

    if not movie:
        await callback.answer("❌ Фільм не знайдено", show_alert=True)
        return

    # Збільшуємо лічільник переглядів (не рахуємо адмінів)
    await increment_views(movie_id, callback.from_user.id)

    # Додаємо в історію перегляду
    await add_to_watch_history(callback.from_user.id, movie_id, movie)

    # Відправляємо постер фільму з розширеною інформацією
    rating = movie.get('rating', 0)
    views = movie.get('views_count', 0)

    poster_caption = (
        f"🎬 <b>{movie['title']}</b>\n\n"
        f"📅 Рік: {movie['year']}\n"
        f"⭐️ IMDB: {movie['imdb_rating']}\n"
        f"⭐️ Рейтинг: {rating}\n"
        f"👁 Перегляди: {views}"
    )

    # Створюємо кнопки для постера
    poster_buttons = await create_content_poster_buttons(movie_id, callback.from_user.id)

    try:
        await bot.send_photo(
            chat_id=callback.from_user.id,
            photo=movie['poster_file_id'],
            caption=poster_caption,
            reply_markup=poster_buttons
        )
    except Exception as e:
        # Якщо не вдалося відправити постер - не критично, продовжуємо
        pass

    # Формуємо підпис для відео
    caption = (
        f"🎬 <b>{movie['title']}</b>\n\n"
        f"📺 <a href='https://t.me/multyky_ua_bot'>Мультики 🇺🇦 | Мультфільми Українською</a>"
    )

    # Перевіряємо чи фільм вже переглянутий
    is_watched = await is_movie_watched(callback.from_user.id, movie_id)

    # Створюємо кнопку "Переглянуто"
    watched_text = "✅ Переглянуто" if is_watched else "Відмітити 👁"
    video_buttons = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=watched_text,
                callback_data=f"watched:{movie_id}"
            )
        ]
    ])

    # Відправляємо відео з кнопкою
    try:
        video_file_id = movie.get("video_file_id")
        video_type = movie.get("video_type", "video")

        if video_type == "video":
            await bot.send_video(
                chat_id=callback.from_user.id,
                video=video_file_id,
                caption=caption,
                reply_markup=video_buttons
            )
        else:
            await bot.send_document(
                chat_id=callback.from_user.id,
                document=video_file_id,
                caption=caption,
                reply_markup=video_buttons
            )

        await callback.answer("✅ Приємного перегляду!")
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)

        # Базове логування
        logger.error(f"Не вдалося відправити '{movie.get('title')}': {str(e)}")

        # Для адмінів відправляємо детальну інформацію
        if callback.from_user.id in config.ADMIN_IDS:
            error_msg = (
                f"❌ <b>Помилка при відправці відео</b>\n\n"
                f"🎬 Фільм: <b>{movie.get('title')}</b>\n"
                f"🆔 ID: <code>{movie_id}</code>\n"
                f"❗️ Помилка: {str(e)}\n\n"
                f"💡 <i>Видаліть і додайте фільм знову через /admin</i>"
            )
            await bot.send_message(
                chat_id=callback.from_user.id,
                text=error_msg
            )
            await callback.answer("❌ Помилка! Деталі вище ⬆️")
        else:
            await callback.answer("❌ Помилка при відправці відео", show_alert=True)


@router.callback_query(F.data.startswith("like:"))
async def handle_like(callback: CallbackQuery):
    """Обробка лайка фільму або серіалу"""
    content_id = callback.data.split(":", 1)[1]

    # Перемикаємо лайк
    result = await toggle_like(content_id, callback.from_user.id)

    if not result:
        await callback.answer("❌ Помилка при обробці лайка", show_alert=True)
        return

    # Отримуємо оновлену інформацію про контент
    content_info = await get_movie_by_id(content_id)
    if not content_info:
        await callback.answer("❌ Контент не знайдено", show_alert=True)
        return

    rating = content_info.get('rating', 0)
    views = content_info.get('views_count', 0)
    content_type = content_info.get('content_type', 'movie')

    # Вибираємо смайлик залежно від типу
    emoji = "📺" if content_type == "series" else "🎬"

    # Оновлюємо caption постера
    new_caption = (
        f"{emoji} <b>{content_info['title']}</b>\n\n"
        f"📅 Рік: {content_info['year']}\n"
        f"⭐️ IMDB: {content_info['imdb_rating']}\n"
        f"⭐️ Рейтинг: {rating}\n"
        f"👁 Перегляди: {views}"
    )

    # Створюємо оновлені кнопки з візуальною індикацією
    poster_buttons = await create_content_poster_buttons(content_id, callback.from_user.id)

    # Оновлюємо постер
    try:
        await callback.message.edit_caption(
            caption=new_caption,
            reply_markup=poster_buttons
        )
    except Exception:
        pass  # Якщо caption не змінився, ігноруємо помилку

    # Показуємо повідомлення користувачу
    if result["action"] == "added":
        await callback.answer("👍 Вам сподобалось!")
    else:
        await callback.answer("Лайк видалено")


@router.callback_query(F.data.startswith("dislike:"))
async def handle_dislike(callback: CallbackQuery):
    """Обробка дизлайка фільму або серіалу"""
    content_id = callback.data.split(":", 1)[1]

    # Перемикаємо дизлайк
    result = await toggle_dislike(content_id, callback.from_user.id)

    if not result:
        await callback.answer("❌ Помилка при обробці дизлайка", show_alert=True)
        return

    # Отримуємо оновлену інформацію про контент
    content_info = await get_movie_by_id(content_id)
    if not content_info:
        await callback.answer("❌ Контент не знайдено", show_alert=True)
        return

    rating = content_info.get('rating', 0)
    views = content_info.get('views_count', 0)
    content_type = content_info.get('content_type', 'movie')

    # Вибираємо смайлик залежно від типу
    emoji = "📺" if content_type == "series" else "🎬"

    # Оновлюємо caption постера
    new_caption = (
        f"{emoji} <b>{content_info['title']}</b>\n\n"
        f"📅 Рік: {content_info['year']}\n"
        f"⭐️ IMDB: {content_info['imdb_rating']}\n"
        f"⭐️ Рейтинг: {rating}\n"
        f"👁 Перегляди: {views}"
    )

    # Створюємо оновлені кнопки з візуальною індикацією
    poster_buttons = await create_content_poster_buttons(content_id, callback.from_user.id)

    # Оновлюємо постер
    try:
        await callback.message.edit_caption(
            caption=new_caption,
            reply_markup=poster_buttons
        )
    except Exception:
        pass  # Якщо caption не змінився, ігноруємо помилку

    # Показуємо повідомлення користувачу
    if result["action"] == "added":
        await callback.answer("👎 Вам не сподобалось")
    else:
        await callback.answer("Дизлайк видалено")


@router.callback_query(F.data.startswith("watchlater:"))
async def handle_watch_later(callback: CallbackQuery):
    """Обробка додавання/видалення з черги перегляду"""
    series_id = callback.data.split(":", 1)[1]

    # Перевіряємо чи серіал вже в черзі
    in_queue = await is_in_watch_later(callback.from_user.id, series_id)

    if in_queue:
        # Видаляємо з черги
        await remove_from_watch_later(callback.from_user.id, series_id)
        await callback.answer("📌 Видалено з черги перегляду")
    else:
        # Додаємо в чергу
        await add_to_watch_later(callback.from_user.id, series_id)
        await callback.answer("📌 Додано в чергу перегляду!")

    # Оновлюємо кнопки щоб показати новий стан
    poster_buttons = await create_series_poster_buttons(series_id, callback.from_user.id)
    try:
        await callback.message.edit_reply_markup(reply_markup=poster_buttons)
    except Exception:
        pass  # Якщо кнопки не змінились, ігноруємо помилку


@router.callback_query(F.data.startswith("watched:"))
async def handle_watched(callback: CallbackQuery):
    """Обробка відмітки перегляду фільму"""
    movie_id = callback.data.split(":", 1)[1]

    # Перевіряємо чи фільм вже переглянутий
    is_watched = await is_movie_watched(callback.from_user.id, movie_id)

    if is_watched:
        # Знімаємо відмітку
        await unmark_movie_as_watched(callback.from_user.id, movie_id)
        await callback.answer("Відмітку перегляду знято")
        watched_text = "Відмітити 👁"
    else:
        # Відмічаємо як переглянутий
        await mark_movie_as_watched(callback.from_user.id, movie_id)
        await callback.answer("✅ Фільм відмічено як переглянутий!")
        watched_text = "✅ Переглянуто"

    # Оновлюємо кнопку щоб показати новий стан
    video_buttons = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=watched_text,
                callback_data=f"watched:{movie_id}"
            )
        ]
    ])

    try:
        await callback.message.edit_reply_markup(reply_markup=video_buttons)
    except Exception:
        pass  # Якщо кнопка не змінилась, ігноруємо помилку


@router.callback_query(F.data == "catalog:back")
async def back_to_catalog(callback: CallbackQuery):
    """Повернутися до головного меню каталогу"""

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎬 Мультфільми", callback_data="catalog:movies"),
            InlineKeyboardButton(text="📺 Мультсеріали", callback_data="catalog:series")
        ],
        [
            InlineKeyboardButton(text="🎌 Аніме", callback_data="catalog:anime")
        ]
    ])

    await callback.message.edit_text(
        "🎬 <b>Каталог</b>\n\n"
        "Виберіть категорію:",
        reply_markup=keyboard
    )
    await callback.answer()


# ===============================================
# АНІМЕ ОБРОБНИКИ
# ===============================================

@router.callback_query(F.data == "catalog:anime")
async def show_anime_categories(callback: CallbackQuery):
    """Показати підкатегорії аніме"""

    # Отримуємо кількість для відображення
    anime_movies_count = await get_anime_movies_only_count()
    anime_series_count = await get_anime_series_only_count()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"🎬 Аніме-фільми ({anime_movies_count})",
                callback_data="catalog:anime_movies"
            ),
            InlineKeyboardButton(
                text=f"📺 Аніме-серіали ({anime_series_count})",
                callback_data="catalog:anime_series"
            )
        ],
        [
            InlineKeyboardButton(text="◀️ Назад", callback_data="catalog:back")
        ]
    ])

    await callback.message.edit_text(
        "🎌 <b>Аніме</b>\n\n"
        "Виберіть категорію:",
        reply_markup=keyboard
    )
    await callback.answer()


# ===============================================
# АНІМЕ-ФІЛЬМИ
# ===============================================

@router.callback_query(F.data.startswith("catalog:anime_movies:new:"))
async def show_anime_movies_new(callback: CallbackQuery):
    """Показати новинки аніме-фільмів (2025 року)"""

    parts = callback.data.split(":")
    page = int(parts[3]) if len(parts) > 3 else 0

    is_admin = callback.from_user.id in config.ADMIN_IDS
    grouped_data = await get_grouped_anime_movies(include_hidden=is_admin)
    grouped = grouped_data["grouped"]
    standalone = grouped_data["standalone"]

    # Збираємо всі фільми
    all_movies = []
    for series_name, movies in grouped.items():
        all_movies.extend(movies)
    all_movies.extend(standalone)

    # Фільтруємо тільки фільми 2025 року
    new_movies = [m for m in all_movies if m.get('year') == 2025]

    if not new_movies:
        await callback.answer("❌ Новинок аніме 2025 року поки немає", show_alert=True)
        return

    # Сортуємо за рейтингом
    new_movies.sort(key=lambda x: x.get('imdb_rating', 0), reverse=True)

    ITEMS_PER_PAGE = 15
    total_pages = (len(new_movies) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    page = max(0, min(page, total_pages - 1))

    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    movies_page = new_movies[start_idx:end_idx]

    buttons = []
    for movie in movies_page:
        movie_id = str(movie["_id"])
        is_watched = await is_movie_watched(callback.from_user.id, movie_id)
        watched_emoji = "👁 " if is_watched else ""

        buttons.append([
            InlineKeyboardButton(
                text=f"{watched_emoji}🎌 {movie['title']} ({movie['year']}) ⭐️ {movie['imdb_rating']}",
                callback_data=f"am:{movie_id}"
            )
        ])

    # Кнопки навігації
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"catalog:anime_movies:new:{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="Далі ▶️", callback_data=f"catalog:anime_movies:new:{page+1}"))

    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([InlineKeyboardButton(text="◀️ Назад до аніме-фільмів", callback_data="catalog:anime_movies")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    page_info = f"\n<i>Сторінка {page + 1}/{total_pages}</i>" if total_pages > 1 else ""

    await callback.message.edit_text(
        f"🆕 <b>Новинки аніме 2025:</b>\n\n"
        f"Всього: {len(new_movies)}{page_info}",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("catalog:anime_movies:top:"))
async def show_anime_movies_top(callback: CallbackQuery):
    """Показати топ аніме-фільмів за рейтингом"""

    parts = callback.data.split(":")
    page = int(parts[3]) if len(parts) > 3 else 0

    is_admin = callback.from_user.id in config.ADMIN_IDS
    grouped_data = await get_grouped_anime_movies(include_hidden=is_admin)
    grouped = grouped_data["grouped"]
    standalone = grouped_data["standalone"]

    # Збираємо всі фільми
    all_movies = []
    for series_name, movies in grouped.items():
        all_movies.extend(movies)
    all_movies.extend(standalone)

    if not all_movies:
        await callback.answer("❌ Аніме-фільмів поки немає", show_alert=True)
        return

    # Сортуємо за рейтингом
    all_movies.sort(key=lambda x: x.get('imdb_rating', 0), reverse=True)

    ITEMS_PER_PAGE = 15
    total_pages = (len(all_movies) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    page = max(0, min(page, total_pages - 1))

    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    movies_page = all_movies[start_idx:end_idx]

    buttons = []
    for movie in movies_page:
        movie_id = str(movie["_id"])
        is_watched = await is_movie_watched(callback.from_user.id, movie_id)
        watched_emoji = "👁 " if is_watched else ""

        buttons.append([
            InlineKeyboardButton(
                text=f"{watched_emoji}🎌 {movie['title']} ({movie['year']}) ⭐️ {movie['imdb_rating']}",
                callback_data=f"am:{movie_id}"
            )
        ])

    # Кнопки навігації
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"catalog:anime_movies:top:{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="Далі ▶️", callback_data=f"catalog:anime_movies:top:{page+1}"))

    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([InlineKeyboardButton(text="◀️ Назад до аніме-фільмів", callback_data="catalog:anime_movies")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    page_info = f"\n<i>Сторінка {page + 1}/{total_pages}</i>" if total_pages > 1 else ""

    await callback.message.edit_text(
        f"🏆 <b>Топ аніме-фільмів:</b>\n\n"
        f"Всього: {len(all_movies)}{page_info}",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("catalog:anime_movies"))
async def show_anime_movies(callback: CallbackQuery):
    """Показати список аніме-фільмів"""

    parts = callback.data.split(":")
    page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0

    is_admin = callback.from_user.id in config.ADMIN_IDS
    grouped_data = await get_grouped_anime_movies(include_hidden=is_admin)
    grouped = grouped_data["grouped"]
    standalone = grouped_data["standalone"]

    # Формуємо список елементів (групи + окремі фільми)
    all_items = []

    for series_name in sorted(grouped.keys()):
        movies = grouped[series_name]
        count = len(movies)
        avg_rating = await calculate_series_average_rating(movies)
        all_items.append({
            "type": "series",
            "name": series_name,
            "count": count,
            "avg_rating": avg_rating
        })

    for movie in standalone:
        all_items.append({
            "type": "movie",
            "movie": movie
        })

    # Рахуємо новинки
    all_movies = []
    for series_name, movies in grouped.items():
        all_movies.extend(movies)
    all_movies.extend(standalone)
    new_movies_count = len([m for m in all_movies if m.get('year') == 2025])

    if not all_items:
        await callback.message.edit_text(
            "🎌 <b>Аніме-фільми</b>\n\n"
            "Поки що тут порожньо. Аніме-фільми скоро з'являться!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="catalog:anime")]
            ])
        )
        await callback.answer()
        return

    ITEMS_PER_PAGE = 15
    total_pages = (len(all_items) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    page = max(0, min(page, total_pages - 1))

    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    items_page = all_items[start_idx:end_idx]

    buttons = []

    # Фільтри на першій сторінці
    if page == 0:
        filter_buttons = []
        if new_movies_count > 0:
            filter_buttons.append(
                InlineKeyboardButton(text=f"🆕 Новинки ({new_movies_count})", callback_data="catalog:anime_movies:new:0")
            )
        filter_buttons.append(
            InlineKeyboardButton(text="🏆 Топ", callback_data="catalog:anime_movies:top:0")
        )
        if filter_buttons:
            buttons.append(filter_buttons)

    for item in items_page:
        if item["type"] == "series":
            buttons.append([
                InlineKeyboardButton(
                    text=f"📁 {item['name']} ({item['count']} фільмів) ⭐️ {item['avg_rating']}",
                    callback_data=f"anime_series_movies:{item['name']}"
                )
            ])
        else:
            movie = item["movie"]
            movie_id = str(movie["_id"])
            is_watched = await is_movie_watched(callback.from_user.id, movie_id)
            watched_emoji = "👁 " if is_watched else ""

            buttons.append([
                InlineKeyboardButton(
                    text=f"{watched_emoji}🎌 {movie['title']} ({movie['year']}) ⭐️ {movie['imdb_rating']}",
                    callback_data=f"am:{movie_id}"
                )
            ])

    # Кнопки навігації
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"catalog:anime_movies:{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="Далі ▶️", callback_data=f"catalog:anime_movies:{page+1}"))

    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([InlineKeyboardButton(text="◀️ Назад до аніме", callback_data="catalog:anime")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    page_info = f"\n<i>Сторінка {page + 1}/{total_pages}</i>" if total_pages > 1 else ""

    await callback.message.edit_text(
        f"🎌 <b>Аніме-фільми</b>\n\n"
        f"Всього: {len(all_movies)}{page_info}",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("anime_series_movies:"))
async def show_anime_series_movies(callback: CallbackQuery):
    """Показати фільми з серії аніме"""

    series_name = callback.data.split(":", 1)[1]
    is_admin = callback.from_user.id in config.ADMIN_IDS

    movies = await get_anime_movies_by_series_name(series_name, include_hidden=is_admin)

    if not movies:
        await callback.answer("❌ Фільми цієї серії не знайдено", show_alert=True)
        return

    buttons = []
    for movie in movies:
        movie_id = str(movie["_id"])
        is_watched = await is_movie_watched(callback.from_user.id, movie_id)
        watched_emoji = "👁 " if is_watched else ""

        buttons.append([
            InlineKeyboardButton(
                text=f"{watched_emoji}🎌 {movie['title']} ({movie['year']}) ⭐️ {movie['imdb_rating']}",
                callback_data=f"am:{movie_id}"
            )
        ])

    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="catalog:anime_movies")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    avg_rating = await calculate_series_average_rating(movies)

    await callback.message.edit_text(
        f"📁 <b>{series_name}</b>\n\n"
        f"Фільмів: {len(movies)}\n"
        f"Середній рейтинг: ⭐️ {avg_rating}",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("am:"))
async def send_anime_movie(callback: CallbackQuery, bot: Bot):
    """Відправити аніме-фільм користувачу"""

    movie_id = callback.data.split(":")[1]
    movie = await get_movie_by_id(movie_id)

    if not movie:
        await callback.answer("❌ Аніме-фільм не знайдено", show_alert=True)
        return

    await callback.answer("📤 Відправляю аніме...")

    # Збільшуємо лічильник переглядів
    await increment_views(movie_id, callback.from_user.id)

    # Додаємо в історію перегляду
    history_data = {
        "title": movie.get("title"),
        "content_type": "anime_movie"
    }
    await add_to_watch_history(callback.from_user.id, movie_id, history_data)

    # Відправляємо постер
    rating = movie.get('rating', 0)
    views = movie.get('views_count', 0)

    poster_caption = (
        f"🎌 <b>{movie['title']}</b>\n\n"
        f"📅 Рік: {movie['year']}\n"
        f"⭐️ IMDB: {movie['imdb_rating']}\n"
        f"⭐️ Рейтинг: {rating}\n"
        f"👁 Перегляди: {views}"
    )

    poster_buttons = await create_content_poster_buttons(movie_id, callback.from_user.id)

    try:
        await bot.send_photo(
            chat_id=callback.from_user.id,
            photo=movie['poster_file_id'],
            caption=poster_caption,
            reply_markup=poster_buttons
        )
    except Exception:
        pass

    # Формуємо підпис для відео
    caption = (
        f"🎌 <b>{movie['title']}</b>\n\n"
        f"📺 <a href='https://t.me/multyky_ua_bot'>Мультики | Мультфільми Українською</a>"
    )

    # Кнопка переглянуто
    watched = await is_movie_watched(callback.from_user.id, movie_id)
    watched_text = "✅ Переглянуто" if watched else "Відмітити 👁"
    video_buttons = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=watched_text, callback_data=f"watched:{movie_id}")]
    ])

    # Відправляємо відео
    try:
        video_file_id = movie.get("video_file_id")
        video_type = movie.get("video_type", "video")

        if not video_file_id:
            await bot.send_message(
                chat_id=callback.from_user.id,
                text=f"❌ Відео для '{movie.get('title')}' не знайдено"
            )
            return

        if video_type == "video":
            await bot.send_video(
                chat_id=callback.from_user.id,
                video=video_file_id,
                caption=caption,
                reply_markup=video_buttons
            )
        else:
            await bot.send_document(
                chat_id=callback.from_user.id,
                document=video_file_id,
                caption=caption,
                reply_markup=video_buttons
            )
    except Exception as e:
        import logging
        logging.error(f"Не вдалося відправити аніме '{movie.get('title')}': {str(e)}")
        await bot.send_message(
            chat_id=callback.from_user.id,
            text=f"❌ На жаль, не вдалося відправити '{movie.get('title')}'.\nСпробуй пізніше."
        )


# ===============================================
# АНІМЕ-СЕРІАЛИ
# ===============================================

@router.callback_query(F.data.startswith("catalog:anime_series:new:"))
async def show_anime_series_new(callback: CallbackQuery):
    """Показати новинки аніме-серіалів (2025 року)"""

    parts = callback.data.split(":")
    page = int(parts[3]) if len(parts) > 3 else 0

    is_admin = callback.from_user.id in config.ADMIN_IDS
    series = await get_all_anime_series_list(include_hidden=is_admin)

    new_series = [s for s in series if s.get('year') == 2025]

    if not new_series:
        await callback.answer("❌ Новинок аніме-серіалів 2025 року поки немає", show_alert=True)
        return

    new_series.sort(key=lambda x: x.get('imdb_rating', 0), reverse=True)

    ITEMS_PER_PAGE = 15
    total_pages = (len(new_series) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    page = max(0, min(page, total_pages - 1))

    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    series_page = new_series[start_idx:end_idx]

    buttons = []
    for show in series_page:
        series_id = str(show["_id"])
        buttons.append([
            InlineKeyboardButton(
                text=f"🎌 {show['title']} ({show['year']}) ⭐️ {show['imdb_rating']}",
                callback_data=f"as:{series_id}"
            )
        ])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"catalog:anime_series:new:{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="Далі ▶️", callback_data=f"catalog:anime_series:new:{page+1}"))

    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([InlineKeyboardButton(text="◀️ Назад до аніме-серіалів", callback_data="catalog:anime_series")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    page_info = f"\n<i>Сторінка {page + 1}/{total_pages}</i>" if total_pages > 1 else ""

    await callback.message.edit_text(
        f"🆕 <b>Новинки аніме-серіалів 2025:</b>\n\n"
        f"Всього: {len(new_series)}{page_info}",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("catalog:anime_series:top:"))
async def show_anime_series_top(callback: CallbackQuery):
    """Показати топ аніме-серіалів за рейтингом"""

    parts = callback.data.split(":")
    page = int(parts[3]) if len(parts) > 3 else 0

    is_admin = callback.from_user.id in config.ADMIN_IDS
    series = await get_all_anime_series_list(include_hidden=is_admin)

    if not series:
        await callback.answer("❌ Аніме-серіалів поки немає", show_alert=True)
        return

    series.sort(key=lambda x: x.get('imdb_rating', 0), reverse=True)

    ITEMS_PER_PAGE = 15
    total_pages = (len(series) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    page = max(0, min(page, total_pages - 1))

    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    series_page = series[start_idx:end_idx]

    buttons = []
    for show in series_page:
        series_id = str(show["_id"])
        buttons.append([
            InlineKeyboardButton(
                text=f"🎌 {show['title']} ({show['year']}) ⭐️ {show['imdb_rating']}",
                callback_data=f"as:{series_id}"
            )
        ])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"catalog:anime_series:top:{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="Далі ▶️", callback_data=f"catalog:anime_series:top:{page+1}"))

    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([InlineKeyboardButton(text="◀️ Назад до аніме-серіалів", callback_data="catalog:anime_series")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    page_info = f"\n<i>Сторінка {page + 1}/{total_pages}</i>" if total_pages > 1 else ""

    await callback.message.edit_text(
        f"🏆 <b>Топ аніме-серіалів:</b>\n\n"
        f"Всього: {len(series)}{page_info}",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("catalog:anime_series"))
async def show_anime_series(callback: CallbackQuery):
    """Показати список аніме-серіалів"""

    parts = callback.data.split(":")
    page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0

    is_admin = callback.from_user.id in config.ADMIN_IDS
    series = await get_all_anime_series_list(include_hidden=is_admin)

    new_series_count = len([s for s in series if s.get('year') == 2025])

    if not series:
        await callback.message.edit_text(
            "🎌 <b>Аніме-серіали</b>\n\n"
            "Поки що тут порожньо. Аніме-серіали скоро з'являться!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="catalog:anime")]
            ])
        )
        await callback.answer()
        return

    ITEMS_PER_PAGE = 15
    total_pages = (len(series) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    page = max(0, min(page, total_pages - 1))

    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    series_page = series[start_idx:end_idx]

    buttons = []

    # Фільтри на першій сторінці
    if page == 0:
        filter_buttons = []
        if new_series_count > 0:
            filter_buttons.append(
                InlineKeyboardButton(text=f"🆕 Новинки ({new_series_count})", callback_data="catalog:anime_series:new:0")
            )
        filter_buttons.append(
            InlineKeyboardButton(text="🏆 Топ", callback_data="catalog:anime_series:top:0")
        )
        if filter_buttons:
            buttons.append(filter_buttons)

    for show in series_page:
        series_id = str(show["_id"])
        buttons.append([
            InlineKeyboardButton(
                text=f"🎌 {show['title']} ({show['year']}) ⭐️ {show['imdb_rating']}",
                callback_data=f"as:{series_id}"
            )
        ])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"catalog:anime_series:{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="Далі ▶️", callback_data=f"catalog:anime_series:{page+1}"))

    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([InlineKeyboardButton(text="◀️ Назад до аніме", callback_data="catalog:anime")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    page_info = f"\n<i>Сторінка {page + 1}/{total_pages}</i>" if total_pages > 1 else ""

    await callback.message.edit_text(
        f"🎌 <b>Аніме-серіали</b>\n\n"
        f"Всього: {len(series)}{page_info}",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("as:"))
async def show_anime_seasons(callback: CallbackQuery, bot: Bot):
    """Показати сезони аніме-серіалу з пагінацією"""

    parts = callback.data.split(":")
    series_id = parts[1]
    page = int(parts[2]) if len(parts) > 2 else 0

    series_info = await get_movie_by_id(series_id)

    if not series_info:
        await callback.answer("❌ Аніме-серіал не знайдено", show_alert=True)
        return

    title = series_info["title"]
    seasons = await get_series_seasons(series_id)

    if not seasons:
        await callback.answer("❌ Не знайдено сезонів для цього серіалу", show_alert=True)
        return

    SEASONS_PER_PAGE = 5
    total_pages = (len(seasons) + SEASONS_PER_PAGE - 1) // SEASONS_PER_PAGE
    page = max(0, min(page, total_pages - 1))

    start_idx = page * SEASONS_PER_PAGE
    end_idx = start_idx + SEASONS_PER_PAGE
    seasons_page = seasons[start_idx:end_idx]

    buttons = []
    for season in seasons_page:
        buttons.append([
            InlineKeyboardButton(
                text=f"📺 Сезон {season}",
                callback_data=f"asn:{series_id}:{season}:0"
            )
        ])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"as:{series_id}:{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="Далі ▶️", callback_data=f"as:{series_id}:{page+1}"))

    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([InlineKeyboardButton(text="◀️ Назад до аніме-серіалів", callback_data="catalog:anime_series")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    page_info = f"Сторінка {page + 1}/{total_pages}" if total_pages > 1 else ""

    if page == 0:
        # На першій сторінці: спочатку постер, потім вибір сезонів
        rating = series_info.get('rating', 0)
        views = series_info.get('views_count', 0)

        poster_caption = (
            f"🎌 <b>{series_info['title']}</b>\n\n"
            f"📅 Рік: {series_info['year']}\n"
            f"⭐️ IMDB: {series_info['imdb_rating']}\n"
            f"⭐️ Рейтинг: {rating}\n"
            f"👁 Перегляди: {views}"
        )

        # Видаляємо попереднє повідомлення
        try:
            await callback.message.delete()
        except Exception:
            pass

        # Спочатку відправляємо постер
        try:
            poster_buttons = await create_content_poster_buttons(series_id, callback.from_user.id)
            await bot.send_photo(
                chat_id=callback.from_user.id,
                photo=series_info.get('poster_file_id'),
                caption=poster_caption,
                reply_markup=poster_buttons
            )
        except Exception:
            pass

        # Потім відправляємо вибір сезонів як нове повідомлення
        await bot.send_message(
            chat_id=callback.from_user.id,
            text=f"🎌 <b>{title}</b>\n\n"
                 f"Виберіть сезон: (Всього сезонів: {len(seasons)})\n{page_info}",
            reply_markup=keyboard
        )
    else:
        # На інших сторінках просто редагуємо повідомлення
        await callback.message.edit_text(
            f"🎌 <b>{title}</b>\n\n"
            f"Виберіть сезон: (Всього сезонів: {len(seasons)})\n{page_info}",
            reply_markup=keyboard
        )

    await callback.answer()


@router.callback_query(F.data.startswith("asn:"))
async def show_anime_episodes(callback: CallbackQuery):
    """Показати серії сезону аніме"""

    parts = callback.data.split(":")
    series_id = parts[1]
    season = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0

    series_info = await get_movie_by_id(series_id)

    if not series_info:
        await callback.answer("❌ Серіал не знайдено", show_alert=True)
        return

    title = series_info["title"]

    if "seasons" not in series_info or str(season) not in series_info["seasons"]:
        await callback.answer("❌ Сезон не знайдено", show_alert=True)
        return

    episodes = series_info["seasons"][str(season)]
    episode_numbers = sorted([int(ep) for ep in episodes.keys()])

    EPISODES_PER_PAGE = 10
    total_pages = (len(episode_numbers) + EPISODES_PER_PAGE - 1) // EPISODES_PER_PAGE
    page = max(0, min(page, total_pages - 1))

    start_idx = page * EPISODES_PER_PAGE
    end_idx = start_idx + EPISODES_PER_PAGE
    episodes_page = episode_numbers[start_idx:end_idx]

    buttons = []
    for ep_num in episodes_page:
        buttons.append([
            InlineKeyboardButton(
                text=f"▶️ Серія {ep_num}",
                callback_data=f"ae:{series_id}:{season}:{ep_num}"
            )
        ])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"asn:{series_id}:{season}:{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="Далі ▶️", callback_data=f"asn:{series_id}:{season}:{page+1}"))

    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([InlineKeyboardButton(text="◀️ Назад до сезонів", callback_data=f"as:{series_id}")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    page_info = f"\n<i>Сторінка {page + 1}/{total_pages}</i>" if total_pages > 1 else ""

    await callback.message.edit_text(
        f"🎌 <b>{title}</b>\n"
        f"📺 Сезон {season}\n\n"
        f"Виберіть серію: (Всього: {len(episode_numbers)}){page_info}",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ae:"))
async def send_anime_episode(callback: CallbackQuery, bot: Bot):
    """Відправити серію аніме"""

    parts = callback.data.split(":")
    series_id = parts[1]
    season = int(parts[2])
    episode = int(parts[3])

    episode_data = await get_episode(series_id, season, episode)

    if not episode_data:
        await callback.answer("❌ Серію не знайдено", show_alert=True)
        return

    await callback.answer("📤 Відправляю серію...")

    series_info = await get_movie_by_id(series_id)

    # Збільшуємо лічильник переглядів
    await increment_views(series_id, callback.from_user.id)

    # Додаємо в історію перегляду
    history_data = {
        "title": episode_data.get("series_title", ""),
        "content_type": "anime_series",
        "season": season,
        "episode": episode
    }
    import logging
    logging.info(f"Adding anime to history: {history_data}")
    await add_to_watch_history(callback.from_user.id, series_id, history_data)

    # Формуємо підпис
    caption = (
        f"🎌 <b>{episode_data.get('series_title', 'Аніме')}</b>\n"
        f"📺 Сезон {season} | Серія {episode}\n\n"
        f"📺 <a href='https://t.me/multyky_ua_bot'>Мультики | Мультфільми Українською</a>"
    )

    # Відправляємо відео
    try:
        video_file_id = episode_data.get("video_file_id")
        video_type = episode_data.get("video_type", "video")

        if not video_file_id:
            await callback.message.answer("❌ Відео для цієї серії не знайдено")
            return

        if video_type == "video":
            sent_message = await bot.send_video(
                chat_id=callback.from_user.id,
                video=video_file_id,
                caption=caption
            )
        else:
            sent_message = await bot.send_document(
                chat_id=callback.from_user.id,
                document=video_file_id,
                caption=caption
            )

        # Шукаємо наступну серію
        current_season = season
        current_episode = episode

        # Перевіряємо чи є наступна серія в поточному сезоні
        next_episode = await get_episode(series_id, current_season, current_episode + 1)

        # Створюємо кнопку для наступної серії
        buttons = []
        if next_episode:
            # Є наступна серія в поточному сезоні
            buttons.append([
                InlineKeyboardButton(
                    text=f"▶️ Наступна серія {current_episode + 1}",
                    callback_data=f"ae:{series_id}:{current_season}:{current_episode + 1}"
                )
            ])
        else:
            # Перевіряємо чи є наступний сезон
            all_seasons = await get_series_seasons(series_id)
            if current_season + 1 in all_seasons:
                # Перевіряємо чи є перша серія наступного сезону
                first_episode = await get_episode(series_id, current_season + 1, 1)
                if first_episode:
                    buttons.append([
                        InlineKeyboardButton(
                            text=f"▶️ Сезон {current_season + 1}, Серія 1",
                            callback_data=f"ae:{series_id}:{current_season + 1}:1"
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

    except Exception as e:
        import logging
        logging.error(f"Не вдалося відправити серію аніме: {str(e)}")
        await bot.send_message(
            chat_id=callback.from_user.id,
            text=f"❌ На жаль, не вдалося відправити серію.\nСпробуй пізніше."
        )
