"""Skill data models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SkillDefinition:
    """A loaded skill."""

    name: str
    description: str
    content: str
    source: str
    path: str | None = None
    base_dir: str | None = None
    command_name: str | None = None
    display_name: str | None = None
    aliases: tuple[str, ...] = ()
    user_invocable: bool = True
    disable_model_invocation: bool = False
    model: str | None = None
    argument_hint: str | None = None
    enabled: bool = True
    # New fields for skill management subsystem
    keywords: tuple[str, ...] = field(default_factory=tuple)
    trigger: str | None = None
    negative_trigger: str | None = None
    requires: tuple[str, ...] = field(default_factory=tuple)
    bm25_search_keywords: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SkillCandidate:
    """A skill candidate returned by the recall stage."""

    skill_name: str
    description: str
    trigger: str | None
    negative_trigger: str | None
    source: str
    trust_level: str | None = None
    score: float = 0.0
    match_type: str = "bm25"  # "exact", "alias", "bm25", "semantic"
