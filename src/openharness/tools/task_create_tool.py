"""Tool for creating background tasks."""

from __future__ import annotations

from pydantic import BaseModel, Field

from openharness.swarm.registry import get_backend_registry
from openharness.swarm.types import TeammateSpawnConfig
from openharness.tasks.manager import get_task_manager
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult
from openharness.tools.bash_tool import _path_aliases
from openharness.tools.skill_permission import infer_skill_from_text, skill_is_approved


class TaskCreateToolInput(BaseModel):
    """Arguments for task creation."""

    type: str = Field(default="local_bash", description="Task type: local_bash or local_agent")
    description: str = Field(description="Short task description")
    command: str | None = Field(default=None, description="Shell command for local_bash")
    prompt: str | None = Field(default=None, description="Prompt for local_agent")
    model: str | None = Field(default=None)


class TaskCreateTool(BaseTool):
    """Create a background task."""

    name = "task_create"
    description = "Create a background shell or local-agent task."
    input_model = TaskCreateToolInput

    async def execute(self, arguments: TaskCreateToolInput, context: ToolExecutionContext) -> ToolResult:
        manager = get_task_manager()
        if arguments.type == "local_bash":
            if not arguments.command:
                return ToolResult(output="command is required for local_bash tasks", is_error=True)
            task = await manager.create_shell_task(
                command=arguments.command,
                description=arguments.description,
                cwd=context.cwd,
                env=_path_aliases(context.cwd),
            )
        elif arguments.type == "local_agent":
            if not arguments.prompt:
                return ToolResult(output="prompt is required for local_agent tasks", is_error=True)
            executor = get_backend_registry().get_executor("subprocess")
            target_skill = infer_skill_from_text(
                f"{arguments.description}\n{arguments.prompt}",
                context.cwd,
                context.metadata,
            )
            permission_mode = "bypassPermissions" if skill_is_approved(target_skill, context.metadata) else None
            result = await executor.spawn(
                TeammateSpawnConfig(
                    name="task",
                    team="default",
                    prompt=arguments.prompt,
                    cwd=str(context.cwd),
                    parent_session_id="main",
                    model=arguments.model,
                    permission_mode=permission_mode,
                    task_type="local_agent",
                )
            )
            if not result.success:
                return ToolResult(output=result.error or "Failed to create local_agent task", is_error=True)
            return ToolResult(
                output=(
                    f"Spawned agent {result.agent_id} "
                    f"(task_id={result.task_id}, backend={result.backend_type})"
                ),
                metadata={
                    "agent_id": result.agent_id,
                    "task_id": result.task_id,
                    "task_type": "local_agent",
                    "backend_type": result.backend_type,
                    "description": arguments.description,
                },
            )
        else:
            return ToolResult(output=f"unsupported task type: {arguments.type}", is_error=True)

        return ToolResult(
            output=f"Created task {task.id} ({task.type})",
            metadata={
                "task_id": task.id,
                "task_type": task.type,
                "description": arguments.description,
            },
        )
