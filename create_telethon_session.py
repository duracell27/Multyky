import asyncio
from telethon import TelegramClient
from dotenv import load_dotenv
import os

load_dotenv()

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")

async def main():
    client = TelegramClient("telethon_session", API_ID, API_HASH)
    await client.start()
    me = await client.get_me()
    print(f"\n✅ Авторизовано як: {me.first_name} (@{me.username})")
    print("Файл сесії 'telethon_session.session' створено.")
    await client.disconnect()

asyncio.run(main())
