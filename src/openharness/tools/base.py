"""Tool abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from openharness.hooks.executor import HookExecutor


@dataclass
class ToolExecutionContext:
    """Shared execution context for tool invocations."""

    cwd: Path
    metadata: dict[str, Any] = field(default_factory=dict)
    hook_executor: HookExecutor | None = None


@dataclass(frozen=True)
class ToolResult:
    """Normalized tool execution result."""

    output: str
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseTool(ABC):
    """Base class for all OpenHarness tools."""

    name: str
    description: str
    input_model: type[BaseModel]

    @abstractmethod
    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
        """Execute the tool."""

    def is_read_only(self, arguments: BaseModel) -> bool:
        """Return whether the invocation is read-only."""
        del arguments
        return False

    def to_api_schema(self) -> dict[str, Any]:
        """Return the tool schema expected by the Anthropic Messages API."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
        }


class ToolRegistry:
    """Map tool names to implementations."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._restrictions: dict[str, dict[str, Any]] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        """Return a registered tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[BaseTool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def set_tool_restriction(
        self,
        tool_name: str,
        *,
        keywords: list[str] | None = None,
        message: str | None = None,
    ) -> None:
        """Attach configurable use-scope restrictions for a tool."""
        normalized = []
        for keyword in keywords or []:
            text = str(keyword or "").strip()
            if text and text not in normalized:
                normalized.append(text)
        if not normalized:
            self._restrictions.pop(tool_name, None)
            return
        self._restrictions[tool_name] = {
            "keywords": normalized,
            "message": str(message or "").strip(),
        }

    def get_tool_restriction(self, tool_name: str) -> dict[str, Any]:
        """Return configured restrictions for a tool."""
        return dict(self._restrictions.get(tool_name) or {})

    def restriction_violation(self, tool_name: str, tool_input: Any) -> str | None:
        """Return a user-facing error when *tool_input* violates a restriction."""
        restriction = self._restrictions.get(tool_name) or {}
        keywords = [str(item).strip() for item in restriction.get("keywords", []) if str(item).strip()]
        if not keywords:
            return None
        haystack = _flatten_text(tool_input).lower()
        matched = [keyword for keyword in keywords if keyword.lower() in haystack]
        if not matched:
            return None
        message = str(restriction.get("message") or "").strip()
        if message:
            return message
        return (
            f"{tool_name} is not allowed for requests matching: {', '.join(matched)}. "
            "Use the appropriate dedicated skill or tool instead."
        )

    def to_api_schema(self) -> list[dict[str, Any]]:
        """Return all tool schemas in API format."""
        schemas = []
        for tool in self._tools.values():
            schema = tool.to_api_schema()
            restriction = self._restrictions.get(tool.name) or {}
            keywords = [str(item).strip() for item in restriction.get("keywords", []) if str(item).strip()]
            if keywords:
                message = str(restriction.get("message") or "").strip()
                restriction_text = (
                    "\n\nUse-scope restriction: Do not use this tool for requests containing or implying "
                    f"these keywords: {', '.join(keywords)}."
                )
                if message:
                    restriction_text += f" {message}"
                schema["description"] = str(schema.get("description") or "") + restriction_text
            schemas.append(schema)
        return schemas


def _flatten_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "\n".join(_flatten_text(item) for pair in value.items() for item in pair)
    if isinstance(value, (list, tuple, set)):
        return "\n".join(_flatten_text(item) for item in value)
    return str(value)
