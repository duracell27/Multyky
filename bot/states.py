from aiogram.fsm.state import State, StatesGroup


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
