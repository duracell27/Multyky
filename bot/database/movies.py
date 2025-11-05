from datetime import datetime, timezone
from typing import Optional
from bot.database import db


async def create_movie(
    title: str,
    title_en: str,
    year: int,
    imdb_rating: float,
    poster_file_id: str,
    video_file_id: str,
    video_type: str,
    added_by: int,
) -> dict:
    """
    Створити новий мультфільм
    """
    movie_data = {
        "title": title,
        "title_en": title_en,
        "year": year,
        "imdb_rating": imdb_rating,
        "poster_file_id": poster_file_id,
        "content_type": "movie",
        "video_file_id": video_file_id,
        "video_type": video_type,
        "added_by": added_by,
        "added_at": datetime.now(timezone.utc),
        "views_count": 0,
        "rating": 0,
        "ratings": [],
    }

    result = await db.videos.insert_one(movie_data)
    movie_data["_id"] = result.inserted_id
    return movie_data


async def create_series(
    title: str,
    title_en: str,
    year: int,
    imdb_rating: float,
    poster_file_id: str,
    added_by: int,
) -> dict:
    """
    Створити новий серіал (без серій)
    """
    series_data = {
        "title": title,
        "title_en": title_en,
        "year": year,
        "imdb_rating": imdb_rating,
        "poster_file_id": poster_file_id,
        "content_type": "series",
        "added_by": added_by,
        "added_at": datetime.now(timezone.utc),
        "views_count": 0,
        "rating": 0,
        "ratings": [],
        "seasons": {}
    }

    result = await db.videos.insert_one(series_data)
    series_data["_id"] = result.inserted_id
    return series_data


async def add_episode_to_series(
    series_id: str,
    season: int,
    episode: int,
    video_file_id: str,
    video_type: str
) -> bool:
    """
    Додати серію до існуючого серіалу
    """
    from bson import ObjectId

    season_key = str(season)
    episode_key = str(episode)

    episode_data = {
        "video_file_id": video_file_id,
        "video_type": video_type,
        "added_at": datetime.now(timezone.utc)
    }

    # Оновлюємо серіал, додаючи нову серію
    result = await db.videos.update_one(
        {"_id": ObjectId(series_id)},
        {
            "$set": {
                f"seasons.{season_key}.{episode_key}": episode_data
            }
        }
    )

    return result.modified_count > 0


async def get_series_by_title(title: str) -> Optional[dict]:
    """Отримати серіал за назвою"""
    return await db.videos.find_one({"title": title, "content_type": "series"})


async def get_movie_by_id(movie_id: str) -> Optional[dict]:
    """Отримати мультфільм/серіал за ID"""
    from bson import ObjectId
    return await db.videos.find_one({"_id": ObjectId(movie_id)})


async def get_movie_by_title(title: str) -> Optional[dict]:
    """Отримати мультфільм/серіал за назвою"""
    return await db.videos.find_one({"title": title})


async def get_all_movies() -> list:
    """Отримати всі мультфільми і серіали"""
    cursor = db.videos.find()
    return await cursor.to_list(length=None)


async def get_movies_count() -> int:
    """Отримати кількість мультфільмів і серіалів"""
    return await db.videos.count_documents({})


async def get_all_movies_list() -> list:
    """Отримати список всіх фільмів"""
    cursor = db.videos.find({"content_type": "movie"}).sort("title", 1)
    return await cursor.to_list(length=None)


async def get_all_series_list() -> list:
    """Отримати список всіх серіалів"""
    cursor = db.videos.find({"content_type": "series"}).sort("title", 1)
    return await cursor.to_list(length=None)


async def get_episode(series_id: str, season: int, episode: int) -> Optional[dict]:
    """Отримати конкретну серію з серіалу"""
    from bson import ObjectId

    series = await db.videos.find_one({"_id": ObjectId(series_id)})
    if not series or "seasons" not in series:
        return None

    season_key = str(season)
    episode_key = str(episode)

    if season_key in series["seasons"] and episode_key in series["seasons"][season_key]:
        episode_data = series["seasons"][season_key][episode_key]
        # Додаємо інформацію про серіал
        return {
            **episode_data,
            "series_id": series_id,
            "series_title": series["title"],
            "season": season,
            "episode": episode
        }

    return None


