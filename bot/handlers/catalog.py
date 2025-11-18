from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext

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
    get_movies_by_series_name
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
        ]
    ])

    await message.answer(
        "🎬 <b>Каталог мультфільмів</b>\n\n"
        "Виберіть категорію:",
        reply_markup=keyboard
    )


@router.callback_query(F.data == "catalog:movies")
async def show_movies(callback: CallbackQuery):
    """Показати список фільмів (згруповані за серіями)"""

    grouped_data = await get_grouped_movies()
    grouped = grouped_data["grouped"]
    standalone = grouped_data["standalone"]

    if not grouped and not standalone:
        await callback.message.edit_text("📭 Поки що немає доданих мультфільмів.")
        await callback.answer()
        return

    # Створюємо кнопки
    buttons = []

    # Спочатку показуємо групи (серії фільмів)
    for series_name in sorted(grouped.keys()):
        movies_in_series = grouped[series_name]
        count = len(movies_in_series)

        buttons.append([
            InlineKeyboardButton(
                text=f"📁 {series_name} ({count} {'фільм' if count == 1 else 'фільми' if count < 5 else 'фільмів'})",
                callback_data=f"series_movies:{series_name}"
            )
        ])

    # Потім окремі фільми
    for movie in standalone:
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
        InlineKeyboardButton(text="◀️ Назад", callback_data="catalog:back")
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text(
        "🎬 <b>Мультфільми:</b>\n\n"
        "Виберіть серію або фільм для перегляду:",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("series_movies:"))
async def show_series_movies(callback: CallbackQuery):
    """Показати фільми в серії"""

    series_name = callback.data.split(":", 1)[1]

    movies = await get_movies_by_series_name(series_name)

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

    # Збільшуємо лічільник переглядів серіалу
    await increment_views(series_id)

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
        await callback.answer(f"❌ Помилка при відправці відео: {str(e)}", show_alert=True)


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
        ]
    ])

    await callback.message.edit_text(
        "🎬 <b>Каталог мультфільмів</b>\n\n"
        "Виберіть категорію:",
        reply_markup=keyboard
    )
    await callback.answer()
