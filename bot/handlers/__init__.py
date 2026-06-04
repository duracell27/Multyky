from bot.handlers.common import router as common_router
from bot.handlers.admin import router as admin_router
from bot.handlers.catalog import router as catalog_router
from bot.handlers.broadcast import router as broadcast_router
from bot.handlers.auto_download import router as auto_download_router
from bot.handlers.auto_movie import router as auto_movie_router
from bot.handlers.auto_anime_movie import router as auto_anime_movie_router
from bot.handlers.auto_anime_download import router as auto_anime_download_router

__all__ = [
    "common_router", "admin_router", "catalog_router",
    "broadcast_router", "auto_download_router", "auto_movie_router",
    "auto_anime_movie_router", "auto_anime_download_router",
]
