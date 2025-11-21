from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext

from bot.database.users import (
    get_or_create_user,
    get_users_count,
    get_active_users_count,
    get_watch_history,
    get_watch_later
)
from bot.database.movies import (
    get_movies_count,
    get_movie_by_id,
    get_movies_only_count,
    get_series_only_count,
    get_total_videos_count,
    get_total_views_count,
    get_total_storage_size,
    get_top_content_by_views,
    search_content
)
from bot.config import config
from bot.states import SearchStates, HelpStates

router = Router()


def get_main_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """Створити головну клавіатуру для користувача"""

    # Основні кнопки для всіх користувачів
    keyboard = [
        [KeyboardButton(text="🎬 Каталог"), KeyboardButton(text="🔍 Пошук")],
        [KeyboardButton(text="📜 Історія"), KeyboardButton(text="📌 Пізніше")],
        [KeyboardButton(text="❓ Допомога"), KeyboardButton(text="📋 Меню")]
    ]

    # Додаємо адмін-кнопки для адміністраторів
    if is_admin:
        keyboard.append([KeyboardButton(text="⚙️ Адмін-панель")])

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        input_field_placeholder="Оберіть дію..."
    )


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    """Обробник команди /start - автоматично реєструє користувача"""

    # Очищаємо стан (наприклад, якщо користувач був у пошуку)
    await state.clear()

    # Автоматична реєстрація користувача
    user = await get_or_create_user(message.from_user, bot)

    # Отримуємо кількість мультфільмів та серіалів
    movies_count = await get_movies_only_count()
    series_count = await get_series_only_count()

    # Перевіряємо чи це новий користувач
    is_new_user = user.get("registered_at") == user.get("last_activity")

    # Перевіряємо чи користувач є адміністратором
    is_admin = message.from_user.id in config.ADMIN_IDS

    if is_new_user:
        welcome_text = (
            f"👋 Привіт, <b>{message.from_user.first_name}</b>!\n\n"
            f"Ласкаво просимо до бота з мультиками! 🎬\n\n"
            f"Тут ти зможеш переглядати улюблені мультфільми та серіали.\n\n"
            f"📊 Наша галерея з кожним днем збільшується і складає:\n"
            f"   🎬 Мультфільмів: <b>{movies_count}</b>\n"
            f"   📺 Мультсеріалів: <b>{series_count}</b>\n\n"
            f"Використовуй кнопки нижче або команди:\n"
            f"📺 /catalog - переглянути каталог\n"
            f"🔍 /search - пошук мультфільмів\n"
            f"❓ /help - допомога і зворотній зв'язок"
        )
    else:
        welcome_text = (
            f"👋 З поверненням, <b>{message.from_user.first_name}</b>!\n\n"
            f"Радий бачити тебе знову! 🎬\n\n"
            f"📊 Наша галерея з кожним днем збільшується і складає:\n"
            f"   🎬 Мультфільмів: <b>{movies_count}</b>\n"
            f"   📺 Мультсеріалів: <b>{series_count}</b>\n\n"
            f"Використовуй кнопки нижче для навігації! 👇"
        )

    await message.answer(welcome_text, reply_markup=get_main_keyboard(is_admin))


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext, bot: Bot):
    """Обробник команди /menu - головне меню"""

    # Очищаємо стан (наприклад, якщо користувач був у пошуку)
    await state.clear()

    # Автоматично оновлюємо активність
    await get_or_create_user(message.from_user, bot)

    # Перевіряємо чи користувач є адміністратором
    is_admin = message.from_user.id in config.ADMIN_IDS

    if is_admin:
        # Меню для адміністратора
        menu_text = (
            "👑 <b>Головне меню адміністратора</b>\n\n"
            "Використовуй кнопки нижче або команди:\n\n"
            "🎬 <b>Основні:</b>\n"
            "/catalog - Каталог мультфільмів\n"
            "/search - Пошук\n"
            "/history - Історія\n"
            "/watchlater - Пізніше\n\n"
            "⚙️ <b>Адмін:</b>\n"
            "/addMovie - Додати мультфільм\n"
            "/editContent - Редагувати\n"
            "/deleteContent - Видалити\n"
            "/stats - Статистика\n\n"
            "💡 <i>Приємної роботи!</i>"
        )
    else:
        # Меню для звичайного користувача
        menu_text = (
            "🎬 <b>Головне меню</b>\n\n"
            "Використовуй кнопки нижче для швидкої навігації! 👇\n\n"
            "Або команди:\n"
            "/catalog - Каталог мультфільмів\n"
            "/search - Пошук\n"
            "/history - Історія переглядів\n"
            "/watchlater - Переглянути пізніше\n"
            "/help - Допомога\n\n"
            "📝 <i>Приємного перегляду!</i>"
        )

    await message.answer(menu_text, reply_markup=get_main_keyboard(is_admin))


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    """Обробник команди /stats - тільки для адмінів"""

    # Перевірка чи користувач є адміністратором
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("⛔️ Ця команда доступна тільки для адміністраторів.")
        return

    # Отримуємо статистику
    users_count = await get_users_count()
    active_users_count = await get_active_users_count(days=7)
    movies_only_count = await get_movies_only_count()
    series_only_count = await get_series_only_count()
    total_videos_count = await get_total_videos_count()
    total_views_count = await get_total_views_count()
    total_storage_gb = await get_total_storage_size()
    top_content = await get_top_content_by_views(5)

    # Формуємо текст топ-5
    top_text = ""
    if top_content:
        for idx, content in enumerate(top_content, 1):
            title = content.get("title", "Без назви")
            views = content.get("views_count", 0)
            content_type = "🎬" if content.get("content_type") == "movie" else "📺"
            top_text += f"   {idx}. {content_type} {title} - {views} переглядів\n"
    else:
        top_text = "   Немає даних\n"

    stats_text = (
        "📊 <b>Статистика бота:</b>\n\n"
        "👥 <b>Користувачі:</b>\n"
        f"   • Всього: {users_count}\n"
        f"   • Активних (7 днів): {active_users_count}\n\n"
        "🎬 <b>Контент:</b>\n"
        f"   • Мультфільмів: {movies_only_count}\n"
        f"   • Мультсеріалів: {series_only_count}\n"
        f"   • Всього відео: {total_videos_count}\n\n"
        "📊 <b>Перегляди:</b>\n"
        f"   • Всього переглядів: {total_views_count}\n\n"
        "🏆 <b>Топ-5 по переглядах:</b>\n"
        f"{top_text}\n"
        "💾 <b>Сховище:</b>\n"
        f"   • Загальний розмір: {total_storage_gb} ГБ\n\n"
        f"<i>Статистика оновлюється в реальному часі</i>"
    )

    await message.answer(stats_text)


