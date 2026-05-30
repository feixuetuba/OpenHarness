"""OpenHarness channel runtime used by the web config app."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from openharness.channels.adapter import ChannelBridge
from openharness.channels.bus.queue import MessageBus
from openharness.channels.impl.manager import ChannelManager
from openharness.config.schema import Config
from openharness.ui.runtime import RuntimeBundle, build_runtime, close_runtime, start_runtime

logger = logging.getLogger(__name__)


class WebConfigChannelRuntime:
    """Own the optional long-running channel listeners for web_config."""

    def __init__(self, *, cwd: str | Path | None = None) -> None:
        self._cwd = str(Path(cwd or Path.cwd()).resolve())
        self._bus: MessageBus | None = None
        self._manager: ChannelManager | None = None
        self._manager_task: asyncio.Task | None = None
        self._bridge: ChannelBridge | None = None
        self._bundle: RuntimeBundle | None = None
        self._raw_settings: dict[str, Any] = {}

    async def start(self, raw_settings: dict[str, Any]) -> None:
        logger.info("WebConfigChannelRuntime.start called with settings keys: %s", list(raw_settings.keys()))
        if self._manager_task is not None:
            return

        self._raw_settings = raw_settings
        config = Config.model_validate(raw_settings)
        enabled = [
            name
            for name, channel_config in config.channels
            if name not in {"send_progress", "send_tool_hints"}
            and getattr(channel_config, "enabled", False)
        ]
        logger.info("WebConfigChannelRuntime: enabled channels: %s", enabled)
        if not enabled:
            logger.info("OpenHarness channel runtime not started: no channels enabled")
            return

        logger.info("Starting OpenHarness channel runtime for channels: %s", ", ".join(enabled))
        self._bus = MessageBus()
        self._manager = ChannelManager(config, self._bus)
        if not self._manager.channels:
            logger.warning("OpenHarness channel runtime found no startable channels")
            return

        self._manager_task = asyncio.create_task(
            self._manager.start_all(),
            name="web-config-channel-manager",
        )
        try:
            self._bundle = await build_runtime(cwd=self._cwd)
            await start_runtime(self._bundle)

            def resolve_agent_id(channel_name: str) -> str | None:
                assignments = self._raw_settings.get("bot_agent_assignments", {})
                if not isinstance(assignments, dict):
                    return None
                agent_id = assignments.get(channel_name)
                if agent_id is None:
                    return None
                return str(agent_id).strip() or None

            def resolve_agent_name(agent_id: str) -> str:
                from openharness.config.paths import get_config_dir
                from openharness.coordinator.agent_definitions import get_agent_definition

                agents_path = get_config_dir() / "agents.json"
                if agents_path.exists():
                    try:
                        agents_data = json.loads(agents_path.read_text(encoding="utf-8"))
                        for agent in agents_data.get("agents", []):
                            if agent.get("id") == agent_id:
                                return str(agent.get("name") or agent_id)
                    except Exception:
                        logger.exception("ChannelBridge: failed to resolve web agent name for %s", agent_id)
                agent_def = get_agent_definition(agent_id)
                return agent_def.name if agent_def else agent_id

            def get_channel_sessions(channel_name: str) -> dict | None:
                if self._manager is None:
                    return None
                ch = self._manager.get_channel(channel_name)
                if ch is None:
                    return None
                return getattr(ch, "sessions", None)

            async def create_engine_for_agent(agent_id: str) -> "QueryEngine":
                from openharness.coordinator.agent_definitions import get_agent_definition
                from openharness.engine.query_engine import QueryEngine
                from openharness.ui.runtime import _resolve_api_client_from_settings
                from openharness.config.settings import load_settings
                from openharness.tools.base import ToolRegistry
                from openharness.permissions.checker import PermissionChecker
                from openharness.config.settings import PermissionSettings
                from openharness.permissions.modes import PermissionMode
                from openharness.bridge import get_bridge_manager
                from openharness.prompts import build_runtime_system_prompt
                from openharness.config.paths import get_config_dir

                logger.info("ChannelBridge: create_engine_for_agent called with agent_id=%s", agent_id)

                settings = load_settings()

                web_agent = None
                agents_path = get_config_dir() / "agents.json"
                logger.info("ChannelBridge: checking agents.json at %s (exists=%s)", agents_path, agents_path.exists())
                if agents_path.exists():
                    try:
                        agents_data = json.loads(agents_path.read_text(encoding="utf-8"))
                        logger.info("ChannelBridge: agents.json content: %s", json.dumps(agents_data, ensure_ascii=False)[:500])
                        for a in agents_data.get("agents", []):
                            if a.get("id") == agent_id:
                                web_agent = a
                                logger.info("ChannelBridge: found web agent: %s", web_agent)
                                break
                    except Exception as e:
                        logger.exception("ChannelBridge: failed to read agents.json: %s", e)

                yaml_agent_def = get_agent_definition(agent_id)

                if web_agent:
                    model = web_agent.get("model") or settings.model
                    system_prompt = web_agent.get("system_prompt", "")
                    if not system_prompt:
                        system_prompt = build_runtime_system_prompt(
                            settings,
                            cwd=self._cwd,
                            latest_user_prompt=None,
                            extra_skill_dirs=(),
                            extra_plugin_roots=(),
                            include_project_memory=True,
                        )
                    max_turns = web_agent.get("max_turns") or settings.max_turns
                    logger.info(
                        "ChannelBridge: using web-config agent '%s' (id=%s), model=%s, system_prompt_preview=%s",
                        web_agent.get("name", agent_id),
                        agent_id,
                        model,
                        system_prompt[:200] if system_prompt else "(empty)",
                    )
                elif yaml_agent_def:
                    model = yaml_agent_def.model if yaml_agent_def.model and yaml_agent_def.model != "inherit" else settings.model
                    system_prompt = yaml_agent_def.system_prompt if yaml_agent_def.system_prompt else build_runtime_system_prompt(
                        settings,
                        cwd=self._cwd,
                        latest_user_prompt=None,
                        extra_skill_dirs=(),
                        extra_plugin_roots=(),
                        include_project_memory=True,
                    )
                    max_turns = settings.max_turns
                else:
                    model = settings.model
                    system_prompt = build_runtime_system_prompt(
                        settings,
                        cwd=self._cwd,
                        latest_user_prompt=None,
                        extra_skill_dirs=(),
                        extra_plugin_roots=(),
                        include_project_memory=True,
                    )
                    max_turns = settings.max_turns

                api_client = _resolve_api_client_from_settings(settings)

                tool_registry = ToolRegistry()
                for tool in self._bundle.tool_registry.list_tools():
                    if yaml_agent_def is None or yaml_agent_def.tools is None or "*" in yaml_agent_def.tools or tool.name in yaml_agent_def.tools:
                        if yaml_agent_def is None or tool.name not in (yaml_agent_def.disallowed_tools or []):
                            tool_registry.register(tool)

                permission_mode = yaml_agent_def.permission_mode if yaml_agent_def and yaml_agent_def.permission_mode else settings.permission.mode.value
                try:
                    perm_mode = PermissionMode(permission_mode)
                except ValueError:
                    perm_mode = settings.permission.mode

                engine = QueryEngine(
                    api_client=api_client,
                    tool_registry=tool_registry,
                    permission_checker=PermissionChecker(PermissionSettings(mode=perm_mode)),
                    cwd=self._cwd,
                    model=model,
                    system_prompt=system_prompt,
                    max_tokens=settings.max_tokens,
                    context_window_tokens=settings.context_window_tokens or settings.memory.context_window_tokens,
                    auto_compact_threshold_tokens=settings.auto_compact_threshold_tokens or settings.memory.auto_compact_threshold_tokens,
                    max_turns=max_turns,
                    settings=settings,
                    tool_metadata={
                        "mcp_manager": self._bundle.mcp_manager,
                        "bridge_manager": get_bridge_manager(),
                        "extra_skill_dirs": (),
                        "extra_plugin_roots": (),
                        "session_id": agent_id,
                    },
                )
                if yaml_agent_def and yaml_agent_def.effort is not None:
                    engine.set_effort(yaml_agent_def.effort if isinstance(yaml_agent_def.effort, str) else None)
                return engine

            self._bridge = ChannelBridge(
                engine=self._bundle.engine,
                bus=self._bus,
                resolve_agent_id=resolve_agent_id,
                create_engine_for_agent=create_engine_for_agent,
                get_channel_sessions=get_channel_sessions,
                resolve_agent_name=resolve_agent_name,
            )
            await self._bridge.start()
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError)):
                raise
            logger.exception(
                "OpenHarness channel listeners are running, but the agent bridge failed to start"
            )

    async def stop(self) -> None:
        if self._bridge is not None:
            await self._bridge.stop()
            self._bridge = None

        if self._manager is not None:
            await self._manager.stop_all()
            self._manager = None

        if self._manager_task is not None:
            self._manager_task.cancel()
            try:
                await self._manager_task
            except asyncio.CancelledError:
                pass
            self._manager_task = None

        if self._bundle is not None:
            await close_runtime(self._bundle)
            self._bundle = None

        self._bus = None

    async def restart(self, raw_settings: dict[str, Any]) -> None:
        await self.stop()
        await self.start(raw_settings)

    def set_bot_agent_assignment(self, channel_name: str, agent_id: str | None) -> None:
        """Update the in-memory bot agent assignment used by the live bridge."""
        assignments = self._raw_settings.get("bot_agent_assignments", {})
        if not isinstance(assignments, dict):
            assignments = {}
        if agent_id:
            assignments[channel_name] = agent_id
        else:
            assignments.pop(channel_name, None)
        self._raw_settings["bot_agent_assignments"] = assignments

    @property
    def running_channels(self) -> list[str]:
        if self._manager is None:
            return []
        return self._manager.enabled_channels
