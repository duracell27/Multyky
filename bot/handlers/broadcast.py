from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from datetime import datetime
import asyncio
import logging

from bot.config import config
from bot.states import BroadcastStates
from bot.database.broadcasts import (
    create_broadcast,
    get_all_broadcasts,
    get_broadcast,
    update_broadcast,
    update_broadcast_status,
    mark_broadcast_as_sent,
    delete_broadcast
)
from bot.database.movies import get_all_movies_list, get_all_series_list, get_movie_by_id
from bot.database.mongodb import db

router = Router()
logger = logging.getLogger(__name__)


async def send_broadcast_to_users(bot: Bot, broadcast_id: str) -> dict:
    """
    Відправити розсилку всім користувачам

    Returns:
        dict: Статистика відправки
    """
    broadcast = await get_broadcast(broadcast_id)
    if not broadcast:
        return {"error": "Broadcast not found"}

    # Отримуємо всіх користувачів (які мають user_id)
    users_cursor = db.users.find({"user_id": {"$exists": True}})
    users = await users_cursor.to_list(length=None)

    stats = {
        "total_users": len(users),
        "sent_success": 0,
        "sent_failed": 0,
        "errors": []  # Список помилок
    }

    # Формуємо текст повідомлення
    message_text = f"<b>{broadcast['title']}</b>\n\n{broadcast['description']}"

    # Додаємо кнопки з фільмами/серіалами якщо є
    keyboard = None
    if broadcast.get('content_ids'):
        buttons = []
        for content_id in broadcast['content_ids']:
            content = await get_movie_by_id(content_id)
            if content:
                content_type = content.get('content_type', 'movie')
                emoji = "📺" if content_type == "series" else "🎬"
                callback_prefix = "s" if content_type == "series" else "m"

                buttons.append([
                    InlineKeyboardButton(
                        text=f"{emoji} {content['title']} ({content['year']}) ⭐️ {content['imdb_rating']}",
                        callback_data=f"{callback_prefix}:{content_id}"
                    )
                ])

        if buttons:
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    # Відправляємо повідомлення кожному користувачу
    for user in users:
        try:
            if broadcast.get('photo_file_id'):
                # Відправляємо з фото
                await bot.send_photo(
                    chat_id=user['user_id'],
                    photo=broadcast['photo_file_id'],
                    caption=message_text,
                    reply_markup=keyboard
                )
            else:
                # Відправляємо тільки текст
                await bot.send_message(
                    chat_id=user['user_id'],
                    text=message_text,
                    reply_markup=keyboard
                )

            stats['sent_success'] += 1

            # Невелика затримка, щоб не перевантажувати API
            await asyncio.sleep(0.05)

        except Exception as e:
            stats['sent_failed'] += 1
            error_info = {
                "user_id": user['user_id'],
                "username": user.get('username', 'немає'),
                "first_name": user.get('first_name', 'немає'),
                "error": str(e)
            }
            stats['errors'].append(error_info)
            logger.error(f"Failed to send broadcast to user {user['user_id']}: {e}")

    # Оновлюємо статус розсилки
    await mark_broadcast_as_sent(broadcast_id, stats)

    return stats


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext):
    """Показати меню розсилок (тільки для адмінів)"""
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("❌ Ця команда доступна тільки адміністраторам")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Створити розсилку", callback_data="broadcast:create")],
        [InlineKeyboardButton(text="📋 Список розсилок", callback_data="broadcast:list")],
        [InlineKeyboardButton(text="◀️ Назад до адмін-меню", callback_data="admin:menu")]
    ])

    await message.answer(
        "📢 <b>Управління розсилками</b>\n\n"
        "Виберіть дію:",
        reply_markup=keyboard
    )


@router.callback_query(F.data == "broadcast:create")
async def start_create_broadcast(callback: CallbackQuery, state: FSMContext):
    """Почати створення нової розсилки"""
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("❌ Недостатньо прав")
        return

    await state.set_state(BroadcastStates.waiting_for_title)
    await callback.message.edit_text(
        "📝 <b>Створення розсилки</b>\n\n"
        "Крок 1/3: Введіть <b>заголовок</b> розсилки:"
    )
    await callback.answer()


