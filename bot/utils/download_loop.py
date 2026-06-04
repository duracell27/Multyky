import asyncio
import logging
import os
import shutil

from aiogram import Bot
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton

from bot.config import config
from bot.database.auto_download_jobs import (
    get_job, update_job_progress, set_job_status
)
from bot.database.movies import add_episode_to_series, get_episode
from bot.utils.ffmpeg_runner import run_ffmpeg, get_video_info, create_thumbnail, format_quality
from bot.utils.scraper import get_m3u8_url

logger = logging.getLogger(__name__)

# Tracks which jobs are currently active; maps job_id -> asyncio.Task
_active_tasks: dict[str, asyncio.Task] = {}


def is_job_running(job_id: str) -> bool:
    task = _active_tasks.get(job_id)
    return task is not None and not task.done()


async def start_job(bot: Bot, job_id: str) -> None:
    """Schedule the download loop as a background task."""
    if is_job_running(job_id):
        return
    task = asyncio.create_task(_run_loop(bot, job_id))
    _active_tasks[job_id] = task
    task.add_done_callback(lambda _: _active_tasks.pop(job_id, None))


async def cancel_job(job_id: str) -> None:
    """Request cancellation. The loop checks after each episode."""
    await set_job_status(job_id, "paused")


async def _check_disk(min_gb: float = 1.0) -> bool:
    usage = await asyncio.to_thread(shutil.disk_usage, "/tmp")
    free_gb = usage.free / (1024 ** 3)
    return free_gb >= min_gb


async def _run_loop(bot: Bot, job_id: str) -> None:
    job = await get_job(job_id)
    if not job:
        logger.error(f"Job {job_id} not found")
        return

    series_id = job["series_id"]
    series_title = job["series_title"]
    season = job["season"]
    episode_urls = job["episode_urls"]
    total = job["total_episodes"]
    admin_id = job["admin_id"]
    start_from = job["current_episode"]  # resume support

    if not await _check_disk():
        await bot.send_message(
            admin_id,
            "❌ Менше 1GB вільного місця на диску. Завантаження скасовано."
        )
        await set_job_status(job_id, "error")
        return

    for idx in range(start_from, total):
        # Check disk space before each episode
        if not await _check_disk():
            await bot.send_message(
                admin_id,
                "❌ Менше 1GB вільного місця на диску. Завантаження зупинено."
            )
            await set_job_status(job_id, "error")
            return

        # Check for cancellation before each episode
        fresh_job = await get_job(job_id)
        if fresh_job and fresh_job["status"] == "paused":
            await bot.send_message(
                admin_id,
                f"⏹ Завантаження зупинено після серії {idx}. "
                f"Додано {idx}/{total} серій."
            )
            return

        episode_url = episode_urls[idx]
        ep_num = idx + 1
        output_path = f"/tmp/{job_id}_e{ep_num}.mp4"

        # Skip episodes that are already in the database
        if await get_episode(series_id, season, ep_num):
            await update_job_progress(job_id, idx + 1)
            await bot.send_message(
                admin_id,
                f"⏭ S{season}E{ep_num} вже є в базі, пропускаю ({ep_num}/{total})"
            )
            continue

        thumb_path = output_path + ".thumb.jpg"
        try:
            # 1. Get m3u8
            m3u8_url = await get_m3u8_url(episode_url)

            # 2. Download + remux with faststart (auto-compresses if > 1.9 GB)
            was_compressed = await run_ffmpeg(m3u8_url, output_path)
            if was_compressed:
                await bot.send_message(
                    admin_id,
                    f"⚠️ S{season}E{ep_num}: файл перевищував 1.9 ГБ — перекодовано для Telegram."
                )

            # 3. Get video metadata and thumbnail
            duration, width, height = await get_video_info(output_path)
            has_thumb = await create_thumbnail(output_path, thumb_path)

            # 4. Upload to storage channel (local Bot API server — no size limit)
            caption = (
                f"id:{series_id}\n"
                f"season:{season}\n"
                f"episode:{ep_num}\n"
                f"name:{series_title}"
            )
            sent = await bot.send_video(
                config.STORAGE_CHANNEL_ID,
                video=FSInputFile(output_path),
                caption=caption,
                supports_streaming=True,
                width=width or None,
                height=height or None,
                duration=duration or None,
                thumbnail=FSInputFile(thumb_path) if has_thumb else None,
            )
            file_id = sent.video.file_id
            file_size = sent.video.file_size or 0
            duration = sent.video.duration or 0

            # 4. Add to database
            await add_episode_to_series(
                series_id=series_id,
                season=season,
                episode=ep_num,
                video_file_id=file_id,
                video_type="video",
                file_size=file_size,
                duration=duration,
            )

            # 5. Update progress
            await update_job_progress(job_id, idx + 1)

            # 6. Notify admin
            quality_label = format_quality(width, height)
            await bot.send_message(
                admin_id,
                f"✅ S{season}E{ep_num} додано ({ep_num}/{total}) · {quality_label}"
            )

        except Exception as e:
            logger.error(f"Job {job_id} episode {ep_num} failed: {e}")
            try:
                await bot.send_message(
                    admin_id,
                    f"⚠️ Помилка на S{season}E{ep_num}: {str(e)[:200]}\n"
                    f"Продовжую з наступною серією..."
                )
            except Exception:
                pass
        finally:
            if await asyncio.to_thread(os.path.exists, output_path):
                await asyncio.to_thread(os.remove, output_path)
            if await asyncio.to_thread(os.path.exists, thumb_path):
                await asyncio.to_thread(os.remove, thumb_path)

    await set_job_status(job_id, "done")

    bot_info = await bot.get_me()
    view_url = f"https://t.me/{bot_info.username}?start=s_{series_id}"

    done_markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Зробити розсилку", callback_data=f"post_quick:series:{series_id}")],
        [InlineKeyboardButton(text="📺 Переглянути серіал", url=view_url)],
        [InlineKeyboardButton(text="➕ Додати ще серіал", callback_data="ad_add_new:series"),
         InlineKeyboardButton(text="🎬 Додати фільм", callback_data="am_add_new:movie")],
    ])

    await bot.send_message(
        admin_id,
        f"🎉 <b>Готово!</b> Всі {total} серій сезону {season} "
        f"серіалу «{series_title}» успішно завантажено!",
        reply_markup=done_markup,
    )
