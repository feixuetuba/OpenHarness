"""Base channel interface for chat platforms."""

import os
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from openharness.channels.bus.events import InboundMessage, OutboundMessage
from openharness.channels.bus.queue import MessageBus
logger = logging.getLogger(__name__)


def resolve_social_root() -> Path:
    """Return the root directory for social-channel runtime files."""
    custom_root = os.environ.get("OPENHARNESS_SOCIAL_DIR") or os.environ.get("OPENHARNESS_SOCIAL_ROOT")
    root = Path(custom_root).expanduser().resolve() if custom_root else (Path.home() / ".openharness" / "social").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_social_id(value: str) -> str:
    """Return a compact filesystem-safe social bot/channel identifier."""
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value).strip())
    return (cleaned.strip("._") or "bot")[:64]


def resolve_social_bot_dir(bot_id: str) -> Path:
    """Return the unified directory for one social bot/channel."""
    bot_dir = resolve_social_root() / safe_social_id(bot_id)
    bot_dir.mkdir(parents=True, exist_ok=True)
    return bot_dir


def allocate_social_file(bot_id: str, original_name: str | None = None, *, default_ext: str = ".dat") -> Path:
    """Allocate a short numeric filename under ``$SOCIAL/<bot-id>/``."""
    bot_dir = resolve_social_bot_dir(bot_id)
    suffix = Path(str(original_name or "")).suffix.lower()
    if not suffix:
        suffix = default_ext if default_ext.startswith(".") else f".{default_ext}"
    for index in range(1, 1000):
        candidate = bot_dir / f"{index:03d}{suffix}"
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"No available social filename under {bot_dir}")


def resolve_channel_media_dir(channel_name: str) -> Path:
    """Return the local download directory for inbound channel media."""
    custom_root = os.environ.get("OPENHARNESS_CHANNEL_MEDIA_DIR")
    if not custom_root:
        return resolve_social_bot_dir(channel_name)
    root = Path(custom_root).expanduser().resolve()
    media_dir = root / safe_social_id(channel_name)
    media_dir.mkdir(parents=True, exist_ok=True)
    return media_dir


class BaseChannel(ABC):
    """
    Abstract base class for chat channel implementations.

    Each channel (Telegram, Discord, etc.) should implement this interface
    to integrate with the nanobot message bus.
    """

    name: str = "base"

    def __init__(self, config: Any, bus: MessageBus):
        """
        Initialize the channel.

        Args:
            config: Channel-specific configuration.
            bus: The message bus for communication.
        """
        self.config = config
        self.bus = bus
        self._running = False
        self.sessions: dict[str, dict[str, Any]] = {}

    @abstractmethod
    async def start(self) -> None:
        """
        Start the channel and begin listening for messages.

        This should be a long-running async task that:
        1. Connects to the chat platform
        2. Listens for incoming messages
        3. Forwards messages to the bus via _handle_message()
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel and clean up resources."""
        pass

    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None:
        """
        Send a message through this channel.

        Args:
            msg: The message to send.
        """
        pass

    def is_allowed(self, sender_id: str) -> bool:
        """Check if *sender_id* is permitted.  Empty list → deny all; ``"*"`` → allow all."""
        allow_list = getattr(self.config, "allow_from", [])
        if not allow_list:
            logger.warning("%s: allow_from is empty — all access denied", self.name)
            return False
        if "*" in allow_list:
            return True
        sender_str = str(sender_id)
        return sender_str in allow_list or any(
            p in allow_list for p in sender_str.split("|") if p
        )

    async def _handle_message(
        self,
        sender_id: str,
        chat_id: str,
        content: str,
        media: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        session_key: str | None = None,
    ) -> None:
        """
        Handle an incoming message from the chat platform.

        This method checks permissions and forwards to the bus.

        Args:
            sender_id: The sender's identifier.
            chat_id: The chat/channel identifier.
            content: Message text content.
            media: Optional list of media URLs.
            metadata: Optional channel-specific metadata.
            session_key: Optional session key override (e.g. thread-scoped sessions).
        """
        if not self.is_allowed(sender_id):
            logger.warning(
                "Access denied for sender %s on channel %s. "
                "Add them to allowFrom list in config to grant access.",
                sender_id, self.name,
            )
            return

        logger.info("BaseChannel._handle_message: channel=%s, sender_id=%s, chat_id=%s, content=%s", self.name, sender_id, chat_id, content[:100] if content else "")

        key = session_key or sender_id
        sender_name = str((metadata or {}).get("sender_name") or sender_id)
        if key not in self.sessions:
            self.sessions[key] = {
                "sender_id": sender_id,
                "sender_name": sender_name,
                "last_message": content,
                "message_count": 0,
                "messages": [],
            }
        session = self.sessions[key]
        session["sender_name"] = sender_name
        session["last_message"] = content
        session["message_count"] += 1
        session["messages"].append({
            "role": "user",
            "content": content,
            "timestamp": __import__("time").time(),
        })

        msg = InboundMessage(
            channel=self.name,
            sender_id=str(sender_id),
            chat_id=str(chat_id),
            content=content,
            media=media or [],
            metadata=metadata or {},
            session_key_override=session_key,
        )

        await self.bus.publish_inbound(msg)

    @property
    def is_running(self) -> bool:
        """Check if the channel is running."""
        return self._running
