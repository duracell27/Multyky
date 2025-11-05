from aiogram.fsm.state import State, StatesGroup


class AddMovieStates(StatesGroup):
    """Стани для додавання мультфільму"""
    choosing_add_type = State()  # Вибір: новий контент чи серія до існуючого
    choosing_existing_series = State()  # Вибір існуючого серіалу
    waiting_for_title = State()  # Чекаємо назву українською
    waiting_for_title_en = State()  # Чекаємо назву англійською
    waiting_for_year = State()  # Чекаємо рік випуску
    waiting_for_imdb_rating = State()  # Чекаємо рейтинг IMDB
    waiting_for_poster = State()  # Чекаємо картинку (poster)
    waiting_for_content_type = State()  # Чекаємо вибір типу (фільм/серіал)
    waiting_for_season = State()  # Чекаємо номер сезону (тільки для серіалів)
    waiting_for_episode = State()  # Чекаємо номер серії (тільки для серіалів)
    waiting_for_video = State()  # Чекаємо відео


class AddBatchMovieStates(StatesGroup):
    """Стани для пакетного додавання серій серіалу"""
    choosing_series_type = State()  # Вибір: новий серіал чи існуючий
    choosing_existing_series = State()  # Вибір існуючого серіалу
    waiting_for_title = State()  # Чекаємо назву українською (для нового серіалу)
    waiting_for_title_en = State()  # Чекаємо назву англійською (для нового серіалу)
    waiting_for_year = State()  # Чекаємо рік випуску (для нового серіалу)
    waiting_for_imdb_rating = State()  # Чекаємо рейтинг IMDB (для нового серіалу)
    waiting_for_poster = State()  # Чекаємо картинку (poster) для нового серіалу
    waiting_for_season = State()  # Чекаємо номер сезону
    waiting_for_episode_range = State()  # Чекаємо діапазон серій (наприклад "1-5")
    waiting_for_videos = State()  # Чекаємо всі відео підряд
