"""Social conversation context policy and isolation tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from openharness.channels.bus.events import InboundMessage
from openharness.channels.bus.queue import MessageBus
from openharness.config.settings import SocialPlatformConfig
from web_config.channel_runtime import WebConfigSmartChannelBridge


class _Engine:
    def __init__(self) -> None:
        self.tool_metadata: dict[str, object] = {}


def _message(sender_id: str) -> InboundMessage:
    return InboundMessage(
        channel="qq",
        sender_id=sender_id,
        chat_id=sender_id,
        content="hello",
    )


@pytest.mark.asyncio
async def test_context_engines_are_isolated_by_social_session(tmp_path: Path) -> None:
    created: list[_Engine] = []

    async def create_engine(_agent_id: str) -> _Engine:
        engine = _Engine()
        created.append(engine)
        return engine

    bridge = WebConfigSmartChannelBridge(
        engine=_Engine(),
        bus=MessageBus(),
        cwd=tmp_path,
        resolve_agent_id=lambda _channel: "agent-1",
        create_engine_for_agent=create_engine,
        get_channel_sessions=lambda _channel: None,
        resolve_agent_name=lambda agent_id: agent_id,
    )

    first = await bridge._engine_for_message(_message("user-1"), "agent-1")
    same_session = await bridge._engine_for_message(_message("user-1"), "agent-1")
    other_session = await bridge._engine_for_message(_message("user-2"), "agent-1")

    assert first is same_session
    assert other_session is not first
    assert len(created) == 2
    assert first.tool_metadata["session_id"] == "qq_user-1"
    assert other_session.tool_metadata["session_id"] == "qq_user-2"


def test_context_clear_policy() -> None:
    reason = WebConfigSmartChannelBridge._context_clear_reason

    assert reason(retain_context=False, max_messages=0, message_count=0) == "context_retention_disabled"
    assert reason(retain_context=True, max_messages=0, message_count=100) is None
    assert reason(retain_context=True, max_messages=3, message_count=2) is None
    assert reason(retain_context=True, max_messages=3, message_count=3) == "context_message_limit_reached"


def test_social_context_settings_defaults_and_validation() -> None:
    defaults = SocialPlatformConfig()
    assert defaults.social_retain_context is False
    assert defaults.social_context_max_messages == 0

    configured = SocialPlatformConfig(
        social_retain_context=True,
        social_context_max_messages=12,
    )
    assert configured.social_retain_context is True
    assert configured.social_context_max_messages == 12

    with pytest.raises(ValidationError):
        SocialPlatformConfig(social_context_max_messages=-1)