@router.message(Command("history"))
async def cmd_history(message: Message, bot: Bot):
    """Обробник команди /history - показати історію переглядів"""

    # Автоматично оновлюємо активність
    await get_or_create_user(message.from_user, bot)

    # Отримуємо історію переглядів
    history = await get_watch_history(message.from_user.id)

    if not history:
        await message.answer(
            "📭 <b>Історія переглядів порожня</b>\n\n"
            "Переглянь щось із /catalog і воно з'явиться тут!"
        )
        return

    # Формуємо кнопки для кожного перегляду (максимум 20 останніх)
    buttons = []
    for item in history[:20]:
        movie_id = item.get("movie_id")
        title = item.get("title", "Невідомо")
        content_type = item.get("content_type", "movie")

        # Формуємо текст кнопки
        if content_type == "series":
            season = item.get("season")
            episode = item.get("episode")

            # Перевіряємо що season і episode є числами
            if season is not None and episode is not None:
                button_text = f"📺 {title} S{season}E{episode}"
                callback_data = f"e:{movie_id}:{season}:{episode}"
            else:
                # Якщо немає інформації про епізод - відкриваємо серіал
                button_text = f"📺 {title}"
                callback_data = f"s:{movie_id}"
        else:
            button_text = f"🎬 {title}"
            callback_data = f"m:{movie_id}"

        buttons.append([
            InlineKeyboardButton(text=button_text, callback_data=callback_data)
        ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(
        "📜 <b>Історія переглядів</b>\n\n"
        f"Останні {len(buttons)} переглянутих:\n"
        "Натисни щоб переглянути знову 👇",
        reply_markup=keyboard
    )


@router.message(Command("watchlater", "watchLater"))
async def cmd_watch_later(message: Message, bot: Bot):
    """Обробник команди /watchlater - показати чергу перегляду"""

    # Автоматично оновлюємо активність
    await get_or_create_user(message.from_user, bot)

    # Отримуємо чергу перегляду
    watch_later_ids = await get_watch_later(message.from_user.id)

    if not watch_later_ids:
        await message.answer(
            "📭 <b>Черга перегляду порожня</b>\n\n"
            "Додай серіали з /catalog і вони з'являться тут!"
        )
        return

    # Формуємо кнопки для кожного серіалу
    buttons = []
    for series_id in watch_later_ids:
        # Отримуємо інформацію про серіал
        series_info = await get_movie_by_id(series_id)
        if not series_info:
            continue

        title = series_info.get("title", "Невідомо")

        # Створюємо кнопку з посиланням на серіал
        buttons.append([
            InlineKeyboardButton(
                text=f"📺 {title}",
                callback_data=f"s:{series_id}"
            )
        ])

    if not buttons:
        await message.answer(
            "📭 <b>Черга перегляду порожня</b>\n\n"
            "Додай серіали з /catalog і вони з'являться тут!"
        )
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(
        "📌 <b>Черга перегляду</b>\n\n"
        f"Збережено серіалів: {len(buttons)}\n"
        "Натисни щоб переглянути 👇",
        reply_markup=keyboard
    )


@router.message(Command("search"))
async def cmd_search(message: Message, state: FSMContext, bot: Bot):
    """Обробник команди /search - пошук мультфільмів"""

    # Автоматично оновлюємо активність
    await get_or_create_user(message.from_user, bot)

    # Встановлюємо стан очікування пошукового запиту
    await state.set_state(SearchStates.waiting_for_query)

    await message.answer(
        "🔍 <b>Пошук мультфільмів</b>\n\n"
        "Введи назву мультфільму або серіалу, який хочеш знайти:\n\n"
        "<i>Можеш вводити як українською, так і англійською</i>"
    )


@router.message(SearchStates.waiting_for_query, ~F.text.startswith("/"))
async def process_search_query(message: Message, state: FSMContext, bot: Bot):
    """Обробник пошукового запиту"""

    query = message.text.strip()

    # Перевіряємо чи це не кнопка клавіатури - якщо так, очищаємо стан і дозволяємо обробнику кнопки спрацювати
    keyboard_buttons = {
        "🎬 Каталог": lambda: cmd_catalog(message, state, bot),
        "🔍 Пошук": lambda: cmd_search(message, state, bot),
        "📜 Історія": lambda: cmd_history(message, bot),
        "📌 Пізніше": lambda: cmd_watch_later(message, bot),
        "❓ Допомога": lambda: cmd_help(message, state, bot),
        "📋 Меню": lambda: cmd_menu(message, state, bot),
        "⚙️ Адмін-панель": lambda: btn_admin(message)
    }

    if query in keyboard_buttons:
        # Очищаємо стан і викликаємо відповідну команду
        await state.clear()
        await keyboard_buttons[query]()
        return

    if not query:
        await message.answer("❌ Введи назву для пошуку")
        return

    # Адміни бачать всі результати, включаючи приховані
    is_admin = message.from_user.id in config.ADMIN_IDS
    results = await search_content(query, include_hidden=is_admin)

    if not results:
        await message.answer(
            f"😔 <b>Нічого не знайдено</b>\n\n"
            f"За запитом '<i>{query}</i>' не знайдено жодного мультфільму.\n\n"
            f"Введи іншу назву для пошуку або /catalog для перегляду всіх мультфільмів"
        )
        return

    # Формуємо кнопки з результатами (максимум 20)
    buttons = []
    for content in results[:20]:
        content_id = str(content.get("_id"))
        title = content.get("title", "Невідомо")
        title_en = content.get("title_en", "")
        year = content.get("year", "")
        imdb_rating = content.get("imdb_rating", 0)
        content_type = content.get("content_type", "movie")

        # Формуємо текст кнопки
        if content_type == "series":
            emoji = "📺"
            callback_data = f"s:{content_id}:0"
        else:
            emoji = "🎬"
            callback_data = f"m:{content_id}"

        # Форматуємо назву кнопки
        button_text = f"{emoji} {title}"
        if year:
            button_text += f" ({year})"
        if imdb_rating > 0:
            button_text += f" ⭐️ {imdb_rating}"

        buttons.append([
            InlineKeyboardButton(text=button_text, callback_data=callback_data)
        ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(
        f"🔍 <b>Результати пошуку</b>\n\n"
        f"За запитом '<i>{query}</i>' знайдено: <b>{len(results)}</b>\n"
        f"Показано перші {min(len(results), 20)} результатів:\n\n"
        f"<i>Натисни на назву для перегляду 👇</i>\n\n"
        f"Можеш відразу ввести нову назву для пошуку або /menu для виходу",
        reply_markup=keyboard
    )


@router.message(Command("help"))
async def cmd_help(message: Message, state: FSMContext, bot: Bot):
    """Обробник команди /help - допомога користувачу"""

    # Очищаємо стан
    await state.clear()

    # Автоматично оновлюємо активність
    await get_or_create_user(message.from_user, bot)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Попросити мультфільм", callback_data="help:request")],
        [InlineKeyboardButton(text="💬 Зв'язок з адміном", callback_data="help:contact")]
    ])

    await message.answer(
        "❓ <b>Допомога</b>\n\n"
        "Виберіть потрібну опцію:\n\n"
        "🎬 <b>Попросити мультфільм</b>\n"
        "Опишіть який мультфільм або серіал ви хочете побачити у боті\n\n"
        "💬 <b>Зв'язок з адміном</b>\n"
        "Напишіть повідомлення адміністратору з питанням або пропозицією",
        reply_markup=keyboard
    )


@router.callback_query(F.data == "help:request")
async def help_request_callback(callback: CallbackQuery, state: FSMContext):
    """Обробник кнопки 'Попросити мультфільм'"""
    await callback.answer()

    await state.set_state(HelpStates.waiting_for_request)

    await callback.message.answer(
        "🎬 <b>Запит на мультфільм</b>\n\n"
        "Напишіть який мультфільм або серіал ви хочете побачити у боті.\n"
        "Вкажіть назву, рік випуску або інші деталі.\n\n"
        "Адміністратори отримають ваш запит і постараються додати його якнайшвидше!\n\n"
        "<i>Для скасування натисніть /menu</i>"
    )


@router.message(HelpStates.waiting_for_request, ~F.text.startswith("/"))
async def process_help_request(message: Message, state: FSMContext, bot: Bot):
    """Обробник запиту на мультфільм"""

    user_request = message.text.strip()

    # Перевіряємо чи це не кнопка клавіатури
    keyboard_buttons = {
        "🎬 Каталог": lambda: cmd_catalog(message, state, bot),
        "🔍 Пошук": lambda: cmd_search(message, state, bot),
        "📜 Історія": lambda: cmd_history(message, bot),
        "📌 Пізніше": lambda: cmd_watch_later(message, bot),
        "❓ Допомога": lambda: cmd_help(message, state, bot),
        "📋 Меню": lambda: cmd_menu(message, state, bot),
        "⚙️ Адмін-панель": lambda: btn_admin(message)
    }

    if user_request in keyboard_buttons:
        await state.clear()
        await keyboard_buttons[user_request]()
        return

    if not user_request:
        await message.answer("❌ Введіть ваш запит")
        return

    # Формуємо повідомлення для адмінів
    user = message.from_user
    username = f"@{user.username}" if user.username else "немає username"

    admin_message = (
        f"🎬 <b>Новий запит на мультфільм!</b>\n\n"
        f"👤 <b>Від користувача:</b>\n"
        f"ID: <code>{user.id}</code>\n"
        f"Ім'я: {user.first_name or 'немає'}"
    )

    if user.last_name:
        admin_message += f" {user.last_name}"

    admin_message += f"\nUsername: {username}\n\n"
    admin_message += f"📝 <b>Запит:</b>\n{user_request}"

    # Надсилаємо повідомлення всім адмінам
    sent_count = 0
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, admin_message)
            sent_count += 1
        except Exception as e:
            import logging
            logging.error(f"Failed to send request to admin {admin_id}: {e}")

    # Очищаємо стан
    await state.clear()

    if sent_count > 0:
        await message.answer(
            "✅ <b>Запит надіслано!</b>\n\n"
            "Дякуємо за ваш запит! Адміністратори отримали його і постараються додати "
            "мультфільм якнайшвидше.\n\n"
            "Повернутися до /menu"
        )
    else:
        await message.answer(
            "❌ <b>Помилка</b>\n\n"
            "На жаль, не вдалося надіслати запит адміністраторам. Спробуйте пізніше.\n\n"
            "Повернутися до /menu"
        )


@router.callback_query(F.data == "help:contact")
async def help_contact_callback(callback: CallbackQuery, state: FSMContext):
    """Обробник кнопки 'Зв'язок з адміном'"""
    await callback.answer()

    await state.set_state(HelpStates.waiting_for_message)

    await callback.message.answer(
        "💬 <b>Зв'язок з адміном</b>\n\n"
        "Напишіть ваше повідомлення адміністратору.\n"
        "Це може бути питання, пропозиція або повідомлення про помилку.\n\n"
        "Адміністратори отримають ваше повідомлення і зв'яжуться з вами найближчим часом!\n\n"
        "<i>Для скасування натисніть /menu</i>"
    )


@router.message(HelpStates.waiting_for_message, ~F.text.startswith("/"))
async def process_help_message(message: Message, state: FSMContext, bot: Bot):
    """Обробник повідомлення адміну"""

    user_message = message.text.strip()

    # Перевіряємо чи це не кнопка клавіатури
    keyboard_buttons = {
        "🎬 Каталог": lambda: cmd_catalog(message, state, bot),
        "🔍 Пошук": lambda: cmd_search(message, state, bot),
        "📜 Історія": lambda: cmd_history(message, bot),
        "📌 Пізніше": lambda: cmd_watch_later(message, bot),
        "❓ Допомога": lambda: cmd_help(message, state, bot),
        "📋 Меню": lambda: cmd_menu(message, state, bot),
        "⚙️ Адмін-панель": lambda: btn_admin(message)
    }

    if user_message in keyboard_buttons:
        await state.clear()
        await keyboard_buttons[user_message]()
        return

    if not user_message:
        await message.answer("❌ Введіть ваше повідомлення")
        return

    # Формуємо повідомлення для адмінів
    user = message.from_user
    username = f"@{user.username}" if user.username else "немає username"

    admin_message = (
        f"💬 <b>Нове повідомлення від користувача!</b>\n\n"
        f"👤 <b>Від:</b>\n"
        f"ID: <code>{user.id}</code>\n"
        f"Ім'я: {user.first_name or 'немає'}"
    )

    if user.last_name:
        admin_message += f" {user.last_name}"

    admin_message += f"\nUsername: {username}\n\n"
    admin_message += f"📩 <b>Повідомлення:</b>\n{user_message}"

    # Надсилаємо повідомлення всім адмінам
    sent_count = 0
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, admin_message)
            sent_count += 1
        except Exception as e:
            import logging
            logging.error(f"Failed to send message to admin {admin_id}: {e}")

    # Очищаємо стан
    await state.clear()

    if sent_count > 0:
        await message.answer(
            "✅ <b>Повідомлення надіслано!</b>\n\n"
            "Дякуємо за ваше повідомлення! Адміністратори отримали його і зв'яжуться з вами "
            "найближчим часом.\n\n"
            "Повернутися до /menu"
        )
    else:
        await message.answer(
            "❌ <b>Помилка</b>\n\n"
            "На жаль, не вдалося надіслати повідомлення адміністраторам. Спробуйте пізніше.\n\n"
            "Повернутися до /menu"
        )


