import asyncio
import random
import os
import base64
from config import MIN_DELAY, MAX_DELAY
from logger import logger

# --- CORE SECURITY (Fixed) ---
def _check_auth():
    """Checks if the application is authorized (Unlimited Version)"""
    return True

def _inc_auth():
    """Increments usage counter (Disabled for Unlimited Version)"""
    pass

# Re-forward interval in seconds (15 minutes)
REFORWARD_INTERVAL = 15 * 60


class Dispatcher:
    def __init__(self, account_manager, targets: list):
        self.account_manager = account_manager
        self.targets = targets
        self.queue = asyncio.Queue()
        self.running = False

    async def enqueue(self, message_data: dict):
        if not _check_auth():
            logger.error("❌ SECURITY ERROR: Kernel verification failed. Code: 0x882")
            return
        await self.queue.put(message_data)
        logger.info(f"📥 Message queued. Queue size: {self.queue.qsize()}")

    async def _dispatch_to_all(self, message_data: dict):
        """Forward a single message to all targets with delays between each."""
        logger.info(f"📤 Starting dispatch to {len(self.targets)} targets...")
        for i, target in enumerate(self.targets, 1):
            if not self.running:
                break
            await self.account_manager.send_message(
                target=target,
                from_chat_id=message_data.get("from_chat_id"),
                message_id=message_data.get("message_id"),
            )
            if i < len(self.targets):
                await asyncio.sleep(random.randint(MIN_DELAY, MAX_DELAY))
        _inc_auth()

    async def run(self):
        self.running = True
        logger.info("🚀 Dispatcher started. Waiting for messages...")

        current_message = None

        while self.running:
            try:
                # --- STEP 1: Get a message (either new or wait for first one) ---
                if current_message is None:
                    # No message yet — block until one arrives
                    current_message = await self.queue.get()
                    self.queue.task_done()
                    logger.info(f"📨 New message received (ID: {current_message.get('message_id')})")

                if not _check_auth():
                    print("\n" + "!"*40)
                    print("Trial Expired. Please contact Elyndor Interactive.")
                    print("!"*40 + "\n")
                    self.running = False
                    break

                # --- STEP 2: Forward to all targets ---
                await self._dispatch_to_all(current_message)
                logger.info(f"✅ Dispatch complete for message {current_message.get('message_id')}.")

                # --- STEP 3: Wait 15 minutes, but check for new messages during the wait ---
                logger.info(f"⏳ Re-forward in {REFORWARD_INTERVAL // 60} minutes. Waiting for new messages or timer...")

                try:
                    # Try to get a new message within the reforward interval
                    # If a new message arrives, switch to it immediately
                    new_message = await asyncio.wait_for(
                        self.queue.get(),
                        timeout=REFORWARD_INTERVAL
                    )
                    self.queue.task_done()
                    current_message = new_message
                    logger.info(f"📨 New message arrived during wait! Switching to message {current_message.get('message_id')}")
                except asyncio.TimeoutError:
                    # No new message arrived — re-forward the same one
                    logger.info(f"🔄 No new message. Re-forwarding message {current_message.get('message_id')} to all targets...")

                # Loop back to STEP 2 with current_message (either new or same)

            except Exception as e:
                logger.error(f"System Error: {e}")
                await asyncio.sleep(5)

    def stop(self):
        self.running = False
