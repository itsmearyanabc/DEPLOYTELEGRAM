import asyncio
import traceback
import os
import sys

# ── Python 3.10+ event loop fix ──────────────────────────────────────────────
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from config import ACCOUNTS, TARGETS_FILE, SOURCE_CHANNEL, MOCK_MODE
from account_manager import AccountManager
from dispatcher import Dispatcher
from monitor import Monitor
from logger import logger


def load_targets(filepath: str) -> list:
    """Load and normalise targets from file. Converts numeric IDs to int."""
    if not os.path.exists(filepath):
        logger.error(f"❌ Targets file not found: {filepath}")
        return []

    targets = []
    with open(filepath, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            # Convert numeric IDs (positive or negative) to int
            if line.lstrip("-").isdigit():
                targets.append(int(line))
            else:
                # Strip leading @ if present
                targets.append(line.lstrip("@"))

    if not targets:
        logger.error("❌ No valid targets found in targets.txt!")
        return []

    logger.info(f"✅ Loaded {len(targets)} target(s):")
    for t in targets:
        logger.info(f"    → {t}")
    return targets


async def main():
    logger.info("=" * 60)
    logger.info("   ARMEDIAS TELEGRAM FORWARDER — Starting Up")
    logger.info("=" * 60)

    # ── 1. Load targets ───────────────────────────────────────────────────────
    targets = load_targets(TARGETS_FILE)
    if not targets:
        logger.error("No valid targets. Add targets in the Admin Panel and restart.")
        return

    # ── 2. Init accounts ──────────────────────────────────────────────────────
    account_manager = AccountManager()
    try:
        await account_manager.initialize()
    except RuntimeError as e:
        logger.error(f"Startup failed: {e}")
        return

    # ── 3. Build dispatcher ───────────────────────────────────────────────────
    dispatcher = Dispatcher(account_manager, targets)

    # ── 4. Mock mode (for stress-testing only) ────────────────────────────────
    if MOCK_MODE:
        logger.info("🛠️  MOCK MODE active. Injecting test messages...")
        for i in range(1, 4):
            await dispatcher.enqueue({
                "from_chat_id": 123456789,
                "message_id": i,
                "text": f"Test message {i}"
            })

        try:
            await dispatcher.run()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            dispatcher.stop()
            await account_manager.stop_all()
        return

    # ── 5. Production mode ────────────────────────────────────────────────────
    # Use the FIRST already-started client as the monitor
    monitor_client = account_manager.clients[0]
    logger.info(f"👁️  Monitor using client: {monitor_client.name}")

    monitor = Monitor(monitor_client, dispatcher)

    # Diagnostic: print all visible channels
    await monitor.list_channels()

    # Start dispatcher as a background task
    dispatcher_task = asyncio.create_task(dispatcher.run())

    try:
        from pyrogram import idle
        logger.info("✅ Bot fully operational. Listening for messages...")
        await idle()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutdown signal received.")
    except Exception as e:
        logger.error(f"❌ Idle error: {e}")
        logger.error(traceback.format_exc())
    finally:
        logger.info("Shutting down...")
        dispatcher.stop()

        # Cancel dispatcher task cleanly
        dispatcher_task.cancel()
        try:
            await dispatcher_task
        except asyncio.CancelledError:
            pass

        await account_manager.stop_all()
        logger.info("✅ Bot stopped cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot interrupted by user.")
    except Exception:
        print("\n" + "=" * 60)
        print("❌ BOT CRASHED:")
        print("=" * 60)
        traceback.print_exc()
        print("=" * 60)
        sys.exit(1)
    finally:
        print("\nBot has stopped.")
