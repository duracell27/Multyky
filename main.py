import asyncio
import logging
import subprocess
import time
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from bot.config import config
from bot.database import db
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from bot.handlers import common_router, admin_router, catalog_router, broadcast_router, auto_download_router
from bot.database.users import send_daily_registration_report
from bot.database.broadcasts import get_scheduled_broadcasts
from bot.handlers.broadcast import send_broadcast_to_users
from bot.database.scheduled_posts import get_due_scheduled_posts, mark_post_as_sent
from bot.handlers.admin import _send_post_to_channel


async def check_and_send_scheduled_posts(bot: Bot):
    """Перевірити і відправити заплановані пости в канал"""
    posts = await get_due_scheduled_posts()
    for post in posts:
        post_id = str(post["_id"])
        try:
            await _send_post_to_channel(
                bot,
                caption=post["caption"],
                deep_link_url=post["deep_link_url"],
                poster_file_id=post.get("poster_file_id"),
            )
            await mark_post_as_sent(post_id)
            logging.info(f"Запланований пост відправлено: {post.get('content_title')}")
        except Exception as e:
            logging.error(f"Помилка відправки запланованого посту {post_id}: {e}")


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


async def resume_unfinished_jobs(bot: Bot):
    """On startup, notify admins about unfinished download jobs."""
    from bot.database.auto_download_jobs import get_running_jobs, set_job_status

    running = await get_running_jobs()
    for job in running:
        job_id = str(job["_id"])
        admin_id = job["admin_id"]
        ep = job["current_episode"]
        total = job["total_episodes"]
        title = job["series_title"]

        buttons = [[
            InlineKeyboardButton(
                text="▶️ Продовжити",
                callback_data=f"ad_resume:{job_id}"
            ),
            InlineKeyboardButton(
                text="❌ Скасувати",
                callback_data=f"ad_resume_cancel:{job_id}"
            ),
        ]]
        try:
            await bot.send_message(
                admin_id,
                f"⚠️ Знайдено незакінчене завантаження:\n\n"
                f"📺 {title}, сезон {job['season']}\n"
                f"Прогрес: {ep}/{total} серій\n\n"
                f"Продовжити?",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
            )
            await set_job_status(job_id, "paused")
        except Exception as e:
            logging.error(f"Could not notify admin {admin_id} about job {job_id}: {e}")


def start_local_bot_api() -> subprocess.Popen:
    """Запускає Telegram Bot API Local Server як дочірній процес."""
    proc = subprocess.Popen(
        [
            "/Users/Apple/telegram-bot-api/build/telegram-bot-api",
            f"--api-id={config.TELEGRAM_API_ID}",
            f"--api-hash={config.TELEGRAM_API_HASH}",
            "--local",
            "--log=/tmp/telegram-bot-api.log",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(3)  # чекаємо поки сервер підніметься
    logging.info("✅ Telegram Bot API Local Server запущено (pid=%d)", proc.pid)
    return proc


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

    # Запускаємо локальний Bot API сервер
    local_api_proc = start_local_bot_api()

    # Ініціалізація бота через локальний сервер (знімає ліміт 50MB)
    session = AiohttpSession(
        api=TelegramAPIServer.from_base("http://localhost:8081", is_local=True)
    )
    bot = Bot(
        token=config.BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()

    # Підключення роутерів
    dp.include_router(common_router)
    dp.include_router(admin_router)
    dp.include_router(catalog_router)
    dp.include_router(broadcast_router)
    dp.include_router(auto_download_router)

    # Підключення до бази даних
    await db.connect()
    await resume_unfinished_jobs(bot)

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
        trigger=CronTrigger(minute='*/5'),
        args=[bot],
        id='check_scheduled_broadcasts',
        name='Перевірка запланованих розсилок',
        replace_existing=True
    )

    # Перевірка запланованих постів в канал (кожну хвилину)
    scheduler.add_job(
        check_and_send_scheduled_posts,
        trigger=CronTrigger(minute='*'),
        args=[bot],
        id='check_scheduled_posts',
        name='Перевірка запланованих постів в канал',
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
        local_api_proc.terminate()
        logging.info("✅ Telegram Bot API Local Server зупинено")


if __name__ == "__main__":
    asyncio.run(main())
