from pyrogram import Client, filters
from pyrogram.types import Message
from config import SOURCE_CHANNEL
from logger import logger

class Monitor:
    """
    Monitors the source Telegram channel for new posts.
    When a new message is detected, it enqueues it in the Dispatcher.
    """

    def __init__(self, client: Client, dispatcher):
        self.client = client
        self.dispatcher = dispatcher
        self._register_handlers()

    async def list_channels(self):
        logger.info("🔍 Scanning joined channels/chats...")
        async for dialog in self.client.get_dialogs():
            if dialog.chat.type.value in ["channel", "supergroup"]:
                logger.info(f"  - [{dialog.chat.id}] {dialog.chat.title} (@{dialog.chat.username})")

    def _register_handlers(self):
        """Register the message handler for new channel posts."""
        from pyrogram.handlers import MessageHandler
        
        async def on_new_post(client: Client, message: Message):
            logger.info(
                f"📡 New post detected in source channel! "
                f"[Message ID: {message.id}]"
            )

            # Build a message data dict that dispatcher can use
            message_data = {
                "from_chat_id": message.chat.id,
                "message_id": message.id,
                "text": message.text or message.caption,
            }

            await self.dispatcher.enqueue(message_data)
            
        self.client.add_handler(MessageHandler(on_new_post, filters.chat(SOURCE_CHANNEL)))

    async def run(self, client: Client):
        """
        Keep the monitor's client running.
        The client passed here should already be started.
        """
        logger.info(f"👁️ Monitor active. Watching: {SOURCE_CHANNEL}")
        await client.run()
