import asyncio
import os
import sys
import traceback
from pyrogram import Client
from config import ACCOUNTS, TARGETS_FILE, SOURCE_CHANNEL, MOCK_MODE
from account_manager import AccountManager
from dispatcher import Dispatcher
from monitor import Monitor
from logger import logger


def load_targets(filepath: str) -> list:
    """Load target usernames/phone numbers from file."""
    if not os.path.exists(filepath):
        logger.error(f"Targets file not found: {filepath}")
        return []

    targets = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            # Strip all whitespace including \r and \n
            line = line.strip()
            if line and not line.startswith("#"):
                # Convert numeric IDs (like -100xxx) to integers
                if line.lstrip('-').isdigit():
                    targets.append(int(line))
                else:
                    targets.append(line)

    if not targets:
        logger.error("No targets found in targets.txt!")
        return []

    logger.info(f"Loaded {len(targets)} targets from {filepath}")
    for t in targets:
        logger.info(f"  Target: {t}")
    return targets


async def main():
    logger.info("=" * 55)
    logger.info("   TELEGRAM BULK MESSENGER — Starting Up")
    logger.info("=" * 55)

    # 1. Load targets
    targets = load_targets(TARGETS_FILE)
    if not targets:
        logger.error("No valid targets. Please add targets in the Admin Panel and restart.")
        return

    # 2. Initialize account manager (logs in all sender accounts)
    account_manager = AccountManager()
    await account_manager.initialize()

    # 3. Set up dispatcher with the target list
    dispatcher = Dispatcher(account_manager, targets)

    # 4. Handle Mock vs Real Monitor
    if MOCK_MODE:
        logger.info("🛠️  MOCK MODE: Injecting a test message to start the demo...")
        # Inject a fake message data
        fake_message = {
            "from_chat_id": 123456789,
            "message_id": 1
        }
        await dispatcher.enqueue(fake_message)
        
        try:
            await dispatcher.run()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
    else:
        # Real production mode
        # Reuse the FIRST client already started by account_manager
        # This avoids the "sqlite3.OperationalError: database is locked" error
        monitor_client = account_manager.clients[0]
        
        logger.info(f"Monitor client active. Watching: {SOURCE_CHANNEL}")
        monitor = Monitor(monitor_client, dispatcher)
        
        # Diagnostic: List all channels we can see
        await monitor.list_channels()
        
        # Start dispatcher in the background
        dispatcher_task = asyncio.create_task(dispatcher.run())
        
        try:
            # idle() keeps the script running and listening for events
            await monitor_client.idle()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            dispatcher.stop()
            await dispatcher_task

    # 5. Shutdown
    await account_manager.stop_all()
    logger.info("Bot stopped cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot interrupted by user.")
    except Exception as e:
        print("\n" + "=" * 55)
        print("❌ BOT CRASHED WITH ERROR:")
        print("=" * 55)
        traceback.print_exc()
        print("=" * 55)
    finally:
        print("\nBot has stopped.")
