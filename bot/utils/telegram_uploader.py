import asyncio
import logging
from telethon import TelegramClient
from telethon.sessions import StringSession

from bot.config import config

logger = logging.getLogger(__name__)

_client: TelegramClient | None = None


async def get_client() -> TelegramClient:
    global _client
    if _client is None or not _client.is_connected():
        _client = TelegramClient(
            "telethon_session",
            config.TELEGRAM_API_ID,
            config.TELEGRAM_API_HASH,
        )
        await _client.start()
    return _client


async def upload_video_to_channel(
    channel_id: int,
    file_path: str,
    caption: str,
) -> int:
    """
    Uploads a video file to the channel via Telethon (no size limit).
    Returns the message_id of the sent message.
    """
    client = await get_client()
    msg = await client.send_file(
        channel_id,
        file_path,
        caption=caption,
        supports_streaming=True,
    )
    logger.info(f"Uploaded via Telethon: message_id={msg.id}")
    return msg.id
