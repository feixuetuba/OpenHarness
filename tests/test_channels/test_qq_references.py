"""QQ quoted-media extraction and persistence tests."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

from openharness.channels.bus.events import InboundMessage
from openharness.channels.bus.queue import MessageBus
from openharness.channels.impl.qq import QQChannel
from web_config.channel_runtime import (
    MESSAGE_REFERENCE_INDEX_FILENAME,
    MESSAGE_REFERENCE_TTL_SECONDS,
    WebConfigSmartChannelBridge,
)


class _Engine:
    pass


def _bridge(tmp_path: Path, monkeypatch) -> WebConfigSmartChannelBridge:
    monkeypatch.setenv("OPENHARNESS_SOCIAL_DIR", str(tmp_path / "social"))
    return WebConfigSmartChannelBridge(
        engine=_Engine(),
        bus=MessageBus(),
        cwd=tmp_path,
        resolve_agent_id=lambda _channel: None,
        create_engine_for_agent=None,
        get_channel_sessions=lambda _channel: None,
        resolve_agent_name=lambda agent_id: agent_id,
    )


def test_qq_extracts_nested_message_reference_id() -> None:
    data = SimpleNamespace(
        message_reference=SimpleNamespace(message_id="quoted-message-id"),
        reply_to=None,
    )

    assert QQChannel._extract_reply_to(data) == "quoted-message-id"


def test_quoted_image_survives_bridge_restart(tmp_path: Path, monkeypatch) -> None:
    image = tmp_path / "quoted.png"
    image.write_bytes(b"image")
    original = InboundMessage(
        channel="qq",
        sender_id="user-1",
        chat_id="user-1",
        content=f"[attachment: {image}]",
        media=[str(image)],
        metadata={"message_id": "original-id"},
    )

    first = _bridge(tmp_path, monkeypatch)
    first._remember_message(original, media_paths=[str(image)])

    index_path = tmp_path / "social" / "qq" / MESSAGE_REFERENCE_INDEX_FILENAME
    assert index_path.exists()

    restarted = _bridge(tmp_path, monkeypatch)
    quoted = restarted._resolve_quoted_message(
        InboundMessage(
            channel="qq",
            sender_id="user-1",
            chat_id="user-1",
            content="详细描述这张图",
            metadata={"reply_to": "original-id"},
        )
    )

    assert quoted is not None
    assert quoted["media"] == [str(image.resolve())]
    prompt = restarted._build_prompt("详细描述这张图", quoted=quoted)
    assert "[attachment:" in prompt
    assert "quoted.png" in prompt


def test_missing_reference_forbids_placeholder_paths(tmp_path: Path, monkeypatch) -> None:
    bridge = _bridge(tmp_path, monkeypatch)
    quoted = bridge._resolve_quoted_message(
        InboundMessage(
            channel="qq",
            sender_id="user-1",
            chat_id="user-1",
            content="详细描述这张图",
            metadata={"reply_to": "missing-id"},
        )
    )

    assert quoted is not None
    assert quoted["media"] == []
    assert quoted["metadata"]["reference_unavailable"] is True
    assert "不要为附件编造路径" in quoted["content"]
    prompt = bridge._build_prompt("详细描述这张图", quoted=quoted)
    assert "[attachment:" not in prompt


def test_reference_cannot_cross_chat_boundaries(tmp_path: Path, monkeypatch) -> None:
    image = tmp_path / "private.png"
    image.write_bytes(b"image")
    bridge = _bridge(tmp_path, monkeypatch)
    bridge._remember_message(
        InboundMessage(
            channel="qq",
            sender_id="user-1",
            chat_id="user-1",
            content="private image",
            media=[str(image)],
            metadata={"message_id": "private-id"},
        ),
        media_paths=[str(image)],
    )

    quoted = bridge._resolve_quoted_message(
        InboundMessage(
            channel="qq",
            sender_id="user-2",
            chat_id="user-2",
            content="describe",
            metadata={"reply_to": "private-id"},
        )
    )

    assert quoted is not None
    assert quoted["media"] == []
    assert quoted["metadata"]["reference_unavailable"] is True


def test_expired_reference_is_not_restored(tmp_path: Path, monkeypatch) -> None:
    bridge = _bridge(tmp_path, monkeypatch)
    index_path = tmp_path / "social" / "qq" / MESSAGE_REFERENCE_INDEX_FILENAME
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {
                "version": 1,
                "messages": {
                    "old-id": {
                        "content": "old",
                        "media": [],
                        "metadata": {},
                        "sender_id": "user-1",
                        "timestamp": time.time() - MESSAGE_REFERENCE_TTL_SECONDS - 1,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    quoted = bridge._resolve_quoted_message(
        InboundMessage(
            channel="qq",
            sender_id="user-1",
            chat_id="user-1",
            content="quote old",
            metadata={"reply_to": "old-id"},
        )
    )

    assert quoted is not None
    assert quoted["metadata"]["reference_unavailable"] is True


def test_deleted_referenced_attachment_is_reported(tmp_path: Path, monkeypatch) -> None:
    image = tmp_path / "deleted.png"
    image.write_bytes(b"image")
    bridge = _bridge(tmp_path, monkeypatch)
    bridge._remember_message(
        InboundMessage(
            channel="qq",
            sender_id="user-1",
            chat_id="user-1",
            content="image",
            media=[str(image)],
            metadata={"message_id": "deleted-id"},
        ),
        media_paths=[str(image)],
    )
    image.unlink()

    quoted = bridge._resolve_quoted_message(
        InboundMessage(
            channel="qq",
            sender_id="user-1",
            chat_id="user-1",
            content="describe",
            metadata={"reply_to": "deleted-id"},
        )
    )

    assert quoted is not None
    assert quoted["media"] == []
    assert quoted["metadata"]["reference_attachment_missing"] is True
    assert "本地附件文件已不存在" in quoted["content"]
