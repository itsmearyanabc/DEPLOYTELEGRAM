import traceback
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.handlers import MessageHandler
from config import SOURCE_CHANNEL
from logger import logger


class Monitor:
    """
    Listens on the source channel for new posts.
    Validates IDs and enqueues messages into the Dispatcher.
    """

    def __init__(self, client: Client, dispatcher):
        self.client = client
        self.dispatcher = dispatcher
        self._validate_source_channel()
        self._register_handlers()

    def _validate_source_channel(self):
        """Warn if SOURCE_CHANNEL looks malformed."""
        sc = SOURCE_CHANNEL
        if isinstance(sc, int):
            if sc > 0:
                logger.warning(
                    f"⚠️  SOURCE_CHANNEL={sc} is a POSITIVE integer. "
                    "Supergroups/Channels must use a NEGATIVE ID like -100XXXXXXXXXX. "
                    "The bot may not receive messages!"
                )
            else:
                logger.info(f"✅ SOURCE_CHANNEL={sc} (numeric, looks correct).")
        elif isinstance(sc, str):
            logger.info(f"✅ SOURCE_CHANNEL='{sc}' (username).")
        else:
            logger.error(f"❌ SOURCE_CHANNEL has invalid type: {type(sc)}. Check config.py!")

    def _register_handlers(self):
        """Register Pyrogram handler for incoming channel posts."""

        async def on_new_post(client: Client, message: Message):
            try:
                # Basic logging for any message that passes the filter
                logger.info(
                    f"📡 [FILTERED] New post in source channel! "
                    f"msg_id={message.id} | "
                    f"type={message.media or 'text'}"
                )

                message_data = {
                    "from_chat_id": message.chat.id,
                    "message_id": message.id,
                    "text": (message.text or message.caption or "")[:100],
                }

                await self.dispatcher.enqueue(message_data)

            except Exception as e:
                logger.error(f"❌ Monitor handler error: {e}")
                logger.error(traceback.format_exc())

        async def raw_debug_handler(client: Client, message: Message):
            """Log ID of EVERY message seen to help find the correct SOURCE_CHANNEL."""
            try:
                # Log only once per chat to avoid spamming
                if not hasattr(self, "_seen_chats"):
                    self._seen_chats = set()
                
                if message.chat.id not in self._seen_chats:
                    logger.info(f"🔍 DEBUG: Bot just saw a message from Chat ID: {message.chat.id} ({message.chat.title or 'Private'})")
                    self._seen_chats.add(message.chat.id)
            except:
                pass

        # 1. Raw Debug Handler (catch all)
        self.client.add_handler(MessageHandler(raw_debug_handler), group=-1)

        # 2. Main Filtered Handler
        # We combine chat filter with channel/group filters to be safe
        chat_filter = filters.chat(SOURCE_CHANNEL)
        
        self.client.add_handler(
            MessageHandler(on_new_post, chat_filter)
        )
        logger.info(f"👂 Listening for posts in: {SOURCE_CHANNEL}")

    async def list_channels(self):
        """Log all channels/supergroups the account can see (for debugging)."""
        logger.info("🔍 Scanning dialogs for channels and supergroups...")
        found = 0
        async for dialog in self.client.get_dialogs():
            chat = dialog.chat
            if hasattr(chat, "type") and chat.type and chat.type.value in ("channel", "supergroup"):
                logger.info(
                    f"  ID={chat.id} | @{chat.username or 'private'} | {chat.title}"
                )
                found += 1
        if found == 0:
            logger.warning("⚠️  No channels or supergroups found in this account's dialogs.")
        else:
            logger.info(f"🔍 Found {found} channel(s)/supergroup(s).")
