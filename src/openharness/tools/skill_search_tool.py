"""Tool for searching available skills when current candidates are insufficient."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from openharness.skills import load_skill_registry
from openharness.skills.index import SkillIndex
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult
from openharness.utils.conversation_log import get_or_init_conversation_logger

logger = logging.getLogger(__name__)


class SkillSearchToolInput(BaseModel):
    """Arguments for skill search."""

    query: str = Field(
        description="Keywords or short natural-language description of the needed skill."
    )
    limit: int = Field(
        default=10,
        description="Maximum number of additional skills to return.",
    )
    exclude_names: list[str] = Field(
        default_factory=list,
        description="Skill names already shown to the model.",
    )


class SkillSearchTool(BaseTool):
    """Search available skills when the current candidate list is insufficient.

    This tool is used when the LLM determines that the current skill candidates
    are not sufficient to fulfill the user's request. It performs a secondary
    search with the provided query to find additional relevant skills.
    """

    name = "skill_search"
    description = "Search available skills when the current candidate list is insufficient."
    input_model = SkillSearchToolInput

    def is_read_only(self, arguments: SkillSearchToolInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: SkillSearchToolInput, context: ToolExecutionContext) -> ToolResult:
        logger.info("[SkillSearchTool] Searching skills with query=%r limit=%d", arguments.query, arguments.limit)

        registry = load_skill_registry(
            context.cwd,
            extra_skill_dirs=context.metadata.get("extra_skill_dirs"),
            extra_plugin_roots=context.metadata.get("extra_plugin_roots"),
        )

        # Build skill index
        index = SkillIndex()
        index.build(registry.list_skills())

        # Search with exclusions
        exclude_set = set(arguments.exclude_names) if arguments.exclude_names else set()
        candidates = index.search(
            arguments.query,
            limit=arguments.limit,
            exclude_names=exclude_set,
        )

        conv_logger = get_or_init_conversation_logger()
        if conv_logger:
            conv_logger.log_skill_recall(
                arguments.query,
                [
                    {
                        "skill_name": candidate.skill_name,
                        "description": candidate.description,
                        "trigger": candidate.trigger,
                        "negative_trigger": candidate.negative_trigger,
                        "source": candidate.source,
                        "trust_level": candidate.trust_level,
                        "score": candidate.score,
                        "match_type": candidate.match_type,
                    }
                    for candidate in candidates
                ],
                source="skill_search",
                exclude_names=arguments.exclude_names,
                limit=arguments.limit,
            )

        if not candidates:
            return ToolResult(
                output="No matching skills found for the given query.",
            )

        # Format results
        lines = []
        for candidate in candidates:
            desc = candidate.trigger or candidate.description
            lines.append(f"- {candidate.skill_name}: {desc[:100]}")

        result = "\n".join(lines)
        logger.info("[SkillSearchTool] Found %d candidates", len(candidates))
        return ToolResult(output=result)