@router.message(BroadcastStates.waiting_for_title)
async def process_broadcast_title(message: Message, state: FSMContext):
    """Обробка заголовка розсилки"""
    await state.update_data(title=message.text)
    await state.set_state(BroadcastStates.waiting_for_description)

    await message.answer(
        "📝 <b>Створення розсилки</b>\n\n"
        "Крок 2/3: Введіть <b>опис</b> розсилки:"
    )


@router.message(BroadcastStates.waiting_for_description)
async def process_broadcast_description(message: Message, state: FSMContext):
    """Обробка опису розсилки"""
    await state.update_data(description=message.text)
    await state.set_state(BroadcastStates.waiting_for_photo)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Пропустити", callback_data="broadcast:skip_photo")]
    ])

    await message.answer(
        "📝 <b>Створення розсилки</b>\n\n"
        "Крок 3/3: Надішліть <b>фото</b> для розсилки або пропустіть цей крок:",
        reply_markup=keyboard
    )


@router.message(BroadcastStates.waiting_for_photo, F.photo)
async def process_broadcast_photo(message: Message, state: FSMContext):
    """Обробка фото розсилки"""
    photo_file_id = message.photo[-1].file_id
    await state.update_data(photo_file_id=photo_file_id)

    await ask_for_content_selection(message, state)


@router.callback_query(F.data == "broadcast:skip_photo", BroadcastStates.waiting_for_photo)
async def skip_broadcast_photo(callback: CallbackQuery, state: FSMContext):
    """Пропустити фото"""
    await ask_for_content_selection(callback.message, state)
    await callback.answer()


async def ask_for_content_selection(message: Message, state: FSMContext):
    """Запитати чи потрібно додати фільми/серіали"""
    await state.set_state(BroadcastStates.choosing_content)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Додати фільми", callback_data="broadcast:add_movies")],
        [InlineKeyboardButton(text="📺 Додати серіали", callback_data="broadcast:add_series")],
        [InlineKeyboardButton(text="⏭ Пропустити", callback_data="broadcast:skip_content")],
        [InlineKeyboardButton(text="✅ Завершити і переглянути", callback_data="broadcast:preview")]
    ])

    data = await state.get_data()
    content_count = len(data.get('content_ids', []))

    await message.answer(
        f"📝 <b>Вибір контенту</b>\n\n"
        f"Додано контенту: {content_count}\n\n"
        f"Виберіть дію:",
        reply_markup=keyboard
    )


@router.callback_query(F.data == "broadcast:add_movies", BroadcastStates.choosing_content)
async def show_movies_for_broadcast(callback: CallbackQuery, state: FSMContext):
    """Показати список фільмів для вибору"""
    await show_movies_page_for_broadcast(callback, state, page=0)


