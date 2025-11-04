from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
from aiogram.fsm.context import FSMContext

from bot.config import config
from bot.states import AddMovieStates
from bot.database.movies import create_movie, get_movies_count, get_all_series_list, get_series_info_by_title
from bot.database.users import get_last_series_added, update_last_series_added

router = Router()


def is_admin(user_id: int) -> bool:
    """Перевірка чи користувач є адміністратором"""
    return user_id in config.ADMIN_IDS


@router.message(Command("addMovie"))
async def cmd_add_movie(message: Message, state: FSMContext):
    """Початок процесу додавання мультфільму"""

    # Перевірка прав адміністратора
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ Ця команда доступна тільки для адміністраторів.")
        return

    # Перевіряємо чи є останній доданий серіал
    last_series = await get_last_series_added(message.from_user.id)

    buttons = []

    # Якщо є останній серіал - показуємо швидку кнопку
    if last_series:
        buttons.append([
            InlineKeyboardButton(
                text=f"➕ Додати серію до \"{last_series}\"",
                callback_data="add_type:quick_series"
            )
        ])

    # Основні варіанти
    buttons.extend([
        [InlineKeyboardButton(text="🆕 Новий контент", callback_data="add_type:new")],
        [InlineKeyboardButton(text="📺 Серія до існуючого серіалу", callback_data="add_type:existing")]
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(
        "🎬 <b>Додавання контенту</b>\n\n"
        "Виберіть що ви хочете додати:\n\n"
        "<i>Для скасування введіть /cancel</i>",
        reply_markup=keyboard
    )
    await state.set_state(AddMovieStates.choosing_add_type)


@router.callback_query(AddMovieStates.choosing_add_type, F.data.startswith("add_type:"))
async def process_add_type(callback: CallbackQuery, state: FSMContext):
    """Обробка вибору типу додавання"""
    add_type = callback.data.split(":", 1)[1]

    if add_type == "new":
        # Новий контент - починаємо з назви
        await callback.message.edit_text(
            "🎬 <b>Додавання нового контенту</b>\n\n"
            "Введіть назву українською:\n\n"
            "<i>Для скасування введіть /cancel</i>"
        )
        await state.set_state(AddMovieStates.waiting_for_title)

    elif add_type == "existing":
        # Показуємо список існуючих серіалів
        series_list = await get_all_series_list()

        if not series_list:
            await callback.message.edit_text(
                "📭 Поки що немає доданих серіалів.\n\n"
                "Спочатку створіть новий серіал."
            )
            await state.clear()
            await callback.answer()
            return

        # Створюємо кнопки для вибору серіалу
        buttons = []
        for series in series_list:
            series_id = str(series["doc_id"])
            buttons.append([
                InlineKeyboardButton(
                    text=f"📺 {series['title']}",
                    callback_data=f"sel_s:{series_id}"
                )
            ])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        await callback.message.edit_text(
            "📺 <b>Виберіть серіал:</b>\n\n"
            "До якого серіалу додати нову серію?",
            reply_markup=keyboard
        )
        await state.set_state(AddMovieStates.choosing_existing_series)

    elif add_type == "quick_series":
        # Швидке додавання до останнього серіалу
        last_series = await get_last_series_added(callback.from_user.id)

        if not last_series:
            await callback.answer("❌ Не знайдено останній серіал", show_alert=True)
            return

        # Отримуємо інформацію про серіал
        series_info = await get_series_info_by_title(last_series)

        if not series_info:
            await callback.answer("❌ Серіал не знайдено в базі", show_alert=True)
            return

        # Зберігаємо інфу про серіал в state
        await state.update_data(
            title=series_info["title"],
            title_en=series_info["title_en"],
            year=series_info["year"],
            imdb_rating=series_info["imdb_rating"],
            content_type="series"
        )

        await callback.message.edit_text(
            f"📺 <b>{last_series}</b>\n\n"
            "Введіть номер сезону (наприклад: 1):"
        )
        await state.set_state(AddMovieStates.waiting_for_season)

    await callback.answer()


@router.callback_query(AddMovieStates.choosing_existing_series, F.data.startswith("sel_s:"))
async def process_select_series(callback: CallbackQuery, state: FSMContext):
    """Обробка вибору існуючого серіалу"""
    from bot.database.movies import get_movie_by_id

    series_id = callback.data.split(":", 1)[1]

    # Отримуємо інформацію про серіал за ID
    series_info = await get_movie_by_id(series_id)

    if not series_info:
        await callback.answer("❌ Серіал не знайдено", show_alert=True)
        return

    # Зберігаємо інфу про серіал в state
    await state.update_data(
        title=series_info["title"],
        title_en=series_info["title_en"],
        year=series_info["year"],
        imdb_rating=series_info["imdb_rating"],
        content_type="series"
    )

    await callback.message.edit_text(
        f"📺 <b>{series_info['title']}</b>\n\n"
        "Введіть номер сезону (наприклад: 1):"
    )
    await state.set_state(AddMovieStates.waiting_for_season)
    await callback.answer()


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """Скасування процесу додавання мультфільму"""
    current_state = await state.get_state()

    if current_state is None:
        await message.answer("Немає активного процесу для скасування.")
        return

    await state.clear()
    await message.answer(
        "❌ Процес додавання мультфільму скасовано.",
    )


@router.message(AddMovieStates.waiting_for_title)
async def process_title(message: Message, state: FSMContext):
    """Обробка назви мультфільму українською"""

    if not message.text:
        await message.answer("❌ Будь ласка, введіть текст назви.")
        return

    # Зберігаємо назву
    await state.update_data(title=message.text)

    await message.answer(
        f"✅ Назва українською: <b>{message.text}</b>\n\n"
        "Тепер введіть назву англійською:"
    )
    await state.set_state(AddMovieStates.waiting_for_title_en)


@router.message(AddMovieStates.waiting_for_title_en)
async def process_title_en(message: Message, state: FSMContext):
    """Обробка назви мультфільму англійською"""

    if not message.text:
        await message.answer("❌ Будь ласка, введіть текст назви.")
        return

    # Зберігаємо англійську назву
    await state.update_data(title_en=message.text)

    await message.answer(
        f"✅ Назва англійською: <b>{message.text}</b>\n\n"
        "Тепер введіть рік випуску (наприклад: 2020):"
    )
    await state.set_state(AddMovieStates.waiting_for_year)


@router.message(AddMovieStates.waiting_for_year)
async def process_year(message: Message, state: FSMContext):
    """Обробка року випуску"""

    if not message.text:
        await message.answer("❌ Будь ласка, введіть рік.")
        return

    # Перевірка чи це число
    try:
        year = int(message.text)
        if year < 1900 or year > 2100:
            await message.answer("❌ Введіть коректний рік (від 1900 до 2100).")
            return
    except ValueError:
        await message.answer("❌ Будь ласка, введіть рік числом (наприклад: 2020).")
        return

    # Зберігаємо рік
    await state.update_data(year=year)

    await message.answer(
        f"✅ Рік випуску: <b>{year}</b>\n\n"
        "Тепер введіть рейтинг IMDB (наприклад: 8.5):"
    )
    await state.set_state(AddMovieStates.waiting_for_imdb_rating)


@router.message(AddMovieStates.waiting_for_imdb_rating)
async def process_imdb_rating(message: Message, state: FSMContext):
    """Обробка рейтингу IMDB"""

    if not message.text:
        await message.answer("❌ Будь ласка, введіть рейтинг.")
        return

    # Перевірка чи це число
    try:
        imdb_rating = float(message.text.replace(',', '.'))
        if imdb_rating < 0 or imdb_rating > 10:
            await message.answer("❌ Рейтинг IMDB має бути від 0 до 10.")
            return
    except ValueError:
        await message.answer("❌ Будь ласка, введіть рейтинг числом (наприклад: 8.5).")
        return

    # Зберігаємо рейтинг
    await state.update_data(imdb_rating=imdb_rating)

    # Створюємо кнопки для вибору типу контенту
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎬 Мультфільм", callback_data="content_type:movie"),
            InlineKeyboardButton(text="📺 Мультсеріал", callback_data="content_type:series")
        ]
    ])

    await message.answer(
        f"✅ Рейтинг IMDB: <b>{imdb_rating}</b>\n\n"
        "Виберіть тип контенту:",
        reply_markup=keyboard
    )
    await state.set_state(AddMovieStates.waiting_for_content_type)


