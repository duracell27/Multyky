import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import config
from bot.database import db
from bot.handlers import common_router, admin_router, catalog_router


async def main():
    """Головна функція для запуску бота"""

    # Налаштування логування
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Перевірка конфігурації
    config.validate()

    # Ініціалізація бота
    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()

    # Підключення роутерів
    dp.include_router(common_router)
    dp.include_router(admin_router)
    dp.include_router(catalog_router)

    # Підключення до бази даних
    await db.connect()

    try:
        logging.info("🤖 Бот запущено!")
        await dp.start_polling(bot)
    finally:
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