async def show_movies_page_for_broadcast(callback: CallbackQuery, state: FSMContext, page: int = 0):
    """Показати сторінку фільмів для вибору в розсилку"""
    movies = await get_all_movies_list(include_hidden=False)

    if not movies:
        await callback.answer("❌ Немає фільмів для додавання", show_alert=True)
        return

    # Пагінація: 15 фільмів на сторінку
    ITEMS_PER_PAGE = 15
    total_pages = (len(movies) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    page = max(0, min(page, total_pages - 1))

    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    movies_page = movies[start_idx:end_idx]

    buttons = []
    for movie in movies_page:
        movie_id = str(movie["_id"])
        buttons.append([
            InlineKeyboardButton(
                text=f"🎬 {movie['title']} ({movie['year']})",
                callback_data=f"broadcast:select_movie:{movie_id}"
            )
        ])

    # Кнопки навігації
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"broadcast:movies_page:{page-1}"
        ))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(
            text="Далі ▶️",
            callback_data=f"broadcast:movies_page:{page+1}"
        ))

    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([InlineKeyboardButton(text="◀️ Назад до вибору", callback_data="broadcast:back_to_content")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    page_info = f"\n<i>Сторінка {page + 1}/{total_pages}</i>" if total_pages > 1 else ""

    await callback.message.edit_text(
        f"🎬 <b>Вибір фільмів</b>\n\n"
        f"Виберіть фільм для додавання:{page_info}",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("broadcast:movies_page:"), BroadcastStates.choosing_content)
async def handle_movies_page_broadcast(callback: CallbackQuery, state: FSMContext):
    """Обробка навігації по сторінках фільмів"""
    page = int(callback.data.split(":", 2)[2])
    await show_movies_page_for_broadcast(callback, state, page=page)


@router.callback_query(F.data == "broadcast:add_series", BroadcastStates.choosing_content)
async def show_series_for_broadcast(callback: CallbackQuery, state: FSMContext):
    """Показати список серіалів для вибору"""
    await show_series_page_for_broadcast(callback, state, page=0)


async def show_series_page_for_broadcast(callback: CallbackQuery, state: FSMContext, page: int = 0):
    """Показати сторінку серіалів для вибору в розсилку"""
    series = await get_all_series_list(include_hidden=False)

    if not series:
        await callback.answer("❌ Немає серіалів для додавання", show_alert=True)
        return

    # Пагінація: 15 серіалів на сторінку
    ITEMS_PER_PAGE = 15
    total_pages = (len(series) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    page = max(0, min(page, total_pages - 1))

    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    series_page = series[start_idx:end_idx]

    buttons = []
    for show in series_page:
        series_id = str(show["_id"])
        buttons.append([
            InlineKeyboardButton(
                text=f"📺 {show['title']} ({show['year']})",
                callback_data=f"broadcast:select_series:{series_id}"
            )
        ])

    # Кнопки навігації
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"broadcast:series_page:{page-1}"
        ))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(
            text="Далі ▶️",
            callback_data=f"broadcast:series_page:{page+1}"
        ))

    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([InlineKeyboardButton(text="◀️ Назад до вибору", callback_data="broadcast:back_to_content")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    page_info = f"\n<i>Сторінка {page + 1}/{total_pages}</i>" if total_pages > 1 else ""

    await callback.message.edit_text(
        f"📺 <b>Вибір серіалів</b>\n\n"
        f"Виберіть серіал для додавання:{page_info}",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("broadcast:series_page:"), BroadcastStates.choosing_content)
async def handle_series_page_broadcast(callback: CallbackQuery, state: FSMContext):
    """Обробка навігації по сторінках серіалів"""
    page = int(callback.data.split(":", 2)[2])
    await show_series_page_for_broadcast(callback, state, page=page)


@router.callback_query(F.data.startswith("broadcast:select_movie:"), BroadcastStates.choosing_content)
async def select_movie_for_broadcast(callback: CallbackQuery, state: FSMContext):
    """Додати фільм до розсилки"""
    movie_id = callback.data.split(":", 2)[2]

    data = await state.get_data()
    content_ids = data.get('content_ids', [])

    if movie_id not in content_ids:
        content_ids.append(movie_id)
        await state.update_data(content_ids=content_ids)
        await callback.answer("✅ Фільм додано")
    else:
        await callback.answer("ℹ️ Фільм вже додано")

    # Повертаємось до вибору контенту
    await callback.message.delete()
    await ask_for_content_selection(callback.message, state)


@router.callback_query(F.data.startswith("broadcast:select_series:"), BroadcastStates.choosing_content)
async def select_series_for_broadcast(callback: CallbackQuery, state: FSMContext):
    """Додати серіал до розсилки"""
    series_id = callback.data.split(":", 2)[2]

    data = await state.get_data()
    content_ids = data.get('content_ids', [])

    if series_id not in content_ids:
        content_ids.append(series_id)
        await state.update_data(content_ids=content_ids)
        await callback.answer("✅ Серіал додано")
    else:
        await callback.answer("ℹ️ Серіал вже додано")

    # Повертаємось до вибору контенту
    await callback.message.delete()
    await ask_for_content_selection(callback.message, state)


@router.callback_query(F.data == "broadcast:back_to_content", BroadcastStates.choosing_content)
async def back_to_content_selection(callback: CallbackQuery, state: FSMContext):
    """Повернутись до вибору контенту"""
    await callback.message.delete()
    await ask_for_content_selection(callback.message, state)


@router.callback_query(F.data == "broadcast:skip_content", BroadcastStates.choosing_content)
async def skip_content_selection(callback: CallbackQuery, state: FSMContext):
    """Пропустити вибір контенту"""
    await show_broadcast_preview(callback, state)


@router.callback_query(F.data == "broadcast:preview", BroadcastStates.choosing_content)
async def show_broadcast_preview(callback: CallbackQuery, state: FSMContext):
    """Показати попередній перегляд розсилки"""
    data = await state.get_data()

    title = data.get('title', '')
    description = data.get('description', '')
    photo_file_id = data.get('photo_file_id')
    content_ids = data.get('content_ids', [])

    # Підраховуємо кількість користувачів
    users_count = await db.users.count_documents({"user_id": {"$exists": True}})

    # Формуємо текст повідомлення
    preview_text = f"<b>{title}</b>\n\n{description}"

    # Формуємо кнопки з контентом
    content_buttons = []
    for content_id in content_ids:
        content = await get_movie_by_id(content_id)
        if content:
            content_type = content.get('content_type', 'movie')
            emoji = "📺" if content_type == "series" else "🎬"
            content_buttons.append([
                InlineKeyboardButton(
                    text=f"{emoji} {content['title']} ({content['year']}) ⭐️ {content['imdb_rating']}",
                    callback_data=f"preview_{content_id}"
                )
            ])

    # Показуємо попередній перегляд
    await state.set_state(BroadcastStates.confirming_broadcast)

    if photo_file_id:
        keyboard_preview = InlineKeyboardMarkup(inline_keyboard=content_buttons) if content_buttons else None
        await callback.message.answer_photo(
            photo=photo_file_id,
            caption=f"📢 <b>Попередній перегляд розсилки:</b>\n\n{preview_text}",
            reply_markup=keyboard_preview
        )
    else:
        await callback.message.answer(f"📢 <b>Попередній перегляд розсилки:</b>\n\n{preview_text}")

    # Кнопки підтвердження
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Відправити зараз", callback_data="broadcast:send_now"),
            InlineKeyboardButton(text="📅 Запланувати", callback_data="broadcast:schedule")
        ],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="broadcast:cancel")]
    ])

    await callback.message.answer(
        f"👥 <b>Розсилка буде відправлена {users_count} користувачам</b>\n\n"
        f"Виберіть дію:",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data == "broadcast:send_now", BroadcastStates.confirming_broadcast)