@router.callback_query(AddMovieStates.waiting_for_content_type, F.data.startswith("content_type:"))
async def process_content_type(callback: CallbackQuery, state: FSMContext):
    """Обробка вибору типу контенту"""
    content_type = callback.data.split(":")[1]  # "movie" або "series"

    await state.update_data(content_type=content_type)

    if content_type == "movie":
        # Для фільму відразу переходимо до завантаження відео
        await callback.message.edit_text(
            "✅ Тип: <b>Мультфільм</b>\n\n"
            "Тепер відправте відео мультфільму:\n\n"
            "⚠️ <b>Важливо:</b>\n"
            "• Приймаються тільки <b>MP4</b> файли\n"
            "• Максимальний розмір: 2GB (надсилайте з галочкою 'Send as file')\n"
            "• Конвертуйте MKV/AVI → MP4 на комп'ютері перед завантаженням\n\n"
            "<i>Для скасування введіть /cancel</i>"
        )
        await state.set_state(AddMovieStates.waiting_for_video)
    else:
        # Для серіалу питаємо номер сезону
        await callback.message.edit_text(
            "✅ Тип: <b>Мультсеріал</b>\n\n"
            "Введіть номер сезону (наприклад: 1):"
        )
        await state.set_state(AddMovieStates.waiting_for_season)

    await callback.answer()


