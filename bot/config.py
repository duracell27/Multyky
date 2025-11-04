import os
from dotenv import load_dotenv

# Завантаження змінних з .env файлу
load_dotenv()


class Config:
    """Конфігурація бота"""

    # Telegram
    BOT_TOKEN = os.getenv("BOT_TOKEN")

    # MongoDB
    MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    MONGODB_DB = os.getenv("MONGODB_DB", "cartoons_bot")

    # Адміністратори
    ADMIN_IDS = [
        int(admin_id.strip())
        for admin_id in os.getenv("ADMIN_IDS", "").split(",")
        if admin_id.strip()
    ]

    @classmethod
    def validate(cls):
        """Перевірка наявності обов'язкових налаштувань"""
        if not cls.BOT_TOKEN:
            raise ValueError("BOT_TOKEN не встановлено в .env файлі")
        return True


config = Config()