async def get_series_seasons(series_id: str) -> list:
    """Отримати список сезонів серіалу"""
    from bson import ObjectId

    series = await db.videos.find_one({"_id": ObjectId(series_id)})
    if not series or "seasons" not in series:
        return []

    # Повертаємо відсортований список номерів сезонів
    return sorted([int(season) for season in series["seasons"].keys()])


async def get_season_episodes(series_id: str, season: int) -> dict:
    """Отримати всі серії певного сезону"""
    from bson import ObjectId

    series = await db.videos.find_one({"_id": ObjectId(series_id)})
    if not series or "seasons" not in series:
        return {}

    season_key = str(season)
    if season_key not in series["seasons"]:
        return {}

    # Повертаємо словник з серіями
    episodes = {}
    for ep_num, ep_data in series["seasons"][season_key].items():
        episodes[int(ep_num)] = ep_data

    return episodes


async def search_content(query: str) -> list:
    """Пошук мультфільмів і серіалів за назвою"""
    cursor = db.videos.find({
        "$or": [
            {"title": {"$regex": query, "$options": "i"}},
            {"title_en": {"$regex": query, "$options": "i"}}
        ]
    })
    return await cursor.to_list(length=None)


async def increment_views(content_id: str):
    """Збільшити лічильник переглядів"""
    from bson import ObjectId
    await db.videos.update_one(
        {"_id": ObjectId(content_id)},
        {"$inc": {"views_count": 1}}
    )


async def update_content_rating(content_id: str, user_id: int, rating: int):
    """Оновити рейтинг контенту від користувача"""
    from bson import ObjectId

    # Видаляємо старий рейтинг користувача
    await db.videos.update_one(
        {"_id": ObjectId(content_id)},
        {"$pull": {"ratings": {"user_id": user_id}}}
    )

    # Додаємо новий рейтинг
    await db.videos.update_one(
        {"_id": ObjectId(content_id)},
        {"$push": {"ratings": {"user_id": user_id, "rating": rating}}}
    )

    # Перераховуємо середній рейтинг
    content = await get_movie_by_id(content_id)
    if content and content.get("ratings"):
        avg_rating = sum(r["rating"] for r in content["ratings"]) / len(content["ratings"])
        await db.videos.update_one(
            {"_id": ObjectId(content_id)},
            {"$set": {"rating": round(avg_rating, 1)}}
        )


# Допоміжні функції для зворотної сумісності
async def get_series_info_by_title(title: str) -> Optional[dict]:
    """Отримати інформацію про серіал за назвою"""
    return await get_series_by_title(title)


async def get_series_episodes(title: str, season: int = None) -> list:
    """
    Отримати серії серіалу (для зворотної сумісності)

    Args:
        title: назва серіалу
        season: номер сезону (опціонально)

    Returns:
        Список епізодів у форматі старої структури
    """
    series = await get_series_by_title(title)
    if not series or "seasons" not in series:
        return []

    episodes = []
    seasons_data = series["seasons"]

    for season_num, season_episodes in seasons_data.items():
        if season is not None and int(season_num) != season:
            continue

        for ep_num, ep_data in season_episodes.items():
            episodes.append({
                "_id": series["_id"],
                "title": series["title"],
                "title_en": series["title_en"],
                "year": series["year"],
                "imdb_rating": series["imdb_rating"],
                "season": int(season_num),
                "episode": int(ep_num),
                "video_file_id": ep_data["video_file_id"],
                "video_type": ep_data["video_type"],
                "added_at": ep_data["added_at"]
            })

    # Сортуємо по сезону і серії
    episodes.sort(key=lambda x: (x["season"], x["episode"]))
    return episodes
