"""OpenHarness channel runtime used by the web config app."""

from __future__ import annotations

import asyncio
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

    async def start(self, raw_settings: dict[str, Any]) -> None:
        if self._manager_task is not None:
            return

        config = Config.model_validate(raw_settings)
        enabled = [
            name
            for name, channel_config in config.channels
            if name not in {"send_progress", "send_tool_hints"}
            and getattr(channel_config, "enabled", False)
        ]
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
            self._bridge = ChannelBridge(engine=self._bundle.engine, bus=self._bus)
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

    @property
    def running_channels(self) -> list[str]:
        if self._manager is None:
            return []
        return self._manager.enabled_channels
