from datetime import datetime
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
    if bot:
        await notify_admins_about_new_user(bot, user)

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

    # Додаємо сезон і серію якщо це серіал
    if movie_data.get("content_type") == "series":
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


async def get_watch_history(user_id: int) -> list:
    """Отримати історію перегляду користувача"""
    user = await get_user(user_id)
    if user and "watch_history" in user:
        # Повертаємо в зворотньому порядку (останні перегляди першими)
        return list(reversed(user["watch_history"]))
    return []


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


async def get_watch_later(user_id: int) -> list:
    """Отримати чергу перегляду користувача"""
    user = await get_user(user_id)
    if user and "watch_later" in user:
        return user["watch_later"]
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
