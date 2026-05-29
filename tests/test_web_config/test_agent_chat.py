from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from openharness.engine.messages import ConversationMessage, TextBlock
from openharness.engine.stream_events import AssistantTextDelta, AssistantTurnComplete
from openharness.api.usage import UsageSnapshot


class _FakeEngine:
    model = "fake-model"
    system_prompt = "fake system"
    total_usage = UsageSnapshot()

    def __init__(self) -> None:
        self.tool_metadata = {}
        self.messages = [
            ConversationMessage.from_user_text("hello"),
            ConversationMessage(role="assistant", content=[TextBlock(text="world")]),
        ]

    async def submit_message(self, message: str):
        assert message == "hello"
        yield AssistantTextDelta(text="world")
        yield AssistantTurnComplete(message=self.messages[-1], usage=UsageSnapshot())


class _FakeSessionBackend:
    def __init__(self) -> None:
        self.saved = None

    def save_snapshot(self, **kwargs):
        self.saved = kwargs


async def test_chat_agent_streams_sse_and_saves_session(monkeypatch):
    from openharness.ui import runtime as runtime_module
    from openharness.services import session_storage
    from web_config import app as web_app

    backend = _FakeSessionBackend()
    bundle = SimpleNamespace(
        cwd="/tmp/project",
        engine=_FakeEngine(),
        session_backend=backend,
        session_id="",
        current_settings=lambda: SimpleNamespace(model="fake-model"),
    )

    async def fake_build_runtime(**kwargs):
        assert kwargs["restore_messages"] is None
        assert kwargs["restore_tool_metadata"] is None
        return bundle

    async def fake_close_runtime(_bundle):
        return None

    monkeypatch.setattr(runtime_module, "build_runtime", fake_build_runtime)
    monkeypatch.setattr(runtime_module, "close_runtime", fake_close_runtime)
    monkeypatch.setattr(session_storage, "load_session_by_id", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(web_app, "_load_agents_payload", lambda: {"agents": [], "active_agent_id": None})

    client = TestClient(web_app.app)
    response = client.post(
        "/api/chat/agent",
        json={"message": "hello", "session_id": "web-session"},
    )

    assert response.status_code == 200
    assert "event: text" in response.text
    assert 'data: {"text": "world"}' in response.text
    assert "event: done" in response.text
    assert backend.saved["session_id"] == "web-session"
    assert bundle.engine.tool_metadata["session_id"] == "web-session"
