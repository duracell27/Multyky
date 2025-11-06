import asyncio
import logging
import re
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext

from bot.config import config
from bot.states import AddBatchMovieStates
from bot.database.movies import (
    add_episode_to_series,
    get_all_series_list, get_movie_by_id,
    get_season_episodes, get_episode
)
from bot.database.users import update_last_series_added

router = Router()

# Locks для синхронізації batch upload (уникнення race condition)
batch_upload_locks = {}


def is_admin(user_id: int) -> bool:
    """Перевірка чи користувач є адміністратором"""
    return user_id in config.ADMIN_IDS


# ===============================================
# Пакетне додавання серій (Batch Upload)
# ===============================================

@router.message(Command("addBatchMovie"))
async def cmd_add_batch_movie(message: Message, state: FSMContext):
    """Початок процесу пакетного додавання серій"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ Ця команда доступна тільки для адміністраторів.")
        return

    # Отримуємо список серіалів
    series_list = await get_all_series_list()

    if not series_list:
        await message.answer("❌ У базі даних немає жодного серіалу.\n\nСпочатку створіть серіал.")
        return

    # Створюємо кнопки для вибору серіалу (тільки назва)
    buttons = []
    for series in series_list:
        series_id = str(series["_id"])
        buttons.append([
            InlineKeyboardButton(
                text=f"📺 {series['title']}",
                callback_data=f"sel_series:{series_id}"
            )
        ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(
        "📺 <b>Виберіть серіал для додавання серій:</b>",
        reply_markup=keyboard
    )
    await state.set_state(AddBatchMovieStates.choosing_existing_series)


@router.callback_query(AddBatchMovieStates.choosing_existing_series, F.data.startswith("sel_series:"))
async def process_series_selection(callback: CallbackQuery, state: FSMContext):
    """Обробка вибору серіалу"""
    series_id = callback.data.split(":", 1)[1]

    # Отримуємо інформацію про серіал
    series_info = await get_movie_by_id(series_id)

    if not series_info:
        await callback.answer("❌ Серіал не знайдено", show_alert=True)
        return

    # Зберігаємо інформацію про серіал
    await state.update_data(
        series_id=series_id,
        title=series_info["title"]
    )

    # Рахуємо детальну інформацію про серії
    seasons_info = []
    total_episodes = 0
    if "seasons" in series_info and series_info["seasons"]:
        for season_num, episodes in sorted(series_info["seasons"].items(), key=lambda x: int(x[0])):
            episode_count = len(episodes)
            total_episodes += episode_count
            seasons_info.append(f"   • Сезон {season_num}: {episode_count} серій")

    if seasons_info:
        info_text = "\n".join(seasons_info)
        summary = f"Всього завантажено: {total_episodes} серій"
    else:
        info_text = "   • Серій ще немає"
        summary = "Серіал порожній"

    await callback.message.edit_text(
        f"✅ <b>Вибрано серіал:</b>\n\n"
        f"📺 <b>{series_info['title']}</b>\n"
        f"🆔 ID: <code>{series_id}</code>\n\n"
        f"<b>📊 Поточний стан:</b>\n{info_text}\n\n"
        f"<i>{summary}</i>\n\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"Введіть номер сезону (наприклад: <code>1</code>):"
    )
    await state.set_state(AddBatchMovieStates.waiting_for_season)
    await callback.answer()


@router.message(AddBatchMovieStates.waiting_for_season, ~F.text.startswith("/"))
async def process_season(message: Message, state: FSMContext):
    """Обробка введення номера сезону"""
    try:
        season = int(message.text.strip())
        if season < 1:
            await message.answer("❌ Номер сезону має бути більше 0. Спробуйте ще раз:")
            return
    except ValueError:
        await message.answer("❌ Некоректний формат. Введіть число (наприклад: 1):")
        return

    await state.update_data(season=season)
    await message.answer(
        f"✅ Сезон: <b>{season}</b>\n\n"
        "Введіть діапазон серій:\n"
        "• Одна серія: <code>3</code>\n"
        "• Діапазон: <code>4-6</code> (з 4 по 6, тобто 3 серії)\n"
        "• Діапазон: <code>7-8</code> (2 серії)"
    )
    await state.set_state(AddBatchMovieStates.waiting_for_episode_range)


@router.message(AddBatchMovieStates.waiting_for_episode_range, ~F.text.startswith("/"))
async def process_episode_range(message: Message, state: FSMContext):
    """Обробка введення діапазону серій"""
    text = message.text.strip()

    # Перевіряємо чи це одна цифра
    if text.isdigit():
        start_episode = int(text)
        end_episode = int(text)
        episodes_count = 1
    elif "-" in text:
        # Це діапазон
        try:
            start_ep, end_ep = text.split("-", 1)
            start_episode = int(start_ep.strip())
            end_episode = int(end_ep.strip())

            if start_episode < 1 or end_episode < 1:
                await message.answer("❌ Номери серій мають бути більше 0. Спробуйте ще раз:")
                return

            if start_episode > end_episode:
                await message.answer("❌ Початковий номер не може бути більше кінцевого. Спробуйте ще раз:")
                return

            if end_episode - start_episode + 1 > 50:
                await message.answer("❌ Максимум 50 серій за раз. Спробуйте менший діапазон:")
                return

            episodes_count = end_episode - start_episode + 1
        except ValueError:
            await message.answer(
                "❌ Некоректний формат. Використовуйте:\n"
                "• Одна серія: <code>3</code>\n"
                "• Діапазон: <code>4-6</code>"
            )
            return
    else:
        await message.answer(
            "❌ Некоректний формат. Використовуйте:\n"
            "• Одна серія: <code>3</code>\n"
            "• Діапазон: <code>4-6</code>"
        )
        return

    await state.update_data(
        start_episode=start_episode,
        end_episode=end_episode,
        episodes_count=episodes_count,
        received_videos=[]  # Лічильник отриманих відео
    )

    data = await state.get_data()

    if episodes_count == 1:
        await message.answer(
            f"✅ Буде додана серія <b>{start_episode}</b>\n\n"
            f"📺 <b>{data.get('title')}</b>\n"
            f"Сезон {data.get('season')}\n\n"
            f"⚠️ <b>Важливо:</b>\n"
            f"Переслати <b>1 відео</b> з каналу зберігання.\n"
            f"У caption відео має бути:\n"
            f"<code>id:{data.get('series_id')} season:{data.get('season')} episode:{start_episode}</code>\n\n"
            f"📤 Очікую <b>1</b> переслане відео"
        )
    else:
        await message.answer(
            f"✅ Діапазон серій: <b>{start_episode}-{end_episode}</b> ({episodes_count} серій)\n\n"
            f"📺 <b>{data.get('title')}</b>\n"
            f"Сезон {data.get('season')}\n\n"
            f"⚠️ <b>Важливо:</b>\n"
            f"Переслати <b>рівно {episodes_count} відео</b> з каналу зберігання.\n"
            f"У caption кожного відео має бути:\n"
            f"<code>id:{data.get('series_id')} season:{data.get('season')} episode:N</code>\n\n"
            f"📤 Очікую <b>{episodes_count}</b> пересланих відео"
        )

    await state.set_state(AddBatchMovieStates.waiting_for_videos)


def parse_video_caption(caption: str) -> dict:
    """
    Парсить caption відео і витягує id, season, episode

    Формат: id:movieID season:seasonNumber episode:episodeNumber
    """
    if not caption:
        return None

    result = {}

    # Шукаємо id:
    id_match = re.search(r'id:(\S+)', caption)
    if id_match:
        result['id'] = id_match.group(1).strip()

    # Шукаємо season:
    season_match = re.search(r'season:(\d+)', caption)
    if season_match:
        result['season'] = int(season_match.group(1))

    # Шукаємо episode:
    episode_match = re.search(r'episode:(\d+)', caption)
    if episode_match:
        result['episode'] = int(episode_match.group(1))

    # Повертаємо тільки якщо всі поля знайдені
    if 'id' in result and 'season' in result and 'episode' in result:
        return result

    return None


@router.message(AddBatchMovieStates.waiting_for_videos, F.video | F.document)
async def process_batch_videos(message: Message, state: FSMContext, bot: Bot):
    """Обробка пересланих відео для пакетного додавання"""
    data = await state.get_data()

    series_id = data.get("series_id")
    expected_season = data.get("season")
    start_episode = data.get("start_episode")
    end_episode = data.get("end_episode")
    episodes_count = data.get("episodes_count")
    received_videos = data.get("received_videos", [])

    # Перевіряємо що відео переслано з каналу
    if not message.forward_from_chat or message.forward_from_chat.id != config.STORAGE_CHANNEL_ID:
        await message.answer("❌ Відео має бути переслане з каналу зберігання!")
        return

    # Визначаємо тип файлу
    if message.video:
        video_file_id = message.video.file_id
        video_type = "video"
    elif message.document:
        video_file_id = message.document.file_id
        video_type = "document"
    else:
        await message.answer("❌ Некоректний тип файлу.")
        return

    # Парсимо caption
    caption = message.caption or ""
    parsed_data = parse_video_caption(caption)

    if not parsed_data:
        await message.answer(
            f"❌ Не вдалося розпарсити caption відео!\n\n"
            f"Очікуваний формат:\n"
            f"<code>id:{series_id} season:{expected_season} episode:N</code>\n\n"
            f"Отриманий caption:\n<code>{caption}</code>"
        )
        return

    # Перевіряємо ID серіалу
    if parsed_data['id'] != series_id:
        await message.answer(
            f"❌ ID серіалу не співпадає!\n\n"
            f"Очікується: <code>{series_id}</code>\n"
            f"Отримано: <code>{parsed_data['id']}</code>"
        )
        return

    # Перевіряємо сезон
    if parsed_data['season'] != expected_season:
        await message.answer(
            f"❌ Номер сезону не співпадає!\n\n"
            f"Очікується: сезон {expected_season}\n"
            f"Отримано: сезон {parsed_data['season']}"
        )
        return

    # Перевіряємо чи серія в діапазоні
    episode_num = parsed_data['episode']
    if episode_num < start_episode or episode_num > end_episode:
        await message.answer(
            f"❌ Номер серії поза діапазоном!\n\n"
            f"Очікується: {start_episode}-{end_episode}\n"
            f"Отримано: {episode_num}"
        )
        return

    # Перевіряємо чи серія вже додана в цій сесії
    if episode_num in [v['episode'] for v in received_videos]:
        await message.answer(f"⚠️ Серія {episode_num} вже була додана в цій сесії!")
        return

    # Використовуємо lock для синхронізації
    lock_key = f"{series_id}:{expected_season}"
    if lock_key not in batch_upload_locks:
        batch_upload_locks[lock_key] = asyncio.Lock()

    async with batch_upload_locks[lock_key]:
        # Перевіряємо чи серія вже є в базі
        existing_episode = await get_episode(series_id, expected_season, episode_num)
        if existing_episode:
            await message.answer(f"⚠️ Серія {episode_num} вже існує в базі!")
            return

        # Додаємо серію в базу
        try:
            status_msg = await message.answer(f"⏳ Додаю серію {episode_num} в базу...")
            await add_episode_to_series(
                series_id=series_id,
                season=expected_season,
                episode=episode_num,
                video_file_id=video_file_id,
                video_type=video_type
            )
            await status_msg.delete()
            logging.info(f"Episode {episode_num} added to database from forwarded video")
        except Exception as e:
            logging.error(f"Error saving episode {episode_num}: {str(e)}")
            await message.answer(
                f"❌ Помилка при збереженні серії {episode_num}: {str(e)}"
            )
            return

        # Додаємо відео до списку отриманих
        received_videos.append({
            'episode': episode_num,
            'file_id': video_file_id
        })
        await state.update_data(received_videos=received_videos)

        current_count = len(received_videos)

        # Перевіряємо чи всі відео отримані
        if current_count < episodes_count:
            await message.answer(
                f"✅ Серія {episode_num} додана ({current_count}/{episodes_count})\n\n"
                f"📤 Очікую ще <b>{episodes_count - current_count}</b> відео"
            )
        elif current_count == episodes_count:
            # Всі відео отримані
            await update_last_series_added(message.from_user.id, data.get("title"))

            added_episodes = sorted([v['episode'] for v in received_videos])
            episodes_list = ", ".join(map(str, added_episodes))

            await message.answer(
                f"✅ <b>Успішно додано всі {episodes_count} серії!</b>\n\n"
                f"📺 {data.get('title')}\n"
                f"Сезон {expected_season}\n"
                f"Серії: {episodes_list}\n\n"
                f"🎬 /catalog - переглянути каталог\n"
                f"➕ /addBatchMovie - додати ще серії"
            )

            # Очищуємо state
            await state.clear()


@router.message(AddBatchMovieStates.waiting_for_videos, ~F.text.startswith("/"))
async def process_batch_invalid_video(message: Message, state: FSMContext):
    """Обробка некоректного типу повідомлення замість відео"""
    await message.answer(
        "❌ Будь ласка, переслати відео файл з каналу зберігання.\n\n"
        "Якщо хочете скасувати, введіть /cancel"
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """Скасування поточної операції"""
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Немає активних операцій для скасування.")
        return

    await state.clear()
    await message.answer("✅ Операцію скасовано.")
