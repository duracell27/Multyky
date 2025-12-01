from datetime import datetime, timezone
from typing import Optional
from bot.database import db
from bot.config import config


async def create_movie(
    title: str,
    title_en: str,
    year: int,
    imdb_rating: float,
    poster_file_id: str,
    video_file_id: str,
    video_type: str,
    added_by: int,
    file_size: int = 0,
    duration: int = 0,
    series_name: str = None
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
        "file_size": file_size,
        "duration": duration,
        "added_by": added_by,
        "added_at": datetime.now(timezone.utc),
        "views_count": 0,
        "rating": 0,
        "ratings": [],
    }

    # Додаємо series_name якщо вказано
    if series_name:
        movie_data["series_name"] = series_name

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
    video_type: str,
    file_size: int = 0,
    duration: int = 0
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
        "file_size": file_size,
        "duration": duration,
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


async def get_movies_only_count() -> int:
    """Отримати кількість тільки фільмів"""
    return await db.videos.count_documents({"content_type": "movie"})


async def get_series_only_count() -> int:
    """Отримати кількість тільки серіалів"""
    return await db.videos.count_documents({"content_type": "series"})


async def get_total_episodes_count() -> int:
    """Отримати загальну кількість епізодів у всіх серіалах"""
    series_list = await db.videos.find({"content_type": "series"}).to_list(length=None)

    total_episodes = 0
    for series in series_list:
        if "seasons" in series:
            for season_num, episodes in series["seasons"].items():
                total_episodes += len(episodes)

    return total_episodes


async def get_total_videos_count() -> int:
    """Отримати загальну кількість відео (фільми + епізоди)"""
    movies_count = await get_movies_only_count()
    episodes_count = await get_total_episodes_count()
    return movies_count + episodes_count


async def get_total_views_count() -> int:
    """Отримати загальну кількість переглядів всіх відео"""
    # Використовуємо агрегацію для підсумовування views_count
    pipeline = [
        {
            "$group": {
                "_id": None,
                "total_views": {"$sum": "$views_count"}
            }
        }
    ]

    result = await db.videos.aggregate(pipeline).to_list(length=1)

    if result:
        return result[0].get("total_views", 0)
    return 0


async def get_top_content_by_views(limit: int = 5, include_hidden: bool = True) -> list:
    """Отримати топ контенту по переглядах"""
    query = {}
    if not include_hidden:
        query["is_hidden"] = {"$ne": True}

    cursor = db.videos.find(query).sort("views_count", -1).limit(limit)

    return await cursor.to_list(length=limit)


async def get_total_storage_size() -> float:
    """
    Отримати загальний розмір всіх відео в гігабайтах
    Базове значення: 53.2 ГБ (для попередньо завантажених серій)
    """
    BASE_SIZE_GB = 53.2

    # Отримуємо всі фільми
    movies = await db.videos.find({"content_type": "movie"}).to_list(length=None)
    movies_size = sum(movie.get("file_size", 0) for movie in movies)

    # Отримуємо всі серіали
    series_list = await db.videos.find({"content_type": "series"}).to_list(length=None)

    # Рахуємо розмір всіх епізодів
    episodes_size = 0
    for series in series_list:
        if "seasons" in series:
            for season_num, episodes in series["seasons"].items():
                for episode_num, episode_data in episodes.items():
                    episodes_size += episode_data.get("file_size", 0)

    # Загальний розмір у байтах
    total_bytes = movies_size + episodes_size

    # Конвертуємо в ГБ і додаємо базове значення
    total_gb = BASE_SIZE_GB + (total_bytes / (1024 ** 3))

    return round(total_gb, 2)


async def get_all_movies_list(include_hidden: bool = False) -> list:
    """Отримати список всіх фільмів"""
    query = {"content_type": "movie"}
    if not include_hidden:
        query["is_hidden"] = {"$ne": True}

    cursor = db.videos.find(query).sort("title", 1)
    return await cursor.to_list(length=None)


async def get_all_series_list(include_hidden: bool = False) -> list:
    """Отримати список всіх серіалів"""
    query = {"content_type": "series"}
    if not include_hidden:
        query["is_hidden"] = {"$ne": True}

    cursor = db.videos.find(query).sort("title", 1)
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


async def search_content(query: str, include_hidden: bool = False) -> list:
    """Пошук мультфільмів і серіалів за назвою"""
    search_filter = {
        "$or": [
            {"title": {"$regex": query, "$options": "i"}},
            {"title_en": {"$regex": query, "$options": "i"}}
        ]
    }

    if not include_hidden:
        search_filter["is_hidden"] = {"$ne": True}

    cursor = db.videos.find(search_filter)
    return await cursor.to_list(length=None)


