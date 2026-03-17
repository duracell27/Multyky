from datetime import datetime, timedelta
from typing import Optional
from aiogram import Bot
from aiogram.types import User
from bot.database import db
from bot.config import config
import logging


async def get_user(user_id: int) -> Optional[dict]:
    """Отримати користувача з бази даних"""
    return await db.users.find_one({"user_id": user_id})


async def create_user(user: User) -> dict:
    """Створити нового користувача"""
    user_data = {
        "user_id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "language_code": user.language_code,
        "is_bot": user.is_bot,
        "is_premium": user.is_premium or False,
        "registered_at": datetime.utcnow(),
        "last_activity": datetime.utcnow(),
        "favorites": [],
        "watch_history": [],
    }

    await db.users.insert_one(user_data)
    return user_data


async def update_last_activity(user_id: int):
    """Оновити час останньої активності користувача"""
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"last_activity": datetime.utcnow()}}
    )


async def notify_admins_about_new_user(bot: Bot, user: User):
    """Надіслати повідомлення адмінам про нового користувача"""
    username = f"@{user.username}" if user.username else "немає username"
    is_premium = "⭐️ Premium" if user.is_premium else ""

    message = (
        f"👤 <b>Новий користувач!</b>\n\n"
        f"ID: <code>{user.id}</code>\n"
        f"Ім'я: {user.first_name or 'немає'}"
    )

    if user.last_name:
        message += f" {user.last_name}"

    message += f"\nUsername: {username}\n"

    if is_premium:
        message += f"{is_premium}\n"

    message += f"Мова: {user.language_code or 'не вказано'}"

    # Надсилаємо повідомлення кожному адміну
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, message)
        except Exception as e:
            logging.error(f"Failed to send notification to admin {admin_id}: {e}")


async def get_or_create_user(user: User, bot: Optional[Bot] = None) -> dict:
    """Отримати користувача або створити нового якщо не існує"""
    existing_user = await get_user(user.id)

    if existing_user:
        # Оновлюємо час останньої активності
        await update_last_activity(user.id)
        return existing_user

    # Створюємо нового користувача
    new_user = await create_user(user)

    # Надсилаємо повідомлення адмінам про нову реєстрацію
    # ВИМКНЕНО: замість миттєвих сповіщень, тепер відправляємо щоденний звіт о 22:00
    # if bot:
    #     await notify_admins_about_new_user(bot, user)

    return new_user


async def get_all_users() -> list:
    """Отримати всіх користувачів"""
    cursor = db.users.find()
    return await cursor.to_list(length=None)


async def get_users_count() -> int:
    """Отримати кількість користувачів"""
    return await db.users.count_documents({})


async def get_active_users_count(days: int = 7) -> int:
    """Отримати кількість активних користувачів за останні N днів"""
    from datetime import datetime, timedelta

    # Вираховуємо дату N днів тому
    date_threshold = datetime.utcnow() - timedelta(days=days)

    # Підраховуємо користувачів, які були активні після цієї дати
    return await db.users.count_documents({
        "last_activity": {"$gte": date_threshold}
    })


async def update_last_series_added(user_id: int, series_title: str):
    """Оновити останній доданий серіал для адміна"""
    await db.users.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "last_series_added": series_title,
                "last_series_added_at": datetime.utcnow()
            }
        }
    )


async def get_last_series_added(user_id: int) -> str:
    """Отримати назву останнього доданого серіалу адміна"""
    user = await get_user(user_id)
    if user:
        return user.get("last_series_added")
    return None


async def add_to_watch_history(user_id: int, movie_id: str, movie_data: dict):
    """Додати мультфільм в історію перегляду"""
    watch_entry = {
        "movie_id": movie_id,
        "title": movie_data.get("title"),
        "content_type": movie_data.get("content_type", "movie"),
        "watched_at": datetime.utcnow()
    }

    # Додаємо сезон і серію якщо це серіал або аніме-серіал
    content_type = movie_data.get("content_type")
    if content_type in ("series", "anime_series"):
        watch_entry["season"] = movie_data.get("season")
        watch_entry["episode"] = movie_data.get("episode")

    # Додаємо в історію перегляду
    # $push додає в кінець масиву, $slice залишає тільки останні 50 записів
    await db.users.update_one(
        {"user_id": user_id},
        {
            "$push": {
                "watch_history": {
                    "$each": [watch_entry],
                    "$slice": -50  # Зберігаємо тільки останні 50 переглядів
                }
            }
        },
        upsert=True  # Створити користувача якщо не існує
    )


