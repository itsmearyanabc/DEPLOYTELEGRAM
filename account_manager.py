import asyncio
import itertools
import traceback
from pyrogram import Client
from pyrogram.errors import (
    FloodWait, PeerFlood, UserPrivacyRestricted,
    ChatWriteForbidden, ChannelPrivate, UserBannedInChannel,
    RPCError, SlowmodeWait, ChatAdminRequired, UserNotParticipant
)
from logger import logger
from config import MOCK_MODE


class AccountManager:
    def __init__(self):
        from config import ACCOUNTS
        self.account_configs = ACCOUNTS
        self.clients = []
        self._cycle = None

    async def initialize(self):
        """Connect all accounts; skip any that fail auth."""
        import os
        os.makedirs("sessions", exist_ok=True)
        
        existing_sessions = os.listdir("sessions")
        logger.info(f"📂 Current session files: {existing_sessions}")
        
        for config in self.account_configs:
            if MOCK_MODE:
                await self._mock_init(config)
                continue

            clean_phone = config["phone"].replace(" ", "").replace("-", "")
            client = Client(
                name=config["session_name"],
                api_id=config["api_id"],
                api_hash=config["api_hash"],
                phone_number=clean_phone,
                device_model="iPhone 15 Pro Max",
                system_version="iOS 17.5.1",
                app_version="10.14.1",
                lang_code="en",
                workdir="."
            )
            await self._start_client_safely(client, config["name"])
            # Small gap to avoid simultaneous Telegram auth requests
            await asyncio.sleep(3)

        if not self.clients:
            logger.error("❌ FATAL: No accounts could be initialized. Check config and session files.")
            raise RuntimeError("No accounts could be initialized.")

        self._cycle = itertools.cycle(self.clients)
        logger.info(f"✅ Account pool ready: {len(self.clients)} account(s) active.")

    async def _start_client_safely(self, client: Client, name: str):
        """
        Connect → verify auth → then start() for event listening.
        Avoids terminal prompts for code — only works if session file exists.
        """
        try:
            logger.info(f"  🔄 Attempting to initialize {name}...")
            await client.connect()
            
            try:
                me = await client.get_me()
                if not me:
                    raise RuntimeError("get_me() returned None")
            except Exception as auth_err:
                logger.error(f"  ❌ {name} is NOT authenticated: {auth_err}")
                await client.disconnect()
                return

            await client.disconnect()

            # Re-start properly so handlers work
            await client.start()
            self.clients.append(client)
            logger.info(f"  ✅ SUCCESS: {name} authenticated as {me.first_name} (@{me.username or 'no_user'})")

        except Exception as e:
            logger.error(f"  ❌ Failed to start {name}: {type(e).__name__}: {e}")
            try:
                await client.disconnect()
            except Exception:
                pass

    async def _mock_init(self, config):
        """Fake client for stress/mock tests."""
        client = type("MockClient", (), {
            "name": config["session_name"],
            "forward_messages": self._mock_forward,
            "start": lambda: None,
            "stop": lambda: None,
        })
        self.clients.append(client)
        logger.info(f"  ✅ [MOCK] Loaded: {config['name']}")

    async def _mock_forward(self, *args, **kwargs):
        """Simulate random Telegram errors in mock mode."""
        import random
        chaos = random.random()
        if chaos < 0.15:
            raise FloodWait(30)
        elif chaos < 0.30:
            raise PeerFlood()
        await asyncio.sleep(0.05)

    def next_client(self) -> Client:
        return next(self._cycle)

    async def send_message(
        self,
        target: str,
        from_chat_id: int,
        message_id: int,
    ) -> bool:
        """
        Forward a message to a target, trying every account before giving up.
        Skips accounts that are FloodWait'd, Restricted, or Banned.
        """
        if not self.clients:
            logger.error("❌ No clients available to send messages.")
            return False

        num_accounts = len(self.clients)

        for attempt in range(num_accounts):
            client = self.next_client()
            acc_tag = f"[{client.name.split('_')[-1]}]"

            try:
                await client.forward_messages(
                    chat_id=target,
                    from_chat_id=from_chat_id,
                    message_ids=message_id,
                )
                logger.info(f"  {acc_tag} ✅ Forwarded → {target}")
                return True

            except FloodWait as e:
                logger.warning(
                    f"  {acc_tag} ⚠️  FloodWait {e.value}s for {target}. "
                    "Trying next account..."
                )
                continue

            except SlowmodeWait as e:
                logger.warning(
                    f"  {acc_tag} ⚠️  SlowmodeWait {e.value}s for {target}. "
                    "Trying next account..."
                )
                continue

            except (PeerFlood, UserPrivacyRestricted):
                logger.warning(
                    f"  {acc_tag} 🚫 PeerFlood/Privacy for {target}. "
                    "Trying next account..."
                )
                continue

            except (ChatWriteForbidden, ChannelPrivate, UserBannedInChannel,
                    ChatAdminRequired, UserNotParticipant) as e:
                # These are target-level problems — no point retrying same target
                logger.error(
                    f"  {acc_tag} 🔒 Target {target} is unreachable: "
                    f"{type(e).__name__}. Skipping target entirely."
                )
                return False  # Skip this target, move to next

            except RPCError as e:
                logger.error(
                    f"  {acc_tag} ❌ RPC Error for {target}: "
                    f"[{e.ID}] {e.MESSAGE}"
                )
                continue

            except Exception as e:
                logger.error(
                    f"  {acc_tag} ❌ Unexpected error for {target}: "
                    f"{type(e).__name__}: {e}"
                )
                logger.error(traceback.format_exc())
                continue

        logger.error(f"  🔥 All {num_accounts} accounts failed for {target}. Message NOT sent.")
        return False

    async def stop_all(self):
        """Gracefully stop all running clients."""
        for client in self.clients:
            try:
                await client.stop()
            except Exception:
                pass
        logger.info("All accounts disconnected.")
