import asyncio
import itertools
from pyrogram import Client
from pyrogram.errors import FloodWait, PeerFlood, UserPrivacyRestricted, RPCError
from logger import logger
from config import MOCK_MODE

class AccountManager:
    def __init__(self):
        from config import ACCOUNTS
        self.account_configs = ACCOUNTS
        self.clients = []
        self._cycle = None

    async def initialize(self):
        """Log in to all configured accounts."""
        import os
        os.makedirs("sessions", exist_ok=True)
        
        tasks = []
        for config in self.account_configs:
            if MOCK_MODE:
                tasks.append(asyncio.create_task(self._mock_init(config)))
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
                lang_code="en"
            )
            # Trigger code request
            tasks.append(asyncio.create_task(self._start_client_safely(client, config['name'])))
            
            # SMALL DELAY: Prevents Telegram from blocking simultaneous requests
            await asyncio.sleep(5)

        # Ensure all tasks are gathered
        await asyncio.gather(*tasks)

        if not self.clients:
            logger.error("No accounts could be initialized. Check config.py.")
            raise RuntimeError("No accounts could be initialized.")

        self._cycle = itertools.cycle(self.clients)
        logger.info(f"Account pool ready with {len(self.clients)} account(s).")

    async def _start_client_safely(self, client, name):
        """Helper to start client and add to pool without terminal prompts."""
        try:
            # Step 1: Raw connection to check auth status silently
            await client.connect()
            me = await client.get_me() # Raises error if not authorized
            await client.disconnect()

            # Step 2: Since we know it's authorized, start() will NOT prompt for code
            # start() is required to initialize the message listener!
            await client.start()
            self.clients.append(client)
            logger.info(f"  ✅ Logged in as: {name} ({me.first_name})")
        except Exception as e:
            logger.error(f"  ❌ Auth Error for {name}: {type(e).__name__}: {e}")
            logger.error(f"     → Please authenticate this account in the Web Panel.")
            try: await client.disconnect() 
            except: pass
    async def _mock_init(self, config):
        """Helper for mock parallel init."""
        client = type('MockClient', (), {
            'name': config['session_name'],
            'forward_messages': self._mock_forward,
            'start': lambda: None,
            'stop': lambda: None
        })
        self.clients.append(client)
        logger.info(f"  ✅ [MOCK] Loaded: {config['name']}")

    async def _mock_forward(self, *args, **kwargs):
        """Helper for MOCK_MODE stress testing."""
        import random
        from pyrogram.errors import FloodWait, PeerFlood
        chaos_factor = random.random()
        if chaos_factor < 0.2:
            raise FloodWait(30)
        elif chaos_factor < 0.4:
            raise PeerFlood()
        await asyncio.sleep(0.1)

    def next_client(self) -> Client:
        return next(self._cycle)

    async def send_message(self, target: str, from_chat_id: int, message_id: int, retries=2) -> bool:
        """Forward message with advanced error handling and account skipping."""
        if not self.clients:
            return False

        # Try multiple accounts if one fails
        for attempt in range(len(self.clients)):
            client = self.next_client()
            acc_info = f"Acc_{client.name.split('_')[-1]}"

            try:
                await client.forward_messages(
                    chat_id=target,
                    from_chat_id=from_chat_id,
                    message_ids=message_id
                )
                logger.info(f"  [{acc_info}] ✅ Success -> {target}")
                return True

            except FloodWait as e:
                logger.warning(f"  [{acc_info}] ⚠️ FloodWait ({e.value}s). Skipping to next account...")
                continue # Try next account immediately
            
            except (PeerFlood, UserPrivacyRestricted):
                logger.warning(f"  [{acc_info}] 🚫 Restricted or Privacy Blocked for {target}. Skipping...")
                continue # Try next account
            
            except RPCError as e:
                logger.error(f"  [{acc_info}] ❌ Telegram Error: {e.MESSAGE}. Skipping...")
                continue

            except Exception as e:
                logger.error(f"  [{acc_info}] ❌ Unexpected Error: {e}")
                continue

        logger.error(f"  🔥 All accounts failed to deliver to {target}.")
        return False

    async def stop_all(self):
        for client in self.clients:
            try:
                await client.stop()
            except:
                pass
