import asyncio
import random
import traceback
from config import MIN_DELAY, MAX_DELAY
from logger import logger

# Re-forward interval: exactly 15 minutes
REFORWARD_INTERVAL = 15 * 60


class Dispatcher:
    def __init__(self, account_manager, targets: list):
        self.account_manager = account_manager
        self.targets = targets
        self.queue = asyncio.Queue()
        self.running = False

    async def enqueue(self, message_data: dict):
        await self.queue.put(message_data)
        logger.info(f"📥 Message enqueued. Queue size: {self.queue.qsize()}")

    async def _interruptible_sleep(self, seconds: int) -> bool:
        """
        Sleep for `seconds` but yield every 1s to check for new messages or stop.
        Returns True if slept fully, False if interrupted.
        """
        for _ in range(seconds):
            if not self.running:
                return False
            if not self.queue.empty():
                logger.info("🚨 New message in queue! Interrupting sleep.")
                return False
            await asyncio.sleep(1)
        return True

    async def _dispatch_to_all(self, message_data: dict) -> bool:
        """
        Forward message_data to every target with a fixed 15-min delay between each.
        Returns True = completed all targets. False = interrupted (stop or new message).
        """
        total = len(self.targets)
        msg_id = message_data.get("message_id")
        from_id = message_data.get("from_chat_id")

        logger.info(f"📤 Dispatching msg={msg_id} to {total} target(s)...")

        for i, target in enumerate(self.targets, 1):
            if not self.running:
                logger.info("🛑 Dispatcher stopped mid-dispatch.")
                return False

            logger.info(f"  [{i}/{total}] Forwarding to {target}...")
            await self.account_manager.send_message(
                target=target,
                from_chat_id=from_id,
                message_id=msg_id,
            )

            # Only sleep BETWEEN targets (not after the last one)
            if i < total:
                delay = random.randint(MIN_DELAY, MAX_DELAY)
                logger.info(f"  ⏳ Waiting {delay}s ({delay//60}m {delay%60}s) before target {i+1}...")
                fully_slept = await self._interruptible_sleep(delay)
                if not fully_slept:
                    logger.info(f"  ⚡ Dispatch interrupted after {i}/{total} targets.")
                    return False

        logger.info(f"✅ All {total} targets received msg={msg_id}.")
        return True

    async def run(self):
        self.running = True
        logger.info("🚀 Dispatcher running. Waiting for first message...")

        current_message = None

        while self.running:
            try:
                # ── STEP 1: Acquire a message ────────────────────────────
                if current_message is None:
                    logger.info("⏸  Queue empty. Blocking until a message arrives...")
                    current_message = await self.queue.get()
                    self.queue.task_done()
                    logger.info(
                        f"📨 Got message ID={current_message.get('message_id')} "
                        f"from chat={current_message.get('from_chat_id')}"
                    )

                # ── STEP 2: Forward to all targets ───────────────────────
                completed = await self._dispatch_to_all(current_message)

                # ── STEP 3a: If interrupted — grab the newest queued msg ──
                if not completed:
                    if not self.queue.empty():
                        current_message = await self.queue.get()
                        self.queue.task_done()
                        logger.info(
                            f"📨 Switching to new msg ID={current_message.get('message_id')}"
                        )
                    # Loop immediately — don't wait 15 min if interrupted
                    continue

                # ── STEP 3b: Completed — wait 15 min or a new message ────
                logger.info(
                    f"⏳ Re-forwarding in {REFORWARD_INTERVAL // 60} min. "
                    "Monitoring queue for early new message..."
                )
                try:
                    new_message = await asyncio.wait_for(
                        self.queue.get(),
                        timeout=REFORWARD_INTERVAL
                    )
                    self.queue.task_done()
                    current_message = new_message
                    logger.info(
                        f"📨 New message arrived early! "
                        f"Switching to msg ID={current_message.get('message_id')}"
                    )
                except asyncio.TimeoutError:
                    # 15 min elapsed, no new message — re-forward same one
                    logger.info(
                        f"🔄 15 min elapsed. Re-forwarding msg ID="
                        f"{current_message.get('message_id')} to all targets..."
                    )
                    # current_message stays the same → loops to STEP 2

            except asyncio.CancelledError:
                logger.info("Dispatcher task cancelled. Shutting down.")
                self.running = False
                break
            except Exception as e:
                logger.error(f"❌ Dispatcher unhandled error: {e}")
                logger.error(traceback.format_exc())
                await asyncio.sleep(5)  # Brief pause before retry

    def stop(self):
        self.running = False
        logger.info("🛑 Dispatcher stop requested.")
