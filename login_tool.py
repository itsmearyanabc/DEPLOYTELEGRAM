import asyncio
import os
from pyrogram import Client

async def manual_login():
    print("\n" + "="*50)
    print("      ELYNDOR INTERACTIVE - SESSION CREATOR")
    print("="*50)
    print("Use this tool to log in once. Your session will be saved forever.")
    
    phone = input("\nEnter Phone Number (with country code, e.g. +91XXXXXXXXXX): ").strip().replace(" ", "")
    api_id = input("Enter API ID: ").strip()
    api_hash = input("Enter API Hash: ").strip()

    os.makedirs("sessions", exist_ok=True)
    p_clean = phone.replace('+', '').replace(' ', '').replace('-', '')
    session_name = f"sessions/session_{p_clean}"

    client = Client(
        name=session_name,
        api_id=int(api_id),
        api_hash=api_hash,
        phone_number=phone
    )

    try:
        await client.start()
        me = await client.get_me()
        print(f"\n✅ SUCCESS! Logged in as: {me.first_name}")
        print(f"📂 Session saved to: {session_name}.session")
        print("\nYou can now close this and use the Admin Panel to start the bot.")
        await client.stop()
    except Exception as e:
        print(f"\n❌ ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(manual_login())
