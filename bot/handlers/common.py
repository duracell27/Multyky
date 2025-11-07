from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup

from bot.database.users import (
    get_or_create_user,
    get_users_count,
    get_active_users_count,
    get_watch_history,
    get_watch_later
)
from bot.database.movies import (
    get_movies_count,
    get_movie_by_id,
    get_movies_only_count,
    get_series_only_count,
    get_total_videos_count,
    get_total_views_count
)
from bot.config import config

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message):
    """Обробник команди /start - автоматично реєструє користувача"""

    # Автоматична реєстрація користувача
    user = await get_or_create_user(message.from_user)

    # Перевіряємо чи це новий користувач
    is_new_user = user.get("registered_at") == user.get("last_activity")

    if is_new_user:
        welcome_text = (
            f"👋 Привіт, <b>{message.from_user.first_name}</b>!\n\n"
            f"Ласкаво просимо до бота з мультиками! 🎬\n\n"
            f"Тут ти зможеш переглядати улюблені мультфільми та серіали.\n\n"
            f"📺 /catalog - переглянути каталог\n"
            f"📜 /menu - головне меню з усіма командами"
        )
    else:
        welcome_text = (
            f"👋 З поверненням, <b>{message.from_user.first_name}</b>!\n\n"
            f"Радий бачити тебе знову! 🎬\n\n"
            f"📺 /catalog - переглянути мультфільми\n"
            f"📜 /menu - головне меню"
        )

    await message.answer(welcome_text)


@router.message(Command("menu"))
async def cmd_menu(message: Message):
    """Обробник команди /menu - головне меню"""

    # Автоматично оновлюємо активність
    await get_or_create_user(message.from_user)

    # Перевіряємо чи користувач є адміністратором
    is_admin = message.from_user.id in config.ADMIN_IDS

    if is_admin:
        # Меню для адміністратора
        menu_text = (
            "👑 <b>Головне меню адміністратора</b>\n\n"
            "🎬 <b>Команди користувача:</b>\n"
            "/catalog - Каталог мультфільмів і серіалів\n"
            "/history - Історія переглядів\n"
            "/watchLater - Переглянути пізніше\n"
            "/menu - Показати це меню\n\n"
            "⚙️ <b>Команди адміністратора:</b>\n"
            "/addMovie - Додати мультфільм\n"
            "/addBatchMovie - Додати серіал\n"
            "/stats - Статистика бота\n"
            "/cancel - Скасувати поточну дію\n\n"
            "💡 <i>Приємної роботи!</i>"
        )
    else:
        # Меню для звичайного користувача
        menu_text = (
            "🎬 <b>Головне меню</b>\n\n"
            "📺 <b>Доступні команди:</b>\n\n"
            "/catalog - Каталог мультфільмів і серіалів\n"
            "/history - Історія переглядів\n"
            "/watchLater - Переглянути пізніше\n"
            "/menu - Показати це меню\n\n"
            "📝 <i>Приємного перегляду!</i>"
        )

    await message.answer(menu_text)


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    """Обробник команди /stats - тільки для адмінів"""

    # Перевірка чи користувач є адміністратором
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("⛔️ Ця команда доступна тільки для адміністраторів.")
        return

    # Отримуємо статистику
    users_count = await get_users_count()
    active_users_count = await get_active_users_count(days=7)
    movies_only_count = await get_movies_only_count()
    series_only_count = await get_series_only_count()
    total_videos_count = await get_total_videos_count()
    total_views_count = await get_total_views_count()

    stats_text = (
        "📊 <b>Статистика бота:</b>\n\n"
        "👥 <b>Користувачі:</b>\n"
        f"   • Всього: {users_count}\n"
        f"   • Активних (7 днів): {active_users_count}\n\n"
        "🎬 <b>Контент:</b>\n"
        f"   • Мультфільмів: {movies_only_count}\n"
        f"   • Мультсеріалів: {series_only_count}\n"
        f"   • Всього відео: {total_videos_count}\n\n"
        "📊 <b>Перегляди:</b>\n"
        f"   • Всього переглядів: {total_views_count}\n\n"
        f"<i>Статистика оновлюється в реальному часі</i>"
    )

    await message.answer(stats_text)


@router.message(Command("history"))
async def cmd_history(message: Message):
    """Обробник команди /history - показати історію переглядів"""

    # Автоматично оновлюємо активність
    await get_or_create_user(message.from_user)

    # Отримуємо історію переглядів
    history = await get_watch_history(message.from_user.id)

    if not history:
        await message.answer(
            "📭 <b>Історія переглядів порожня</b>\n\n"
            "Переглянь щось із /catalog і воно з'явиться тут!"
        )
        return

    # Формуємо кнопки для кожного перегляду (максимум 20 останніх)
    buttons = []
    for item in history[:20]:
        movie_id = item.get("movie_id")
        title = item.get("title", "Невідомо")
        content_type = item.get("content_type", "movie")

        # Формуємо текст кнопки
        if content_type == "series":
            season = item.get("season")
            episode = item.get("episode")

            # Перевіряємо що season і episode є числами
            if season is not None and episode is not None:
                button_text = f"📺 {title} S{season}E{episode}"
                callback_data = f"e:{movie_id}:{season}:{episode}"
            else:
                # Якщо немає інформації про епізод - відкриваємо серіал
                button_text = f"📺 {title}"
                callback_data = f"s:{movie_id}"
        else:
            button_text = f"🎬 {title}"
            callback_data = f"m:{movie_id}"

        buttons.append([
            InlineKeyboardButton(text=button_text, callback_data=callback_data)
        ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(
        "📜 <b>Історія переглядів</b>\n\n"
        f"Останні {len(buttons)} переглянутих:\n"
        "Натисни щоб переглянути знову 👇",
        reply_markup=keyboard
    )


@router.message(Command("watchLater"))
async def cmd_watch_later(message: Message):
    """Обробник команди /watchLater - показати чергу перегляду"""

    # Автоматично оновлюємо активність
    await get_or_create_user(message.from_user)

    # Отримуємо чергу перегляду
    watch_later_ids = await get_watch_later(message.from_user.id)

    if not watch_later_ids:
        await message.answer(
            "📭 <b>Черга перегляду порожня</b>\n\n"
            "Додай серіали з /catalog і вони з'являться тут!"
        )
        return

    # Формуємо кнопки для кожного серіалу
    buttons = []
    for series_id in watch_later_ids:
        # Отримуємо інформацію про серіал
        series_info = await get_movie_by_id(series_id)
        if not series_info:
            continue

        title = series_info.get("title", "Невідомо")

        # Створюємо кнопку з посиланням на серіал
        buttons.append([
            InlineKeyboardButton(
                text=f"📺 {title}",
                callback_data=f"s:{series_id}"
            )
        ])

    if not buttons:
        await message.answer(
            "📭 <b>Черга перегляду порожня</b>\n\n"
            "Додай серіали з /catalog і вони з'являться тут!"
        )
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(
        "📌 <b>Черга перегляду</b>\n\n"
        f"Збережено серіалів: {len(buttons)}\n"
        "Натисни щоб переглянути 👇",
        reply_markup=keyboard
    )