async def send_broadcast_now(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Відправити розсилку зараз"""
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("❌ Недостатньо прав")
        return

    data = await state.get_data()

    # Створюємо розсилку в базі
    broadcast_id = await create_broadcast(
        title=data['title'],
        description=data['description'],
        photo_file_id=data.get('photo_file_id'),
        content_ids=data.get('content_ids', [])
    )

    await callback.message.edit_text("⏳ Відправка розсилки...")
    await callback.answer()

    # Відправляємо розсилку
    stats = await send_broadcast_to_users(bot, broadcast_id)

    await state.clear()

    result_text = (
        f"✅ <b>Розсилку відправлено!</b>\n\n"
        f"📊 Статистика:\n"
        f"👥 Всього користувачів: {stats['total_users']}\n"
        f"✅ Успішно відправлено: {stats['sent_success']}\n"
        f"❌ Помилок: {stats['sent_failed']}"
    )

    await callback.message.edit_text(result_text)

    # Якщо є помилки, відправляємо окреме повідомлення з деталями
    if stats['sent_failed'] > 0 and stats.get('errors'):
        errors_text = "❌ <b>Деталі помилок:</b>\n\n"

        # Показуємо перші 20 помилок
        for i, error in enumerate(stats['errors'][:20], 1):
            user_name = error['first_name']
            username = f"@{error['username']}" if error['username'] != 'немає' else 'немає username'
            errors_text += (
                f"{i}. <b>{user_name}</b> ({username})\n"
                f"   ID: <code>{error['user_id']}</code>\n"
                f"   Помилка: {error['error']}\n\n"
            )

        if len(stats['errors']) > 20:
            errors_text += f"... і ще {len(stats['errors']) - 20} помилок"

        await bot.send_message(
            chat_id=callback.from_user.id,
            text=errors_text
        )


@router.callback_query(F.data == "broadcast:schedule", BroadcastStates.confirming_broadcast)
async def schedule_broadcast(callback: CallbackQuery, state: FSMContext):
    """Запланувати розсилку"""
    await state.set_state(BroadcastStates.waiting_for_schedule_time)

    await callback.message.edit_text(
        "📅 <b>Планування розсилки</b>\n\n"
        "Введіть дату і час у форматі:\n"
        "<code>ДД.MM.РРРР ГГ:ХХ</code>\n\n"
        "Наприклад: <code>31.12.2025 20:00</code>"
    )
    await callback.answer()


@router.message(BroadcastStates.waiting_for_schedule_time)
async def process_schedule_time(message: Message, state: FSMContext):
    """Обробка часу для планування"""
    try:
        # Парсимо дату і час
        scheduled_time = datetime.strptime(message.text, "%d.%m.%Y %H:%M")

        # Перевіряємо що час в майбутньому
        if scheduled_time <= datetime.now():
            await message.answer("❌ Час повинен бути в майбутньому. Спробуйте ще раз.")
            return

        data = await state.get_data()

        # Створюємо розсилку в базі
        broadcast_id = await create_broadcast(
            title=data['title'],
            description=data['description'],
            photo_file_id=data.get('photo_file_id'),
            content_ids=data.get('content_ids', []),
            scheduled_time=scheduled_time
        )

        # Оновлюємо статус на "scheduled"
        await update_broadcast_status(broadcast_id, "scheduled")

        await state.clear()

        await message.answer(
            f"✅ <b>Розсилку заплановано!</b>\n\n"
            f"📅 Дата відправки: {scheduled_time.strftime('%d.%m.%Y о %H:%M')}\n\n"
            f"Розсилка буде автоматично відправлена у вказаний час."
        )

    except ValueError:
        await message.answer(
            "❌ Невірний формат дати.\n\n"
            "Використовуйте формат: <code>ДД.MM.РРРР ГГ:ХХ</code>\n"
            "Наприклад: <code>31.12.2025 20:00</code>"
        )


@router.callback_query(F.data == "broadcast:cancel", BroadcastStates.confirming_broadcast)
async def cancel_broadcast(callback: CallbackQuery, state: FSMContext):
    """Скасувати розсилку"""
    await state.clear()
    await callback.message.edit_text("❌ Розсилку скасовано")
    await callback.answer()


@router.callback_query(F.data == "broadcast:list")
async def show_broadcasts_list(callback: CallbackQuery):
    """Показати список розсилок"""
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("❌ Недостатньо прав")
        return

    broadcasts = await get_all_broadcasts()

    if not broadcasts:
        await callback.message.edit_text(
            "📭 Немає створених розсилок\n\n"
            "Створіть нову розсилку через /broadcast"
        )
        await callback.answer()
        return

    buttons = []
    for broadcast in broadcasts[:10]:  # Показуємо останні 10
        broadcast_id = str(broadcast['_id'])
        status_emoji = {
            'draft': '📝',
            'scheduled': '📅',
            'sent': '✅',
            'cancelled': '❌'
        }.get(broadcast['status'], '❓')

        title = broadcast['title'][:25] + '...' if len(broadcast['title']) > 25 else broadcast['title']

        # Додаємо дату
        date_str = ""
        if broadcast.get('sent_at'):
            date_str = broadcast['sent_at'].strftime(' %d.%m.%y')
        elif broadcast.get('scheduled_time'):
            date_str = broadcast['scheduled_time'].strftime(' %d.%m.%y')
        elif broadcast.get('created_at'):
            date_str = broadcast['created_at'].strftime(' %d.%m.%y')

        buttons.append([
            InlineKeyboardButton(
                text=f"{status_emoji} {title}{date_str}",
                callback_data=f"broadcast:view:{broadcast_id}"
            )
        ])

    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="broadcast:menu")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text(
        "📋 <b>Список розсилок:</b>\n\n"
        "Виберіть розсилку для перегляду:",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("broadcast:view:"))
async def view_broadcast_details(callback: CallbackQuery):
    """Показати деталі розсилки"""
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("❌ Недостатньо прав")
        return

    broadcast_id = callback.data.split(":", 2)[2]
    broadcast = await get_broadcast(broadcast_id)

    if not broadcast:
        await callback.answer("❌ Розсилку не знайдено", show_alert=True)
        return

    # Статус
    status_emoji = {
        'draft': '📝',
        'scheduled': '📅',
        'sent': '✅',
        'cancelled': '❌'
    }.get(broadcast['status'], '❓')

    status_text = {
        'draft': 'Чернетка',
        'scheduled': 'Заплановано',
        'sent': 'Відправлено',
        'cancelled': 'Скасовано'
    }.get(broadcast['status'], 'Невідомо')

    # Формуємо текст з деталями
    details_text = (
        f"📢 <b>Деталі розсилки</b>\n\n"
        f"<b>Назва:</b> {broadcast['title']}\n"
        f"<b>Опис:</b> {broadcast['description']}\n\n"
        f"<b>Статус:</b> {status_emoji} {status_text}\n"
    )

    # Додаємо дату створення
    if broadcast.get('created_at'):
        created_str = broadcast['created_at'].strftime('%d.%m.%Y о %H:%M')
        details_text += f"<b>Створено:</b> {created_str}\n"

    # Додаємо дату планування
    if broadcast.get('scheduled_time'):
        scheduled_str = broadcast['scheduled_time'].strftime('%d.%m.%Y о %H:%M')
        details_text += f"<b>Заплановано на:</b> {scheduled_str}\n"

    # Додаємо дату відправки
    if broadcast.get('sent_at'):
        sent_str = broadcast['sent_at'].strftime('%d.%m.%Y о %H:%M')
        details_text += f"<b>Відправлено:</b> {sent_str}\n"

    # Додаємо статистику якщо є
    if broadcast.get('stats'):
        stats = broadcast['stats']
        details_text += (
            f"\n📊 <b>Статистика:</b>\n"
            f"👥 Всього користувачів: {stats.get('total_users', 0)}\n"
            f"✅ Успішно відправлено: {stats.get('sent_success', 0)}\n"
            f"❌ Помилок: {stats.get('sent_failed', 0)}\n"
        )

        # Якщо є помилки, показуємо їх
        if stats.get('sent_failed', 0) > 0 and stats.get('errors'):
            details_text += "\n❌ <b>Деталі помилок:</b>\n\n"

            # Показуємо перші 10 помилок
            for i, error in enumerate(stats['errors'][:10], 1):
                user_name = error.get('first_name', 'немає')
                username = error.get('username', 'немає')
                username_str = f"@{username}" if username != 'немає' else 'немає username'
                details_text += (
                    f"{i}. <b>{user_name}</b> ({username_str})\n"
                    f"   ID: <code>{error.get('user_id', 'немає')}</code>\n"
                    f"   Помилка: {error.get('error', 'немає')}\n\n"
                )

            if len(stats['errors']) > 10:
                details_text += f"... і ще {len(stats['errors']) - 10} помилок\n"

    # Додаємо інформацію про контент
    if broadcast.get('content_ids'):
        details_text += f"\n🎬 <b>Контент:</b> {len(broadcast['content_ids'])} шт.\n"

    # Додаємо інформацію про фото
    if broadcast.get('photo_file_id'):
        details_text += "🖼 <b>Є фото</b>\n"

    # Кнопка назад
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад до списку", callback_data="broadcast:list")]
    ])

    await callback.message.edit_text(
        details_text,
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data == "broadcast:menu")
async def back_to_broadcast_menu(callback: CallbackQuery):
    """Повернутись до меню розсилок"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Створити розсилку", callback_data="broadcast:create")],
        [InlineKeyboardButton(text="📋 Список розсилок", callback_data="broadcast:list")],
        [InlineKeyboardButton(text="◀️ Назад до адмін-меню", callback_data="admin:menu")]
    ])

    await callback.message.edit_text(
        "📢 <b>Управління розсилками</b>\n\n"
        "Виберіть дію:",
        reply_markup=keyboard
    )
    await callback.answer()
