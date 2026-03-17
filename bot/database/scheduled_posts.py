from datetime import datetime
from typing import Optional, List, Dict
from bson import ObjectId

from bot.database.mongodb import db


async def create_scheduled_post(
    caption: str,
    deep_link_url: str,
    scheduled_time: datetime,
    content_title: str,
    poster_file_id: Optional[str] = None,
) -> str:
    """Зберегти запланований пост в канал"""
    post_data = {
        "caption": caption,
        "deep_link_url": deep_link_url,
        "poster_file_id": poster_file_id,
        "scheduled_time": scheduled_time,
        "content_title": content_title,
        "status": "pending",  # pending | sent
        "created_at": datetime.utcnow(),
        "sent_at": None,
    }
    result = await db.scheduled_posts.insert_one(post_data)
    return str(result.inserted_id)


async def get_due_scheduled_posts() -> List[Dict]:
    """Отримати пости час яких вже настав"""
    now = datetime.utcnow()
    posts = await db.scheduled_posts.find({
        "status": "pending",
        "scheduled_time": {"$lte": now}
    }).to_list(length=100)
    return posts


async def get_all_scheduled_posts() -> List[Dict]:
    """Отримати всі заплановані пости (для відображення адміну)"""
    posts = await db.scheduled_posts.find(
        {"status": "pending"}
    ).sort("scheduled_time", 1).to_list(length=100)
    return posts


async def mark_post_as_sent(post_id: str) -> None:
    await db.scheduled_posts.update_one(
        {"_id": ObjectId(post_id)},
        {"$set": {"status": "sent", "sent_at": datetime.utcnow()}}
    )


async def delete_scheduled_post(post_id: str) -> bool:
    result = await db.scheduled_posts.delete_one({"_id": ObjectId(post_id)})
    return result.deleted_count > 0
