"""Tool for spawning local agent tasks."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from openharness.coordinator.agent_definitions import get_agent_definition
from openharness.coordinator.coordinator_mode import get_team_registry
from openharness.hooks import HookEvent
from openharness.swarm.registry import get_backend_registry
from openharness.swarm.types import TeammateSpawnConfig
from openharness.tasks import get_task_manager
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult
from openharness.tools.skill_permission import infer_skill_from_text, skill_is_approved

logger = logging.getLogger(__name__)


class AgentToolInput(BaseModel):
    """Arguments for local agent spawning."""

    description: str = Field(description="Short description of the delegated work")
    prompt: str = Field(description="Full prompt for the local agent")
    subagent_type: str | None = Field(
        default=None,
        description="Agent type for definition lookup (e.g. 'general-purpose', 'Explore', 'worker')",
    )
    model: str | None = Field(default=None)
    command: str | None = Field(default=None, description="Override spawn command")
    team: str | None = Field(default=None, description="Optional team to attach the agent to")
    mode: str = Field(
        default="local_agent",
        description="Agent mode: local_agent, remote_agent, or in_process_teammate",
    )


class AgentTool(BaseTool):
    """Spawn a local agent subprocess."""

    name = "agent"
    description = "Spawn a local background agent task."
    input_model = AgentToolInput

    def is_read_only(self, arguments: AgentToolInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: AgentToolInput, context: ToolExecutionContext) -> ToolResult:
        try:
            subagent_depth = int(context.metadata.get("subagent_depth") or 0)
        except (TypeError, ValueError):
            subagent_depth = 0
        if subagent_depth >= 1:
            return ToolResult(
                output="Nested subagents are disabled for this execution context.",
                is_error=True,
                metadata={"nested_subagent_blocked": True},
            )
        if arguments.mode not in {"local_agent", "remote_agent", "in_process_teammate"}:
            return ToolResult(
                output="Invalid mode. Use local_agent, remote_agent, or in_process_teammate.",
                is_error=True,
            )

        # Look up agent definition if subagent_type is specified
        agent_def = None
        if arguments.subagent_type:
            agent_def = get_agent_definition(arguments.subagent_type)

        # Resolve team and agent name for the swarm backend
        team = arguments.team or "default"
        agent_name = arguments.subagent_type or "agent"
        target_skill = infer_skill_from_text(
            f"{arguments.description}\n{arguments.prompt}",
            context.cwd,
            context.metadata,
        )
        permission_mode = "bypassPermissions" if skill_is_approved(target_skill, context.metadata) else None

        # Use subprocess backend so spawned agents are registered in
        # BackgroundTaskManager and are pollable by the task tools.
        # in_process tasks return asyncio-internal IDs that task tools
        # cannot query, and subprocess is always available on all platforms.
        registry = get_backend_registry()
        executor = registry.get_executor("subprocess")

        config = TeammateSpawnConfig(
            name=agent_name,
            team=team,
            prompt=arguments.prompt,
            cwd=str(context.cwd),
            parent_session_id="main",
            model=arguments.model or (agent_def.model if agent_def else None),
            command=arguments.command,
            system_prompt=agent_def.system_prompt if agent_def else None,
            permissions=agent_def.permissions if agent_def else [],
            permission_mode=permission_mode,
            task_type=arguments.mode,
        )

        try:
            result = await executor.spawn(config)
        except Exception as exc:
            logger.error("Failed to spawn agent: %s", exc)
            return ToolResult(output=str(exc), is_error=True)

        if not result.success:
            return ToolResult(output=result.error or "Failed to spawn agent", is_error=True)

        if arguments.team:
            registry = get_team_registry()
            try:
                registry.add_agent(arguments.team, result.task_id)
            except ValueError:
                registry.create_team(arguments.team)
                registry.add_agent(arguments.team, result.task_id)

        if context.hook_executor is not None:
            manager = get_task_manager()
            unregister = None

            async def _emit_subagent_stop(task_record) -> None:
                nonlocal unregister
                if task_record.id != result.task_id:
                    return
                if unregister is not None:
                    unregister()
                    unregister = None
                await context.hook_executor.execute(
                    HookEvent.SUBAGENT_STOP,
                    {
                        "event": HookEvent.SUBAGENT_STOP.value,
                        "agent_id": result.agent_id,
                        "task_id": result.task_id,
                        "backend_type": result.backend_type,
                        "status": task_record.status,
                        "return_code": task_record.return_code,
                        "description": arguments.description,
                        "subagent_type": arguments.subagent_type or "agent",
                        "team": team,
                        "mode": arguments.mode,
                    },
                )

            unregister = manager.register_completion_listener(_emit_subagent_stop)
            task_record = manager.get_task(result.task_id)
            if task_record is not None and task_record.status in {"completed", "failed", "killed"}:
                await _emit_subagent_stop(task_record)

        return ToolResult(
            output=(
                f"Spawned agent {result.agent_id} "
                f"(task_id={result.task_id}, backend={result.backend_type})"
            ),
            metadata={
                "agent_id": result.agent_id,
                "task_id": result.task_id,
                "backend_type": result.backend_type,
                "description": arguments.description,
            },
        )
