from bot.handlers.common import router as common_router
from bot.handlers.admin import router as admin_router
from bot.handlers.catalog import router as catalog_router
from bot.handlers.broadcast import router as broadcast_router

__all__ = ["common_router", "admin_router", "catalog_router", "broadcast_router"]