@router.message(AddMovieStates.waiting_for_season)
async def process_season(message: Message, state: FSMContext):
    """Обробка номеру сезону"""

    if not message.text:
        await message.answer("❌ Будь ласка, введіть номер сезону.")
        return

    try:
        season = int(message.text)
        if season < 1:
            await message.answer("❌ Номер сезону має бути більше 0.")
            return
    except ValueError:
        await message.answer("❌ Будь ласка, введіть номер сезону числом (наприклад: 1).")
        return

    await state.update_data(season=season)

    await message.answer(
        f"✅ Сезон: <b>{season}</b>\n\n"
        "Тепер введіть номер серії (наприклад: 1):"
    )
    await state.set_state(AddMovieStates.waiting_for_episode)


@router.message(AddMovieStates.waiting_for_episode)
async def process_episode(message: Message, state: FSMContext):
    """Обробка номеру серії"""

    if not message.text:
        await message.answer("❌ Будь ласка, введіть номер серії.")
        return

    try:
        episode = int(message.text)
        if episode < 1:
            await message.answer("❌ Номер серії має бути більше 0.")
            return
    except ValueError:
        await message.answer("❌ Будь ласка, введіть номер серії числом (наприклад: 1).")
        return

    await state.update_data(episode=episode)

    await message.answer(
        f"✅ Серія: <b>{episode}</b>\n\n"
        "Тепер відправте відео серії:\n\n"
        "⚠️ <b>Важливо:</b>\n"
        "• Приймаються тільки <b>MP4</b> файли\n"
        "• Максимальний розмір: 2GB (надсилайте з галочкою 'Send as file')\n"
        "• Конвертуйте MKV/AVI → MP4 на комп'ютері перед завантаженням\n\n"
        "<i>Для скасування введіть /cancel</i>"
    )
    await state.set_state(AddMovieStates.waiting_for_video)


