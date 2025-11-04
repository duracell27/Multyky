import logging
import certifi
from motor.motor_asyncio import AsyncIOMotorClient
from bot.config import config

logger = logging.getLogger(__name__)


class MongoDB:
    """Клас для роботи з MongoDB"""

    def __init__(self):
        self.client = None
        self.db = None

    async def connect(self):
        """Підключення до MongoDB"""
        try:
            self.client = AsyncIOMotorClient(
                config.MONGODB_URL,
                tlsCAFile=certifi.where()
            )
            self.db = self.client[config.MONGODB_DB]
            # Перевірка підключення
            await self.client.admin.command('ping')
            logger.info(f"✅ Підключено до MongoDB: {config.MONGODB_DB}")
        except Exception as e:
            logger.error(f"❌ Помилка підключення до MongoDB: {e}")
            raise

    async def close(self):
        """Закриття з'єднання з MongoDB"""
        if self.client:
            self.client.close()
            logger.info("❌ З'єднання з MongoDB закрито")

    # Колекції
    @property
    def users(self):
        """Колекція користувачів"""
        return self.db.users

    @property
    def videos(self):
        """Колекція відео"""
        return self.db.videos


# Глобальний екземпляр
db = MongoDB()
