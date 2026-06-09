"""Structured logging and sanitization helpers for introspection."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("openharness.introspection.logging")

# Patterns that may contain secrets
_SECRET_PATTERNS = [
    re.compile(r"(?:api[_-]?key|token|secret|password|credential)\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),
]

_MAX_DISPLAY_TEXT_LENGTH = 500


def sanitize_text(text: str, *, max_length: int = 200) -> str:
    """Remove potential secrets and truncate text for safe display."""
    if not text:
        return ""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    if len(text) > max_length:
        return text[:max_length] + "..."
    return text


def make_safe_display_text(text: str) -> str:
    """Create a display-safe string for web_config events."""
    if not text:
        return ""
    cleaned = sanitize_text(text, max_length=_MAX_DISPLAY_TEXT_LENGTH)
    # Remove newlines for single-line display
    return cleaned.replace("\n", " ").replace("\r", "")


def utc_now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_event(
    events_path: Path,
    event: str,
    level: str = "INFO",
    reflection_id: str | None = None,
    source_id: str | None = None,
    source_kind: str | None = None,
    display_text: str | None = None,
    summary: str | None = None,
    memory_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Append a structured event to the introspection events JSONL file."""
    entry: dict[str, Any] = {
        "timestamp": utc_now_iso(),
        "level": level,
        "event": event,
    }
    if reflection_id is not None:
        entry["reflection_id"] = reflection_id
    if source_id is not None:
        entry["source_id"] = source_id
    if source_kind is not None:
        entry["source_kind"] = source_kind
    if display_text is not None:
        entry["display_text"] = make_safe_display_text(display_text)
    if summary is not None:
        entry["summary"] = summary
    if memory_id is not None:
        entry["memory_id"] = memory_id
    if metadata is not None:
        entry["metadata"] = metadata

    try:
        events_path.parent.mkdir(parents=True, exist_ok=True)
        with open(events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("Failed to write introspection event: %s", exc)


def log_event(
    logger_obj: logging.Logger,
    level: str,
    message: str,
    reflection_id: str | None = None,
    source_id: str | None = None,
    **extra: Any,
) -> None:
    """Log an introspection event with optional context IDs."""
    parts = [message]
    if reflection_id:
        parts.append(f"reflection_id={reflection_id}")
    if source_id:
        parts.append(f"source_id={source_id}")
    for key, value in extra.items():
        parts.append(f"{key}={value}")
    log_line = " ".join(parts)
    if level == "DEBUG":
        logger_obj.debug(log_line)
    elif level == "WARNING":
        logger_obj.warning(log_line)
    elif level == "ERROR":
        logger_obj.error(log_line)
    else:
        logger_obj.info(log_line)
