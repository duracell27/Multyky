from aiogram.fsm.state import State, StatesGroup


class AddMovieStates(StatesGroup):
    """Стани для додавання одиночного фільму"""
    waiting_for_title = State()  # Чекаємо українську назву
    waiting_for_title_en = State()  # Чекаємо англійську назву
    waiting_for_year = State()  # Чекаємо рік
    waiting_for_imdb = State()  # Чекаємо IMDB рейтинг
    waiting_for_poster = State()  # Чекаємо постер
    waiting_for_video = State()  # Чекаємо відео


class AddBatchMovieStates(StatesGroup):
    """Стани для пакетного додавання серій серіалу"""
    choosing_existing_series = State()  # Вибір існуючого серіалу
    # Створення нового серіалу
    waiting_for_new_series_title = State()  # Чекаємо українську назву
    waiting_for_new_series_title_en = State()  # Чекаємо англійську назву
    waiting_for_new_series_year = State()  # Чекаємо рік
    waiting_for_new_series_imdb = State()  # Чекаємо IMDB рейтинг
    waiting_for_new_series_poster = State()  # Чекаємо постер
    # Додавання епізодів
    waiting_for_season = State()  # Чекаємо номер сезону
    waiting_for_episode_range = State()  # Чекаємо діапазон серій (наприклад "1-5" або "3")
    waiting_for_videos = State()  # Чекаємо пересланні відео з каналу


class DeleteContentStates(StatesGroup):
    """Стани для видалення контенту"""
    choosing_content_type = State()  # Вибір типу (фільм або серіал)
    choosing_content = State()  # Вибір конкретного контенту
    choosing_delete_option = State()  # Вибір опції видалення (для серіалів)
    choosing_season = State()  # Вибір сезону для видалення
    choosing_episode = State()  # Вибір серії для видалення


class EditContentStates(StatesGroup):
    """Стани для редагування контенту"""
    choosing_content_type = State()  # Вибір типу (фільм або серіал)
    choosing_content = State()  # Вибір конкретного контенту
    choosing_field = State()  # Вибір поля для редагування
    waiting_for_new_value = State()  # Чекаємо нове значення
    waiting_for_poster = State()  # Чекаємо новий постер
    waiting_for_video = State()  # Чекаємо нове відео (для фільму)
    choosing_season_for_edit = State()  # Вибір сезону для редагування серії
    choosing_episode_for_edit = State()  # Вибір серії для редагування
    waiting_for_episode_video = State()  # Чекаємо нове відео для серії


class SearchStates(StatesGroup):
    """Стани для пошуку контенту"""
    waiting_for_query = State()  # Чекаємо пошуковий запит від користувача


class AddSuperBatchMovieStates(StatesGroup):
    """Стани для супер пакетного додавання серій (автоматичне визначення сезону/епізоду)"""
    choosing_existing_series = State()  # Вибір існуючого серіалу
    # Створення нового серіалу (якщо потрібно)
    waiting_for_new_series_title = State()  # Чекаємо українську назву
    waiting_for_new_series_title_en = State()  # Чекаємо англійську назву
    waiting_for_new_series_year = State()  # Чекаємо рік
    waiting_for_new_series_imdb = State()  # Чекаємо IMDB рейтинг
    waiting_for_new_series_poster = State()  # Чекаємо постер
    # Додавання епізодів (автоматично визначаємо сезон і епізод з caption)
    waiting_for_videos = State()  # Чекаємо переслані відео з каналу


class HelpStates(StatesGroup):
    """Стани для допомоги користувачам"""
    waiting_for_request = State()  # Чекаємо запит на мультфільм
    waiting_for_message = State()  # Чекаємо повідомлення адміну
