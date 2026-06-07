"""Skill registry."""

from __future__ import annotations

import logging

from openharness.skills.types import SkillDefinition

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Store loaded skills by name."""

    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition] = {}
        logger.debug("[skills] SkillRegistry initialized")

    def register(self, skill: SkillDefinition) -> None:
        """Register one skill."""
        keys = [
            key
            for key in (skill.name, skill.command_name, skill.display_name, *skill.aliases)
            if key
        ]

        # Check for overrides
        overridden = {self._skills[key] for key in keys if key in self._skills}
        if overridden:
            for existing in overridden:
                logger.info(
                    "[skills] Overriding skill '%s' (source=%s) with '%s' (source=%s)",
                    existing.name,
                    existing.source,
                    skill.name,
                    skill.source,
                )
            self._skills = {
                key: existing
                for key, existing in self._skills.items()
                if existing not in overridden
            }

        for key in keys:
            self._skills[key] = skill

        logger.debug("[skills] Registered skill '%s' with keys: %s", skill.name, keys)

    def get(self, name: str) -> SkillDefinition | None:
        """Return a skill by name."""
        result = self._skills.get(name)
        if result:
            logger.debug("[skills] Retrieved skill '%s'", name)
        else:
            logger.debug("[skills] Skill '%s' not found", name)
        return result

    def list_skills(self) -> list[SkillDefinition]:
        """Return all skills sorted by name."""
        unique: dict[tuple[str, str | None], SkillDefinition] = {}
        for skill in self._skills.values():
            unique[(skill.source, skill.path or skill.name)] = skill
        result = sorted(unique.values(), key=lambda skill: skill.command_name or skill.name)
        logger.debug("[skills] Listed %d unique skills", len(result))
        return result
