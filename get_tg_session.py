"""
Run this script ONCE on your local machine to get the Telethon session string.
Then save the output as TG_SESSION env var in Railway.

Usage:
    python3 get_tg_session.py

You need:
    TG_API_ID   — integer from https://my.telegram.org
    TG_API_HASH — string  from https://my.telegram.org
"""
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID   = int(input("Enter TG_API_ID:   ").strip())
API_HASH = input("Enter TG_API_HASH: ").strip()

async def main():
    async with TelegramClient(StringSession(), API_ID, API_HASH) as client:
        session_str = client.session.save()
        print("\n✅ Session string (copy this to Railway as TG_SESSION):\n")
        print(session_str)
        print()

asyncio.run(main())