async def increment_views(content_id: str, user_id: int = None):
    """Збільшити лічильник переглядів (не рахує перегляди адмінів)"""
    # Не рахуємо перегляди від адмінів
    if user_id and user_id in config.ADMIN_IDS:
        return

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


async def toggle_like(series_id: str, user_id: int) -> dict:
    """
    Перемикач лайка для серіалу
    Якщо користувач вже лайкнув - видаляє лайк
    Якщо користувач дизлайкнув - переключає на лайк
    Якщо не голосував - додає лайк

    Returns: {"action": "added"/"removed", "rating": new_rating}
    """
    from bson import ObjectId

    series = await get_movie_by_id(series_id)
    if not series:
        return None

    likes = series.get("likes", [])
    dislikes = series.get("dislikes", [])

    action = None

    if user_id in likes:
        # Користувач вже лайкнув - видаляємо лайк
        likes.remove(user_id)
        action = "removed"
    else:
        # Видаляємо дизлайк якщо є
        if user_id in dislikes:
            dislikes.remove(user_id)
        # Додаємо лайк
        likes.append(user_id)
        action = "added"

    # Оновлюємо рейтинг
    rating = len(likes) - len(dislikes)

    # Зберігаємо в базу
    await db.videos.update_one(
        {"_id": ObjectId(series_id)},
        {
            "$set": {
                "likes": likes,
                "dislikes": dislikes,
                "rating": rating
            }
        }
    )

    return {"action": action, "rating": rating}


async def toggle_dislike(series_id: str, user_id: int) -> dict:
    """
    Перемикач дизлайка для серіалу
    Якщо користувач вже дизлайкнув - видаляє дизлайк
    Якщо користувач лайкнув - переключає на дизлайк
    Якщо не голосував - додає дизлайк

    Returns: {"action": "added"/"removed", "rating": new_rating}
    """
    from bson import ObjectId

    series = await get_movie_by_id(series_id)
    if not series:
        return None

    likes = series.get("likes", [])
    dislikes = series.get("dislikes", [])

    action = None

    if user_id in dislikes:
        # Користувач вже дизлайкнув - видаляємо дизлайк
        dislikes.remove(user_id)
        action = "removed"
    else:
        # Видаляємо лайк якщо є
        if user_id in likes:
            likes.remove(user_id)
        # Додаємо дизлайк
        dislikes.append(user_id)
        action = "added"

    # Оновлюємо рейтинг
    rating = len(likes) - len(dislikes)

    # Зберігаємо в базу
    await db.videos.update_one(
        {"_id": ObjectId(series_id)},
        {
            "$set": {
                "likes": likes,
                "dislikes": dislikes,
                "rating": rating
            }
        }
    )

    return {"action": action, "rating": rating}


async def get_user_vote(series_id: str, user_id: int) -> str:
    """
    Отримати голос користувача
    Returns: "like", "dislike", або None
    """
    series = await get_movie_by_id(series_id)
    if not series:
        return None

    likes = series.get("likes", [])
    dislikes = series.get("dislikes", [])

    if user_id in likes:
        return "like"
    elif user_id in dislikes:
        return "dislike"
    else:
        return None


async def delete_movie(movie_id: str) -> bool:
    """Видалити фільм"""
    from bson import ObjectId
    result = await db.videos.delete_one({"_id": ObjectId(movie_id)})
    return result.deleted_count > 0


async def delete_series(series_id: str) -> bool:
    """Видалити серіал повністю"""
    from bson import ObjectId
    result = await db.videos.delete_one({"_id": ObjectId(series_id)})
    return result.deleted_count > 0


async def delete_season(series_id: str, season: int) -> bool:
    """Видалити сезон з серіалу"""
    from bson import ObjectId

    season_key = str(season)
    result = await db.videos.update_one(
        {"_id": ObjectId(series_id)},
        {"$unset": {f"seasons.{season_key}": ""}}
    )
    return result.modified_count > 0


async def delete_episode(series_id: str, season: int, episode: int) -> bool:
    """Видалити серію з сезону"""
    from bson import ObjectId

    season_key = str(season)
    episode_key = str(episode)

    result = await db.videos.update_one(
        {"_id": ObjectId(series_id)},
        {"$unset": {f"seasons.{season_key}.{episode_key}": ""}}
    )
    return result.modified_count > 0


# ===============================================
# Редагування контенту
# ===============================================

async def update_movie_field(movie_id: str, field: str, value) -> bool:
    """Оновити поле фільму або серіалу"""
    from bson import ObjectId

    result = await db.videos.update_one(
        {"_id": ObjectId(movie_id)},
        {"$set": {field: value}}
    )
    return result.modified_count > 0


