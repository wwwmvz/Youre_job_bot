"""
One-time script to get Telethon session string for Railway.
Run locally: python3 get_tg_session.py
"""
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID   = int(input("Enter TG_API_ID:   ").strip())
API_HASH = input("Enter TG_API_HASH: ").strip()
PHONE    = input("Enter phone (+380...): ").strip()

async def main():
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()

    # Request code explicitly — tries app first, falls back to SMS
    sent = await client.send_code_request(PHONE)
    print(f"\nCode sent via: {type(sent.type).__name__}")
    print("Check Telegram app OR SMS.\n")

    code = input("Enter the code: ").strip()

    try:
        await client.sign_in(PHONE, code)
    except Exception as e:
        if "two" in str(e).lower() or "password" in str(e).lower():
            pwd = input("2FA password: ").strip()
            await client.sign_in(password=pwd)
        else:
            raise

    session_str = client.session.save()
    print("\n✅ Copy this to Railway as TG_SESSION:\n")
    print(session_str)
    await client.disconnect()

asyncio.run(main())
