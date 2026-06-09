"""Configuration management for introspection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from openharness.config.paths import get_data_dir


@dataclass
class IntrospectionConfig:
    """Configuration for the introspection system."""

    enabled: bool = False
    auto_reflect: bool = False
    reflection_model: str = ""  # empty = use default model
    min_confidence: float = 0.7
    max_experience_top_k: int = 5
    reflection_timeout_seconds: float = 60.0
    events_log_path: Path | None = None
    reflections_dir: Path | None = None
    # Learning sources to enable
    learn_from_interactive: bool = True
    learn_from_bot_chat: bool = True
    learn_from_cron: bool = True
    learn_from_remote_trigger: bool = True
    learn_from_subtask: bool = False
    # Skip reflection for short sessions (fewer than N tool calls)
    min_tool_calls_for_reflection: int = 2
    # Experience injection mode: "off", "reference", "auto"
    injection_mode: Literal["off", "reference", "auto"] = "reference"

    @classmethod
    def from_settings(cls, settings: Any | None = None) -> "IntrospectionConfig":
        """Create config from OpenHarness settings or defaults."""
        config = cls()
        if settings is None:
            return config

        # Try to read from settings if introspection section exists
        introspection = getattr(settings, "introspection", None)
        if introspection is not None:
            config.enabled = bool(getattr(introspection, "enabled", False))
            config.auto_reflect = bool(getattr(introspection, "auto_reflect", False))
            config.reflection_model = str(getattr(introspection, "reflection_model", ""))
            config.min_confidence = float(
                getattr(
                    introspection,
                    "min_confidence",
                    getattr(introspection, "min_confidence_threshold", 0.7),
                )
            )
            config.max_experience_top_k = int(
                getattr(
                    introspection,
                    "max_experience_top_k",
                    getattr(introspection, "top_k_experiences", 5),
                )
            )
            config.reflection_timeout_seconds = float(getattr(introspection, "reflection_timeout_seconds", 60.0))
            config.injection_mode = str(getattr(introspection, "injection_mode", "reference"))
            config.min_tool_calls_for_reflection = int(getattr(introspection, "min_tool_calls_for_reflection", 2))
            sources = getattr(introspection, "sources", None)
            if sources is not None:
                config.learn_from_interactive = bool(getattr(sources, "interactive", True))
                config.learn_from_bot_chat = bool(getattr(sources, "bot_chat", True))
                config.learn_from_cron = bool(getattr(sources, "cron", True))
                config.learn_from_remote_trigger = bool(getattr(sources, "remote_trigger", True))
                config.learn_from_subtask = bool(getattr(sources, "subtask", False))

        return config

    def get_events_path(self, _cwd: str | Path) -> Path:
        """Get the path to the events JSONL file."""
        if self.events_log_path is not None:
            return self.events_log_path
        data_dir = get_data_dir()
        return data_dir / "introspection" / "events.jsonl"

    def get_reflections_dir(self, _cwd: str | Path) -> Path:
        """Get the directory for reflection JSON files."""
        if self.reflections_dir is not None:
            return self.reflections_dir
        data_dir = get_data_dir()
        return data_dir / "introspection" / "reflections"

    def is_source_enabled(self, source_kind: str) -> bool:
        """Check if a learning source kind is enabled."""
        mapping = {
            "interactive": self.learn_from_interactive,
            "bot_chat": self.learn_from_bot_chat,
            "cron": self.learn_from_cron,
            "remote_trigger": self.learn_from_remote_trigger,
            "subtask": self.learn_from_subtask,
        }
        return mapping.get(source_kind, True)
