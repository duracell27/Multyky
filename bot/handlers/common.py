from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

from bot.database.users import get_or_create_user, get_users_count
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
            f"📺 Використовуй /catalog щоб переглянути каталог\n"
            f"ℹ️ Або /help щоб дізнатися більше про можливості бота."
        )
    else:
        welcome_text = (
            f"👋 З поверненням, <b>{message.from_user.first_name}</b>!\n\n"
            f"Радий бачити тебе знову! 🎬\n\n"
            f"📺 /catalog - переглянути мультфільми\n"
            f"ℹ️ /help - список команд"
        )

    await message.answer(welcome_text)


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Обробник команди /help"""

    # Автоматично оновлюємо активність
    await get_or_create_user(message.from_user)

    help_text = (
        "🎬 <b>Доступні команди:</b>\n\n"
        "/start - Почати роботу з ботом\n"
        "/catalog - Каталог мультфільмів і серіалів\n"
        "/help - Показати це повідомлення\n"
        "/stats - Статистика бота (тільки для адмінів)\n\n"
        "📝 <i>Приємного перегляду!</i>"
    )

    # Додаємо команди для адмінів
    if message.from_user.id in config.ADMIN_IDS:
        help_text += (
            "\n\n👑 <b>Команди адміністратора:</b>\n\n"
            "/addMovie - Додати новий мультфільм\n"
            "/cancel - Скасувати поточну дію"
        )

    await message.answer(help_text)


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