async def get_watch_history(user_id: int, limit: int = 50) -> list:
    """Отримати історію перегляду користувача (обмежено останніми 50)"""
    user = await get_user(user_id)
    if user and "watch_history" in user:
        # Повертаємо в зворотньому порядку (останні перегляди першими), максимум 50
        return list(reversed(user["watch_history"][-limit:]))
    return []


async def get_recent_views_all_users(limit: int = 5) -> list:
    """Отримати останні N переглядів по всіх користувачах"""
    pipeline = [
        {"$unwind": "$watch_history"},
        {"$sort": {"watch_history.watched_at": -1}},
        {"$limit": limit},
        {"$project": {
            "user_id": 1,
            "first_name": 1,
            "username": 1,
            "entry": "$watch_history"
        }}
    ]
    cursor = db.users.aggregate(pipeline)
    return await cursor.to_list(length=None)


async def add_to_watch_later(user_id: int, series_id: str) -> bool:
    """Додати серіал в чергу перегляду"""
    result = await db.users.update_one(
        {"user_id": user_id},
        {"$addToSet": {"watch_later": series_id}},  # $addToSet не додає дублікати
        upsert=True
    )
    return result.modified_count > 0 or result.upserted_id is not None


async def remove_from_watch_later(user_id: int, series_id: str) -> bool:
    """Видалити серіал з черги перегляду"""
    result = await db.users.update_one(
        {"user_id": user_id},
        {"$pull": {"watch_later": series_id}}
    )
    return result.modified_count > 0


async def get_watch_later(user_id: int, limit: int = 50) -> list:
    """Отримати чергу перегляду користувача (обмежено останніми 50)"""
    user = await get_user(user_id)
    if user and "watch_later" in user:
        # Повертаємо останні N записів (максимум 50)
        return user["watch_later"][-limit:]
    return []


async def is_in_watch_later(user_id: int, series_id: str) -> bool:
    """Перевірити чи серіал в черзі перегляду"""
    user = await get_user(user_id)
    if user and "watch_later" in user:
        return series_id in user["watch_later"]
    return False


async def mark_movie_as_watched(user_id: int, movie_id: str) -> bool:
    """Відмітити фільм як переглянутий"""
    result = await db.users.update_one(
        {"user_id": user_id},
        {"$addToSet": {"watched_movies": movie_id}},  # $addToSet не додає дублікати
        upsert=True
    )
    return result.modified_count > 0 or result.upserted_id is not None


async def unmark_movie_as_watched(user_id: int, movie_id: str) -> bool:
    """Зняти відмітку перегляду з фільму"""
    result = await db.users.update_one(
        {"user_id": user_id},
        {"$pull": {"watched_movies": movie_id}}
    )
    return result.modified_count > 0


async def is_movie_watched(user_id: int, movie_id: str) -> bool:
    """Перевірити чи фільм переглянутий"""
    user = await get_user(user_id)
    if user and "watched_movies" in user:
        return movie_id in user["watched_movies"]
    return False


async def get_watched_movies(user_id: int) -> list:
    """Отримати список переглянутих фільмів"""
    user = await get_user(user_id)
    if user and "watched_movies" in user:
        return user["watched_movies"]
    return []


async def get_new_users_count_for_date(date: datetime) -> int:
    """Отримати кількість нових користувачів за конкретну дату"""
    from datetime import timedelta

    # Визначаємо початок та кінець дня
    start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)

    # Підраховуємо користувачів, зареєстрованих в цей день
    count = await db.users.count_documents({
        "registered_at": {
            "$gte": start_of_day,
            "$lt": end_of_day
        }
    })

    return count


async def get_new_users_for_date(date: datetime) -> list:
    """Отримати список нових користувачів за конкретну дату"""
    from datetime import timedelta

    # Визначаємо початок та кінець дня
    start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)

    # Отримуємо користувачів, зареєстрованих в цей день
    cursor = db.users.find({
        "registered_at": {
            "$gte": start_of_day,
            "$lt": end_of_day
        }
    })

    return await cursor.to_list(length=None)