async def update_episode_video(series_id: str, season: int, episode: int, video_file_id: str, video_type: str, file_size: int = 0, duration: int = 0) -> bool:
    """Оновити відео серії"""
    from bson import ObjectId

    season_key = str(season)
    episode_key = str(episode)

    result = await db.videos.update_one(
        {"_id": ObjectId(series_id)},
        {
            "$set": {
                f"seasons.{season_key}.{episode_key}.video_file_id": video_file_id,
                f"seasons.{season_key}.{episode_key}.video_type": video_type,
                f"seasons.{season_key}.{episode_key}.file_size": file_size,
                f"seasons.{season_key}.{episode_key}.duration": duration,
            }
        }
    )
    return result.modified_count > 0


# ===============================================
# Приховування/показування контенту
# ===============================================

async def hide_content(content_id: str) -> bool:
    """Приховати мультфільм або серіал"""
    from bson import ObjectId

    result = await db.videos.update_one(
        {"_id": ObjectId(content_id)},
        {"$set": {"is_hidden": True}}
    )
    return result.modified_count > 0


async def show_content(content_id: str) -> bool:
    """Показати мультфільм або серіал"""
    from bson import ObjectId

    result = await db.videos.update_one(
        {"_id": ObjectId(content_id)},
        {"$set": {"is_hidden": False}}
    )
    return result.modified_count > 0


async def toggle_content_visibility(content_id: str) -> dict:
    """
    Перемикач видимості контенту
    Returns: {"is_hidden": bool, "title": str}
    """
    from bson import ObjectId

    content = await get_movie_by_id(content_id)
    if not content:
        return None

    # Визначаємо поточний стан (якщо поля немає - контент видимий)
    is_hidden = content.get("is_hidden", False)
    new_state = not is_hidden

    # Оновлюємо стан
    await db.videos.update_one(
        {"_id": ObjectId(content_id)},
        {"$set": {"is_hidden": new_state}}
    )

    return {
        "is_hidden": new_state,
        "title": content.get("title", "")
    }


# ===============================================
# Робота з серіями фільмів (групування)
# ===============================================

async def get_all_movie_series_names() -> list:
    """Отримати всі унікальні назви серій фільмів"""
    pipeline = [
        {"$match": {"content_type": "movie", "series_name": {"$exists": True, "$ne": None}}},
        {"$group": {"_id": "$series_name"}},
        {"$sort": {"_id": 1}}
    ]

    result = await db.videos.aggregate(pipeline).to_list(length=None)
    return [item["_id"] for item in result]


async def search_movie_series_names(query: str) -> list:
    """Пошук схожих назв серій фільмів"""
    pipeline = [
        {
            "$match": {
                "content_type": "movie",
                "series_name": {
                    "$exists": True,
                    "$ne": None,
                    "$regex": query,
                    "$options": "i"
                }
            }
        },
        {"$group": {"_id": "$series_name"}},
        {"$sort": {"_id": 1}}
    ]

    result = await db.videos.aggregate(pipeline).to_list(length=None)
    return [item["_id"] for item in result]


async def get_movies_by_series_name(series_name: str, include_hidden: bool = False) -> list:
    """Отримати всі фільми за назвою серії"""
    query = {"content_type": "movie", "series_name": series_name}
    if not include_hidden:
        query["is_hidden"] = {"$ne": True}

    cursor = db.videos.find(query).sort("year", 1)
    return await cursor.to_list(length=None)


async def calculate_series_average_rating(movies: list) -> float:
    """
    Обчислити середній IMDB рейтинг для серії фільмів

    Args:
        movies: список фільмів у серії

    Returns:
        Середній рейтинг (округлений до 1 знаку після коми)
    """
    if not movies:
        return 0.0

    total_rating = sum(movie.get("imdb_rating", 0) for movie in movies)
    average = total_rating / len(movies)

    return round(average, 1)


async def get_grouped_movies(include_hidden: bool = False) -> dict:
    """
    Отримати фільми, згруповані за series_name
    Returns: {
        "grouped": {series_name: [movies]},
        "standalone": [movies without series_name]
    }
    """
    query = {"content_type": "movie"}
    if not include_hidden:
        query["is_hidden"] = {"$ne": True}

    all_movies = await db.videos.find(query).sort("title", 1).to_list(length=None)

    grouped = {}
    standalone = []

    for movie in all_movies:
        series_name = movie.get("series_name")
        if series_name:
            if series_name not in grouped:
                grouped[series_name] = []
            grouped[series_name].append(movie)
        else:
            standalone.append(movie)

    # Сортуємо фільми в кожній групі за роком
    for series_name in grouped:
        grouped[series_name].sort(key=lambda m: m.get("year", 0))

    return {
        "grouped": grouped,
        "standalone": standalone
    }
