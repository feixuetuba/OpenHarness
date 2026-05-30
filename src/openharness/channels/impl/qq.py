"""QQ channel implementation using botpy SDK."""

import asyncio
import logging
from collections import deque
from typing import TYPE_CHECKING


from openharness.channels.bus.events import OutboundMessage
from openharness.channels.bus.queue import MessageBus
from openharness.channels.impl.base import BaseChannel
from openharness.config.schema import QQConfig

logger = logging.getLogger(__name__)

try:
    import botpy
    from botpy.message import C2CMessage

    QQ_AVAILABLE = True
    QQ_IMPORT_ERROR: Exception | None = None
except ImportError as exc:
    QQ_AVAILABLE = False
    QQ_IMPORT_ERROR = exc
    botpy = None
    C2CMessage = None

if TYPE_CHECKING:
    from botpy.message import C2CMessage


def _make_bot_class(channel: "QQChannel") -> "type[botpy.Client]":
    """Create a botpy Client subclass bound to the given channel."""
    intents = botpy.Intents(public_messages=True, direct_message=True)

    class _Bot(botpy.Client):
        def __init__(self):
            # Disable botpy's file log — not using loguru; default "botpy.log" fails on read-only fs
            super().__init__(
                intents=intents,
                ext_handlers=False,
                is_sandbox=bool(getattr(channel.config, "sandbox", False)),
            )

        async def on_ready(self):
            channel.online = True
            channel.last_error = None
            logger.info("QQ bot ready: %s", self.robot.name)

        async def on_c2c_message_create(self, message: "C2CMessage"):
            logger.info("QQ c2c message event received: id=%s", getattr(message, "id", None))
            await channel._on_message(message)

        async def on_direct_message_create(self, message):
            logger.info("QQ direct message event received: id=%s", getattr(message, "id", None))
            await channel._on_message(message)

    return _Bot


class QQChannel(BaseChannel):
    """QQ channel using botpy SDK with WebSocket connection."""

    name = "qq"

    def __init__(self, config: QQConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: QQConfig = config
        self._client: "botpy.Client | None" = None
        self._processed_ids: deque = deque(maxlen=1000)
        self._msg_seq: int = 1  # 消息序列号，避免被 QQ API 去重
        self.online: bool = False
        self.last_error: str | None = None

    async def start(self) -> None:
        """Start the QQ bot."""
        if not QQ_AVAILABLE:
            self.last_error = f"QQ SDK import failed: {QQ_IMPORT_ERROR}"
            logger.error(
                "QQ SDK not installed or failed to import. Run: pip install qq-botpy. error=%s",
                QQ_IMPORT_ERROR,
            )
            return

        if not self.config.app_id or not self.config.app_secret:
            self.last_error = "QQ app_id and secret not configured"
            logger.error("QQ app_id and secret not configured")
            return

        self._running = True
        BotClass = _make_bot_class(self)
        self._client = BotClass()

        logger.info("QQ bot started (C2C private message)")
        await self._run_bot()

    async def _run_bot(self) -> None:
        """Run the bot connection with auto-reconnect."""
        while self._running:
            try:
                self.online = False
                await self._client.start(appid=self.config.app_id, secret=self.config.app_secret)
            except Exception as e:
                self.online = False
                self.last_error = str(e)
                logger.warning("QQ bot error: %s", e, exc_info=True)
            if self._running:
                logger.info("Reconnecting QQ bot in 5 seconds...")
                await asyncio.sleep(5)

    async def stop(self) -> None:
        """Stop the QQ bot."""
        self._running = False
        self.online = False
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass
        logger.info("QQ bot stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through QQ."""
        if not self._client:
            logger.warning("QQ client not initialized")
            return
        try:
            msg_id = msg.metadata.get("message_id")
            self._msg_seq += 1  # 递增序列号
            await self._client.api.post_c2c_message(
                openid=msg.chat_id,
                msg_type=0,
                content=msg.content,
                msg_id=msg_id,
                msg_seq=self._msg_seq,  # 添加序列号避免去重
            )
        except Exception as e:
            logger.error("Error sending QQ message: %s", e)

    async def _on_message(self, data: "C2CMessage") -> None:
        """Handle incoming message from QQ."""
        try:
            logger.info("QQChannel._on_message called: id=%s", getattr(data, "id", None))
            # Dedup by message ID
            if data.id in self._processed_ids:
                logger.info("QQChannel ignored duplicate message: id=%s", data.id)
                return
            self._processed_ids.append(data.id)

            author = data.author
            user_id = str(getattr(author, "id", None) or getattr(author, "user_openid", "unknown"))
            user_name = (
                getattr(author, "username", None)
                or getattr(author, "nick", None)
                or f"QQ用户 {user_id[:8]}"
            )
            content = (data.content or "").strip()
            if not content:
                logger.info("QQChannel ignored empty message: id=%s sender=%s", data.id, user_id)
                return

            logger.info(
                "QQChannel forwarding message: id=%s sender=%s content=%s",
                data.id,
                user_id,
                content[:100],
            )

            await self._handle_message(
                sender_id=user_id,
                chat_id=user_id,
                content=content,
                metadata={"message_id": data.id, "sender_name": user_name},
            )
        except Exception:
            logger.exception("Error handling QQ message")