# Обробники для кнопок клавіатури
@router.message(F.text == "🎬 Каталог")
async def btn_catalog(message: Message, state: FSMContext, bot: Bot):
    """Обробник кнопки 'Каталог'"""
    await cmd_catalog(message, state, bot)


@router.message(F.text == "🔍 Пошук")
async def btn_search(message: Message, state: FSMContext, bot: Bot):
    """Обробник кнопки 'Пошук'"""
    await cmd_search(message, state, bot)


@router.message(F.text == "📜 Історія")
async def btn_history(message: Message, bot: Bot):
    """Обробник кнопки 'Історія'"""
    await cmd_history(message, bot)


@router.message(F.text == "📌 Пізніше")
async def btn_watchlater(message: Message, bot: Bot):
    """Обробник кнопки 'Пізніше'"""
    await cmd_watch_later(message, bot)


@router.message(F.text == "❓ Допомога")
async def btn_help(message: Message, state: FSMContext, bot: Bot):
    """Обробник кнопки 'Допомога'"""
    await cmd_help(message, state, bot)


@router.message(F.text == "📋 Меню")
async def btn_menu(message: Message, state: FSMContext, bot: Bot):
    """Обробник кнопки 'Меню'"""
    await cmd_menu(message, state, bot)


@router.message(F.text == "⚙️ Адмін-панель")
async def btn_admin(message: Message):
    """Обробник кнопки 'Адмін-панель'"""
    # Перевірка чи користувач є адміністратором
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("⛔️ Ця функція доступна тільки для адміністраторів.")
        return

    await message.answer(
        "⚙️ <b>Адмін-панель</b>\n\n"
        "<b>Управління контентом:</b>\n"
        "/addMovie - Додати мультфільм\n"
        "/addBatchMovie - Додати серіал (базовий)\n"
        "/addSuperBatchMovie - Додати серіал (авто-режим)\n"
        "/editContent - Редагувати контент\n"
        "/deleteContent - Видалити контент\n\n"
        "<b>Статистика:</b>\n"
        "/stats - Статистика бота\n\n"
        "<b>Інше:</b>\n"
        "/cancel - Скасувати поточну дію"
    )


# Імпортуємо команду /catalog з catalog handler
async def cmd_catalog(message: Message, state: FSMContext, bot: Bot):
    """Викликати команду /catalog"""
    from bot.handlers.catalog import cmd_catalog as catalog_cmd
    await catalog_cmd(message, state, bot)
