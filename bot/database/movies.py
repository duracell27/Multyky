from datetime import datetime, timezone
from typing import Optional
from bot.database import db


async def create_movie(
    title: str,
    title_en: str,
    year: int,
    imdb_rating: float,
    video_file_id: str,
    video_type: str,
    added_by: int,
    content_type: str = "movie",
    season: int = None,
    episode: int = None
) -> dict:
    """
    Створити новий мультфільм або серію серіалу

    Args:
        content_type: "movie" (фільм) або "series" (серіал)
        season: номер сезону (тільки для серіалів)
        episode: номер серії (тільки для серіалів)
    """
    movie_data = {
        "title": title,
        "title_en": title_en,
        "year": year,
        "imdb_rating": imdb_rating,
        "rating": 0,  # Рейтинг по замовчуванню
        "video_file_id": video_file_id,
        "video_type": video_type,  # "video" або "document"
        "content_type": content_type,  # "movie" або "series"
        "added_by": added_by,
        "added_at": datetime.now(timezone.utc),
        "views_count": 0,
        "ratings": [],  # Масив рейтингів від користувачів
    }

    # Додаємо інформацію про сезон і серію для серіалів
    if content_type == "series":
        movie_data["season"] = season
        movie_data["episode"] = episode

    result = await db.videos.insert_one(movie_data)
    movie_data["_id"] = result.inserted_id
    return movie_data


async def get_movie_by_id(movie_id: str) -> Optional[dict]:
    """Отримати мультфільм за ID"""
    from bson import ObjectId
    return await db.videos.find_one({"_id": ObjectId(movie_id)})


async def get_movie_by_title(title: str) -> Optional[dict]:
    """Отримати мультфільм за назвою"""
    return await db.videos.find_one({"title": title})


async def get_all_movies() -> list:
    """Отримати всі мультфільми"""
    cursor = db.videos.find()
    return await cursor.to_list(length=None)


async def get_movies_count() -> int:
    """Отримати кількість мультфільмів"""
    return await db.videos.count_documents({})


async def get_series_episodes(title: str, season: int = None) -> list:
    """
    Отримати серії серіалу

    Args:
        title: назва серіалу
        season: номер сезону (опціонально, якщо не вказано - всі сезони)
    """
    query = {"title": title, "content_type": "series"}
    if season is not None:
        query["season"] = season

    cursor = db.videos.find(query).sort([("season", 1), ("episode", 1)])
    return await cursor.to_list(length=None)


async def get_series_seasons(title: str) -> list:
    """Отримати список сезонів серіалу"""
    pipeline = [
        {"$match": {"title": title, "content_type": "series"}},
        {"$group": {"_id": "$season"}},
        {"$sort": {"_id": 1}}
    ]
    result = await db.videos.aggregate(pipeline).to_list(length=None)
    return [item["_id"] for item in result]


async def get_all_movies_list() -> list:
    """Отримати список всіх фільмів"""
    cursor = db.videos.find({"content_type": "movie"}).sort("title", 1)
    return await cursor.to_list(length=None)


async def get_all_series_list() -> list:
    """
    Отримати список всіх серіалів (унікальні назви)
    Повертає тільки унікальні назви серіалів, без дублювання для кожної серії
    """
    pipeline = [
        {"$match": {"content_type": "series"}},
        {
            "$group": {
                "_id": "$title",
                "doc_id": {"$first": "$_id"},  # Зберігаємо ID першого документа
                "title": {"$first": "$title"},
                "title_en": {"$first": "$title_en"},
                "year": {"$first": "$year"},
                "imdb_rating": {"$first": "$imdb_rating"},
                "rating": {"$first": "$rating"},
            }
        },
        {"$sort": {"title": 1}}
    ]
    return await db.videos.aggregate(pipeline).to_list(length=None)


async def get_episode(title: str, season: int, episode: int) -> Optional[dict]:
    """Отримати конкретну серію"""
    return await db.videos.find_one({
        "title": title,
        "content_type": "series",
        "season": season,
        "episode": episode
    })


async def get_series_info_by_title(title: str) -> Optional[dict]:
    """Отримати інформацію про серіал за назвою"""
    return await db.videos.find_one({"title": title, "content_type": "series"})


async def search_movies(query: str) -> list:
    """Пошук мультфільмів за назвою"""
    cursor = db.videos.find({
        "$or": [
            {"title": {"$regex": query, "$options": "i"}},
            {"title_en": {"$regex": query, "$options": "i"}}
        ]
    })
    return await cursor.to_list(length=None)


async def increment_views(movie_id: str):
    """Збільшити лічильник переглядів"""
    from bson import ObjectId
    await db.videos.update_one(
        {"_id": ObjectId(movie_id)},
        {"$inc": {"views_count": 1}}
    )


async def update_movie_rating(movie_id: str, user_id: int, rating: int):
    """Оновити рейтинг мультфільма від користувача"""
    from bson import ObjectId

    # Додаємо або оновлюємо рейтинг користувача
    await db.videos.update_one(
        {"_id": ObjectId(movie_id)},
        {
            "$pull": {"ratings": {"user_id": user_id}},  # Видаляємо старий рейтинг
        }
    )

    await db.videos.update_one(
        {"_id": ObjectId(movie_id)},
        {
            "$push": {"ratings": {"user_id": user_id, "rating": rating}},
        }
    )

    # Перераховуємо середній рейтинг
    movie = await get_movie_by_id(movie_id)
    if movie and movie.get("ratings"):
        avg_rating = sum(r["rating"] for r in movie["ratings"]) / len(movie["ratings"])
        await db.videos.update_one(
            {"_id": ObjectId(movie_id)},
            {"$set": {"rating": round(avg_rating, 1)}}
        )
