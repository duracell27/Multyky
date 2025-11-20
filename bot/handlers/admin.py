import asyncio
import logging
import re
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext

from bot.config import config
from bot.states import AddMovieStates, AddBatchMovieStates, DeleteContentStates, EditContentStates, AddSuperBatchMovieStates
from bot.database.movies import (
    add_episode_to_series,
    get_all_series_list,
    get_all_movies_list,
    get_movie_by_id,
    get_season_episodes,
    get_episode,
    get_series_seasons,
    create_series,
    create_movie,
    delete_movie,
    delete_series,
    delete_season,
    delete_episode,
    update_movie_field,
    update_episode_video,
    toggle_content_visibility,
    search_movie_series_names,
    get_all_movie_series_names
)
from bot.database.users import update_last_series_added

router = Router()

# Locks для синхронізації batch upload (уникнення race condition)
batch_upload_locks = {}


def is_admin(user_id: int) -> bool:
    """Перевірка чи користувач є адміністратором"""
    return user_id in config.ADMIN_IDS


# ===============================================
# Додавання одиночного фільму
# ===============================================

@router.message(Command("addMovie"))
async def cmd_add_movie(message: Message, state: FSMContext):
    """Початок процесу додавання фільму"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ Ця команда доступна тільки для адміністраторів.")
        return

    await message.answer(
        "🎬 <b>Додавання нового фільму</b>\n\n"
        "Введіть українську назву фільму:"
    )
    await state.set_state(AddMovieStates.waiting_for_title)


@router.message(AddMovieStates.waiting_for_title, ~F.text.startswith("/"))
async def process_movie_title(message: Message, state: FSMContext):
    """Обробка української назви фільму"""
    title = message.text.strip()

    await state.update_data(title=title)

    # Шукаємо схожі серії фільмів за назвою
    similar_series = await search_movie_series_names(title)

    buttons = []

    # Додаємо знайдені схожі серії (максимум 10)
    for series_name in similar_series[:10]:
        buttons.append([
            InlineKeyboardButton(
                text=f"📁 {series_name}",
                callback_data=f"select_series:{series_name}"
            )
        ])

    # Додаємо варіанти вибору, створення або окремого фільму
    buttons.append([
        InlineKeyboardButton(
            text="🔍 Вибрати з усіх серій",
            callback_data="select_series:browse_all"
        )
    ])
    buttons.append([
        InlineKeyboardButton(
            text="➕ Створити нову серію",
            callback_data="select_series:new"
        )
    ])
    buttons.append([
        InlineKeyboardButton(
            text="🎬 Окремий фільм (без серії)",
            callback_data="select_series:standalone"
        )
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    if similar_series:
        await message.answer(
            f"✅ Назва: <b>{title}</b>\n\n"
            f"🔍 Знайдено схожі серії фільмів. Оберіть серію або створіть нову:",
            reply_markup=keyboard
        )
    else:
        await message.answer(
            f"✅ Назва: <b>{title}</b>\n\n"
            f"Оберіть опцію:",
            reply_markup=keyboard
        )

    await state.set_state(AddMovieStates.choosing_series)


@router.callback_query(AddMovieStates.choosing_series, F.data.startswith("select_series:"))
async def process_series_selection(callback: CallbackQuery, state: FSMContext):
    """Обробка вибору серії фільмів"""
    series_choice = callback.data.split(":", 1)[1]

    if series_choice == "standalone":
        # Фільм без серії
        await state.update_data(series_name=None)
        await callback.message.edit_text(
            "✅ Фільм буде доданий як окремий (без серії)\n\n"
            "Введіть англійську назву фільму:"
        )
        await state.set_state(AddMovieStates.waiting_for_title_en)
        await callback.answer()
    elif series_choice == "new":
        # Створюємо нову серію - запитуємо назву
        await callback.message.edit_text(
            "➕ <b>Створення нової серії</b>\n\n"
            "Введіть назву серії фільмів (наприклад: <code>Шрек</code>, <code>Мадагаскар</code>):"
        )
        # Залишаємося в тому ж стані, чекаємо текст
        await state.update_data(awaiting_new_series_name=True)
        await callback.answer()
    elif series_choice == "browse_all":
        # Показати всі існуючі серії
        all_series = await get_all_movie_series_names()

        if not all_series:
            await callback.answer("📁 Ще немає жодної серії фільмів", show_alert=True)
            return

        # Зберігаємо список серій у стейті для використання індексів
        await state.update_data(all_series_list=all_series)

        buttons = []
        for idx, series_name in enumerate(all_series):
            buttons.append([
                InlineKeyboardButton(
                    text=f"📁 {series_name}",
                    callback_data=f"pickser:{idx}"
                )
            ])

        # Кнопка назад
        buttons.append([
            InlineKeyboardButton(
                text="◀️ Назад",
                callback_data="select_series:back"
            )
        ])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.edit_text(
            "🔍 <b>Оберіть серію фільмів:</b>",
            reply_markup=keyboard
        )
        await callback.answer()
    elif series_choice == "back":
        # Повернутися до початкового меню вибору
        data = await state.get_data()
        title = data.get("title", "")
        similar_series = await search_movie_series_names(title)

        buttons = []
        for series_name in similar_series[:10]:
            buttons.append([
                InlineKeyboardButton(
                    text=f"📁 {series_name}",
                    callback_data=f"select_series:{series_name}"
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                text="🔍 Вибрати з усіх серій",
                callback_data="select_series:browse_all"
            )
        ])
        buttons.append([
            InlineKeyboardButton(
                text="➕ Створити нову серію",
                callback_data="select_series:new"
            )
        ])
        buttons.append([
            InlineKeyboardButton(
                text="🎬 Окремий фільм (без серії)",
                callback_data="select_series:standalone"
            )
        ])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        if similar_series:
            await callback.message.edit_text(
                f"✅ Назва: <b>{title}</b>\n\n"
                f"🔍 Знайдено схожі серії фільмів. Оберіть серію або створіть нову:",
                reply_markup=keyboard
            )
        else:
            await callback.message.edit_text(
                f"✅ Назва: <b>{title}</b>\n\n"
                f"Оберіть опцію:",
                reply_markup=keyboard
            )
        await callback.answer()
    else:
        # Вибрано існуючу серію
        await state.update_data(series_name=series_choice)
        await callback.message.edit_text(
            f"✅ Серія: <b>{series_choice}</b>\n\n"
            "Введіть англійську назву фільму:"
        )
        await state.set_state(AddMovieStates.waiting_for_title_en)
        await callback.answer()


@router.callback_query(AddMovieStates.choosing_series, F.data.startswith("pickser:"))
async def process_pick_series(callback: CallbackQuery, state: FSMContext):
    """Обробка вибору серії зі списку всіх серій за індексом"""
    idx = int(callback.data.split(":", 1)[1])

    data = await state.get_data()
    all_series_list = data.get("all_series_list", [])

    if idx >= len(all_series_list):
        await callback.answer("❌ Помилка: серія не знайдена", show_alert=True)
        return

    series_name = all_series_list[idx]
    await state.update_data(series_name=series_name)

    await callback.message.edit_text(
        f"✅ Серія: <b>{series_name}</b>\n\n"
        "Введіть англійську назву фільму:"
    )

    await state.set_state(AddMovieStates.waiting_for_title_en)
    await callback.answer()


@router.message(AddMovieStates.choosing_series, ~F.text.startswith("/"))
async def process_new_series_name(message: Message, state: FSMContext):
    """Обробка введення назви нової серії"""
    data = await state.get_data()

    # Перевіряємо чи ми чекаємо назву нової серії
    if data.get("awaiting_new_series_name"):
        series_name = message.text.strip()
        await state.update_data(series_name=series_name, awaiting_new_series_name=False)

        await message.answer(
            f"✅ Нова серія: <b>{series_name}</b>\n\n"
            "Введіть англійську назву фільму:"
        )
        await state.set_state(AddMovieStates.waiting_for_title_en)
    else:
        await message.answer(
            "❌ Будь ласка, виберіть опцію за допомогою кнопок вище."
        )


@router.message(AddMovieStates.waiting_for_title_en, ~F.text.startswith("/"))
async def process_movie_title_en(message: Message, state: FSMContext):
    """Обробка англійської назви фільму"""
    title_en = message.text.strip()

    await state.update_data(title_en=title_en)
    await message.answer(
        f"✅ Англійська назва: <b>{title_en}</b>\n\n"
        "Введіть рік випуску (наприклад: <code>2015</code>):"
    )
    await state.set_state(AddMovieStates.waiting_for_year)


@router.message(AddMovieStates.waiting_for_year, ~F.text.startswith("/"))
async def process_movie_year(message: Message, state: FSMContext):
    """Обробка року випуску"""
    try:
        year = int(message.text.strip())
        if year < 1900 or year > 2100:
            await message.answer("❌ Введіть коректний рік (1900-2100):")
            return
    except ValueError:
        await message.answer("❌ Введіть рік числом (наприклад: 2015):")
        return

    await state.update_data(year=year)
    await message.answer(
        f"✅ Рік: <b>{year}</b>\n\n"
        "Введіть IMDB рейтинг (наприклад: <code>7.5</code>):"
    )
    await state.set_state(AddMovieStates.waiting_for_imdb)


@router.message(AddMovieStates.waiting_for_imdb, ~F.text.startswith("/"))
async def process_movie_imdb(message: Message, state: FSMContext):
    """Обробка IMDB рейтингу"""
    try:
        imdb = float(message.text.strip())
        if imdb < 0 or imdb > 10:
            await message.answer("❌ IMDB рейтинг має бути від 0 до 10:")
            return
    except ValueError:
        await message.answer("❌ Введіть рейтинг числом (наприклад: 7.5):")
        return

    await state.update_data(imdb=imdb)
    await message.answer(
        f"✅ IMDB: <b>{imdb}</b>\n\n"
        "Тепер переслати постер (фото) з каналу зберігання:"
    )
    await state.set_state(AddMovieStates.waiting_for_poster)


@router.message(AddMovieStates.waiting_for_poster, F.photo)
async def process_movie_poster(message: Message, state: FSMContext):
    """Обробка постера фільму"""
    # Перевіряємо що фото переслано з каналу зберігання
    if not message.forward_from_chat or message.forward_from_chat.id != config.STORAGE_CHANNEL_ID:
        await message.answer("❌ Постер має бути пересланий з каналу зберігання!")
        return

    poster_file_id = message.photo[-1].file_id
    await state.update_data(poster_file_id=poster_file_id)

    await message.answer(
        "✅ Постер отримано!\n\n"
        "Тепер переслати відео фільму з каналу зберігання:"
    )
    await state.set_state(AddMovieStates.waiting_for_video)


@router.message(AddMovieStates.waiting_for_poster, ~F.text.startswith("/"))
async def process_movie_poster_invalid(message: Message, state: FSMContext):
    """Обробка некоректного повідомлення замість постера"""
    await message.answer(
        "❌ Будь ласка, переслати фото (постер) з каналу зберігання.\n\n"
        "Якщо хочете скасувати, введіть /cancel"
    )


@router.message(AddMovieStates.waiting_for_video, F.video | F.document)
async def process_movie_video(message: Message, state: FSMContext):
    """Обробка відео фільму"""
    # Перевіряємо що відео переслано з каналу зберігання
    if not message.forward_from_chat or message.forward_from_chat.id != config.STORAGE_CHANNEL_ID:
        await message.answer("❌ Відео має бути переслане з каналу зберігання!")
        return

    # Визначаємо тип файлу та отримуємо розмір
    if message.video:
        video_file_id = message.video.file_id
        video_type = "video"
        file_size = message.video.file_size or 0
        duration = message.video.duration or 0
    elif message.document:
        video_file_id = message.document.file_id
        video_type = "document"
        file_size = message.document.file_size or 0
        duration = 0  # У document немає duration
    else:
        await message.answer("❌ Некоректний тип файлу.")
        return

    data = await state.get_data()

    # Створюємо фільм в базі
    try:
        movie = await create_movie(
            title=data["title"],
            title_en=data["title_en"],
            year=data["year"],
            imdb_rating=data["imdb"],
            poster_file_id=data["poster_file_id"],
            video_file_id=video_file_id,
            video_type=video_type,
            added_by=message.from_user.id,
            file_size=file_size,
            duration=duration,
            series_name=data.get("series_name")
        )

        movie_id = str(movie["_id"])

        series_info = ""
        if data.get("series_name"):
            series_info = f"📁 Серія: {data['series_name']}\n"

        await message.answer(
            f"✅ <b>Фільм успішно додано!</b>\n\n"
            f"🎬 <b>{data['title']}</b>\n"
            f"{series_info}"
            f"📅 Рік: {data['year']}\n"
            f"⭐️ IMDB: {data['imdb']}\n"
            f"🆔 ID: <code>{movie_id}</code>\n\n"
            f"🎬 /catalog - переглянути каталог\n"
            f"➕ /addMovie - додати ще фільм"
        )

        await state.clear()

    except Exception as e:
        logging.error(f"Error creating movie: {str(e)}")
        await message.answer(f"❌ Помилка при створенні фільму: {str(e)}")
        await state.clear()


@router.message(AddMovieStates.waiting_for_video, ~F.text.startswith("/"))
async def process_movie_video_invalid(message: Message, state: FSMContext):
    """Обробка некоректного повідомлення замість відео"""
    await message.answer(
        "❌ Будь ласка, переслати відео файл з каналу зберігання.\n\n"
        "Якщо хочете скасувати, введіть /cancel"
    )


# ===============================================
# Пакетне додавання серій (Batch Upload)
# ===============================================

@router.message(Command("addBatchMovie"))
async def cmd_add_batch_movie(message: Message, state: FSMContext):
    """Початок процесу пакетного додавання серій"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ Ця команда доступна тільки для адміністраторів.")
        return

    # Отримуємо список серіалів (включно з прихованими для адмінів)
    series_list = await get_all_series_list(include_hidden=True)

    # Створюємо кнопки для вибору серіалу (тільки назва)
    buttons = []
    if series_list:
        for series in series_list:
            series_id = str(series["_id"])
            buttons.append([
                InlineKeyboardButton(
                    text=f"📺 {series['title']}",
                    callback_data=f"sel_series:{series_id}"
                )
            ])

    # Додаємо кнопку для створення нового серіалу
    buttons.append([
        InlineKeyboardButton(
            text="➕ Створити новий серіал",
            callback_data="create_new_series"
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


# ===============================================
# Створення нового серіалу
# ===============================================

@router.callback_query(AddBatchMovieStates.choosing_existing_series, F.data == "create_new_series")
async def start_create_new_series(callback: CallbackQuery, state: FSMContext):
    """Початок створення нового серіалу"""
    await callback.message.edit_text(
        "➕ <b>Створення нового серіалу</b>\n\n"
        "Введіть українську назву серіалу:"
    )
    await state.set_state(AddBatchMovieStates.waiting_for_new_series_title)
    await callback.answer()


@router.message(AddBatchMovieStates.waiting_for_new_series_title, ~F.text.startswith("/"))
async def process_new_series_title(message: Message, state: FSMContext):
    """Обробка української назви серіалу"""
    title = message.text.strip()

    await state.update_data(new_series_title=title)
    await message.answer(
        f"✅ Назва: <b>{title}</b>\n\n"
        "Введіть англійську назву серіалу:"
    )
    await state.set_state(AddBatchMovieStates.waiting_for_new_series_title_en)


@router.message(AddBatchMovieStates.waiting_for_new_series_title_en, ~F.text.startswith("/"))
async def process_new_series_title_en(message: Message, state: FSMContext):
    """Обробка англійської назви серіалу"""
    title_en = message.text.strip()

    await state.update_data(new_series_title_en=title_en)
    await message.answer(
        f"✅ Англійська назва: <b>{title_en}</b>\n\n"
        "Введіть рік випуску (наприклад: <code>2012</code>):"
    )
    await state.set_state(AddBatchMovieStates.waiting_for_new_series_year)


@router.message(AddBatchMovieStates.waiting_for_new_series_year, ~F.text.startswith("/"))
async def process_new_series_year(message: Message, state: FSMContext):
    """Обробка року випуску"""
    try:
        year = int(message.text.strip())
        if year < 1900 or year > 2100:
            await message.answer("❌ Введіть коректний рік (1900-2100):")
            return
    except ValueError:
        await message.answer("❌ Введіть рік числом (наприклад: 2012):")
        return

    await state.update_data(new_series_year=year)
    await message.answer(
        f"✅ Рік: <b>{year}</b>\n\n"
        "Введіть IMDB рейтинг (наприклад: <code>8.9</code>):"
    )
    await state.set_state(AddBatchMovieStates.waiting_for_new_series_imdb)


@router.message(AddBatchMovieStates.waiting_for_new_series_imdb, ~F.text.startswith("/"))
async def process_new_series_imdb(message: Message, state: FSMContext):
    """Обробка IMDB рейтингу"""
    try:
        imdb = float(message.text.strip())
        if imdb < 0 or imdb > 10:
            await message.answer("❌ IMDB рейтинг має бути від 0 до 10:")
            return
    except ValueError:
        await message.answer("❌ Введіть рейтинг числом (наприклад: 8.9):")
        return

    await state.update_data(new_series_imdb=imdb)
    await message.answer(
        f"✅ IMDB: <b>{imdb}</b>\n\n"
        "Тепер переслати постер (фото) з каналу зберігання:"
    )
    await state.set_state(AddBatchMovieStates.waiting_for_new_series_poster)


@router.message(AddBatchMovieStates.waiting_for_new_series_poster, F.photo)
async def process_new_series_poster(message: Message, state: FSMContext, bot: Bot):
    """Обробка постера серіалу"""
    from bot.config import config

    # Перевіряємо що фото переслано з каналу зберігання
    if not message.forward_from_chat or message.forward_from_chat.id != config.STORAGE_CHANNEL_ID:
        await message.answer("❌ Постер має бути пересланий з каналу зберігання!")
        return

    poster_file_id = message.photo[-1].file_id
    data = await state.get_data()

    # Створюємо серіал в базі
    try:
        series = await create_series(
            title=data["new_series_title"],
            title_en=data["new_series_title_en"],
            year=data["new_series_year"],
            imdb_rating=data["new_series_imdb"],
            poster_file_id=poster_file_id,
            added_by=message.from_user.id
        )

        series_id = str(series["_id"])

        await state.update_data(
            series_id=series_id,
            title=data["new_series_title"]
        )

        await message.answer(
            f"✅ <b>Серіал створено!</b>\n\n"
            f"📺 <b>{data['new_series_title']}</b>\n"
            f"🆔 ID: <code>{series_id}</code>\n\n"
            f"━━━━━━━━━━━━━━━━\n\n"
            f"Введіть номер сезону (наприклад: <code>1</code>):"
        )
        await state.set_state(AddBatchMovieStates.waiting_for_season)

    except Exception as e:
        logging.error(f"Error creating series: {str(e)}")
        await message.answer(f"❌ Помилка при створенні серіалу: {str(e)}")
        await state.clear()


@router.message(AddBatchMovieStates.waiting_for_new_series_poster, ~F.text.startswith("/"))
async def process_new_series_poster_invalid(message: Message, state: FSMContext):
    """Обробка некоректного повідомлення замість постера"""
    await message.answer(
        "❌ Будь ласка, переслати фото (постер) з каналу зберігання.\n\n"
        "Якщо хочете скасувати, введіть /cancel"
    )


# ===============================================
# Додавання епізодів
# ===============================================

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

    # Визначаємо тип файлу та отримуємо розмір
    if message.video:
        video_file_id = message.video.file_id
        video_type = "video"
        file_size = message.video.file_size or 0
        duration = message.video.duration or 0
    elif message.document:
        video_file_id = message.document.file_id
        video_type = "document"
        file_size = message.document.file_size or 0
        duration = 0  # У document немає duration
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
            await add_episode_to_series(
                series_id=series_id,
                season=expected_season,
                episode=episode_num,
                video_file_id=video_file_id,
                video_type=video_type,
                file_size=file_size,
                duration=duration
            )
            logging.info(f"Episode {episode_num} added to database from forwarded video (size: {file_size} bytes)")
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
            # Відправляємо прогрес тільки кожні 5 серій або при першій серії (щоб уникнути rate limit)
            if current_count == 1 or current_count % 5 == 0:
                await message.answer(
                    f"📊 <b>Прогрес:</b> {current_count}/{episodes_count} серій додано\n\n"
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


# ===============================================
# Супер пакетне додавання серій (Auto-detect season/episode)
# ===============================================

@router.message(Command("addSuperBatchMovie"))
async def cmd_add_super_batch_movie(message: Message, state: FSMContext):
    """Початок процесу супер пакетного додавання серій з автоматичним визначенням сезону/епізоду"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ Ця команда доступна тільки для адміністраторів.")
        return

    # Отримуємо список серіалів (включно з прихованими для адмінів)
    series_list = await get_all_series_list(include_hidden=True)

    # Створюємо кнопки для вибору серіалу
    buttons = []
    if series_list:
        for series in series_list:
            series_id = str(series["_id"])
            buttons.append([
                InlineKeyboardButton(
                    text=f"📺 {series['title']}",
                    callback_data=f"super_sel_series:{series_id}"
                )
            ])

    # Додаємо кнопку для створення нового серіалу
    buttons.append([
        InlineKeyboardButton(
            text="➕ Створити новий серіал",
            callback_data="super_create_new_series"
        )
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(
        "🚀 <b>Супер пакетне додавання серій</b>\n\n"
        "Ця команда автоматично визначає сезон і епізод з caption відео.\n\n"
        "📺 <b>Виберіть серіал для додавання серій:</b>",
        reply_markup=keyboard
    )
    await state.set_state(AddSuperBatchMovieStates.choosing_existing_series)


@router.callback_query(AddSuperBatchMovieStates.choosing_existing_series, F.data.startswith("super_sel_series:"))
async def process_super_series_selection(callback: CallbackQuery, state: FSMContext):
    """Обробка вибору серіалу для супер пакетного додавання"""
    series_id = callback.data.split(":", 1)[1]

    # Отримуємо інформацію про серіал
    series_info = await get_movie_by_id(series_id)

    if not series_info:
        await callback.answer("❌ Серіал не знайдено", show_alert=True)
        return

    # Зберігаємо інформацію про серіал
    await state.update_data(
        series_id=series_id,
        title=series_info["title"],
        received_videos={}  # Словник для відстеження доданих відео: {(season, episode): file_id}
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
        f"🚀 <b>Супер режим активовано!</b>\n\n"
        f"📤 Надсилайте відео з каналу зберігання.\n"
        f"Кожне відео має містити caption:\n"
        f"<code>id:{series_id} season:N episode:M</code>\n\n"
        f"⚡️ <b>Переваги:</b>\n"
        f"• Автоматичне визначення сезону та епізоду\n"
        f"• Можна додавати серії з різних сезонів\n"
        f"• Надсилайте відео по одному або кілька підряд\n\n"
        f"Щоб завершити, надішліть: <code>готово</code> або <code>/done</code>"
    )
    await state.set_state(AddSuperBatchMovieStates.waiting_for_videos)
    await callback.answer()


# ===============================================
# Створення нового серіалу для супер пакетного режиму
# ===============================================

@router.callback_query(AddSuperBatchMovieStates.choosing_existing_series, F.data == "super_create_new_series")
async def start_create_new_super_series(callback: CallbackQuery, state: FSMContext):
    """Початок створення нового серіалу для супер режиму"""
    await callback.message.edit_text(
        "➕ <b>Створення нового серіалу (Супер режим)</b>\n\n"
        "Введіть українську назву серіалу:"
    )
    await state.set_state(AddSuperBatchMovieStates.waiting_for_new_series_title)
    await callback.answer()


@router.message(AddSuperBatchMovieStates.waiting_for_new_series_title, ~F.text.startswith("/"))
async def process_super_new_series_title(message: Message, state: FSMContext):
    """Обробка української назви серіалу для супер режиму"""
    title = message.text.strip()

    await state.update_data(new_series_title=title)
    await message.answer(
        f"✅ Назва: <b>{title}</b>\n\n"
        "Введіть англійську назву серіалу:"
    )
    await state.set_state(AddSuperBatchMovieStates.waiting_for_new_series_title_en)


@router.message(AddSuperBatchMovieStates.waiting_for_new_series_title_en, ~F.text.startswith("/"))
async def process_super_new_series_title_en(message: Message, state: FSMContext):
    """Обробка англійської назви серіалу для супер режиму"""
    title_en = message.text.strip()

    await state.update_data(new_series_title_en=title_en)
    await message.answer(
        f"✅ Англійська назва: <b>{title_en}</b>\n\n"
        "Введіть рік випуску (наприклад: <code>2012</code>):"
    )
    await state.set_state(AddSuperBatchMovieStates.waiting_for_new_series_year)


@router.message(AddSuperBatchMovieStates.waiting_for_new_series_year, ~F.text.startswith("/"))
async def process_super_new_series_year(message: Message, state: FSMContext):
    """Обробка року випуску для супер режиму"""
    try:
        year = int(message.text.strip())
        if year < 1900 or year > 2100:
            await message.answer("❌ Введіть коректний рік (1900-2100):")
            return
    except ValueError:
        await message.answer("❌ Введіть рік числом (наприклад: 2012):")
        return

    await state.update_data(new_series_year=year)
    await message.answer(
        f"✅ Рік: <b>{year}</b>\n\n"
        "Введіть IMDB рейтинг (наприклад: <code>8.9</code>):"
    )
    await state.set_state(AddSuperBatchMovieStates.waiting_for_new_series_imdb)


@router.message(AddSuperBatchMovieStates.waiting_for_new_series_imdb, ~F.text.startswith("/"))
async def process_super_new_series_imdb(message: Message, state: FSMContext):
    """Обробка IMDB рейтингу для супер режиму"""
    try:
        imdb_rating = float(message.text.strip().replace(',', '.'))
        if imdb_rating < 0 or imdb_rating > 10:
            await message.answer("❌ Рейтинг має бути від 0 до 10:")
            return
    except ValueError:
        await message.answer("❌ Введіть число (наприклад: 8.9):")
        return

    await state.update_data(new_series_imdb=imdb_rating)
    await message.answer(
        f"✅ IMDB рейтинг: <b>{imdb_rating}</b>\n\n"
        "Надішліть постер серіалу (фото):"
    )
    await state.set_state(AddSuperBatchMovieStates.waiting_for_new_series_poster)


@router.message(AddSuperBatchMovieStates.waiting_for_new_series_poster, F.photo)
async def process_super_new_series_poster(message: Message, state: FSMContext):
    """Обробка постера для нового серіалу (супер режим)"""
    poster_file_id = message.photo[-1].file_id
    data = await state.get_data()

    # Створюємо новий серіал
    try:
        series_id = await create_series(
            title=data["new_series_title"],
            title_en=data["new_series_title_en"],
            year=data["new_series_year"],
            imdb_rating=data["new_series_imdb"],
            poster_file_id=poster_file_id,
            added_by=message.from_user.id
        )

        # Зберігаємо ID серіалу
        await state.update_data(
            series_id=str(series_id),
            title=data["new_series_title"],
            received_videos={}
        )

        await message.answer(
            f"✅ <b>Серіал створено!</b>\n\n"
            f"📺 <b>{data['new_series_title']}</b>\n"
            f"🆔 ID: <code>{series_id}</code>\n\n"
            f"━━━━━━━━━━━━━━━━\n\n"
            f"🚀 <b>Супер режим активовано!</b>\n\n"
            f"📤 Надсилайте відео з каналу зберігання.\n"
            f"Кожне відео має містити caption:\n"
            f"<code>id:{series_id} season:N episode:M</code>\n\n"
            f"⚡️ <b>Переваги:</b>\n"
            f"• Автоматичне визначення сезону та епізоду\n"
            f"• Можна додавати серії з різних сезонів\n"
            f"• Надсилайте відео по одному або кілька підряд\n\n"
            f"Щоб завершити, надішліть: <code>готово</code> або <code>/done</code>"
        )

        await state.set_state(AddSuperBatchMovieStates.waiting_for_videos)

    except Exception as e:
        logging.error(f"Error creating series: {str(e)}")
        await message.answer(f"❌ Помилка при створенні серіалу: {str(e)}")
        await state.clear()


@router.message(AddSuperBatchMovieStates.waiting_for_new_series_poster)
async def process_super_invalid_poster(message: Message, state: FSMContext):
    """Обробка некоректного типу замість постера"""
    await message.answer("❌ Будь ласка, надішліть фото постера.")


# ===============================================
# Обробка відео для супер пакетного режиму
# ===============================================

@router.message(AddSuperBatchMovieStates.waiting_for_videos, F.video | F.document)
async def process_super_batch_videos(message: Message, state: FSMContext, bot: Bot):
    """Обробка пересланих відео для супер пакетного додавання з автоматичним визначенням сезону/епізоду"""
    data = await state.get_data()

    series_id = data.get("series_id")
    received_videos = data.get("received_videos", {})

    # Перевіряємо що відео переслано з каналу
    if not message.forward_from_chat or message.forward_from_chat.id != config.STORAGE_CHANNEL_ID:
        await message.answer("❌ Відео має бути переслане з каналу зберігання!")
        return

    # Визначаємо тип файлу та отримуємо розмір
    if message.video:
        video_file_id = message.video.file_id
        video_type = "video"
        file_size = message.video.file_size or 0
        duration = message.video.duration or 0
    elif message.document:
        video_file_id = message.document.file_id
        video_type = "document"
        file_size = message.document.file_size or 0
        duration = 0
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
            f"<code>id:{series_id} season:N episode:M</code>\n\n"
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

    season = parsed_data['season']
    episode_num = parsed_data['episode']

    # Перевіряємо чи серія вже додана в цій сесії
    video_key = f"{season}:{episode_num}"
    if video_key in received_videos:
        await message.answer(f"⚠️ Серія S{season}E{episode_num} вже була додана в цій сесії!")
        return

    # Використовуємо lock для синхронізації
    lock_key = f"{series_id}:{season}"
    if lock_key not in batch_upload_locks:
        batch_upload_locks[lock_key] = asyncio.Lock()

    async with batch_upload_locks[lock_key]:
        # Перевіряємо чи серія вже є в базі
        existing_episode = await get_episode(series_id, season, episode_num)
        if existing_episode:
            await message.answer(f"⏭️ Серія S{season}E{episode_num} вже існує, пропускаю...")
            return

        # Додаємо серію в базу
        try:
            await add_episode_to_series(
                series_id=series_id,
                season=season,
                episode=episode_num,
                video_file_id=video_file_id,
                video_type=video_type,
                file_size=file_size,
                duration=duration
            )
            logging.info(f"Episode S{season}E{episode_num} added to database in super batch mode (size: {file_size} bytes)")
        except Exception as e:
            logging.error(f"Error saving episode S{season}E{episode_num}: {str(e)}")
            await message.answer(
                f"❌ Помилка при збереженні серії S{season}E{episode_num}: {str(e)}"
            )
            return

        # Додаємо відео до списку отриманих
        received_videos[video_key] = video_file_id
        await state.update_data(received_videos=received_videos)

        current_count = len(received_videos)

        # Відправляємо прогрес тільки кожні 10 серій (щоб уникнути rate limit)
        if current_count % 10 == 0:
            # Групуємо серії по сезонах
            seasons_summary = {}
            for key in received_videos.keys():
                s, e = key.split(":")
                if s not in seasons_summary:
                    seasons_summary[s] = []
                seasons_summary[s].append(int(e))

            # Формуємо повідомлення про додані серії
            summary_lines = []
            for s in sorted(seasons_summary.keys(), key=int):
                episodes = sorted(seasons_summary[s])
                summary_lines.append(f"   Сезон {s}: {len(episodes)} серій")

            summary_text = "\n".join(summary_lines)

            await message.answer(
                f"📊 <b>Прогрес: {current_count} серій додано</b>\n\n"
                f"{summary_text}\n\n"
                f"📤 Продовжуйте надсилати відео або надішліть <code>готово</code> для завершення"
            )


@router.message(AddSuperBatchMovieStates.waiting_for_videos, F.text.regexp(r"(?i)^(готово|done|/done)$"))
async def finish_super_batch_upload(message: Message, state: FSMContext):
    """Завершення супер пакетного додавання"""
    data = await state.get_data()
    received_videos = data.get("received_videos", {})

    if not received_videos:
        await message.answer(
            "⚠️ Не додано жодної серії.\n\n"
            "Операцію скасовано."
        )
        await state.clear()
        return

    # Групуємо серії по сезонах
    seasons_summary = {}
    for key in received_videos.keys():
        s, e = key.split(":")
        if s not in seasons_summary:
            seasons_summary[s] = []
        seasons_summary[s].append(int(e))

    # Формуємо детальне повідомлення
    summary_lines = []
    total_count = 0
    for s in sorted(seasons_summary.keys(), key=int):
        episodes = sorted(seasons_summary[s])
        total_count += len(episodes)
        episodes_str = ", ".join(map(str, episodes))
        summary_lines.append(f"   • Сезон {s}: {len(episodes)} серій ({episodes_str})")

    summary_text = "\n".join(summary_lines)

    await update_last_series_added(message.from_user.id, data.get("title"))

    await message.answer(
        f"🎉 <b>Супер пакетне додавання завершено!</b>\n\n"
        f"📺 <b>{data.get('title')}</b>\n\n"
        f"✅ <b>Успішно додано {total_count} серій:</b>\n\n"
        f"{summary_text}\n\n"
        f"🎬 /catalog - переглянути каталог\n"
        f"🚀 /addSuperBatchMovie - додати ще серії"
    )

    # Очищуємо state
    await state.clear()


@router.message(AddSuperBatchMovieStates.waiting_for_videos, ~F.text.startswith("/"))
async def process_super_batch_invalid_message(message: Message, state: FSMContext):
    """Обробка некоректного типу повідомлення в супер режимі"""
    await message.answer(
        "❌ Будь ласка, переслати відео файл з каналу зберігання.\n\n"
        "Щоб завершити додавання, надішліть: <code>готово</code> або <code>/done</code>\n"
        "Для скасування: /cancel"
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


# ===============================================
# Видалення контенту
# ===============================================

@router.message(Command("deleteContent"))
async def cmd_delete_content(message: Message, state: FSMContext):
    """Початок процесу видалення контенту"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ Ця команда доступна тільки для адміністраторів.")
        return

    buttons = [
        [InlineKeyboardButton(text="🎬 Видалити фільм", callback_data="deltype:movie")],
        [InlineKeyboardButton(text="📺 Видалити серіал", callback_data="deltype:series")],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="deltype:cancel")]
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(
        "🗑 <b>Видалення контенту</b>\n\n"
        "Оберіть тип контенту для видалення:",
        reply_markup=keyboard
    )
    await state.set_state(DeleteContentStates.choosing_content_type)


@router.callback_query(DeleteContentStates.choosing_content_type, F.data.startswith("deltype:"))
async def process_delete_type(callback: CallbackQuery, state: FSMContext):
    """Обробка вибору типу контенту для видалення"""
    content_type = callback.data.split(":", 1)[1]

    if content_type == "cancel":
        await callback.message.edit_text("❌ Видалення скасовано.")
        await state.clear()
        await callback.answer()
        return

    await state.update_data(delete_content_type=content_type)

    if content_type == "movie":
        # Отримуємо список фільмів (включно з прихованими для адмінів)
        movies_list = await get_all_movies_list(include_hidden=True)

        if not movies_list:
            await callback.message.edit_text("❌ Немає фільмів для видалення.")
            await state.clear()
            await callback.answer()
            return

        # Створюємо кнопки для вибору фільму
        buttons = []
        for movie in movies_list[:20]:  # Обмежуємо до 20 для уникнення великих меню
            movie_id = str(movie["_id"])
            is_hidden = movie.get("is_hidden", False)
            hidden_emoji = "🔒 " if is_hidden else ""
            buttons.append([
                InlineKeyboardButton(
                    text=f"{hidden_emoji}🎬 {movie['title']} ({movie['year']})",
                    callback_data=f"delmovie:{movie_id}"
                )
            ])

        buttons.append([
            InlineKeyboardButton(text="❌ Скасувати", callback_data="delmovie:cancel")
        ])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        await callback.message.edit_text(
            "🎬 <b>Виберіть фільм для видалення:</b>\n\n"
            f"<i>Всього фільмів: {len(movies_list)}</i>",
            reply_markup=keyboard
        )
        await state.set_state(DeleteContentStates.choosing_content)

    elif content_type == "series":
        # Отримуємо список серіалів (включно з прихованими для адмінів)
        series_list = await get_all_series_list(include_hidden=True)

        if not series_list:
            await callback.message.edit_text("❌ Немає серіалів для видалення.")
            await state.clear()
            await callback.answer()
            return

        # Створюємо кнопки для вибору серіалу
        buttons = []
        for series in series_list[:20]:
            series_id = str(series["_id"])
            is_hidden = series.get("is_hidden", False)
            hidden_emoji = "🔒 " if is_hidden else ""
            buttons.append([
                InlineKeyboardButton(
                    text=f"{hidden_emoji}📺 {series['title']}",
                    callback_data=f"delseries:{series_id}"
                )
            ])

        buttons.append([
            InlineKeyboardButton(text="❌ Скасувати", callback_data="delseries:cancel")
        ])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        await callback.message.edit_text(
            "📺 <b>Виберіть серіал:</b>",
            reply_markup=keyboard
        )
        await state.set_state(DeleteContentStates.choosing_content)

    await callback.answer()


@router.callback_query(DeleteContentStates.choosing_content, F.data.startswith("delmovie:"))
async def process_delete_movie_selection(callback: CallbackQuery, state: FSMContext):
    """Обробка вибору фільму для видалення"""
    movie_id = callback.data.split(":", 1)[1]

    if movie_id == "cancel":
        await callback.message.edit_text("❌ Видалення скасовано.")
        await state.clear()
        await callback.answer()
        return

    # Отримуємо інформацію про фільм
    movie = await get_movie_by_id(movie_id)

    if not movie:
        await callback.answer("❌ Фільм не знайдено", show_alert=True)
        await state.clear()
        return

    await state.update_data(delete_movie_id=movie_id)

    # Показуємо підтвердження
    buttons = [
        [InlineKeyboardButton(text="✅ Так, видалити", callback_data=f"confirm_del_movie:{movie_id}")],
        [InlineKeyboardButton(text="❌ Ні, скасувати", callback_data="confirm_del_movie:cancel")]
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text(
        f"⚠️ <b>Підтвердження видалення</b>\n\n"
        f"🎬 <b>{movie['title']}</b>\n"
        f"📅 Рік: {movie['year']}\n"
        f"⭐️ IMDB: {movie['imdb_rating']}\n\n"
        f"Ви впевнені, що хочете видалити цей фільм?",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_del_movie:"))
async def process_confirm_delete_movie(callback: CallbackQuery, state: FSMContext):
    """Підтвердження видалення фільму"""
    movie_id = callback.data.split(":", 1)[1]

    if movie_id == "cancel":
        await callback.message.edit_text("❌ Видалення скасовано.")
        await state.clear()
        await callback.answer()
        return

    # Видаляємо фільм
    success = await delete_movie(movie_id)

    if success:
        await callback.message.edit_text("✅ Фільм успішно видалено!")
        await callback.answer("✅ Фільм видалено")
    else:
        await callback.message.edit_text("❌ Помилка при видаленні фільму.")
        await callback.answer("❌ Помилка", show_alert=True)

    await state.clear()


@router.callback_query(DeleteContentStates.choosing_content, F.data.startswith("delseries:"))
async def process_delete_series_selection(callback: CallbackQuery, state: FSMContext):
    """Обробка вибору серіалу"""
    series_id = callback.data.split(":", 1)[1]

    if series_id == "cancel":
        await callback.message.edit_text("❌ Видалення скасовано.")
        await state.clear()
        await callback.answer()
        return

    # Отримуємо інформацію про серіал
    series = await get_movie_by_id(series_id)

    if not series:
        await callback.answer("❌ Серіал не знайдено", show_alert=True)
        await state.clear()
        return

    await state.update_data(delete_series_id=series_id, series_title=series['title'])

    # Показуємо опції видалення
    buttons = [
        [InlineKeyboardButton(text="🗑 Видалити весь серіал", callback_data=f"delopt:whole:{series_id}")],
        [InlineKeyboardButton(text="📺 Видалити сезон", callback_data=f"delopt:season:{series_id}")],
        [InlineKeyboardButton(text="🎬 Видалити серію", callback_data=f"delopt:episode:{series_id}")],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="delopt:cancel")]
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text(
        f"📺 <b>{series['title']}</b>\n\n"
        f"Оберіть опцію видалення:",
        reply_markup=keyboard
    )
    await state.set_state(DeleteContentStates.choosing_delete_option)
    await callback.answer()


@router.callback_query(DeleteContentStates.choosing_delete_option, F.data.startswith("delopt:"))
async def process_delete_option(callback: CallbackQuery, state: FSMContext):
    """Обробка опції видалення серіалу"""
    parts = callback.data.split(":", 2)
    option = parts[1]

    if option == "cancel":
        await callback.message.edit_text("❌ Видалення скасовано.")
        await state.clear()
        await callback.answer()
        return

    series_id = parts[2]
    data = await state.get_data()
    series_title = data.get('series_title')

    if option == "whole":
        # Підтвердження видалення всього серіалу
        buttons = [
            [InlineKeyboardButton(text="✅ Так, видалити весь серіал", callback_data=f"confirm_del_whole:{series_id}")],
            [InlineKeyboardButton(text="❌ Ні, скасувати", callback_data="confirm_del_whole:cancel")]
        ]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        await callback.message.edit_text(
            f"⚠️ <b>Підтвердження видалення</b>\n\n"
            f"📺 <b>{series_title}</b>\n\n"
            f"Ви впевнені, що хочете видалити ВЕСЬ серіал з усіма сезонами та серіями?",
            reply_markup=keyboard
        )

    elif option == "season":
        # Показуємо список сезонів
        series = await get_movie_by_id(series_id)
        if not series or "seasons" not in series or not series["seasons"]:
            await callback.answer("❌ У серіалу немає сезонів", show_alert=True)
            return

        seasons = sorted([int(s) for s in series["seasons"].keys()])
        buttons = []
        for season_num in seasons:
            episode_count = len(series["seasons"][str(season_num)])
            buttons.append([
                InlineKeyboardButton(
                    text=f"Сезон {season_num} ({episode_count} серій)",
                    callback_data=f"delseason:{series_id}:{season_num}"
                )
            ])

        buttons.append([
            InlineKeyboardButton(text="❌ Скасувати", callback_data="delseason:cancel")
        ])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        await callback.message.edit_text(
            f"📺 <b>{series_title}</b>\n\n"
            f"Оберіть сезон для видалення:",
            reply_markup=keyboard
        )
        await state.set_state(DeleteContentStates.choosing_season)

    elif option == "episode":
        # Показуємо список сезонів для вибору серії
        series = await get_movie_by_id(series_id)
        if not series or "seasons" not in series or not series["seasons"]:
            await callback.answer("❌ У серіалу немає сезонів", show_alert=True)
            return

        seasons = sorted([int(s) for s in series["seasons"].keys()])
        buttons = []
        for season_num in seasons:
            episode_count = len(series["seasons"][str(season_num)])
            buttons.append([
                InlineKeyboardButton(
                    text=f"Сезон {season_num} ({episode_count} серій)",
                    callback_data=f"delepisode_season:{series_id}:{season_num}"
                )
            ])

        buttons.append([
            InlineKeyboardButton(text="❌ Скасувати", callback_data="delepisode_season:cancel")
        ])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        await callback.message.edit_text(
            f"📺 <b>{series_title}</b>\n\n"
            f"Спочатку оберіть сезон:",
            reply_markup=keyboard
        )
        await state.set_state(DeleteContentStates.choosing_season)

    await callback.answer()


@router.callback_query(F.data.startswith("confirm_del_whole:"))
async def process_confirm_delete_whole_series(callback: CallbackQuery, state: FSMContext):
    """Підтвердження видалення всього серіалу"""
    series_id = callback.data.split(":", 1)[1]

    if series_id == "cancel":
        await callback.message.edit_text("❌ Видалення скасовано.")
        await state.clear()
        await callback.answer()
        return

    # Видаляємо серіал
    success = await delete_series(series_id)

    if success:
        await callback.message.edit_text("✅ Серіал успішно видалено!")
        await callback.answer("✅ Серіал видалено")
    else:
        await callback.message.edit_text("❌ Помилка при видаленні серіалу.")
        await callback.answer("❌ Помилка", show_alert=True)

    await state.clear()


@router.callback_query(DeleteContentStates.choosing_season, F.data.startswith("delseason:"))
async def process_delete_season_selection(callback: CallbackQuery, state: FSMContext):
    """Обробка вибору сезону для видалення"""
    parts = callback.data.split(":", 2)

    if parts[1] == "cancel":
        await callback.message.edit_text("❌ Видалення скасовано.")
        await state.clear()
        await callback.answer()
        return

    series_id = parts[1]
    season_num = int(parts[2])

    data = await state.get_data()
    series_title = data.get('series_title')

    # Підтвердження видалення сезону
    buttons = [
        [InlineKeyboardButton(text="✅ Так, видалити", callback_data=f"confirm_del_season:{series_id}:{season_num}")],
        [InlineKeyboardButton(text="❌ Ні, скасувати", callback_data="confirm_del_season:cancel")]
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text(
        f"⚠️ <b>Підтвердження видалення</b>\n\n"
        f"📺 <b>{series_title}</b>\n"
        f"Сезон {season_num}\n\n"
        f"Ви впевнені, що хочете видалити цей сезон з усіма серіями?",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_del_season:"))
async def process_confirm_delete_season(callback: CallbackQuery, state: FSMContext):
    """Підтвердження видалення сезону"""
    parts = callback.data.split(":", 2)

    if parts[1] == "cancel":
        await callback.message.edit_text("❌ Видалення скасовано.")
        await state.clear()
        await callback.answer()
        return

    series_id = parts[1]
    season_num = int(parts[2])

    # Видаляємо сезон
    success = await delete_season(series_id, season_num)

    if success:
        await callback.message.edit_text(f"✅ Сезон {season_num} успішно видалено!")
        await callback.answer("✅ Сезон видалено")
    else:
        await callback.message.edit_text("❌ Помилка при видаленні сезону.")
        await callback.answer("❌ Помилка", show_alert=True)

    await state.clear()


@router.callback_query(DeleteContentStates.choosing_season, F.data.startswith("delepisode_season:"))
async def process_delete_episode_season_selection(callback: CallbackQuery, state: FSMContext):
    """Обробка вибору сезону для видалення серії"""
    parts = callback.data.split(":", 2)

    if parts[1] == "cancel":
        await callback.message.edit_text("❌ Видалення скасовано.")
        await state.clear()
        await callback.answer()
        return

    series_id = parts[1]
    season_num = int(parts[2])

    await state.update_data(delete_season=season_num)

    # Отримуємо список серій
    episodes = await get_season_episodes(series_id, season_num)

    if not episodes:
        await callback.answer("❌ У цьому сезоні немає серій", show_alert=True)
        return

    data = await state.get_data()
    series_title = data.get('series_title')

    # Створюємо кнопки для вибору серії
    episode_nums = sorted([int(ep) for ep in episodes.keys()])
    buttons = []
    for ep_num in episode_nums:
        buttons.append([
            InlineKeyboardButton(
                text=f"Серія {ep_num}",
                callback_data=f"delepisode:{series_id}:{season_num}:{ep_num}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(text="❌ Скасувати", callback_data="delepisode:cancel")
    ])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text(
        f"📺 <b>{series_title}</b>\n"
        f"Сезон {season_num}\n\n"
        f"Оберіть серію для видалення:",
        reply_markup=keyboard
    )
    await state.set_state(DeleteContentStates.choosing_episode)
    await callback.answer()


@router.callback_query(DeleteContentStates.choosing_episode, F.data.startswith("delepisode:"))
async def process_delete_episode_selection(callback: CallbackQuery, state: FSMContext):
    """Обробка вибору серії для видалення"""
    parts = callback.data.split(":", 3)

    if parts[1] == "cancel":
        await callback.message.edit_text("❌ Видалення скасовано.")
        await state.clear()
        await callback.answer()
        return

    series_id = parts[1]
    season_num = int(parts[2])
    episode_num = int(parts[3])

    data = await state.get_data()
    series_title = data.get('series_title')

    # Підтвердження видалення серії
    buttons = [
        [InlineKeyboardButton(text="✅ Так, видалити", callback_data=f"confirm_del_episode:{series_id}:{season_num}:{episode_num}")],
        [InlineKeyboardButton(text="❌ Ні, скасувати", callback_data="confirm_del_episode:cancel")]
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text(
        f"⚠️ <b>Підтвердження видалення</b>\n\n"
        f"📺 <b>{series_title}</b>\n"
        f"Сезон {season_num}, Серія {episode_num}\n\n"
        f"Ви впевнені, що хочете видалити цю серію?",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_del_episode:"))
async def process_confirm_delete_episode(callback: CallbackQuery, state: FSMContext):
    """Підтвердження видалення серії"""
    parts = callback.data.split(":", 3)

    if parts[1] == "cancel":
        await callback.message.edit_text("❌ Видалення скасовано.")
        await state.clear()
        await callback.answer()
        return

    series_id = parts[1]
    season_num = int(parts[2])
    episode_num = int(parts[3])

    # Видаляємо серію
    success = await delete_episode(series_id, season_num, episode_num)

    if success:
        await callback.message.edit_text(f"✅ Серія {episode_num} успішно видалено!")
        await callback.answer("✅ Серія видалено")
    else:
        await callback.message.edit_text("❌ Помилка при видаленні серії.")
        await callback.answer("❌ Помилка", show_alert=True)

    await state.clear()


# ===============================================
# Редагування контенту
# ===============================================

@router.message(Command("editContent"))
async def cmd_edit_content(message: Message, state: FSMContext):
    """Початок процесу редагування контенту"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ Ця команда доступна тільки для адміністраторів.")
        return

    buttons = [
        [InlineKeyboardButton(text="🎬 Редагувати фільм", callback_data="edittype:movie")],
        [InlineKeyboardButton(text="📺 Редагувати серіал", callback_data="edittype:series")],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="edittype:cancel")]
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(
        "✏️ <b>Редагування контенту</b>\n\n"
        "Оберіть тип контенту для редагування:",
        reply_markup=keyboard
    )
    await state.set_state(EditContentStates.choosing_content_type)


@router.callback_query(EditContentStates.choosing_content_type, F.data.startswith("edittype:"))
async def process_edit_type(callback: CallbackQuery, state: FSMContext):
    """Обробка вибору типу контенту для редагування"""
    parts = callback.data.split(":")
    content_type = parts[1]
    page = int(parts[2]) if len(parts) > 2 else 0

    if content_type == "cancel":
        await callback.message.edit_text("❌ Редагування скасовано.")
        await state.clear()
        await callback.answer()
        return

    await state.update_data(edit_content_type=content_type)

    if content_type == "movie":
        # Отримуємо список фільмів (включно з прихованими для адмінів)
        movies_list = await get_all_movies_list(include_hidden=True)

        if not movies_list:
            await callback.message.edit_text("❌ Немає фільмів для редагування.")
            await state.clear()
            await callback.answer()
            return

        # Пагінація: 15 фільмів на сторінку
        ITEMS_PER_PAGE = 15
        total_pages = (len(movies_list) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        page = max(0, min(page, total_pages - 1))

        start_idx = page * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        movies_page = movies_list[start_idx:end_idx]

        # Створюємо кнопки для вибору фільму
        buttons = []
        for movie in movies_page:
            movie_id = str(movie["_id"])
            is_hidden = movie.get("is_hidden", False)
            hidden_emoji = "🔒 " if is_hidden else ""
            buttons.append([
                InlineKeyboardButton(
                    text=f"{hidden_emoji}🎬 {movie['title']} ({movie['year']})",
                    callback_data=f"editmovie:{movie_id}"
                )
            ])

        # Кнопки навігації
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(
                text="◀️ Назад",
                callback_data=f"edittype:movie:{page-1}"
            ))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton(
                text="Далі ▶️",
                callback_data=f"edittype:movie:{page+1}"
            ))

        if nav_buttons:
            buttons.append(nav_buttons)

        buttons.append([
            InlineKeyboardButton(text="❌ Скасувати", callback_data="editmovie:cancel")
        ])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        page_info = f"Сторінка {page + 1}/{total_pages}" if total_pages > 1 else ""

        await callback.message.edit_text(
            "🎬 <b>Виберіть фільм для редагування:</b>\n\n"
            f"<i>Всього фільмів: {len(movies_list)}</i>\n"
            f"{page_info}",
            reply_markup=keyboard
        )
        await state.set_state(EditContentStates.choosing_content)

    elif content_type == "series":
        # Отримуємо список серіалів (включно з прихованими для адмінів)
        series_list = await get_all_series_list(include_hidden=True)

        if not series_list:
            await callback.message.edit_text("❌ Немає серіалів для редагування.")
            await state.clear()
            await callback.answer()
            return

        # Пагінація: 15 серіалів на сторінку
        ITEMS_PER_PAGE = 15
        total_pages = (len(series_list) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        page = max(0, min(page, total_pages - 1))

        start_idx = page * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        series_page = series_list[start_idx:end_idx]

        # Створюємо кнопки для вибору серіалу
        buttons = []
        for series in series_page:
            series_id = str(series["_id"])
            is_hidden = series.get("is_hidden", False)
            hidden_emoji = "🔒 " if is_hidden else ""
            buttons.append([
                InlineKeyboardButton(
                    text=f"{hidden_emoji}📺 {series['title']}",
                    callback_data=f"editseries:{series_id}"
                )
            ])

        # Кнопки навігації
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(
                text="◀️ Назад",
                callback_data=f"edittype:series:{page-1}"
            ))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton(
                text="Далі ▶️",
                callback_data=f"edittype:series:{page+1}"
            ))

        if nav_buttons:
            buttons.append(nav_buttons)

        buttons.append([
            InlineKeyboardButton(text="❌ Скасувати", callback_data="editseries:cancel")
        ])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        page_info = f"Сторінка {page + 1}/{total_pages}" if total_pages > 1 else ""

        await callback.message.edit_text(
            "📺 <b>Виберіть серіал для редагування:</b>\n\n"
            f"<i>Всього серіалів: {len(series_list)}</i>\n"
            f"{page_info}",
            reply_markup=keyboard
        )
        await state.set_state(EditContentStates.choosing_content)

    await callback.answer()


@router.callback_query(EditContentStates.choosing_content, F.data.startswith("editmovie:") | F.data.startswith("editseries:"))
async def process_edit_content_selection(callback: CallbackQuery, state: FSMContext):
    """Обробка вибору контенту для редагування"""
    data_parts = callback.data.split(":", 1)
    content_id = data_parts[1]

    if content_id == "cancel":
        await callback.message.edit_text("❌ Редагування скасовано.")
        await state.clear()
        await callback.answer()
        return

    # Отримуємо інформацію про контент
    content = await get_movie_by_id(content_id)

    if not content:
        await callback.answer("❌ Контент не знайдено", show_alert=True)
        await state.clear()
        return

    await state.update_data(edit_content_id=content_id)

    # Показуємо доступні поля для редагування
    buttons = [
        [InlineKeyboardButton(text="📝 Українська назва", callback_data=f"editfield:title:{content_id}")],
        [InlineKeyboardButton(text="🔤 Англійська назва", callback_data=f"editfield:title_en:{content_id}")],
        [InlineKeyboardButton(text="📅 Рік", callback_data=f"editfield:year:{content_id}")],
        [InlineKeyboardButton(text="⭐️ IMDB рейтинг", callback_data=f"editfield:imdb_rating:{content_id}")],
        [InlineKeyboardButton(text="🖼 Замінити постер", callback_data=f"editfield:poster:{content_id}")],
    ]

    # Додаємо кнопку заміни відео в залежності від типу контенту
    if content['content_type'] == 'movie':
        buttons.append([InlineKeyboardButton(text="🎬 Замінити відео", callback_data=f"editfield:video:{content_id}")])
        # Додаємо кнопку серії фільмів тільки для фільмів
        buttons.append([InlineKeyboardButton(text="📁 Серія фільмів", callback_data=f"editfield:series_name:{content_id}")])
    else:  # series
        buttons.append([InlineKeyboardButton(text="📺 Замінити серію", callback_data=f"editfield:episode_video:{content_id}")])

    # Додаємо кнопку приховування/показування
    is_hidden = content.get("is_hidden", False)
    visibility_text = "👁 Показати" if is_hidden else "🔒 Приховати"
    buttons.append([InlineKeyboardButton(text=visibility_text, callback_data=f"toggle_visibility:{content_id}")])

    buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="editfield:cancel")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    visibility_status = "🔒 <b>ПРИХОВАНИЙ</b>" if is_hidden else "👁 Видимий"

    # Додаємо інформацію про серію якщо є
    series_info = ""
    if content['content_type'] == 'movie':
        series_name = content.get("series_name")
        if series_name:
            series_info = f"📁 Серія: {series_name}\n"
        else:
            series_info = f"📁 Серія: <i>без серії</i>\n"

    await callback.message.edit_text(
        f"✏️ <b>Редагування:</b>\n\n"
        f"{'🎬' if content['content_type'] == 'movie' else '📺'} <b>{content['title']}</b>\n"
        f"Англійська назва: {content['title_en']}\n"
        f"📅 Рік: {content['year']}\n"
        f"⭐️ IMDB: {content['imdb_rating']}\n"
        f"{series_info}"
        f"Статус: {visibility_status}\n\n"
        f"Оберіть поле для редагування:",
        reply_markup=keyboard
    )
    await state.set_state(EditContentStates.choosing_field)
    await callback.answer()


@router.callback_query(EditContentStates.choosing_field, F.data.startswith("editfield:"))
async def process_edit_field_selection(callback: CallbackQuery, state: FSMContext):
    """Обробка вибору поля для редагування"""
    parts = callback.data.split(":", 2)
    field = parts[1]

    if field == "cancel":
        await callback.message.edit_text("❌ Редагування скасовано.")
        await state.clear()
        await callback.answer()
        return

    content_id = parts[2]

    # Зберігаємо поле яке редагуємо
    await state.update_data(edit_field=field)

    # Обробка постера
    if field == "poster":
        await callback.message.edit_text(
            "🖼 <b>Заміна постера</b>\n\n"
            "Перешліть новий постер (фото) з каналу зберігання:"
        )
        await state.set_state(EditContentStates.waiting_for_poster)
        await callback.answer()
        return

    # Обробка відео для фільму
    if field == "video":
        await callback.message.edit_text(
            "🎬 <b>Заміна відео фільму</b>\n\n"
            "Перешліть нове відео з каналу зберігання:"
        )
        await state.set_state(EditContentStates.waiting_for_video)
        await callback.answer()
        return

    # Обробка заміни серії для серіалу
    if field == "episode_video":
        # Отримуємо інформацію про серіал
        series = await get_movie_by_id(content_id)
        if not series or "seasons" not in series or not series["seasons"]:
            await callback.answer("❌ У серіалу немає сезонів", show_alert=True)
            return

        seasons = sorted([int(s) for s in series["seasons"].keys()])
        buttons = []
        for season_num in seasons:
            episode_count = len(series["seasons"][str(season_num)])
            buttons.append([
                InlineKeyboardButton(
                    text=f"Сезон {season_num} ({episode_count} серій)",
                    callback_data=f"editepisode_season:{content_id}:{season_num}"
                )
            ])

        buttons.append([
            InlineKeyboardButton(text="❌ Скасувати", callback_data="editepisode_season:cancel")
        ])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        await callback.message.edit_text(
            f"📺 <b>{series['title']}</b>\n\n"
            f"Спочатку оберіть сезон:",
            reply_markup=keyboard
        )
        await state.set_state(EditContentStates.choosing_season_for_edit)
        await callback.answer()
        return

    # Обробка серії фільмів
    if field == "series_name":
        # Отримуємо інформацію про фільм
        movie = await get_movie_by_id(content_id)
        if not movie:
            await callback.answer("❌ Фільм не знайдено", show_alert=True)
            return

        current_series = movie.get("series_name")

        # Отримуємо всі існуючі серії
        all_series = await get_all_movie_series_names()

        # Зберігаємо список серій в state для подальшого використання
        await state.update_data(series_list=all_series)

        buttons = []

        # Кнопки існуючих серій (максимум 10) - використовуємо індекси
        for idx, series_name in enumerate(all_series[:10]):
            # Позначаємо поточну серію
            prefix = "✅ " if series_name == current_series else "📁 "
            buttons.append([
                InlineKeyboardButton(
                    text=f"{prefix}{series_name}",
                    callback_data=f"setseries:{content_id}:{idx}"
                )
            ])

        # Кнопки для створення нової серії або видалення
        buttons.append([
            InlineKeyboardButton(
                text="➕ Створити нову серію",
                callback_data=f"setseries:{content_id}:new"
            )
        ])

        if current_series:
            buttons.append([
                InlineKeyboardButton(
                    text="❌ Видалити з серії",
                    callback_data=f"setseries:{content_id}:remove"
                )
            ])

        buttons.append([
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"editmovie:{content_id}")
        ])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        current_info = f"Поточна серія: <b>{current_series}</b>" if current_series else "Фільм без серії"

        await callback.message.edit_text(
            f"📁 <b>Серія фільмів</b>\n\n"
            f"🎬 {movie['title']}\n"
            f"{current_info}\n\n"
            f"Оберіть серію або створіть нову:",
            reply_markup=keyboard
        )
        await state.set_state(EditContentStates.choosing_field)
        await callback.answer()
        return

    # Показуємо підказку в залежності від поля
    field_names = {
        "title": "українську назву",
        "title_en": "англійську назву",
        "year": "рік (наприклад: 2015)",
        "imdb_rating": "IMDB рейтинг (наприклад: 7.5)"
    }

    await callback.message.edit_text(
        f"✏️ <b>Редагування поля</b>\n\n"
        f"Введіть нове значення для поля <b>{field_names.get(field, field)}</b>:"
    )
    await state.set_state(EditContentStates.waiting_for_new_value)
    await callback.answer()


@router.message(EditContentStates.choosing_field, ~F.text.startswith("/"))
async def process_new_series_name_for_edit(message: Message, state: FSMContext):
    """Обробка введення назви нової серії при редагуванні"""
    data = await state.get_data()

    # Перевіряємо чи ми чекаємо назву серії
    if not data.get("awaiting_series_name"):
        await message.answer("❌ Будь ласка, використовуйте кнопки для навігації.")
        return

    movie_id = data.get("edit_content_id")
    series_name = message.text.strip()

    # Оновлюємо серію
    await update_movie_field(movie_id, "series_name", series_name)

    movie = await get_movie_by_id(movie_id)

    await message.answer(f"✅ Фільм додано до нової серії: <b>{series_name}</b>")

    # Показуємо оновлене меню серій
    current_series = series_name
    all_series = await get_all_movie_series_names()

    buttons = []
    for s_name in all_series[:10]:
        prefix = "✅ " if s_name == current_series else "📁 "
        buttons.append([
            InlineKeyboardButton(
                text=f"{prefix}{s_name}",
                callback_data=f"set_series:{movie_id}:{s_name}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="➕ Створити нову серію",
            callback_data=f"set_series:{movie_id}:new"
        )
    ])

    if current_series:
        buttons.append([
            InlineKeyboardButton(
                text="❌ Видалити з серії",
                callback_data=f"set_series:{movie_id}:remove"
            )
        ])

    buttons.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"editmovie:{movie_id}")
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    current_info = f"Поточна серія: <b>{current_series}</b>"

    await message.answer(
        f"📁 <b>Серія фільмів</b>\n\n"
        f"🎬 {movie['title']}\n"
        f"{current_info}\n\n"
        f"Оберіть серію або створіть нову:",
        reply_markup=keyboard
    )

    # Очищаємо прапорець
    await state.update_data(awaiting_series_name=False)


@router.message(EditContentStates.waiting_for_new_value, ~F.text.startswith("/"))
async def process_edit_new_value(message: Message, state: FSMContext):
    """Обробка нового значення для поля"""
    data = await state.get_data()
    content_id = data.get("edit_content_id")
    field = data.get("edit_field")
    new_value = message.text.strip()

    # Валідація в залежності від типу поля
    if field == "year":
        try:
            year = int(new_value)
            if year < 1900 or year > 2100:
                await message.answer("❌ Введіть коректний рік (1900-2100):")
                return
            new_value = year
        except ValueError:
            await message.answer("❌ Введіть рік числом (наприклад: 2015):")
            return

    elif field == "imdb_rating":
        try:
            rating = float(new_value)
            if rating < 0 or rating > 10:
                await message.answer("❌ IMDB рейтинг має бути від 0 до 10:")
                return
            new_value = rating
        except ValueError:
            await message.answer("❌ Введіть рейтинг числом (наприклад: 7.5):")
            return

    # Оновлюємо поле
    success = await update_movie_field(content_id, field, new_value)

    if success:
        await message.answer(
            f"✅ <b>Поле успішно оновлено!</b>\n\n"
            f"Поле: <b>{field}</b>\n"
            f"Нове значення: <b>{new_value}</b>"
        )
    else:
        await message.answer("❌ Помилка при оновленні поля.")

    await state.clear()


# ===============================================
# Обробники заміни постера та відео
# ===============================================

@router.message(EditContentStates.waiting_for_poster, F.photo)
async def process_edit_poster(message: Message, state: FSMContext):
    """Обробка нового постера"""
    # Перевіряємо що фото переслано з каналу зберігання
    if not message.forward_from_chat or message.forward_from_chat.id != config.STORAGE_CHANNEL_ID:
        await message.answer("❌ Постер має бути пересланий з каналу зберігання!")
        return

    data = await state.get_data()
    content_id = data.get("edit_content_id")
    poster_file_id = message.photo[-1].file_id

    # Оновлюємо постер
    success = await update_movie_field(content_id, "poster_file_id", poster_file_id)

    if success:
        await message.answer("✅ Постер успішно замінено!")
    else:
        await message.answer("❌ Помилка при оновленні постера.")

    await state.clear()


@router.message(EditContentStates.waiting_for_poster, ~F.text.startswith("/"))
async def process_edit_poster_invalid(message: Message, state: FSMContext):
    """Обробка некоректного повідомлення замість постера"""
    await message.answer(
        "❌ Будь ласка, переслати фото (постер) з каналу зберігання.\n\n"
        "Якщо хочете скасувати, введіть /cancel"
    )


@router.message(EditContentStates.waiting_for_video, F.video | F.document)
async def process_edit_video(message: Message, state: FSMContext):
    """Обробка нового відео для фільму"""
    # Перевіряємо що відео переслано з каналу зберігання
    if not message.forward_from_chat or message.forward_from_chat.id != config.STORAGE_CHANNEL_ID:
        await message.answer("❌ Відео має бути переслане з каналу зберігання!")
        return

    data = await state.get_data()
    content_id = data.get("edit_content_id")

    # Визначаємо тип файлу та отримуємо розмір
    if message.video:
        video_file_id = message.video.file_id
        video_type = "video"
        file_size = message.video.file_size or 0
        duration = message.video.duration or 0
    elif message.document:
        video_file_id = message.document.file_id
        video_type = "document"
        file_size = message.document.file_size or 0
        duration = 0
    else:
        await message.answer("❌ Некоректний тип файлу.")
        return

    # Оновлюємо відео та супутні поля
    try:
        success1 = await update_movie_field(content_id, "video_file_id", video_file_id)
        success2 = await update_movie_field(content_id, "video_type", video_type)
        success3 = await update_movie_field(content_id, "file_size", file_size)
        success4 = await update_movie_field(content_id, "duration", duration)

        if success1:
            await message.answer("✅ Відео успішно замінено!")
        else:
            await message.answer("❌ Помилка при оновленні відео.")
    except Exception as e:
        logging.error(f"Error updating video: {str(e)}")
        await message.answer(f"❌ Помилка: {str(e)}")

    await state.clear()


@router.message(EditContentStates.waiting_for_video, ~F.text.startswith("/"))
async def process_edit_video_invalid(message: Message, state: FSMContext):
    """Обробка некоректного повідомлення замість відео"""
    await message.answer(
        "❌ Будь ласка, переслати відео файл з каналу зберігання.\n\n"
        "Якщо хочете скасувати, введіть /cancel"
    )


@router.callback_query(EditContentStates.choosing_season_for_edit, F.data.startswith("editepisode_season:"))
async def process_edit_episode_season_selection(callback: CallbackQuery, state: FSMContext):
    """Обробка вибору сезону для редагування серії"""
    parts = callback.data.split(":", 2)

    if parts[1] == "cancel":
        await callback.message.edit_text("❌ Редагування скасовано.")
        await state.clear()
        await callback.answer()
        return

    series_id = parts[1]
    season_num = int(parts[2])

    await state.update_data(edit_season=season_num)

    # Отримуємо список серій
    episodes = await get_season_episodes(series_id, season_num)

    if not episodes:
        await callback.answer("❌ У цьому сезоні немає серій", show_alert=True)
        return

    data = await state.get_data()

    # Отримуємо інформацію про серіал для відображення назви
    series = await get_movie_by_id(series_id)
    series_title = series['title'] if series else "Серіал"

    # Створюємо кнопки для вибору серії
    episode_nums = sorted([int(ep) for ep in episodes.keys()])
    buttons = []
    for ep_num in episode_nums:
        buttons.append([
            InlineKeyboardButton(
                text=f"Серія {ep_num}",
                callback_data=f"editepisode:{series_id}:{season_num}:{ep_num}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(text="❌ Скасувати", callback_data="editepisode:cancel")
    ])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text(
        f"📺 <b>{series_title}</b>\n"
        f"Сезон {season_num}\n\n"
        f"Оберіть серію для заміни відео:",
        reply_markup=keyboard
    )
    await state.set_state(EditContentStates.choosing_episode_for_edit)
    await callback.answer()


@router.callback_query(EditContentStates.choosing_episode_for_edit, F.data.startswith("editepisode:"))
async def process_edit_episode_selection(callback: CallbackQuery, state: FSMContext):
    """Обробка вибору серії для заміни відео"""
    parts = callback.data.split(":", 3)

    if parts[1] == "cancel":
        await callback.message.edit_text("❌ Редагування скасовано.")
        await state.clear()
        await callback.answer()
        return

    series_id = parts[1]
    season_num = int(parts[2])
    episode_num = int(parts[3])

    data = await state.get_data()
    await state.update_data(
        edit_series_id=series_id,
        edit_season=season_num,
        edit_episode=episode_num
    )

    # Отримуємо інформацію про серіал
    series = await get_movie_by_id(series_id)
    series_title = series['title'] if series else "Серіал"

    await callback.message.edit_text(
        f"📺 <b>{series_title}</b>\n"
        f"Сезон {season_num}, Серія {episode_num}\n\n"
        f"Перешліть нове відео з каналу зберігання:"
    )
    await state.set_state(EditContentStates.waiting_for_episode_video)
    await callback.answer()


@router.message(EditContentStates.waiting_for_episode_video, F.video | F.document)
async def process_edit_episode_video(message: Message, state: FSMContext):
    """Обробка нового відео для серії"""
    # Перевіряємо що відео переслано з каналу зберігання
    if not message.forward_from_chat or message.forward_from_chat.id != config.STORAGE_CHANNEL_ID:
        await message.answer("❌ Відео має бути переслане з каналу зберігання!")
        return

    data = await state.get_data()
    series_id = data.get("edit_series_id")
    season_num = data.get("edit_season")
    episode_num = data.get("edit_episode")

    # Визначаємо тип файлу та отримуємо розмір
    if message.video:
        video_file_id = message.video.file_id
        video_type = "video"
        file_size = message.video.file_size or 0
        duration = message.video.duration or 0
    elif message.document:
        video_file_id = message.document.file_id
        video_type = "document"
        file_size = message.document.file_size or 0
        duration = 0
    else:
        await message.answer("❌ Некоректний тип файлу.")
        return

    # Оновлюємо відео серії
    try:
        success = await update_episode_video(
            series_id, season_num, episode_num,
            video_file_id, video_type, file_size, duration
        )

        if success:
            await message.answer(
                f"✅ Відео серії успішно замінено!\n\n"
                f"Сезон {season_num}, Серія {episode_num}"
            )
        else:
            await message.answer("❌ Помилка при оновленні відео серії.")
    except Exception as e:
        logging.error(f"Error updating episode video: {str(e)}")
        await message.answer(f"❌ Помилка: {str(e)}")

    await state.clear()


@router.message(EditContentStates.waiting_for_episode_video, ~F.text.startswith("/"))
async def process_edit_episode_video_invalid(message: Message, state: FSMContext):
    """Обробка некоректного повідомлення замість відео серії"""
    await message.answer(
        "❌ Будь ласка, переслати відео файл з каналу зберігання.\n\n"
        "Якщо хочете скасувати, введіть /cancel"
    )


# ===============================================
# Управління видимістю контенту
# ===============================================

@router.callback_query(F.data.startswith("toggle_visibility:"))
async def toggle_visibility_handler(callback: CallbackQuery, state: FSMContext):
    """Обробка приховування/показування контенту"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔️ Ця функція доступна тільки для адміністраторів.", show_alert=True)
        return

    content_id = callback.data.split(":", 1)[1]

    # Перемикаємо видимість
    result = await toggle_content_visibility(content_id)

    if not result:
        await callback.answer("❌ Помилка при зміні видимості контенту", show_alert=True)
        return

    # Отримуємо оновлену інформацію про контент
    content = await get_movie_by_id(content_id)
    if not content:
        await callback.answer("❌ Контент не знайдено", show_alert=True)
        return

    # Оновлюємо кнопки
    is_hidden = content.get("is_hidden", False)

    buttons = [
        [InlineKeyboardButton(text="📝 Українська назва", callback_data=f"editfield:title:{content_id}")],
        [InlineKeyboardButton(text="🔤 Англійська назва", callback_data=f"editfield:title_en:{content_id}")],
        [InlineKeyboardButton(text="📅 Рік", callback_data=f"editfield:year:{content_id}")],
        [InlineKeyboardButton(text="⭐️ IMDB рейтинг", callback_data=f"editfield:imdb_rating:{content_id}")],
        [InlineKeyboardButton(text="🖼 Замінити постер", callback_data=f"editfield:poster:{content_id}")],
    ]

    # Додаємо кнопку заміни відео в залежності від типу контенту
    if content['content_type'] == 'movie':
        buttons.append([InlineKeyboardButton(text="🎬 Замінити відео", callback_data=f"editfield:video:{content_id}")])
    else:  # series
        buttons.append([InlineKeyboardButton(text="📺 Замінити серію", callback_data=f"editfield:episode_video:{content_id}")])

    # Оновлюємо кнопку видимості
    visibility_text = "👁 Показати" if is_hidden else "🔒 Приховати"
    buttons.append([InlineKeyboardButton(text=visibility_text, callback_data=f"toggle_visibility:{content_id}")])

    buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="editfield:cancel")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    # Оновлюємо повідомлення
    visibility_status = "🔒 <b>ПРИХОВАНИЙ</b>" if is_hidden else "👁 Видимий"
    await callback.message.edit_text(
        f"✏️ <b>Редагування:</b>\n\n"
        f"{'🎬' if content['content_type'] == 'movie' else '📺'} <b>{content['title']}</b>\n"
        f"Англійська назва: {content['title_en']}\n"
        f"📅 Рік: {content['year']}\n"
        f"⭐️ IMDB: {content['imdb_rating']}\n"
        f"Статус: {visibility_status}\n\n"
        f"Оберіть поле для редагування:",
        reply_markup=keyboard
    )

    # Показуємо повідомлення користувачу
    if is_hidden:
        await callback.answer("🔒 Контент приховано! Він більше не буде показуватись користувачам.")
    else:
        await callback.answer("👁 Контент показано! Тепер він видимий для всіх користувачів.")


# ===============================================
# Управління серіями фільмів
# ===============================================

@router.callback_query(F.data.startswith("setseries:"))
async def handle_set_series(callback: CallbackQuery, state: FSMContext):
    """Обробка встановлення серії для фільму"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔️ Ця функція доступна тільки для адміністраторів.", show_alert=True)
        return

    parts = callback.data.split(":", 2)
    movie_id = parts[1]
    action = parts[2] if len(parts) > 2 else None

    movie = await get_movie_by_id(movie_id)
    if not movie:
        await callback.answer("❌ Фільм не знайдено", show_alert=True)
        return

    # Видалення з серії
    if action == "remove":
        await update_movie_field(movie_id, "series_name", None)
        await callback.answer("✅ Фільм видалено з серії")
        await state.clear()
        return

    # Створення нової серії
    if action == "new":
        await callback.message.edit_text(
            "➕ <b>Створення нової серії</b>\n\n"
            "Введіть назву нової серії фільмів (наприклад: <code>Шрек</code>, <code>Мадагаскар</code>):"
        )
        await state.update_data(edit_content_id=movie_id, awaiting_series_name=True)
        await callback.answer()
        return

    # Встановлення існуючої серії за індексом
    try:
        series_idx = int(action)
        data = await state.get_data()
        series_list = data.get("series_list", [])

        if series_idx >= len(series_list):
            await callback.answer("❌ Помилка: серія не знайдена", show_alert=True)
            return

        series_name = series_list[series_idx]
        await update_movie_field(movie_id, "series_name", series_name)
        await callback.answer(f"✅ Фільм додано до серії: {series_name}")

        # Оновлюємо меню
        current_series = series_name
        all_series = await get_all_movie_series_names()
        await state.update_data(series_list=all_series)

        buttons = []
        for idx, s_name in enumerate(all_series[:10]):
            prefix = "✅ " if s_name == current_series else "📁 "
            buttons.append([
                InlineKeyboardButton(
                    text=f"{prefix}{s_name}",
                    callback_data=f"setseries:{movie_id}:{idx}"
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                text="➕ Створити нову серію",
                callback_data=f"setseries:{movie_id}:new"
            )
        ])

        if current_series:
            buttons.append([
                InlineKeyboardButton(
                    text="❌ Видалити з серії",
                    callback_data=f"setseries:{movie_id}:remove"
                )
            ])

        buttons.append([
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"editmovie:{movie_id}")
        ])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        current_info = f"Поточна серія: <b>{current_series}</b>"

        await callback.message.edit_text(
            f"📁 <b>Серія фільмів</b>\n\n"
            f"🎬 {movie['title']}\n"
            f"{current_info}\n\n"
            f"Оберіть серію або створіть нову:",
            reply_markup=keyboard
        )
    except (ValueError, IndexError) as e:
        await callback.answer("❌ Помилка при обробці серії", show_alert=True)
