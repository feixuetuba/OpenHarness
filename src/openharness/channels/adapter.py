"""ChannelBridge: connects the MessageBus to a QueryEngine instance.

Usage::

    bridge = ChannelBridge(engine=query_engine, bus=message_bus)
    asyncio.create_task(bridge.run())

The bridge continuously consumes inbound messages from the bus, feeds them
to QueryEngine.submit_message(), and publishes the assembled reply as an
OutboundMessage back to the bus for delivery by ChannelManager.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Awaitable, Callable

from openharness.channels.bus.events import InboundMessage, OutboundMessage
from openharness.channels.bus.queue import MessageBus
from openharness.engine.stream_events import AssistantTextDelta, AssistantTurnComplete
from openharness.utils.conversation_log import ConversationSource, init_conversation_logger

if TYPE_CHECKING:
    from openharness.engine.query_engine import QueryEngine

logger = logging.getLogger(__name__)


def _conversation_session_id(msg: InboundMessage) -> str:
    raw = f"{msg.channel}_{msg.session_key}"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", raw)[:120] or "bot"


class ChannelBridge:
    """Bridges inbound channel messages to the QueryEngine and routes replies back.

    One bridge instance should be created per QueryEngine.  It owns the asyncio
    loop integration and handles back-pressure through the MessageBus queues.
    """

    def __init__(
        self,
        *,
        engine: "QueryEngine",
        bus: MessageBus,
        resolve_agent_id: Callable[[str], str | None] | None = None,
        create_engine_for_agent: Callable[[str], Awaitable["QueryEngine"]] | None = None,
        get_channel_sessions: Callable[[str], dict | None] | None = None,
        resolve_agent_name: Callable[[str], str] | None = None,
    ) -> None:
        self._engine = engine
        self._bus = bus
        self._running = False
        self._task: asyncio.Task | None = None
        self._resolve_agent_id = resolve_agent_id
        self._create_engine_for_agent = create_engine_for_agent
        self._get_channel_sessions = get_channel_sessions
        self._resolve_agent_name = resolve_agent_name
        self._agent_engines: dict[str, "QueryEngine"] = {}

    # ------------------------------------------------------------------
    # Public control API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the bridge loop as a background task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="channel-bridge")
        logger.info("ChannelBridge started")

    async def stop(self) -> None:
        """Stop the bridge loop gracefully."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("ChannelBridge stopped")

    async def run(self) -> None:
        """Run the bridge inline (blocks until stopped or cancelled)."""
        self._running = True
        try:
            await self._loop()
        finally:
            self._running = False

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        """Main processing loop: consume → process → publish."""
        while self._running:
            try:
                msg = await asyncio.wait_for(
                    self._bus.consume_inbound(),
                    timeout=1.0,
                )
                await self._handle(msg)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("ChannelBridge: unhandled error processing message")

    async def _handle(self, msg: InboundMessage) -> None:
        """Process one inbound message and publish the reply."""
        conv_logger = init_conversation_logger(
            source=ConversationSource.BOT,
            session_id=_conversation_session_id(msg),
        )
        conv_logger.log_metadata(
            "inbound_message",
            {
                "channel": msg.channel,
                "chat_id": msg.chat_id,
                "sender_id": msg.sender_id,
                "session_key": msg.session_key,
                "content": msg.content,
            },
        )
        logger.info(
            "ChannelBridge received from %s/%s, content=%s",
            msg.channel,
            msg.chat_id,
            msg.content[:100] if msg.content else "",
        )

        engine = self._engine
        agent_id = None
        if self._resolve_agent_id is not None:
            agent_id = self._resolve_agent_id(msg.channel)
            logger.info("ChannelBridge: resolve_agent_id(%s) = %s", msg.channel, agent_id)

        if agent_id and self._create_engine_for_agent is not None:
            if agent_id not in self._agent_engines:
                logger.info("Creating QueryEngine for agent %s (channel %s)", agent_id, msg.channel)
                try:
                    self._agent_engines[agent_id] = await self._create_engine_for_agent(agent_id)
                except Exception:
                    logger.exception("Failed to create engine for agent %s, falling back to default", agent_id)
                    agent_id = None
            if agent_id in self._agent_engines:
                engine = self._agent_engines[agent_id]

        reply_parts: list[str] = []
        try:
            async for event in engine.submit_message(msg.content):
                if isinstance(event, AssistantTextDelta):
                    reply_parts.append(event.text)
                elif isinstance(event, AssistantTurnComplete):
                    pass
        except Exception:
            logger.exception(
                "ChannelBridge: engine error for message from %s/%s",
                msg.channel,
                msg.chat_id,
            )
            reply_parts = ["[Error: failed to process your message]"]

        reply_text = "".join(reply_parts).strip()
        if not reply_text:
            logger.debug("ChannelBridge: empty reply, skipping publish")
            return
        conv_logger.log_metadata(
            "outbound_message",
            {
                "channel": msg.channel,
                "chat_id": msg.chat_id,
                "session_key": msg.session_key,
                "content": reply_text,
            },
        )

        sessions = self._get_channel_sessions(msg.channel) if self._get_channel_sessions else None
        if sessions is not None:
            key = msg.session_key_override or msg.sender_id
            if key in sessions:
                agent_name = None
                if agent_id and self._resolve_agent_name:
                    agent_name = self._resolve_agent_name(agent_id)
                sessions[key]["messages"].append(
                    {
                        "role": "assistant",
                        "content": reply_text,
                        "timestamp": __import__("time").time(),
                        "agent_name": agent_name,
                    }
                )

        outbound = OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=reply_text,
            metadata={"_session_key": msg.session_key},
        )
        await self._bus.publish_outbound(outbound)
        logger.debug(
            "ChannelBridge published reply to %s/%s (%d chars)",
            msg.channel,
            msg.chat_id,
            len(reply_text),
        )
