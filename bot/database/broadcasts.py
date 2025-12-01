from datetime import datetime
from typing import Optional, List, Dict
from bson import ObjectId

from bot.database.mongodb import db


async def create_broadcast(
    title: str,
    description: str,
    photo_file_id: Optional[str] = None,
    content_ids: Optional[List[str]] = None,
    scheduled_time: Optional[datetime] = None
) -> str:
    """
    Створити нову розсилку

    Args:
        title: Заголовок розсилки
        description: Опис розсилки
        photo_file_id: ID фото з Telegram
        content_ids: Список ID фільмів/серіалів для прикріплення
        scheduled_time: Час для автоматичної відправки (опціонально)

    Returns:
        ID створеної розсилки
    """
    broadcast_data = {
        "title": title,
        "description": description,
        "photo_file_id": photo_file_id,
        "content_ids": content_ids or [],
        "scheduled_time": scheduled_time,
        "status": "draft",  # draft, scheduled, sent, cancelled
        "created_at": datetime.utcnow(),
        "sent_at": None,
        "stats": {
            "total_users": 0,
            "sent_success": 0,
            "sent_failed": 0
        }
    }

    result = await db.broadcasts.insert_one(broadcast_data)
    return str(result.inserted_id)


async def get_broadcast(broadcast_id: str) -> Optional[Dict]:
    """Отримати розсилку за ID"""
    broadcast = await db.broadcasts.find_one({"_id": ObjectId(broadcast_id)})
    return broadcast


async def get_all_broadcasts(status: Optional[str] = None) -> List[Dict]:
    """
    Отримати всі розсилки

    Args:
        status: Фільтр за статусом (draft, scheduled, sent, cancelled)
    """
    query = {}
    if status:
        query["status"] = status

    broadcasts = await db.broadcasts.find(query).sort("created_at", -1).to_list(length=100)
    return broadcasts


async def update_broadcast(
    broadcast_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    photo_file_id: Optional[str] = None,
    content_ids: Optional[List[str]] = None,
    scheduled_time: Optional[datetime] = None
) -> bool:
    """Оновити розсилку"""
    update_data = {}

    if title is not None:
        update_data["title"] = title
    if description is not None:
        update_data["description"] = description
    if photo_file_id is not None:
        update_data["photo_file_id"] = photo_file_id
    if content_ids is not None:
        update_data["content_ids"] = content_ids
    if scheduled_time is not None:
        update_data["scheduled_time"] = scheduled_time

    if not update_data:
        return False

    result = await db.broadcasts.update_one(
        {"_id": ObjectId(broadcast_id)},
        {"$set": update_data}
    )

    return result.modified_count > 0


async def update_broadcast_status(broadcast_id: str, status: str) -> bool:
    """Оновити статус розсилки"""
    result = await db.broadcasts.update_one(
        {"_id": ObjectId(broadcast_id)},
        {"$set": {"status": status}}
    )
    return result.modified_count > 0


async def mark_broadcast_as_sent(broadcast_id: str, stats: Dict) -> bool:
    """Позначити розсилку як відправлену з статистикою"""
    result = await db.broadcasts.update_one(
        {"_id": ObjectId(broadcast_id)},
        {
            "$set": {
                "status": "sent",
                "sent_at": datetime.utcnow(),
                "stats": stats
            }
        }
    )
    return result.modified_count > 0


async def delete_broadcast(broadcast_id: str) -> bool:
    """Видалити розсилку"""
    result = await db.broadcasts.delete_one({"_id": ObjectId(broadcast_id)})
    return result.deleted_count > 0


async def get_scheduled_broadcasts() -> List[Dict]:
    """Отримати всі заплановані розсилки"""
    now = datetime.utcnow()
    broadcasts = await db.broadcasts.find({
        "status": "scheduled",
        "scheduled_time": {"$lte": now}
    }).to_list(length=100)

    return broadcasts
