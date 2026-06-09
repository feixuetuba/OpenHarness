"""Data type definitions for the introspection system."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class IntrospectionSource:
    """Normalized introspection input source."""

    id: str
    kind: Literal["interactive", "bot_chat", "cron", "remote_trigger", "subtask"]
    timestamp: str
    cwd: str
    session_id: str | None = None
    channel: str | None = None
    actor_hash: str | None = None
    task_id: str | None = None
    messages: list[dict] = field(default_factory=list)
    tool_events: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


@dataclass
class AnalysisResult:
    """Result of session analysis."""

    completion: float
    tool_efficiency: dict[str, float]
    error_patterns: list[dict]
    patterns_identified: list[str]
    success_patterns: list[str]
    failure_patterns: list[str]
    tool_calls_count: int = 0
    duration_seconds: float = 0.0
    total_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "completion": self.completion,
            "tool_efficiency": self.tool_efficiency,
            "error_patterns": self.error_patterns,
            "patterns_identified": self.patterns_identified,
            "success_patterns": self.success_patterns,
            "failure_patterns": self.failure_patterns,
            "tool_calls_count": self.tool_calls_count,
            "duration_seconds": self.duration_seconds,
            "total_tokens": self.total_tokens,
        }


@dataclass
class ReflectionReport:
    """Session introspection report."""

    session_id: str
    reflection_id: str
    source_id: str
    source_kind: str
    duration_seconds: float
    task_summary: str
    outcome: Literal["success", "partial", "failure", "abandoned", "unknown"]
    tools_efficiency: dict[str, float]
    errors: list[dict]
    patterns_identified: list[str]
    recommendations: list[str]
    thinking_steps: list[dict] = field(default_factory=list)
    experience_candidates: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "reflection_id": self.reflection_id,
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "duration_seconds": self.duration_seconds,
            "task_summary": self.task_summary,
            "outcome": self.outcome,
            "tools_efficiency": self.tools_efficiency,
            "errors": self.errors,
            "patterns_identified": self.patterns_identified,
            "recommendations": self.recommendations,
            "thinking_steps": self.thinking_steps,
            "experience_candidates": self.experience_candidates,
            "metadata": self.metadata,
        }


@dataclass
class ExperienceRecord:
    """Experience record for storage and retrieval."""

    id: str
    task_type: str
    timestamp: str
    context: dict
    source_kind: Literal["interactive", "bot_chat", "cron", "remote_trigger", "subtask"]
    outcome: Literal["success", "partial", "failure", "abandoned", "unknown"]
    metrics: dict
    lessons: list[str]
    tools_used: list[str]
    evidence: list[str]
    confidence: float = 1.0
    use_count: int = 0
    last_used: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_type": self.task_type,
            "timestamp": self.timestamp,
            "context": self.context,
            "source_kind": self.source_kind,
            "outcome": self.outcome,
            "metrics": self.metrics,
            "lessons": self.lessons,
            "tools_used": self.tools_used,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "use_count": self.use_count,
            "last_used": self.last_used,
        }


@dataclass
class ExperienceQuery:
    """Query parameters for experience retrieval."""

    task_type: str | None = None
    tools: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    min_confidence: float = 0.7
    source_kinds: list[str] = field(default_factory=list)
