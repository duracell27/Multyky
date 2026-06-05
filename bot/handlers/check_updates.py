import logging
import re
from aiogram import Router, Bot, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import config
from bot.database.movies import get_ongoing_series
from bot.database.auto_download_jobs import create_job
from bot.utils.download_loop import start_job
from bot.utils.scraper import parse_season_page, get_dubbing_options

router = Router()
logger = logging.getLogger(__name__)

# in-memory store: admin_id → check results (cleared after use)
_pending_updates: dict[int, list] = {}


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


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

    results = []

    for series in ongoing:
        series_id = str(series["_id"])
        title = series.get("title", "?")
        source_url = series.get("source_url", "")
        source_dubbing = series.get("source_dubbing", "")
        seasons = series.get("seasons", {})

        if not source_url:
            results.append({
                "series": series, "season": 0,
                "new_ep_nums": [], "new_ep_urls": [],
                "error": "URL не вказано"
            })
            continue

        if not seasons:
            results.append({
                "series": series, "season": 0,
                "new_ep_nums": [], "new_ep_urls": [],
                "error": "Немає сезонів в базі"
            })
            continue

        max_season = max(int(s) for s in seasons.keys())

        try:
            site = "uafix" if "uafix.net" in source_url else "uakino"

            if site == "uafix":
                url_season = max_season
                season_param = max_season
            else:
                # Визначаємо сезон з URL uakino (напр. "23-sezon" → 23)
                m = re.search(r'(\d+)-sezon', source_url, re.I)
                url_season = int(m.group(1)) if m else max_season
                season_param = None

            dubbings = await get_dubbing_options(source_url, season=season_param)
            dubbing = dubbings[0] if dubbings else source_dubbing
            parsed = await parse_season_page(source_url, dubbing, season=season_param)

            existing_eps = {int(k) for k in seasons.get(str(url_season), {}).keys()}

            new_pairs = [
                (num, url)
                for num, url in zip(parsed["episode_numbers"], parsed["episode_urls"])
                if num not in existing_eps
            ]

            results.append({
                "series": series,
                "season": url_season,
                "new_ep_nums": [p[0] for p in new_pairs],
                "new_ep_urls": [p[1] for p in new_pairs],
                "error": None,
            })
        except Exception as e:
            logger.error(f"checkUpdates error for {title}: {e}")
            results.append({
                "series": series,
                "season": max_season,
                "new_ep_nums": [], "new_ep_urls": [],
                "error": str(e)[:120],
            })

    lines = ["📋 <b>Звіт оновлень:</b>\n"]
    has_new = False

    for r in results:
        title = r["series"].get("title", "?")
        if r["error"]:
            lines.append(f"❌ {title} — {r['error']}")
        elif r["new_ep_nums"]:
            has_new = True
            ep_list = ", ".join(str(n) for n in r["new_ep_nums"])
            lines.append(
                f"✅ {title} — знайдено {len(r['new_ep_nums'])} нових серій "
                f"(с.{r['season']}: {ep_list})"
            )
        else:
            lines.append(f"⏸ {title} — актуальний")

    report_text = "\n".join(lines)

    if has_new:
        _pending_updates[message.from_user.id] = results
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
                f"▶️ <b>{title}</b>: запущено завантаження серій {ep_list}"
            )
        except Exception as e:
            logger.error(f"download_all_updates error for {title}: {e}")
            await bot.send_message(
                callback.from_user.id,
                f"❌ <b>{title}</b>: помилка запуску — {e}"
            )

    await bot.send_message(
        callback.from_user.id,
        f"✅ Оновлення запущено для {len(new_results)} серіал(ів)."
    )


@router.callback_query(F.data == "cu_cancel")
async def cancel_updates(callback: CallbackQuery) -> None:
    _pending_updates.pop(callback.from_user.id, None)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("❌ Скасовано")
