import logging
import re
from collections import defaultdict
from aiogram import Router, Bot, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import config
from bot.database.movies import get_ongoing_series
from bot.database.auto_download_jobs import create_job
from bot.utils.download_loop import start_job
from bot.utils.scraper import parse_season_page, get_dubbing_options, get_uakino_season_urls

router = Router()
logger = logging.getLogger(__name__)

# in-memory store: admin_id → check results (cleared after use)
_pending_updates: dict[int, list] = {}


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


async def _collect_missing_episodes(series: dict) -> list[dict]:
    """
    Returns a list of result dicts (one per season that has missing episodes or errors).
    Each dict: {series, season, new_ep_nums, new_ep_urls, error}.
    """
    source_url = series.get("source_url", "")
    source_dubbing = series.get("source_dubbing", "")
    seasons = series.get("seasons", {})

    if not source_url:
        return [{"series": series, "season": 0, "new_ep_nums": [], "new_ep_urls": [], "error": "URL не вказано"}]

    site = "uafix" if "uafix.net" in source_url else "uakino"
    results = []

    try:
        if site == "uakino":
            season_urls = await get_uakino_season_urls(source_url)
            if not season_urls:
                return [{"series": series, "season": 0, "new_ep_nums": [], "new_ep_urls": [], "error": "Не знайдено сезонів на сайті"}]

            for site_season, check_url in sorted(season_urls.items()):
                try:
                    dubbings = await get_dubbing_options(check_url)
                    dubbing = dubbings[0] if dubbings else source_dubbing
                    parsed = await parse_season_page(check_url, dubbing)

                    existing_eps = {int(k) for k in seasons.get(str(site_season), {}).keys()}
                    new_pairs = [
                        (num, ep_url)
                        for num, ep_url in zip(parsed["episode_numbers"], parsed["episode_urls"])
                        if num not in existing_eps
                    ]

                    if new_pairs:
                        results.append({
                            "series": series,
                            "season": site_season,
                            "new_ep_nums": [p[0] for p in new_pairs],
                            "new_ep_urls": [p[1] for p in new_pairs],
                            "error": None,
                        })
                except Exception as e:
                    logger.error(f"checkUpdates uakino season {site_season}: {e}")
                    results.append({
                        "series": series,
                        "season": site_season,
                        "new_ep_nums": [], "new_ep_urls": [],
                        "error": str(e)[:120],
                    })

        else:  # uafix
            max_db_season = max((int(s) for s in seasons.keys()), default=0)
            # Check from season 1 up to max_db_season+1 to catch both gaps and new seasons
            for season_num in range(1, max_db_season + 2):
                try:
                    dubbings = await get_dubbing_options(source_url, season=season_num)
                    dubbing = dubbings[0] if dubbings else source_dubbing
                    parsed = await parse_season_page(source_url, dubbing, season=season_num)
                except ValueError:
                    # Season doesn't exist on site — stop scanning
                    break
                except Exception as e:
                    logger.error(f"checkUpdates uafix season {season_num}: {e}")
                    results.append({
                        "series": series,
                        "season": season_num,
                        "new_ep_nums": [], "new_ep_urls": [],
                        "error": str(e)[:120],
                    })
                    break

                existing_eps = {int(k) for k in seasons.get(str(season_num), {}).keys()}
                new_pairs = [
                    (num, ep_url)
                    for num, ep_url in zip(parsed["episode_numbers"], parsed["episode_urls"])
                    if num not in existing_eps
                ]

                if new_pairs:
                    results.append({
                        "series": series,
                        "season": season_num,
                        "new_ep_nums": [p[0] for p in new_pairs],
                        "new_ep_urls": [p[1] for p in new_pairs],
                        "error": None,
                    })

    except Exception as e:
        logger.error(f"checkUpdates error for {series.get('title', '?')}: {e}")
        return [{"series": series, "season": 0, "new_ep_nums": [], "new_ep_urls": [], "error": str(e)[:120]}]

    return results


@router.message(Command("checkUpdates"))
async def cmd_check_updates(message: Message) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ Тільки для адміністраторів.")
        return

    await message.answer("⏳ Перевіряю оновлення...")

    ongoing = await get_ongoing_series()
    if not ongoing:
        await message.answer("ℹ️ Немає серіалів з позначкою 'незавершений'.")
        return

    all_results = []
    for series in ongoing:
        season_results = await _collect_missing_episodes(series)
        all_results.extend(season_results)

    # Group by series for the report
    grouped: dict[str, list] = defaultdict(list)
    for r in all_results:
        grouped[str(r["series"]["_id"])].append(r)

    lines = ["📋 <b>Звіт оновлень:</b>\n"]
    has_new = False

    for series_results in grouped.values():
        title = series_results[0]["series"].get("title", "?")
        errors = [r for r in series_results if r["error"]]
        new_seasons = [r for r in series_results if r["new_ep_nums"] and not r["error"]]

        if errors:
            for r in errors:
                lines.append(f"❌ {title} (с.{r['season']}) — {r['error']}")

        if new_seasons:
            has_new = True
            parts = []
            for r in new_seasons:
                ep_list = ", ".join(str(n) for n in r["new_ep_nums"])
                parts.append(f"с.{r['season']}: {ep_list}")
            lines.append(f"✅ {title} — нові серії ({'; '.join(parts)})")

        if not errors and not new_seasons:
            lines.append(f"⏸ {title} — актуальний")

    report_text = "\n".join(lines)

    if has_new:
        _pending_updates[message.from_user.id] = all_results
        buttons = [
            [InlineKeyboardButton(text="✅ Завантажити все", callback_data="cu_download_all")],
            [InlineKeyboardButton(text="❌ Скасувати", callback_data="cu_cancel")],
        ]
        await message.answer(report_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    else:
        await message.answer(report_text)


@router.callback_query(F.data == "cu_download_all")
async def download_all_updates(callback: CallbackQuery, bot: Bot) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔️", show_alert=True)
        return

    results = _pending_updates.pop(callback.from_user.id, None)
    if not results:
        await callback.answer(
            "❌ Дані застаріли. Запусти /checkUpdates знову.",
            show_alert=True
        )
        return

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()

    new_results = [r for r in results if r["new_ep_nums"] and not r["error"]]

    for r in new_results:
        series = r["series"]
        series_id = str(series["_id"])
        title = series.get("title", "?")
        content_type = series.get("content_type", "series")

        try:
            job_id = await create_job(
                series_id=series_id,
                series_title=title,
                season=r["season"],
                dubbing=series.get("source_dubbing", ""),
                episode_urls=r["new_ep_urls"],
                admin_id=callback.from_user.id,
                content_type=content_type,
                episode_numbers=r["new_ep_nums"],
            )
            await start_job(bot, job_id)
            ep_list = ", ".join(str(n) for n in r["new_ep_nums"])
            await bot.send_message(
                callback.from_user.id,
                f"▶️ <b>{title}</b> с.{r['season']}: запущено завантаження серій {ep_list}"
            )
        except Exception as e:
            logger.error(f"download_all_updates error for {title}: {e}")
            await bot.send_message(
                callback.from_user.id,
                f"❌ <b>{title}</b> с.{r['season']}: помилка запуску — {e}"
            )

    await bot.send_message(
        callback.from_user.id,
        f"✅ Оновлення запущено для {len(new_results)} сезон(ів)."
    )


@router.callback_query(F.data == "cu_cancel")
async def cancel_updates(callback: CallbackQuery) -> None:
    _pending_updates.pop(callback.from_user.id, None)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("❌ Скасовано")
