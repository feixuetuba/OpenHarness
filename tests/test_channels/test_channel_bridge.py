import pytest

from openharness.channels.adapter import ChannelBridge
from openharness.channels.bus.events import InboundMessage
from openharness.channels.bus.queue import MessageBus
from openharness.engine.stream_events import AssistantTextDelta


class _Engine:
    def __init__(self, text: str) -> None:
        self.text = text
        self.messages: list[str] = []

    async def submit_message(self, message: str):
        self.messages.append(message)
        yield AssistantTextDelta(text=self.text)


@pytest.mark.asyncio
async def test_bridge_appends_assistant_reply_to_sender_session():
    bus = MessageBus()
    sessions = {"user-1": {"messages": []}}
    bridge = ChannelBridge(
        engine=_Engine("hello"),
        bus=bus,
        get_channel_sessions=lambda _channel: sessions,
        resolve_agent_id=lambda _channel: "piglet",
        resolve_agent_name=lambda _agent_id: "猪小弟",
    )

    await bridge._handle(
        InboundMessage(
            channel="qq",
            sender_id="user-1",
            chat_id="user-1",
            content="hi",
        )
    )

    assert len(sessions["user-1"]["messages"]) == 1
    saved_reply = sessions["user-1"]["messages"][0]
    assert saved_reply["role"] == "assistant"
    assert saved_reply["content"] == "hello"
    assert saved_reply["agent_name"] == "猪小弟"
    assert isinstance(saved_reply["timestamp"], float)
    outbound = await bus.consume_outbound()
    assert outbound.channel == "qq"
    assert outbound.chat_id == "user-1"
    assert outbound.content == "hello"


@pytest.mark.asyncio
async def test_bridge_uses_resolved_agent_engine():
    bus = MessageBus()
    default_engine = _Engine("default")
    agent_engine = _Engine("agent")

    async def create_engine(agent_id: str):
        assert agent_id == "piglet"
        return agent_engine

    bridge = ChannelBridge(
        engine=default_engine,
        bus=bus,
        resolve_agent_id=lambda _channel: "piglet",
        create_engine_for_agent=create_engine,
    )

    await bridge._handle(
        InboundMessage(
            channel="qq",
            sender_id="user-1",
            chat_id="user-1",
            content="hi",
        )
    )

    assert default_engine.messages == []
    assert agent_engine.messages == ["hi"]
    outbound = await bus.consume_outbound()
    assert outbound.content == "agent"