async def send_daily_registration_report(bot: Bot):
    """Відправити щоденний звіт про реєстрації адміністраторам"""
    from datetime import datetime, timedelta
    from bot.database.movies import get_total_views_count

    # Зберігаємо щоденну статистику
    await save_daily_stats()

    # Отримуємо вчорашню дату (звіт за попередній день)
    yesterday = datetime.utcnow() - timedelta(days=1)

    # Отримуємо кількість та список нових користувачів за вчора
    new_users_count = await get_new_users_count_for_date(yesterday)

    # Отримуємо статистику переглядів
    total_views = await get_total_views_count()
    views_today = await get_views_for_last_day()

    if new_users_count == 0:
        # Якщо немає нових користувачів, не відправляємо звіт
        # (або можна відправити повідомлення про те, що нових немає)
        message = (
            f"📊 <b>Щоденний звіт</b>\n\n"
            f"📅 Дата: {yesterday.strftime('%d.%m.%Y')}\n\n"
            f"👥 Нових користувачів: <b>0</b>\n"
            f"<i>Вчора не було нових реєстрацій</i>\n\n"
            f"👁 <b>Перегляди:</b>\n"
            f"   • За останній день: <b>{views_today}</b>\n"
            f"   • Всього: <b>{total_views}</b>"
        )
    else:
        # Отримуємо детальний список нових користувачів
        new_users = await get_new_users_for_date(yesterday)

        message = (
            f"📊 <b>Щоденний звіт</b>\n\n"
            f"📅 Дата: {yesterday.strftime('%d.%m.%Y')}\n\n"
            f"👥 Нових користувачів: <b>{new_users_count}</b>\n\n"
            f"👁 <b>Перегляди:</b>\n"
            f"   • За останній день: <b>{views_today}</b>\n"
            f"   • Всього: <b>{total_views}</b>\n\n"
        )

        # Додаємо інформацію про кожного нового користувача (максимум 20)
        if new_users_count <= 20:
            message += "<b>Список нових користувачів:</b>\n\n"
            for i, user in enumerate(new_users, 1):
                username = f"@{user.get('username')}" if user.get('username') else "немає username"
                first_name = user.get('first_name', 'немає')
                user_id = user.get('user_id')
                is_premium = "⭐️" if user.get('is_premium') else ""

                message += f"{i}. {first_name} {is_premium}\n"
                message += f"   ID: <code>{user_id}</code>\n"
                message += f"   Username: {username}\n\n"
        else:
            message += f"<i>Показано перші 20 з {new_users_count} користувачів:</i>\n\n"
            for i, user in enumerate(new_users[:20], 1):
                username = f"@{user.get('username')}" if user.get('username') else "немає username"
                first_name = user.get('first_name', 'немає')
                user_id = user.get('user_id')
                is_premium = "⭐️" if user.get('is_premium') else ""

                message += f"{i}. {first_name} {is_premium}\n"
                message += f"   ID: <code>{user_id}</code>\n"
                message += f"   Username: {username}\n\n"

    # Надсилаємо звіт всім адміністраторам
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, message)
        except Exception as e:
            logging.error(f"Failed to send daily report to admin {admin_id}: {e}")


# ===============================================
# Щоденна статистика
# ===============================================

async def save_daily_stats():
    """Зберегти щоденну статистику"""
    from bot.database.movies import get_total_views_count

    # Отримуємо поточну статистику
    total_users = await get_users_count()
    total_views = await get_total_views_count()

    # Зберігаємо в базу
    stats_data = {
        "date": datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0),
        "users_count": total_users,
        "views_count": total_views,
        "created_at": datetime.utcnow()
    }

    # Використовуємо upsert щоб не дублювати записи за один день
    await db.daily_stats.update_one(
        {"date": stats_data["date"]},
        {"$set": stats_data},
        upsert=True
    )

    logging.info(f"Daily stats saved: {total_users} users, {total_views} views")


async def get_yesterday_stats() -> Optional[dict]:
    """Отримати статистику за вчора"""
    yesterday = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    return await db.daily_stats.find_one({"date": yesterday})


async def get_views_for_last_day() -> int:
    """Отримати кількість переглядів за останній день"""
    from bot.database.movies import get_total_views_count

    # Отримуємо поточну кількість переглядів
    current_views = await get_total_views_count()

    # Отримуємо вчорашню статистику
    yesterday_stats = await get_yesterday_stats()

    if yesterday_stats:
        yesterday_views = yesterday_stats.get("views_count", 0)
        return current_views - yesterday_views

    # Якщо немає даних за вчора - повертаємо загальну кількість
    return current_views
