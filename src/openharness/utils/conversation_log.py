"""Conversation logging for model interactions.

Records model requests, responses, and thinking processes separately from
regular logs, organized by source (cli/web/bot).

Directory structure:
    ~/.openharness/conversations/
    ├── cli/2026-06-05/session_xxx.jsonl
    ├── web/2026-06-05/session_xxx.jsonl
    └── bot/2026-06-05/session_xxx.jsonl

File format: JSONL (one JSON object per line) for easy appending and reading.
"""

from __future__ import annotations

import json
import os
from contextvars import ContextVar, Token
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4


class ConversationSource(str, Enum):
    """Source of the conversation."""

    CLI = "cli"
    WEB = "web"
    BOT = "bot"


def get_conversations_dir() -> Path:
    """Get the base directory for conversation logs."""
    configured = os.environ.get("OPENHARNESS_CONVERSATIONS_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".openharness" / "conversations"


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "..."


def _extract_skill_section(system_prompt: str | None) -> str | None:
    """Extract the lightweight skill candidate section from a system prompt."""
    if not system_prompt:
        return None
    marker = "# Available Skill Candidates"
    start = system_prompt.find(marker)
    if start == -1:
        return None
    next_section = system_prompt.find("\n#", start + len(marker))
    if next_section == -1:
        return system_prompt[start:].strip()
    return system_prompt[start:next_section].strip()


def _summarize_message(message: Any, *, preview_limit: int = 2000) -> dict[str, Any]:
    """Return a JSON-safe conversation message summary."""
    if isinstance(message, dict):
        role = message.get("role", "unknown")
        content = message.get("content", "")
    else:
        role = getattr(message, "role", "unknown")
        content = getattr(message, "content", "")

    tool_calls: list[dict[str, Any]] = []
    if isinstance(content, list):
        text_parts: list[str] = []
        block_types: list[str] = []
        for block in content:
            block_type = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
            block_types.append(str(block_type or type(block).__name__))
            if isinstance(block, dict):
                if block.get("type") in {"text", "input_text", "output_text"}:
                    text_parts.append(str(block.get("text", "")))
                elif block.get("type") in {"tool_use", "function_call"}:
                    tool_calls.append(
                        {
                            "id": block.get("id") or block.get("call_id"),
                            "name": block.get("name"),
                            "input": block.get("input") or block.get("arguments"),
                        }
                    )
                elif block.get("type") == "tool_result":
                    tool_calls.append(
                        {
                            "id": block.get("tool_use_id"),
                            "name": "tool_result",
                            "is_error": block.get("is_error"),
                        }
                    )
            else:
                text = getattr(block, "text", None)
                if isinstance(text, str):
                    text_parts.append(text)
                name = getattr(block, "name", None)
                if name:
                    tool_calls.append(
                        {
                            "id": getattr(block, "id", None),
                            "name": name,
                            "input": getattr(block, "input", None),
                        }
                    )
        content_preview = _truncate("".join(text_parts), preview_limit)
        return {
            "role": role,
            "content_preview": content_preview,
            "block_count": len(content),
            "block_types": block_types,
            "tool_calls": tool_calls or None,
        }
    if isinstance(content, str):
        content_preview = _truncate(content, preview_limit)
    else:
        content_preview = _truncate(str(content), preview_limit)
    return {"role": role, "content_preview": content_preview}


class ConversationLogger:
    """Logger for model conversations, separate from regular logs.

    Each session creates a new file, records are appended as JSONL.
    """

    def __init__(
        self,
        source: ConversationSource | str = ConversationSource.CLI,
        session_id: str | None = None,
        enabled: bool = True,
    ) -> None:
        """Initialize the conversation logger.

        Args:
            source: Where the conversation originates (cli/web/bot).
            session_id: Unique session identifier. If None, generates a new one.
            enabled: Whether logging is enabled.
        """
        self.source = ConversationSource(source) if isinstance(source, str) else source
        self.session_id = session_id or str(uuid4())[:8]
        self.created_at = datetime.now()
        self.enabled = enabled
        self._file_handle: Any = None
        self._current_date: str | None = None

    def _get_log_file_path(self) -> Path:
        """Get the log file path for current date."""
        today = self.created_at.strftime("%Y-%m-%d")
        base_dir = get_conversations_dir() / self.source.value / today
        base_dir.mkdir(parents=True, exist_ok=True)
        created = self.created_at.strftime("%Y%m%d_%H%M%S")
        safe_session_id = "".join(
            ch if ch.isalnum() or ch in {"-", "_"} else "_"
            for ch in str(self.session_id)
        ).strip("_") or "session"
        return base_dir / f"{created}_{safe_session_id}.jsonl"

    def _write_record(self, record: dict[str, Any]) -> None:
        """Write a record to the log file."""
        if not self.enabled:
            return

        try:
            file_path = self._get_log_file_path()
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            # Silently ignore logging errors to not disrupt the main flow
            pass

    def log_request(
        self,
        model: str,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
        tools: list[str] | None = None,
        max_tokens: int | None = None,
        **extra: Any,
    ) -> None:
        """Log a model request.

        Args:
            model: Model name.
            messages: List of messages sent to the model.
            system_prompt: System prompt (truncated if too long).
            tools: List of tool names available.
            max_tokens: Maximum tokens requested.
            **extra: Additional metadata.
        """
        system_prompt_summary = _truncate(system_prompt, 20000) if system_prompt else None
        skill_section = _extract_skill_section(system_prompt)
        message_summary = [_summarize_message(msg) for msg in messages]

        record = {
            "timestamp": datetime.now().isoformat(),
            "event": "request",
            "model": model,
            "message_count": len(messages),
            "messages": message_summary,
            "system_prompt": system_prompt_summary,
            "system_prompt_length": len(system_prompt or ""),
            "skill_section": skill_section,
            "tools": tools,
            "max_tokens": max_tokens,
            **extra,
        }
        self._write_record(record)

    def log_response(
        self,
        model: str,
        content: str | None = None,
        reasoning: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        finish_reason: str | None = None,
        duration_ms: float | None = None,
        **extra: Any,
    ) -> None:
        """Log a model response.

        Args:
            model: Model name.
            content: Response content (truncated if too long).
            reasoning: Thinking/reasoning content from the model.
            tool_calls: List of tool calls made.
            input_tokens: Input token count.
            output_tokens: Output token count.
            finish_reason: Why the response finished.
            duration_ms: Response duration in milliseconds.
            **extra: Additional metadata.
        """
        # Truncate content if too long
        content_summary = None
        if content:
            content_summary = content[:1000] + "..." if len(content) > 1000 else content

        # Truncate reasoning if too long
        reasoning_summary = None
        if reasoning:
            reasoning_summary = reasoning[:2000] + "..." if len(reasoning) > 2000 else reasoning

        record = {
            "timestamp": datetime.now().isoformat(),
            "event": "response",
            "model": model,
            "content": content_summary,
            "reasoning": reasoning_summary,
            "tool_calls": tool_calls,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "finish_reason": finish_reason,
            "duration_ms": duration_ms,
            **extra,
        }
        self._write_record(record)

    def log_skill_recall(
        self,
        query: str | None,
        candidates: list[dict[str, Any]],
        *,
        source: str = "prompt",
        exclude_names: list[str] | None = None,
        **extra: Any,
    ) -> None:
        """Log skill recall candidates shown to, or returned for, the model."""
        record = {
            "timestamp": datetime.now().isoformat(),
            "event": "skill_recall",
            "source": source,
            "query": query,
            "exclude_names": exclude_names or [],
            "candidate_count": len(candidates),
            "candidates": candidates,
            **extra,
        }
        self._write_record(record)

    def log_thinking(
        self,
        thinking: str,
        model: str | None = None,
        **extra: Any,
    ) -> None:
        """Log model thinking/reasoning process.

        Args:
            thinking: The thinking content.
            model: Model name.
            **extra: Additional metadata.
        """
        # Truncate if too long
        thinking_summary = thinking[:5000] + "..." if len(thinking) > 5000 else thinking

        record = {
            "timestamp": datetime.now().isoformat(),
            "event": "thinking",
            "model": model,
            "thinking": thinking_summary,
            "thinking_length": len(thinking),
            **extra,
        }
        self._write_record(record)

    def log_tool_call(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        tool_output: str | None = None,
        is_error: bool = False,
        duration_ms: float | None = None,
        **extra: Any,
    ) -> None:
        """Log a tool call.

        Args:
            tool_name: Name of the tool.
            tool_input: Tool input parameters.
            tool_output: Tool output (truncated if too long).
            is_error: Whether the call resulted in an error.
            duration_ms: Execution duration in milliseconds.
            **extra: Additional metadata.
        """
        # Truncate output if too long
        output_summary = None
        if tool_output:
            output_summary = tool_output[:2000] + "..." if len(tool_output) > 2000 else tool_output

        record = {
            "timestamp": datetime.now().isoformat(),
            "event": "tool_call",
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_output": output_summary,
            "is_error": is_error,
            "duration_ms": duration_ms,
            **extra,
        }
        self._write_record(record)

    def log_error(
        self,
        error: str,
        error_type: str | None = None,
        **extra: Any,
    ) -> None:
        """Log an error during conversation.

        Args:
            error: Error message.
            error_type: Error type/exception name.
            **extra: Additional metadata.
        """
        record = {
            "timestamp": datetime.now().isoformat(),
            "event": "error",
            "error": error,
            "error_type": error_type,
            **extra,
        }
        self._write_record(record)

    def log_metadata(
        self,
        key: str,
        value: Any,
    ) -> None:
        """Log session metadata.

        Args:
            key: Metadata key.
            value: Metadata value.
        """
        record = {
            "timestamp": datetime.now().isoformat(),
            "event": "metadata",
            "key": key,
            "value": value,
        }
        self._write_record(record)


# Global conversation logger (can be set by the application)
_global_logger: ConversationLogger | None = None
_context_logger: ContextVar[ConversationLogger | None] = ContextVar(
    "openharness_conversation_logger",
    default=None,
)


def get_conversation_logger() -> ConversationLogger | None:
    """Get the global conversation logger."""
    return _context_logger.get() or _global_logger


def get_or_init_conversation_logger(
    source: ConversationSource | str | None = None,
    session_id: str | None = None,
) -> ConversationLogger | None:
    """Return the global logger, lazily initializing it when enabled."""
    current = get_conversation_logger()
    if current is not None:
        return current
    enabled = os.environ.get("OPENHARNESS_CONVERSATION_LOG", "true").lower() not in (
        "false",
        "0",
        "no",
    )
    if not enabled:
        return None
    resolved_source = source or os.environ.get("OPENHARNESS_CONVERSATION_SOURCE", ConversationSource.CLI.value)
    return init_conversation_logger(source=resolved_source, session_id=session_id, enabled=True)


def set_conversation_logger(logger: ConversationLogger | None) -> None:
    """Set the global conversation logger."""
    global _global_logger
    _global_logger = logger
    _context_logger.set(logger)


def push_conversation_logger(logger: ConversationLogger | None) -> Token[ConversationLogger | None]:
    """Set a request-local conversation logger and return a reset token."""
    return _context_logger.set(logger)


def reset_conversation_logger(token: Token[ConversationLogger | None]) -> None:
    """Reset the request-local conversation logger."""
    _context_logger.reset(token)


def init_conversation_logger(
    source: ConversationSource | str = ConversationSource.CLI,
    session_id: str | None = None,
    enabled: bool | None = None,
) -> ConversationLogger:
    """Initialize and set the global conversation logger.

    Args:
        source: Where the conversation originates.
        session_id: Session ID (auto-generated if None).
        enabled: Whether logging is enabled. If None, checks env var.

    Returns:
        The initialized logger.
    """
    if enabled is None:
        # Check environment variable
        enabled = os.environ.get("OPENHARNESS_CONVERSATION_LOG", "true").lower() not in ("false", "0", "no")

    logger = ConversationLogger(source=source, session_id=session_id, enabled=enabled)
    set_conversation_logger(logger)
    return logger


def init_context_conversation_logger(
    source: ConversationSource | str = ConversationSource.CLI,
    session_id: str | None = None,
    enabled: bool | None = None,
) -> tuple[ConversationLogger, Token[ConversationLogger | None]]:
    """Initialize a request-local conversation logger."""
    if enabled is None:
        enabled = os.environ.get("OPENHARNESS_CONVERSATION_LOG", "true").lower() not in ("false", "0", "no")
    logger = ConversationLogger(source=source, session_id=session_id, enabled=enabled)
    token = push_conversation_logger(logger)
    return logger, token
