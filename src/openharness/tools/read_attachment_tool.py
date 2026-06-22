"""Analyze a local media attachment with the agent's configured media model."""

from __future__ import annotations

import asyncio
import base64
import mimetypes
import traceback
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel, Field

from openharness.api.client import (
    ApiMessageCompleteEvent,
    ApiMessageRequest,
    ApiTextDeltaEvent,
)
from openharness.engine.messages import AudioBlock, ConversationMessage, ImageBlock, TextBlock
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult
from openharness.tools.path_aliases import path_aliases, resolve_path

DEFAULT_MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024


def attachment_model_configs_from_agent(
    agent: Mapping[str, Any] | None,
) -> dict[str, dict[str, str]]:
    """Extract persisted image/audio model selections from an Agent record."""
    if not isinstance(agent, Mapping):
        return {}
    configs: dict[str, dict[str, str]] = {}
    for kind in ("image", "audio"):
        profile = str(agent.get(f"{kind}_profile") or "").strip()
        model = str(agent.get(f"{kind}_model") or "").strip()
        if profile:
            configs[kind] = {"profile": profile, "model": model}
    return configs


class ReadAttachmentToolInput(BaseModel):
    """Arguments for analyzing one user attachment."""

    path: str = Field(description="Local path shown in an attachment/media marker")
    prompt: str = Field(
        min_length=1,
        description=(
            "Question or instruction for the configured media model, including exactly what "
            "information should be extracted from the attachment"
        )
    )
    max_tokens: int = Field(
        default=4096,
        ge=64,
        le=32768,
        description="Maximum tokens returned by the media model",
    )


class ReadAttachmentTool(BaseTool):
    """Send a media file and prompt to the Agent's dedicated media model."""

    name = "read_attachment"
    description = (
        "Analyze an image or audio attachment using the dedicated provider and model configured "
        "for this Agent. Pass the user's actual question as prompt. Use only when the user asks "
        "you to inspect or answer from an attachment; the tool returns the media model's text."
    )
    input_model = ReadAttachmentToolInput

    def is_read_only(self, arguments: ReadAttachmentToolInput) -> bool:
        del arguments
        return True

    async def execute(
        self,
        arguments: ReadAttachmentToolInput,
        context: ToolExecutionContext,
    ) -> ToolResult:
        path = self._resolve_path(arguments.path, context)
        error = self._validate_path(path, context)
        if error:
            return ToolResult(output=error, is_error=True)

        media_type, _ = mimetypes.guess_type(str(path))
        kind = (media_type or "").split("/", 1)[0]
        if kind not in {"image", "audio"}:
            return ToolResult(
                output=f"Unsupported attachment type: {media_type or path.suffix or 'unknown'}",
                is_error=True,
            )

        configs = context.metadata.get("attachment_model_configs", {})
        config = configs.get(kind, {}) if isinstance(configs, dict) else {}
        profile = str(config.get("profile") or "").strip() if isinstance(config, dict) else ""
        model_override = str(config.get("model") or "").strip() if isinstance(config, dict) else ""
        if not profile:
            return ToolResult(
                output=f"This Agent has no {kind} processing provider configured.",
                is_error=True,
            )

        try:
            output, model = await self._analyze(
                path=path,
                kind=kind,
                media_type=media_type or f"{kind}/octet-stream",
                prompt=arguments.prompt,
                profile=profile,
                model_override=model_override,
                max_tokens=arguments.max_tokens,
            )
        except BaseException as exc:
            if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, GeneratorExit)):
                raise
            traceback.print_exc()
            return ToolResult(
                output=f"Attachment analysis failed via profile {profile}: {exc}",
                is_error=True,
            )

        return ToolResult(
            output=f"[{kind.capitalize()} analysis via {profile}/{model}]\n\n{output}",
            metadata={"profile": profile, "model": model, "kind": kind, "path": str(path)},
        )

    @staticmethod
    def _resolve_path(raw_path: str, context: ToolExecutionContext) -> Path:
        aliases = path_aliases(context.cwd)
        configured_aliases = context.metadata.get("path_aliases")
        if isinstance(configured_aliases, dict):
            aliases.update(
                {
                    str(name).strip().lstrip("$"): str(value)
                    for name, value in configured_aliases.items()
                    if str(name).strip() and str(value).strip()
                }
            )
        return resolve_path(context.cwd, raw_path, aliases)

    @staticmethod
    def _validate_path(path: Path, context: ToolExecutionContext) -> str | None:
        from openharness.sandbox.session import is_docker_sandbox_active

        if is_docker_sandbox_active():
            from openharness.sandbox.path_validator import validate_sandbox_path

            allowed, reason = validate_sandbox_path(path, context.cwd)
            if not allowed:
                return f"Sandbox: {reason}"
        if not path.exists():
            return f"Attachment not found: {path}"
        if not path.is_file():
            return f"Attachment path is not a file: {path}"

        configured_limit = context.metadata.get(
            "max_attachment_bytes", DEFAULT_MAX_ATTACHMENT_BYTES
        )
        try:
            max_bytes = max(1, int(configured_limit))
        except (TypeError, ValueError):
            max_bytes = DEFAULT_MAX_ATTACHMENT_BYTES
        size = path.stat().st_size
        if size > max_bytes:
            return f"Attachment is too large ({size} bytes; limit {max_bytes} bytes): {path}"
        return None

    @staticmethod
    async def _analyze(
        *,
        path: Path,
        kind: str,
        media_type: str,
        prompt: str,
        profile: str,
        model_override: str,
        max_tokens: int,
    ) -> tuple[str, str]:
        from openharness.config import load_settings
        from openharness.ui.runtime import _resolve_api_client_from_settings

        settings = load_settings()
        profiles = settings.merged_profiles()
        if profile not in profiles:
            raise ValueError(f"configured profile does not exist: {profile}")
        profile_settings = settings.model_copy(
            update={"active_profile": profile}
        ).materialize_active_profile()
        model = model_override or profile_settings.model

        if kind == "audio" and (
            profile_settings.provider == "openai_codex"
            or profile_settings.api_format not in {"openai", "openai_compat", "copilot"}
        ):
            raise ValueError(
                f"profile {profile} uses {profile_settings.api_format}, which cannot carry audio"
            )

        client = _resolve_api_client_from_settings(profile_settings)
        try:
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            media = (
                ImageBlock(media_type=media_type, data=encoded, source_path=str(path))
                if kind == "image"
                else AudioBlock(media_type=media_type, data=encoded, source_path=str(path))
            )
            message = ConversationMessage.from_user_content(
                [TextBlock(text=prompt.strip()), media]
            )
            collected = ""
            async for event in client.stream_message(
                ApiMessageRequest(
                    model=model,
                    messages=[message],
                    system_prompt=(
                        "Analyze the attached media and answer the supplied instruction "
                        "accurately. "
                        "Return text only."
                    ),
                    max_tokens=max_tokens,
                    tools=[],
                )
            ):
                if isinstance(event, ApiTextDeltaEvent):
                    collected += event.text
                elif isinstance(event, ApiMessageCompleteEvent):
                    final_text = event.message.text
                    if final_text and final_text not in collected:
                        collected = final_text
            return collected.strip() or "(media model returned no text)", model
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                await close()
