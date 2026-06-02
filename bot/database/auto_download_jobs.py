from datetime import datetime, timezone
from bson import ObjectId
from bot.database import db


async def create_job(
    series_id: str,
    series_title: str,
    season: int,
    dubbing: str,
    episode_urls: list[str],
    admin_id: int,
) -> str:
    doc = {
        "series_id": series_id,
        "series_title": series_title,
        "season": season,
        "dubbing": dubbing,
        "episode_urls": episode_urls,
        "total_episodes": len(episode_urls),
        "current_episode": 0,
        "status": "running",
        "admin_id": admin_id,
        "created_at": datetime.now(timezone.utc),
    }
    result = await db.auto_download_jobs.insert_one(doc)
    return str(result.inserted_id)


async def update_job_progress(job_id: str, current_episode: int) -> None:
    await db.auto_download_jobs.update_one(
        {"_id": ObjectId(job_id)},
        {"$set": {"current_episode": current_episode}}
    )


async def set_job_status(job_id: str, status: str) -> None:
    """status: 'running' | 'paused' | 'done' | 'error'"""
    await db.auto_download_jobs.update_one(
        {"_id": ObjectId(job_id)},
        {"$set": {"status": status}}
    )


async def get_job(job_id: str) -> dict | None:
    return await db.auto_download_jobs.find_one({"_id": ObjectId(job_id)})


async def get_running_jobs() -> list[dict]:
    cursor = db.auto_download_jobs.find({"status": "running"})
    return await cursor.to_list(length=None)


async def get_paused_jobs_for_admin(admin_id: int) -> list[dict]:
    cursor = db.auto_download_jobs.find(
        {"admin_id": admin_id, "status": "paused"}
    )
    return await cursor.to_list(length=None)
