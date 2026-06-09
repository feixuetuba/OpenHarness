"""Learning source normalization for introspection."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from openharness.introspection.types import IntrospectionSource

log = logging.getLogger("openharness.introspection.sources")

_SENSITIVE_METADATA_KEYS = {
    "sender_id",
    "sender_name",
    "user_id",
    "group_id",
    "chat_id",
    "email",
    "phone",
}


def hash_actor(raw: str | None) -> str | None:
    """Hash a sender/actor identifier for privacy."""
    if not raw:
        return None
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def sanitize_message(msg: dict) -> dict:
    """Remove potentially sensitive fields from a message dict."""
    sanitized = {}
    for key, value in msg.items():
        if key in _SENSITIVE_METADATA_KEYS:
            continue
        sanitized[key] = value
    return sanitized


def sanitize_metadata(metadata: dict | None) -> dict:
    """Remove raw actor/channel identifiers from source metadata."""
    sanitized = {}
    for key, value in (metadata or {}).items():
        if key in _SENSITIVE_METADATA_KEYS:
            sanitized[f"{key}_hash"] = hash_actor(str(value))
            continue
        sanitized[key] = value
    return sanitized


def source_from_interactive_session(
    session_id: str,
    cwd: str,
    messages: list[dict] | None = None,
    tool_events: list[dict] | None = None,
    usage: dict | None = None,
    timestamp: str | None = None,
    metadata: dict | None = None,
) -> IntrospectionSource:
    """Create an IntrospectionSource from an interactive CLI/UI session."""
    from openharness.introspection.logging import utc_now_iso

    return IntrospectionSource(
        id=f"sess_{session_id}",
        kind="interactive",
        timestamp=timestamp or utc_now_iso(),
        cwd=cwd,
        session_id=session_id,
        channel="cli",
        messages=[sanitize_message(m) for m in (messages or [])],
        tool_events=tool_events or [],
        usage=usage or {},
        metadata=sanitize_metadata(metadata),
    )


def source_from_bot_chat(
    chat_id: str,
    channel: str,
    cwd: str,
    messages: list[dict] | None = None,
    tool_events: list[dict] | None = None,
    usage: dict | None = None,
    sender_raw: str | None = None,
    timestamp: str | None = None,
    metadata: dict | None = None,
) -> IntrospectionSource:
    """Create an IntrospectionSource from a bot chat channel."""
    from openharness.introspection.logging import utc_now_iso

    chat_hash = hash_actor(chat_id) or "unknown"
    meta: dict[str, Any] = sanitize_metadata(metadata)
    meta.setdefault("chat_hash", chat_hash)

    return IntrospectionSource(
        id=f"bot_{channel}_{chat_hash}",
        kind="bot_chat",
        timestamp=timestamp or utc_now_iso(),
        cwd=cwd,
        channel=channel,
        actor_hash=hash_actor(sender_raw),
        messages=[sanitize_message(m) for m in (messages or [])],
        tool_events=tool_events or [],
        usage=usage or {},
        metadata=meta,
    )


def source_from_cron(
    job_id: str,
    cwd: str,
    schedule: str | None = None,
    exit_code: int | None = None,
    output_summary: str | None = None,
    tool_events: list[dict] | None = None,
    usage: dict | None = None,
    timestamp: str | None = None,
    metadata: dict | None = None,
) -> IntrospectionSource:
    """Create an IntrospectionSource from a cron job execution."""
    from openharness.introspection.logging import utc_now_iso

    meta: dict[str, Any] = sanitize_metadata(metadata)
    if schedule:
        meta["schedule"] = schedule
    if exit_code is not None:
        meta["exit_code"] = exit_code
    if output_summary:
        # Truncate output summary to avoid large payloads
        meta["output_summary"] = output_summary[:500]

    return IntrospectionSource(
        id=f"cron_{job_id}",
        kind="cron",
        timestamp=timestamp or utc_now_iso(),
        cwd=cwd,
        task_id=job_id,
        tool_events=tool_events or [],
        usage=usage or {},
        metadata=meta,
    )


def source_from_remote_trigger(
    trigger_id: str,
    cwd: str,
    result: dict | None = None,
    tool_events: list[dict] | None = None,
    usage: dict | None = None,
    timestamp: str | None = None,
    metadata: dict | None = None,
) -> IntrospectionSource:
    """Create an IntrospectionSource from a remote trigger execution."""
    from openharness.introspection.logging import utc_now_iso

    meta: dict[str, Any] = sanitize_metadata(metadata)
    if result:
        meta["result_summary"] = str(result)[:500]

    return IntrospectionSource(
        id=f"remote_{trigger_id}",
        kind="remote_trigger",
        timestamp=timestamp or utc_now_iso(),
        cwd=cwd,
        task_id=trigger_id,
        tool_events=tool_events or [],
        usage=usage or {},
        metadata=meta,
    )


def source_from_subtask(
    task_id: str,
    cwd: str,
    session_id: str | None = None,
    outcome: str | None = None,
    tool_events: list[dict] | None = None,
    usage: dict | None = None,
    timestamp: str | None = None,
    metadata: dict | None = None,
) -> IntrospectionSource:
    """Create an IntrospectionSource from a subtask execution."""
    from openharness.introspection.logging import utc_now_iso

    meta: dict[str, Any] = sanitize_metadata(metadata)
    if outcome:
        meta["outcome"] = outcome

    return IntrospectionSource(
        id=f"subtask_{task_id}",
        kind="subtask",
        timestamp=timestamp or utc_now_iso(),
        cwd=cwd,
        session_id=session_id,
        task_id=task_id,
        tool_events=tool_events or [],
        usage=usage or {},
        metadata=meta,
    )


def build_session_summary(source: IntrospectionSource) -> str:
    """Build a text summary of a source for LLM analysis."""
    parts: list[str] = []
    parts.append(f"Source: {source.kind} (id={source.id})")
    parts.append(f"Timestamp: {source.timestamp}")
    parts.append(f"CWD: {source.cwd}")

    if source.session_id:
        parts.append(f"Session: {source.session_id}")
    if source.channel:
        parts.append(f"Channel: {source.channel}")

    msg_count = len(source.messages)
    tool_count = len(source.tool_events)
    parts.append(f"Messages: {msg_count}, Tool events: {tool_count}")

    if source.usage:
        total_tokens = source.usage.get("total_tokens", 0)
        parts.append(f"Total tokens: {total_tokens}")

    if source.metadata:
        for key, value in source.metadata.items():
            if key not in ("output_summary", "result_summary"):
                parts.append(f"{key}: {value}")

    # Add last few messages for context
    if source.messages:
        parts.append("\n--- Recent Messages ---")
        for msg in source.messages[-5:]:
            role = msg.get("role", "unknown")
            text = str(msg.get("content", ""))[:200]
            parts.append(f"[{role}] {text}")

    # Add tool events summary
    if source.tool_events:
        parts.append("\n--- Tool Events ---")
        for evt in source.tool_events[-10:]:
            tool_name = evt.get("tool_name", "unknown")
            success = evt.get("success", "unknown")
            parts.append(f"  {tool_name}: {success}")

    return "\n".join(parts)
