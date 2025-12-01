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

    # Отримуємо всіх користувачів (які мають telegram_id)
    users_cursor = db.users.find({"telegram_id": {"$exists": True}})
    users = await users_cursor.to_list(length=None)

    stats = {
        "total_users": len(users),
        "sent_success": 0,
        "sent_failed": 0
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
                    chat_id=user['telegram_id'],
                    photo=broadcast['photo_file_id'],
                    caption=message_text,
                    reply_markup=keyboard
                )
            else:
                # Відправляємо тільки текст
                await bot.send_message(
                    chat_id=user['telegram_id'],
                    text=message_text,
                    reply_markup=keyboard
                )

            stats['sent_success'] += 1

            # Невелика затримка, щоб не перевантажувати API
            await asyncio.sleep(0.05)

        except Exception as e:
            stats['sent_failed'] += 1
            logger.error(f"Failed to send broadcast to user {user['telegram_id']}: {e}")

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
    movies = await get_all_movies_list(include_hidden=False)

    if not movies:
        await callback.answer("❌ Немає фільмів для додавання", show_alert=True)
        return

    # Беремо перші 10 фільмів
    buttons = []
    for movie in movies[:10]:
        movie_id = str(movie["_id"])
        buttons.append([
            InlineKeyboardButton(
                text=f"🎬 {movie['title']} ({movie['year']})",
                callback_data=f"broadcast:select_movie:{movie_id}"
            )
        ])

    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="broadcast:back_to_content")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text(
        "🎬 <b>Вибір фільмів</b>\n\n"
        "Виберіть фільм для додавання:",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data == "broadcast:add_series", BroadcastStates.choosing_content)
async def show_series_for_broadcast(callback: CallbackQuery, state: FSMContext):
    """Показати список серіалів для вибору"""
    series = await get_all_series_list(include_hidden=False)

    if not series:
        await callback.answer("❌ Немає серіалів для додавання", show_alert=True)
        return

    # Беремо перші 10 серіалів
    buttons = []
    for show in series[:10]:
        series_id = str(show["_id"])
        buttons.append([
            InlineKeyboardButton(
                text=f"📺 {show['title']} ({show['year']})",
                callback_data=f"broadcast:select_series:{series_id}"
            )
        ])

    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="broadcast:back_to_content")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text(
        "📺 <b>Вибір серіалів</b>\n\n"
        "Виберіть серіал для додавання:",
        reply_markup=keyboard
    )
    await callback.answer()


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
    users_count = await db.users.count_documents({"telegram_id": {"$exists": True}})

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

    await callback.message.edit_text(
        f"✅ <b>Розсилку відправлено!</b>\n\n"
        f"📊 Статистика:\n"
        f"👥 Всього користувачів: {stats['total_users']}\n"
        f"✅ Успішно відправлено: {stats['sent_success']}\n"
        f"❌ Помилок: {stats['sent_failed']}"
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

        title = broadcast['title'][:30] + '...' if len(broadcast['title']) > 30 else broadcast['title']

        buttons.append([
            InlineKeyboardButton(
                text=f"{status_emoji} {title}",
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
