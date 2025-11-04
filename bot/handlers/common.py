from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

from bot.database.users import get_or_create_user, get_users_count
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
            f"Тут ти зможеш переглядати улюблені мультфільми.\n\n"
            f"Використовуй /help щоб дізнатися більше про можливості бота."
        )
    else:
        welcome_text = (
            f"👋 З поверненням, <b>{message.from_user.first_name}</b>!\n\n"
            f"Радий бачити тебе знову! 🎬\n\n"
            f"Використовуй /help щоб дізнатися про команди."
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
        "/help - Показати це повідомлення\n"
        "/stats - Статистика бота (тільки для адмінів)\n\n"
        "📝 <i>Більше функцій з'явиться скоро!</i>"
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

    stats_text = (
        "📊 <b>Статистика бота:</b>\n\n"
        f"👥 Користувачів: {users_count}\n"
        f"🎬 Відео: 0\n\n"
        f"<i>Статистика оновлюється в реальному часі</i>"
    )

    await message.answer(stats_text)
