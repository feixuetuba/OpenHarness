"""Tests for Agent-configured image/audio attachment analysis."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from openharness.api.client import ApiMessageCompleteEvent
from openharness.api.usage import UsageSnapshot
from openharness.config.settings import PermissionSettings
from openharness.engine.messages import ConversationMessage, ImageBlock, TextBlock
from openharness.engine.query import QueryContext, _execute_tool_call, _tool_schemas_for_model
from openharness.permissions import PermissionChecker
from openharness.tools import create_default_tool_registry
from openharness.tools.read_attachment_tool import (
    ReadAttachmentTool,
    attachment_model_configs_from_agent,
)


class _NoopClient:
    async def stream_message(self, request):
        del request
        if False:
            yield


def _context(
    tmp_path: Path,
    configs: dict[str, dict[str, str]] | None = None,
) -> QueryContext:
    return QueryContext(
        api_client=_NoopClient(),
        tool_registry=create_default_tool_registry(),
        permission_checker=PermissionChecker(PermissionSettings()),
        cwd=tmp_path,
        model="text-only-main-model",
        system_prompt="system",
        max_tokens=16,
        tool_metadata={"attachment_model_configs": configs or {}},
    )


def test_attachment_configs_are_extracted_from_agent() -> None:
    assert attachment_model_configs_from_agent(
        {
            "image_profile": "openai",
            "image_model": "gpt-image-reader",
            "audio_profile": "dashscope",
            "audio_model": "qwen-omni",
        }
    ) == {
        "image": {"profile": "openai", "model": "gpt-image-reader"},
        "audio": {"profile": "dashscope", "model": "qwen-omni"},
    }


def test_attachment_tool_is_hidden_without_agent_media_config(tmp_path: Path) -> None:
    schemas = _tool_schemas_for_model(_context(tmp_path))
    assert "read_attachment" not in {schema["name"] for schema in schemas}


def test_attachment_tool_lists_only_configured_types(tmp_path: Path) -> None:
    schemas = _tool_schemas_for_model(
        _context(tmp_path, {"image": {"profile": "vision", "model": "model-v"}})
    )
    schema = next(schema for schema in schemas if schema["name"] == "read_attachment")
    assert "image" in schema["description"]
    assert "audio" not in schema["description"].rsplit("types:", 1)[-1]


@pytest.mark.asyncio
async def test_read_attachment_sends_prompt_to_configured_image_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_path = tmp_path / "question.png"
    image_path.write_bytes(b"image")
    captured: dict[str, object] = {}

    async def fake_analyze(**kwargs):
        captured.update(kwargs)
        return "There are three objects.", "vision-model"

    monkeypatch.setattr(ReadAttachmentTool, "_analyze", staticmethod(fake_analyze))
    context = _context(
        tmp_path,
        {"image": {"profile": "vision-profile", "model": "vision-model"}},
    )

    result = await _execute_tool_call(
        context,
        "read_attachment",
        "toolu_attachment",
        {"path": str(image_path), "prompt": "Count the objects."},
    )

    assert result.is_error is False
    assert "There are three objects" in result.content
    assert captured["prompt"] == "Count the objects."
    assert captured["profile"] == "vision-profile"
    assert captured["model_override"] == "vision-model"


@pytest.mark.asyncio
async def test_read_attachment_rejects_unconfigured_audio(tmp_path: Path) -> None:
    audio_path = tmp_path / "voice.wav"
    audio_path.write_bytes(b"RIFFfake")

    result = await _execute_tool_call(
        _context(tmp_path, {"image": {"profile": "vision", "model": "v"}}),
        "read_attachment",
        "toolu_attachment",
        {"path": str(audio_path), "prompt": "Transcribe it."},
    )

    assert result.is_error is True
    assert "no audio processing provider configured" in result.content


@pytest.mark.asyncio
async def test_analyze_delivers_media_and_prompt_to_selected_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from openharness import config as config_module
    from openharness.ui import runtime as runtime_module

    image_path = tmp_path / "input.png"
    image_path.write_bytes(b"image")
    profile_settings = SimpleNamespace(
        provider="openai",
        api_format="openai",
        model="profile-default-model",
        resolve_auth=lambda: SimpleNamespace(value="test-key"),
    )

    class FakeSettings:
        def merged_profiles(self):
            return {"vision-profile": object()}

        def model_copy(self, *, update):
            assert update == {"active_profile": "vision-profile"}
            return self

        def materialize_active_profile(self):
            return profile_settings

    class FakeMediaClient:
        def __init__(self):
            self.request = None
            self.closed = False

        async def stream_message(self, request):
            self.request = request
            yield ApiMessageCompleteEvent(
                message=ConversationMessage.from_user_text("analysis result"),
                usage=UsageSnapshot(),
            )

        async def close(self):
            self.closed = True

    media_client = FakeMediaClient()
    monkeypatch.setattr(config_module, "load_settings", lambda: FakeSettings())
    monkeypatch.setattr(
        runtime_module,
        "_resolve_api_client_from_settings",
        lambda settings: media_client,
    )

    output, model = await ReadAttachmentTool._analyze(
        path=image_path,
        kind="image",
        media_type="image/png",
        prompt="Read the serial number.",
        profile="vision-profile",
        model_override="chosen-model",
        max_tokens=512,
    )

    assert output == "analysis result"
    assert model == "chosen-model"
    assert media_client.closed is True
    request = media_client.request
    assert request.model == "chosen-model"
    assert request.messages[0].content[0] == TextBlock(text="Read the serial number.")
    assert isinstance(request.messages[0].content[1], ImageBlock)
