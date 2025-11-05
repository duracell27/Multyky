from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup

from bot.database.users import get_or_create_user, get_users_count, get_watch_history
from bot.database.movies import get_movies_count
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
            "/menu - Показати це меню\n\n"
            "⚙️ <b>Команди адміністратора:</b>\n"
            "/addMovie - Додати новий мультфільм або серіал\n"
            "/addBatchMovie - Пакетне додавання серій (5-20 серій)\n"
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
    movies_count = await get_movies_count()

    stats_text = (
        "📊 <b>Статистика бота:</b>\n\n"
        f"👥 Користувачів: {users_count}\n"
        f"🎬 Мультфільмів: {movies_count}\n\n"
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
            season = item.get("season", "?")
            episode = item.get("episode", "?")
            button_text = f"📺 {title} S{season}E{episode}"
            callback_data = f"e:{movie_id}"
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
