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
                logger.info(
                    f"📡 New post detected! "
                    f"chat_id={message.chat.id} | "
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

        # Filter to only the configured source channel
        self.client.add_handler(
            MessageHandler(on_new_post, filters.chat(SOURCE_CHANNEL))
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
