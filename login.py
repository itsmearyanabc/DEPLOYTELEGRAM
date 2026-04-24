"""
Direct Login Script — Authenticates your Telegram accounts reliably.
Run this ONCE before starting the bot.

Usage: python login.py
"""
import asyncio
import os
import json
from pyrogram import Client

async def main():
    # Load config
    with open("config.json", "r") as f:
        config = json.load(f)

    api_id = int(config["api_id"])
    api_hash = config["api_hash"]
    phones = [p.strip() for p in config["phones"].replace('\r\n', '\n').replace('\r', '\n').split('\n') if p.strip()]

    if not phones:
        print("❌ No phone numbers found in config.json!")
        return

    os.makedirs("sessions", exist_ok=True)

    print("=" * 50)
    print("  TELEGRAM ACCOUNT LOGIN")
    print("=" * 50)

    for phone in phones:
        p_clean = phone.replace('+', '').replace(' ', '').replace('-', '')
        session_path = f"sessions/session_{p_clean}"
        session_file = f"{session_path}.session"

        # Delete old broken session
        if os.path.exists(session_file):
            os.remove(session_file)
            print(f"🗑️  Deleted old session for {phone}")

        print(f"\n📱 Logging in: {phone}")
        print("   Telegram will send you a code...")

        client = Client(
            session_path,
            api_id=api_id,
            api_hash=api_hash,
            phone_number=phone,
            device_model="iPhone 15 Pro Max",
            system_version="iOS 17.5.1",
            app_version="10.14.1",
            lang_code="en"
        )

        try:
            # start() handles the full interactive login flow:
            # sends code, prompts you to enter it, handles 2FA if needed
            await client.start()
            me = await client.get_me()
            print(f"   ✅ SUCCESS! Logged in as: {me.first_name} (ID: {me.id})")
            await client.stop()
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            # Clean up broken session
            if os.path.exists(session_file):
                try: os.remove(session_file)
                except: pass

    print("\n" + "=" * 50)
    print("  LOGIN COMPLETE — You can now run: python app.py")
    print("=" * 50)

if __name__ == "__main__":
    asyncio.run(main())
