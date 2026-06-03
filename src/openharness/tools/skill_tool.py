"""Tool for reading skill contents."""

from __future__ import annotations

import logging
import shlex
from pathlib import Path
from pydantic import BaseModel, Field

from openharness.skills import load_skill_registry
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult
from openharness.tools.path_aliases import compress_path_alias

logger = logging.getLogger(__name__)


class SkillToolInput(BaseModel):
    """Arguments for skill lookup."""

    name: str = Field(description="Skill name")


class SkillTool(BaseTool):
    """Return the content of a loaded skill."""

    name = "skill"
    description = "Read a bundled, user, project, or plugin skill by name."
    input_model = SkillToolInput

    def is_read_only(self, arguments: SkillToolInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: SkillToolInput, context: ToolExecutionContext) -> ToolResult:
        logger.info("[SkillTool] Looking up skill: name=%s", arguments.name)
        registry = load_skill_registry(
            context.cwd,
            extra_skill_dirs=context.metadata.get("extra_skill_dirs"),
            extra_plugin_roots=context.metadata.get("extra_plugin_roots"),
        )
        skill = registry.get(arguments.name) or registry.get(arguments.name.lower()) or registry.get(arguments.name.title())
        if skill is None:
            logger.warning("[SkillTool] Skill not found: %s", arguments.name)
            available = ", ".join(
                sorted({skill.command_name or skill.name for skill in registry.list_skills()})[:30]
            )
            hint = f" Available skills: {available}" if available else ""
            return ToolResult(
                output=(
                    f"Skill not found: {arguments.name}. Choose one of the available skills and call "
                    f"the skill tool again with its exact name.{hint}"
                ),
                is_error=True,
            )
        if skill.disable_model_invocation:
            command_name = skill.command_name or skill.name
            logger.warning("[SkillTool] Skill %s has disable_model_invocation", command_name)
            return ToolResult(
                output=f"Skill {command_name} can only be invoked by the user as /{command_name}.",
                is_error=True,
            )
        logger.info("[SkillTool] Found skill: name=%s base_dir=%s path=%s", skill.name, skill.base_dir, skill.path)
        content = skill.content
        if skill.base_dir:
            compact_dir = compress_path_alias(skill.base_dir, context.cwd)
            content = (
                f"Skill directory: {compact_dir}\n"
                f"Run scripts from this directory, for example: cd {shlex.quote(compact_dir)} && <command>\n"
                "Path aliases such as $USKILL are available to shell tools as environment variables.\n\n"
                f"{content}"
            )
        logger.info("[SkillTool] Returning skill content (first 500 chars): %s", content[:500])
        return ToolResult(output=content)

