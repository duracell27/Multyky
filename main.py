import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from bot.config import config
from bot.database import db
from bot.handlers import common_router, admin_router, catalog_router, broadcast_router
from bot.database.users import send_daily_registration_report
from bot.database.broadcasts import get_scheduled_broadcasts
from bot.handlers.broadcast import send_broadcast_to_users


async def check_and_send_scheduled_broadcasts(bot: Bot):
    """Перевірити і відправити заплановані розсилки"""
    broadcasts = await get_scheduled_broadcasts()

    for broadcast in broadcasts:
        broadcast_id = str(broadcast['_id'])
        try:
            logging.info(f"Відправка запланованої розсилки: {broadcast['title']}")
            await send_broadcast_to_users(bot, broadcast_id)
        except Exception as e:
            logging.error(f"Помилка при відправці розсилки {broadcast_id}: {e}")


async def main():
    """Головна функція для запуску бота"""

    # Налаштування логування
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Перевірка конфігурації
    config.validate()

    # Виводимо список адмінів для перевірки
    logging.info(f"👑 Admin IDs: {config.ADMIN_IDS}")

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
    dp.include_router(broadcast_router)

    # Підключення до бази даних
    await db.connect()

    # Налаштування scheduler для щоденних звітів
    scheduler = AsyncIOScheduler()

    # Додаємо завдання для щоденного звіту о 22:00 (за київським часом)
    from datetime import datetime
    import pytz

    kyiv_tz = pytz.timezone('Europe/Kiev')

    scheduler.add_job(
        send_daily_registration_report,
        trigger=CronTrigger(hour=22, minute=0, timezone=kyiv_tz),
        args=[bot],
        id='daily_registration_report',
        name='Щоденний звіт про нові реєстрації',
        replace_existing=True
    )

    # Додаємо завдання для перевірки запланованих розсилок (кожні 5 хвилин)
    scheduler.add_job(
        check_and_send_scheduled_broadcasts,
        trigger=CronTrigger(minute='*/5'),  # Кожні 5 хвилин
        args=[bot],
        id='check_scheduled_broadcasts',
        name='Перевірка запланованих розсилок',
        replace_existing=True
    )

    # Запускаємо scheduler
    scheduler.start()

    # Показуємо наступний запуск
    next_run = scheduler.get_job('daily_registration_report').next_run_time
    logging.info(f"⏰ Scheduler запущено. Щоденний звіт буде відправлятися о 22:00 (Europe/Kiev)")
    logging.info(f"⏰ Наступний запуск: {next_run.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    # Налаштування меню команд
    from aiogram.types import BotCommand

    # Команди для користувачів (адміністраторські команди доступні через /menu)
    commands = [
        BotCommand(command="start", description="Запустити бота"),
        BotCommand(command="catalog", description="Каталог мультфільмів"),
        BotCommand(command="search", description="Пошук мультфільмів"),
        BotCommand(command="history", description="Історія переглядів"),
        BotCommand(command="watchlater", description="Переглянути пізніше"),
        BotCommand(command="help", description="Допомога і зворотній зв'язок"),
        BotCommand(command="menu", description="Головне меню"),
    ]

    # Встановлюємо команди
    await bot.set_my_commands(commands)
    logging.info("✅ Меню команд налаштовано")

    try:
        logging.info("🤖 Бот запущено!")
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
