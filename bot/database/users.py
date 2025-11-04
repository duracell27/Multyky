from datetime import datetime
from typing import Optional
from aiogram.types import User
from bot.database import db


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


async def get_or_create_user(user: User) -> dict:
    """Отримати користувача або створити нового якщо не існує"""
    existing_user = await get_user(user.id)

    if existing_user:
        # Оновлюємо час останньої активності
        await update_last_activity(user.id)
        return existing_user

    # Створюємо нового користувача
    return await create_user(user)


async def get_all_users() -> list:
    """Отримати всіх користувачів"""
    cursor = db.users.find()
    return await cursor.to_list(length=None)


async def get_users_count() -> int:
    """Отримати кількість користувачів"""
    return await db.users.count_documents({})


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