@router.message(AddMovieStates.waiting_for_video, F.video | F.document)
async def process_video(message: Message, state: FSMContext, bot: Bot):
    """Обробка відео"""

    # Отримуємо всі збережені дані
    data = await state.get_data()

    # Отримуємо file_id відео (може бути video або document)
    video_file_id = None
    video_type = None
    file_name = None

    if message.video:
        # Відео надіслано як відео (стиснуте Telegram)
        video_file_id = message.video.file_id
        video_type = "video"
        file_name = message.video.file_name or "video.mp4"

    elif message.document:
        # Відео надіслано як документ
        mime_type = message.document.mime_type or ""
        file_name = message.document.file_name or ""

        # Перевіряємо що це відео файл
        is_video = (
            mime_type.startswith("video/") or
            file_name.lower().endswith(('.mp4', '.mkv', '.avi', '.mov', '.webm'))
        )

        if not is_video:
            await message.answer(
                "❌ Будь ласка, відправте відео файл.\n\n"
                "<i>Для скасування введіть /cancel</i>"
            )
            return

        # Попереджуємо якщо не MP4
        if not (file_name.lower().endswith('.mp4') or mime_type == "video/mp4"):
            await message.answer(
                f"⚠️ <b>Увага!</b> Файл {file_name} не в MP4 форматі.\n\n"
                f"Рекомендується конвертувати в MP4 для кращої сумісності.\n"
                f"Продовжую збереження..."
            )

        video_file_id = message.document.file_id
        video_type = "document"

    else:
        await message.answer("❌ Будь ласка, відправте відео файл.")
        return

    try:
        # Підготовка параметрів для збереження
        content_type = data.get("content_type", "movie")
        season = data.get("season")
        episode = data.get("episode")

        # Зберігаємо мультфільм або серію в базу даних
        movie = await create_movie(
            title=data["title"],
            title_en=data["title_en"],
            year=data["year"],
            imdb_rating=data["imdb_rating"],
            video_file_id=video_file_id,
            video_type=video_type,
            added_by=message.from_user.id,
            content_type=content_type,
            season=season,
            episode=episode
        )

        # Отримуємо загальну кількість мультфільмів
        total_movies = await get_movies_count()

        # Формуємо повідомлення залежно від типу
        if content_type == "movie":
            success_message = (
                "✅ <b>Мультфільм успішно додано!</b>\n\n"
                f"📝 Назва: {data['title']}\n"
                f"🌍 Назва (EN): {data['title_en']}\n"
                f"📅 Рік: {data['year']}\n"
                f"⭐️ IMDB: {data['imdb_rating']}\n"
                f"🎬 Тип: Мультфільм\n"
                f"📊 Всього записів у базі: {total_movies}"
            )
        else:
            success_message = (
                "✅ <b>Серію мультсеріалу успішно додано!</b>\n\n"
                f"📝 Назва: {data['title']}\n"
                f"🌍 Назва (EN): {data['title_en']}\n"
                f"📅 Рік: {data['year']}\n"
                f"⭐️ IMDB: {data['imdb_rating']}\n"
                f"📺 Тип: Мультсеріал\n"
                f"🎯 Сезон: {season}, Серія: {episode}\n"
                f"📊 Всього записів у базі: {total_movies}"
            )

        # Зберігаємо останній серіал для швидкого додавання
        if content_type == "series":
            await update_last_series_added(message.from_user.id, data["title"])

        # Для серіалів показуємо кнопки швидкого додавання
        if content_type == "series":
            # Створюємо кнопки
            next_episode = episode + 1
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"➕ Наступна серія (S{season:02d}E{next_episode:02d})",
                    callback_data=f"next_ep:{season}:{next_episode}"
                )],
                [InlineKeyboardButton(
                    text="🔄 Інший сезон",
                    callback_data="other_season"
                )],
                [InlineKeyboardButton(
                    text="🏠 Головне меню",
                    callback_data="main_menu"
                )]
            ])

            await message.answer(success_message, reply_markup=keyboard)
        else:
            await message.answer(success_message)

    except Exception as e:
        await message.answer(
            f"❌ Помилка при збереженні мультфільму:\n{str(e)}"
        )

    # Очищаємо стан
    await state.clear()


@router.message(AddMovieStates.waiting_for_video)
async def process_invalid_video(message: Message, state: FSMContext):
    """Обробка некоректного типу повідомлення замість відео"""
    await message.answer(
        "❌ Будь ласка, відправте відео файл.\n\n"
        "Якщо хочете скасувати, введіть /cancel"
    )


@router.callback_query(F.data.startswith("next_ep:"))
async def process_next_episode(callback: CallbackQuery, state: FSMContext):
    """Обробка швидкого додавання наступної серії"""
    # Парсимо дані: next_ep:1:2 -> сезон 1, серія 2
    parts = callback.data.split(":")
    season = int(parts[1])
    episode = int(parts[2])

    # Отримуємо дані останнього серіалу
    last_series = await get_last_series_added(callback.from_user.id)

    if not last_series:
        await callback.answer("❌ Не знайдено останній серіал", show_alert=True)
        return

    # Отримуємо інформацію про серіал
    from bot.database.movies import get_series_info_by_title
    series_info = await get_series_info_by_title(last_series)

    if not series_info:
        await callback.answer("❌ Серіал не знайдено в базі", show_alert=True)
        return

    # Зберігаємо всі дані в state
    await state.update_data(
        title=series_info["title"],
        title_en=series_info["title_en"],
        year=series_info["year"],
        imdb_rating=series_info["imdb_rating"],
        content_type="series",
        season=season,
        episode=episode
    )

    await callback.message.edit_text(
        f"📺 <b>{last_series}</b>\n"
        f"🎯 Сезон {season}, Серія {episode}\n\n"
        "Тепер відправте відео серії:\n\n"
        "⚠️ <b>Важливо:</b>\n"
        "• Приймаються тільки <b>MP4</b> файли\n"
        "• Максимальний розмір: 2GB (надсилайте з галочкою 'Send as file')\n"
        "• Конвертуйте MKV/AVI → MP4 на комп'ютері перед завантаженням\n\n"
        "<i>Для скасування введіть /cancel</i>"
    )
    await state.set_state(AddMovieStates.waiting_for_video)
    await callback.answer()


@router.callback_query(F.data == "other_season")
async def process_other_season(callback: CallbackQuery, state: FSMContext):
    """Обробка додавання серії до іншого сезону"""
    # Отримуємо дані останнього серіалу
    last_series = await get_last_series_added(callback.from_user.id)

    if not last_series:
        await callback.answer("❌ Не знайдено останній серіал", show_alert=True)
        return

    # Отримуємо інформацію про серіал
    from bot.database.movies import get_series_info_by_title
    series_info = await get_series_info_by_title(last_series)

    if not series_info:
        await callback.answer("❌ Серіал не знайдено в базі", show_alert=True)
        return

    # Зберігаємо основні дані в state
    await state.update_data(
        title=series_info["title"],
        title_en=series_info["title_en"],
        year=series_info["year"],
        imdb_rating=series_info["imdb_rating"],
        content_type="series"
    )

    await callback.message.edit_text(
        f"📺 <b>{last_series}</b>\n\n"
        "Введіть номер сезону (наприклад: 2):"
    )
    await state.set_state(AddMovieStates.waiting_for_season)
    await callback.answer()


@router.callback_query(F.data == "main_menu")
async def process_main_menu(callback: CallbackQuery, state: FSMContext):
    """Повернення до головного меню"""
    await state.clear()
    await callback.message.edit_text(
        "✅ Повернення до головного меню.\n\n"
        "🎬 /catalog - переглянути каталог\n"
        "➕ /addMovie - додати новий контент"
    )
    await callback.answer()
