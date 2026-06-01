"""OpenHarness channel runtime used by the web config app."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from openharness.channels.bus.events import InboundMessage, OutboundMessage
from openharness.channels.bus.queue import MessageBus
from openharness.channels.impl.manager import ChannelManager
from openharness.config.schema import Config
from openharness.engine.stream_events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from openharness.engine.query_engine import QueryEngine
from openharness.tools.base import ToolRegistry
from openharness.ui.runtime import RuntimeBundle, build_runtime, close_runtime, start_runtime

logger = logging.getLogger(__name__)


ATTACHMENT_RE = re.compile(r"\[attachment:\s*([^\]\n]+?)\s*\]", re.IGNORECASE)
MEDIA_MARKER_RE = re.compile(r"\[(?:file|image|photo|video|audio|media|document):\s*([^\]\n]+?)\s*\]", re.IGNORECASE)
OUTBOUND_MEDIA_RE = re.compile(
    r"\[(attachment|file|document|image|photo|video|audio|voice|audio-file|media):\s*([^\]\n]+?)\s*\]",
    re.IGNORECASE,
)
PENDING_MEDIA_NOTICE_SECONDS = 30.0
SOCIAL_ENGINE_EVENT_TIMEOUT_SECONDS = 180.0
SOCIAL_DIAGNOSTIC_AGENT_TIMEOUT_SECONDS = 120.0
MEDIA_WORDS = (
    "文件", "附件", "图片", "照片", "图像", "视频", "音频", "压缩包", "文档", "表格",
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "zip", "rar", "7z",
    "image", "photo", "video", "audio", "file", "attachment", "document",
)
ACTION_WORDS = (
    "处理", "分析", "总结", "识别", "读取", "打开", "看看", "看下", "检查", "转换",
    "提取", "翻译", "修改", "压缩", "解压", "帮我", "根据", "基于", "process",
    "analyze", "summarize", "read", "extract", "translate", "convert",
)
SOCIAL_OUTPUT_INSTRUCTIONS = (
    "\n\n[社交平台输出约定]\n"
    "如果需要生成新文件，必须保存到本消息指定的社交输出目录中，不要保存到 /tmp 或不确定的相对目录。\n"
    "如果需要把本地文件发送给用户，请在回复中单独写一行 [attachment: /absolute/path/to/file]，必须优先使用绝对路径。\n"
    "如果音频要作为语音消息发送，请写 [voice: /absolute/path/to/audio]；"
    "如果音频要作为普通文件发送，请写 [audio-file: /absolute/path/to/audio]。\n"
    "输出这些标记前，必须确认文件已经真实存在；不要编造 /tmp 路径，也不要只把文件路径作为普通文本返回。\n"
    "如果使用 ffmpeg，输出文件路径应作为命令最后一个参数；不要使用不存在的 -output 参数。"
)


class WebConfigSmartChannelBridge:
    """Web-config bridge with quote-aware, instruction-gated media handling."""

    def __init__(
        self,
        *,
        engine: "QueryEngine",
        bus: MessageBus,
        cwd: str | Path,
        resolve_agent_id,
        create_engine_for_agent,
        get_channel_sessions,
        resolve_agent_name,
    ) -> None:
        self._engine = engine
        self._bus = bus
        self._cwd = str(Path(cwd).resolve())
        self._running = False
        self._task: asyncio.Task | None = None
        self._resolve_agent_id = resolve_agent_id
        self._create_engine_for_agent = create_engine_for_agent
        self._get_channel_sessions = get_channel_sessions
        self._resolve_agent_name = resolve_agent_name
        self._agent_engines: dict[str, "QueryEngine"] = {}
        self._states: dict[str, dict[str, Any]] = {}
        self._messages_by_id: dict[str, dict[str, Any]] = {}

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="web-config-smart-channel-bridge")
        logger.info("WebConfigSmartChannelBridge started")

    async def stop(self) -> None:
        self._running = False
        for state in self._states.values():
            task = state.get("notice_task")
            if isinstance(task, asyncio.Task):
                task.cancel()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("WebConfigSmartChannelBridge stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                msg = await asyncio.wait_for(self._bus.consume_inbound(), timeout=1.0)
                await self._handle(msg)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("WebConfigSmartChannelBridge: unhandled error")

    async def _handle(self, msg: InboundMessage) -> None:
        key = self._state_key(msg)
        state = self._states.setdefault(key, {"pending_media": [], "pending_instruction": ""})
        self._remember_message(msg)

        media_paths = self._extract_media_paths(msg)
        text = self._strip_attachment_markers(msg.content).strip()
        quoted = self._resolve_quoted_message(msg)
        instruction = text if text and text != "[empty message]" else ""
        pending_media = list(state.get("pending_media") or [])

        if self._is_unmentioned_group_message(msg) and not media_paths and not pending_media:
            logger.info(
                "Ignoring unmentioned group text after web media capture passthrough: %s/%s",
                msg.channel,
                msg.chat_id,
            )
            return

        if quoted and instruction:
            prompt = self._build_prompt(instruction, quoted=quoted)
            await self._clear_state_and_process(state, msg, prompt)
            return

        if media_paths and instruction:
            pending_instruction = str(state.get("pending_instruction") or "").strip()
            final_instruction = self._combine_instruction(pending_instruction, instruction)
            pending_media = list(state.get("pending_media") or [])
            current = self._media_item(msg, media_paths)
            prompt = self._build_prompt(final_instruction, media_items=[*pending_media, current])
            await self._clear_state_and_process(state, msg, prompt)
            return

        if media_paths and not instruction:
            pending_instruction = str(state.get("pending_instruction") or "").strip()
            if pending_instruction:
                pending_media = list(state.get("pending_media") or [])
                current = self._media_item(msg, media_paths)
                prompt = self._build_prompt(pending_instruction, media_items=[*pending_media, current])
                await self._clear_state_and_process(state, msg, prompt)
                return
            state["pending_media"] = self._merge_pending_media(state.get("pending_media", []), msg, media_paths)
            self._schedule_notice(state, msg, "已收到文件/多媒体内容，请继续说明你希望我怎么处理。")
            logger.info("Held inbound media for later instruction: %s/%s", msg.channel, msg.chat_id)
            return

        if pending_media and instruction:
            pending_instruction = str(state.get("pending_instruction") or "").strip()
            final_instruction = self._combine_instruction(pending_instruction, instruction)
            prompt = self._build_prompt(final_instruction, media_items=pending_media)
            await self._clear_state_and_process(state, msg, prompt)
            return

        if instruction and self._looks_like_media_instruction(instruction):
            state["pending_instruction"] = self._combine_instruction(str(state.get("pending_instruction") or ""), instruction)
            self._schedule_notice(state, msg, "我还没有收到要处理的目标文件。请发送文件，或引用之前的文件/消息再说明要怎么处理。")
            logger.info("Held media-related instruction awaiting file/reference: %s", instruction[:100])
            return

        await self._process_now(msg, msg.content)

    async def _clear_state_and_process(self, state: dict[str, Any], msg: InboundMessage, prompt: str) -> None:
        self._cancel_notice(state)
        state["pending_media"] = []
        state["pending_instruction"] = ""
        await self._process_now(msg, prompt)

    async def _process_now(self, msg: InboundMessage, content: str) -> None:
        logger.info(
            "WebConfigSmartChannelBridge processing %s/%s, content=%s",
            msg.channel,
            msg.chat_id,
            content[:100] if content else "",
        )

        engine = self._engine
        agent_id = self._resolve_agent_id(msg.channel) if self._resolve_agent_id else None
        if agent_id and self._create_engine_for_agent is not None:
            if agent_id not in self._agent_engines:
                try:
                    self._agent_engines[agent_id] = await self._create_engine_for_agent(agent_id)
                except Exception:
                    logger.exception("Failed to create engine for agent %s, falling back to default", agent_id)
                    agent_id = None
            if agent_id in self._agent_engines:
                engine = self._agent_engines[agent_id]

        reply_parts: list[str] = []
        output_dir = self._ensure_social_output_dir(msg)
        tool_call_count = 0
        tool_names: list[str] = []
        tool_errors: list[dict[str, Any]] = []
        full_prompt = self._with_social_output_instructions(content, output_dir)
        logger.info(
            "Social model prompt channel=%s chat_id=%s sender=%s output_dir=%s prompt=%s",
            msg.channel,
            msg.chat_id,
            msg.sender_id,
            output_dir,
            self._truncate_log_text(full_prompt, limit=2000),
        )
        self._social_debug(
            "model_prompt",
            msg,
            output_dir=str(output_dir),
            prompt=self._truncate_log_text(full_prompt, limit=4000),
        )
        try:
            stream = engine.submit_message(full_prompt).__aiter__()
            while True:
                try:
                    event = await asyncio.wait_for(
                        stream.__anext__(),
                        timeout=self._engine_event_timeout_seconds(),
                    )
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    timeout_text = self._diagnose_stalled_turn(msg, tool_names, tool_errors)
                    logger.warning(
                        "Social engine event timeout channel=%s chat_id=%s sender=%s tools=%s",
                        msg.channel,
                        msg.chat_id,
                        msg.sender_id,
                        ",".join(tool_names) if tool_names else "(none)",
                    )
                    self._social_debug(
                        "engine_event_timeout",
                        msg,
                        timeout_seconds=self._engine_event_timeout_seconds(),
                        tool_names=tool_names,
                        tool_errors=tool_errors[-5:],
                        diagnosis=timeout_text,
                    )
                    aclose = getattr(stream, "aclose", None)
                    if aclose is not None:
                        try:
                            await aclose()
                        except Exception:
                            logger.debug("Failed to close timed-out social stream", exc_info=True)
                    diagnostic_reply = await self._run_diagnostic_subagent(
                        engine,
                        msg,
                        original_prompt=full_prompt,
                        output_dir=output_dir,
                        tool_names=tool_names,
                        tool_errors=tool_errors,
                        reason="主 agent 长时间没有产生新的模型/工具事件。",
                    )
                    if diagnostic_reply:
                        outbound_text, outbound_media, media_modes = self._extract_outbound_media(
                            diagnostic_reply,
                            base_dir=Path(self._cwd),
                        )
                        outbound_media, media_modes, missing_media = self._filter_existing_outbound_media(
                            outbound_media,
                            media_modes,
                        )
                        if missing_media:
                            missing_text = "无法发送以下文件，因为路径不存在：\n" + "\n".join(f"- {path}" for path in missing_media)
                            outbound_text = f"{outbound_text}\n\n{missing_text}".strip() if outbound_text else missing_text
                        if outbound_text or outbound_media:
                            self._append_assistant_session_message(msg, diagnostic_reply, agent_id)
                            await self._publish_reply(msg, outbound_text, media=outbound_media, media_modes=media_modes)
                            return
                    await self._publish_reply(msg, timeout_text)
                    return
                if isinstance(event, AssistantTextDelta):
                    reply_parts.append(event.text)
                elif isinstance(event, AssistantTurnComplete):
                    tool_uses = getattr(event.message, "tool_uses", None) or []
                    logger.info(
                        "Social assistant turn complete channel=%s chat_id=%s sender=%s tool_use_count=%s message=%s",
                        msg.channel,
                        msg.chat_id,
                        msg.sender_id,
                        len(tool_uses),
                        self._truncate_log_text(getattr(event.message, "text", "") or str(event.message), limit=2000),
                    )
                    self._social_debug(
                        "assistant_turn_complete",
                        msg,
                        tool_use_count=len(tool_uses),
                        message=self._truncate_log_text(getattr(event.message, "text", "") or str(event.message), limit=4000),
                    )
                elif isinstance(event, ToolExecutionStarted):
                    tool_call_count += 1
                    tool_names.append(event.tool_name)
                    self._log_tool_started(msg, event, output_dir)
                elif isinstance(event, ToolExecutionCompleted):
                    self._log_tool_completed(msg, event)
                    if event.is_error:
                        tool_errors.append({
                            "tool": event.tool_name,
                            "output": self._truncate_log_text(event.output, limit=1200),
                            "metadata": event.metadata or {},
                        })
        except Exception:
            logger.exception("Channel engine error for %s/%s", msg.channel, msg.chat_id)
            reply_parts = ["[Error: failed to process your message]"]

        reply_text = "".join(reply_parts).strip()
        logger.info(
            "Social assistant raw reply channel=%s chat_id=%s sender=%s tool_call_count=%s tool_names=%s reply=%s",
            msg.channel,
            msg.chat_id,
            msg.sender_id,
            tool_call_count,
            ",".join(tool_names) if tool_names else "(none)",
            self._truncate_log_text(reply_text, limit=3000),
        )
        self._social_debug(
            "assistant_raw_reply",
            msg,
            tool_call_count=tool_call_count,
            tool_names=tool_names,
            reply=self._truncate_log_text(reply_text, limit=5000),
        )
        outbound_text, outbound_media, media_modes = self._extract_outbound_media(reply_text, base_dir=Path(self._cwd))
        outbound_media, media_modes, missing_media = self._filter_existing_outbound_media(outbound_media, media_modes)
        logger.info(
            "Social outbound media channel=%s chat_id=%s sender=%s media=%s modes=%s missing=%s",
            msg.channel,
            msg.chat_id,
            msg.sender_id,
            self._compact_json(outbound_media),
            self._compact_json(media_modes),
            self._compact_json(missing_media),
        )
        self._social_debug(
            "outbound_media",
            msg,
            media=outbound_media,
            modes=media_modes,
            missing=missing_media,
        )
        if missing_media:
            missing_text = "无法发送以下文件，因为路径不存在：\n" + "\n".join(f"- {path}" for path in missing_media)
            outbound_text = f"{outbound_text}\n\n{missing_text}".strip() if outbound_text else missing_text
        if not outbound_text and not outbound_media:
            if tool_errors:
                diagnostic_reply = await self._run_diagnostic_subagent(
                    engine,
                    msg,
                    original_prompt=full_prompt,
                    output_dir=output_dir,
                    tool_names=tool_names,
                    tool_errors=tool_errors,
                    reason="主 agent 工具调用失败后没有返回任何可发送内容。",
                )
                if diagnostic_reply:
                    reply_text = diagnostic_reply
                    outbound_text, outbound_media, media_modes = self._extract_outbound_media(
                        reply_text,
                        base_dir=Path(self._cwd),
                    )
                    outbound_media, media_modes, missing_media = self._filter_existing_outbound_media(
                        outbound_media,
                        media_modes,
                    )
                    if missing_media:
                        missing_text = "无法发送以下文件，因为路径不存在：\n" + "\n".join(f"- {path}" for path in missing_media)
                        outbound_text = f"{outbound_text}\n\n{missing_text}".strip() if outbound_text else missing_text
                if not outbound_text and not outbound_media:
                    outbound_text = self._diagnose_failed_tools(tool_errors)
                self._social_debug(
                    "empty_reply_after_tool_errors",
                    msg,
                    tool_names=tool_names,
                    tool_errors=tool_errors[-5:],
                    fallback_reply=outbound_text,
                )
            else:
                self._social_debug("empty_reply", msg, tool_names=tool_names)
                outbound_text = "任务没有返回可发送的内容。请稍后重试，或补充更明确的处理要求。"

        self._append_assistant_session_message(msg, reply_text or outbound_text, agent_id)
        await self._publish_reply(msg, outbound_text, media=outbound_media, media_modes=media_modes)

    async def _publish_reply(
        self,
        msg: InboundMessage,
        text: str,
        *,
        media: list[str] | None = None,
        media_modes: dict[str, str] | None = None,
    ) -> None:
        metadata = dict(msg.metadata or {})
        metadata["_session_key"] = msg.session_key
        if media_modes:
            metadata["_media_modes"] = media_modes
        await self._bus.publish_outbound(
            OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=text,
                media=media or [],
                metadata=metadata,
            )
        )

    async def _publish_notice(self, msg: InboundMessage, text: str) -> None:
        self._append_assistant_session_message(msg, text, None)
        await self._publish_reply(msg, text)

    async def _run_diagnostic_subagent(
        self,
        engine: QueryEngine,
        msg: InboundMessage,
        *,
        original_prompt: str,
        output_dir: Path,
        tool_names: list[str],
        tool_errors: list[dict[str, Any]],
        reason: str,
    ) -> str:
        if self._diagnostic_agent_timeout_seconds() <= 0:
            return ""
        try:
            diagnostic_engine = self._make_diagnostic_engine(engine, msg)
        except Exception:
            logger.exception("Failed to create social diagnostic subagent")
            return ""

        diagnostic_prompt = self._build_diagnostic_prompt(
            msg,
            original_prompt=original_prompt,
            output_dir=output_dir,
            tool_names=tool_names,
            tool_errors=tool_errors,
            reason=reason,
        )
        self._social_debug(
            "diagnostic_subagent_start",
            msg,
            timeout_seconds=self._diagnostic_agent_timeout_seconds(),
            reason=reason,
            tool_names=tool_names,
            tool_errors=tool_errors[-5:],
        )
        reply_parts: list[str] = []
        diagnostic_tool_errors: list[dict[str, Any]] = []
        try:
            stream = diagnostic_engine.submit_message(diagnostic_prompt).__aiter__()
            deadline = time.monotonic() + self._diagnostic_agent_timeout_seconds()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise asyncio.TimeoutError
                try:
                    event = await asyncio.wait_for(stream.__anext__(), timeout=max(1.0, remaining))
                except StopAsyncIteration:
                    break
                if isinstance(event, AssistantTextDelta):
                    reply_parts.append(event.text)
                elif isinstance(event, AssistantTurnComplete):
                    self._social_debug(
                        "diagnostic_assistant_turn_complete",
                        msg,
                        message=self._truncate_log_text(getattr(event.message, "text", "") or str(event.message), limit=3000),
                        tool_use_count=len(getattr(event.message, "tool_uses", None) or []),
                    )
                elif isinstance(event, ToolExecutionStarted):
                    self._social_debug(
                        "diagnostic_tool_call_start",
                        msg,
                        tool=event.tool_name,
                        input=event.tool_input,
                    )
                elif isinstance(event, ToolExecutionCompleted):
                    self._social_debug(
                        "diagnostic_tool_call_done",
                        msg,
                        tool=event.tool_name,
                        is_error=event.is_error,
                        output=self._truncate_log_text(event.output, limit=5000),
                        metadata=event.metadata or {},
                    )
                    if event.is_error:
                        diagnostic_tool_errors.append({
                            "tool": event.tool_name,
                            "output": self._truncate_log_text(event.output, limit=1200),
                            "metadata": event.metadata or {},
                        })
        except asyncio.TimeoutError:
            self._social_debug(
                "diagnostic_subagent_timeout",
                msg,
                timeout_seconds=self._diagnostic_agent_timeout_seconds(),
                tool_errors=diagnostic_tool_errors[-5:],
            )
            return ""
        except Exception:
            logger.exception("Social diagnostic subagent failed")
            self._social_debug(
                "diagnostic_subagent_error",
                msg,
                tool_errors=diagnostic_tool_errors[-5:],
            )
            return ""

        reply = "".join(reply_parts).strip()
        self._social_debug(
            "diagnostic_subagent_reply",
            msg,
            reply=self._truncate_log_text(reply, limit=5000),
            tool_errors=diagnostic_tool_errors[-5:],
        )
        return reply

    def _make_diagnostic_engine(self, engine: QueryEngine, msg: InboundMessage) -> QueryEngine:
        tool_registry = ToolRegistry()
        source_registry = getattr(engine, "_tool_registry")
        for tool in source_registry.list_tools():
            if tool.name == "agent":
                continue
            tool_registry.register(tool)
        metadata = dict(getattr(engine, "_tool_metadata", {}) or {})
        metadata["subagent_depth"] = 1
        metadata["social_diagnostic_subagent"] = True
        metadata["session_id"] = f"{msg.session_key or msg.sender_id}:diagnostic"
        system_prompt = (
            f"{engine.system_prompt}\n\n"
            "[社交故障诊断子 agent]\n"
            "你正在诊断主 agent 的失败。你只能作为一层子 agent 工作，禁止调用或请求任何新的子 agent。\n"
            "你的目标是分析最近的工具/MCP错误；如果可以安全修复，就直接用现有工具修复并返回最终可发送回复。\n"
            "如果需要发送生成文件，仍然使用 [attachment: /absolute/path] 或 [audio-file: /absolute/path] 标记。\n"
            "如果无法修复，请用简短中文说明失败原因和下一步建议。"
        )
        return QueryEngine(
            api_client=engine.api_client,
            tool_registry=tool_registry,
            permission_checker=getattr(engine, "_permission_checker"),
            cwd=getattr(engine, "_cwd"),
            model=engine.model,
            system_prompt=system_prompt,
            max_tokens=getattr(engine, "_max_tokens"),
            context_window_tokens=getattr(engine, "_context_window_tokens"),
            auto_compact_threshold_tokens=getattr(engine, "_auto_compact_threshold_tokens"),
            max_turns=3,
            permission_prompt=None,
            ask_user_prompt=None,
            hook_executor=getattr(engine, "_hook_executor"),
            tool_metadata=metadata,
            settings=getattr(engine, "_settings"),
        )

    def _build_diagnostic_prompt(
        self,
        msg: InboundMessage,
        *,
        original_prompt: str,
        output_dir: Path,
        tool_names: list[str],
        tool_errors: list[dict[str, Any]],
        reason: str,
    ) -> str:
        debug_log = Path(self._cwd) / ".openharness" / "social_debug.log"
        return (
            "主 agent 处理社交消息失败，需要你作为唯一一层诊断子 agent 进行分析和有限修复。\n"
            f"失败原因触发条件：{reason}\n"
            f"社交通道：{msg.channel}\n"
            f"会话：{msg.chat_id}\n"
            f"输出目录：{output_dir}\n"
            f"社交调试日志：{debug_log}\n"
            f"主 agent 已调用工具：{json.dumps(tool_names, ensure_ascii=False)}\n"
            f"最近工具错误：{json.dumps(tool_errors[-5:], ensure_ascii=False, default=str)}\n\n"
            "原始用户需求和社交输出约定如下：\n"
            f"{original_prompt}\n\n"
            "要求：\n"
            "1. 不要调用 agent，也不要生成新的子 agent。\n"
            "2. 如果错误很明显且可修复，可以尝试最多两次修复动作，例如改正命令参数后重新生成文件。\n"
            "3. 如果修复成功，直接返回给用户的最终文本/文件标记。\n"
            "4. 如果无法修复、风险较高或仍失败，返回简短失败原因，不要沉默。"
        )

    @staticmethod
    def _engine_event_timeout_seconds() -> float:
        raw = os.environ.get("OPENHARNESS_SOCIAL_ENGINE_EVENT_TIMEOUT_SECONDS", "").strip()
        if not raw:
            return SOCIAL_ENGINE_EVENT_TIMEOUT_SECONDS
        try:
            return max(10.0, float(raw))
        except ValueError:
            logger.warning("Invalid OPENHARNESS_SOCIAL_ENGINE_EVENT_TIMEOUT_SECONDS=%r", raw)
            return SOCIAL_ENGINE_EVENT_TIMEOUT_SECONDS

    @staticmethod
    def _diagnostic_agent_timeout_seconds() -> float:
        raw = os.environ.get("OPENHARNESS_SOCIAL_DIAGNOSTIC_AGENT_TIMEOUT_SECONDS", "").strip()
        if not raw:
            return SOCIAL_DIAGNOSTIC_AGENT_TIMEOUT_SECONDS
        try:
            return max(0.0, float(raw))
        except ValueError:
            logger.warning("Invalid OPENHARNESS_SOCIAL_DIAGNOSTIC_AGENT_TIMEOUT_SECONDS=%r", raw)
            return SOCIAL_DIAGNOSTIC_AGENT_TIMEOUT_SECONDS

    def _diagnose_failed_tools(self, tool_errors: list[dict[str, Any]]) -> str:
        last = tool_errors[-1] if tool_errors else {}
        tool = str(last.get("tool") or "tool")
        output = self._truncate_log_text(str(last.get("output") or ""), limit=900)
        if "Unrecognized option 'output'" in output:
            return (
                "处理没有完成：工具命令失败了。最近一次错误来自 "
                f"`{tool}`，ffmpeg 不支持 `-output` 参数，输出文件应直接放在命令末尾。"
            )
        if "timed out" in output.lower() or "timeout" in output.lower():
            return f"处理超时：`{tool}` 长时间没有完成。可以缩小任务范围后重试，或稍后让我继续检查。"
        if output:
            return f"处理没有完成：`{tool}` 执行失败。\n\n最近错误：{output}"
        return f"处理没有完成：`{tool}` 执行失败，但没有返回可用错误信息。"

    def _diagnose_stalled_turn(
        self,
        msg: InboundMessage,
        tool_names: list[str],
        tool_errors: list[dict[str, Any]],
    ) -> str:
        if tool_errors:
            return self._diagnose_failed_tools(tool_errors)
        active = tool_names[-1] if tool_names else "模型响应"
        debug_path = Path(self._cwd) / ".openharness" / "social_debug.log"
        return (
            f"任务执行时间过长，当前停在 `{active}` 附近。"
            f"我已经停止等待本轮执行，详细记录可查看：{debug_path}"
        )

    def _schedule_notice(self, state: dict[str, Any], msg: InboundMessage, text: str) -> None:
        self._cancel_notice(state)

        async def notify_later() -> None:
            try:
                await asyncio.sleep(PENDING_MEDIA_NOTICE_SECONDS)
                await self._publish_notice(msg, text)
            except asyncio.CancelledError:
                pass

        state["notice_task"] = asyncio.create_task(notify_later())

    @staticmethod
    def _cancel_notice(state: dict[str, Any]) -> None:
        task = state.get("notice_task")
        if isinstance(task, asyncio.Task):
            task.cancel()
        state["notice_task"] = None

    def _append_assistant_session_message(self, msg: InboundMessage, content: str, agent_id: str | None) -> None:
        sessions = self._get_channel_sessions(msg.channel) if self._get_channel_sessions else None
        if sessions is None:
            return
        key = msg.session_key_override or msg.sender_id
        if key not in sessions:
            return
        agent_name = self._resolve_agent_name(agent_id) if agent_id and self._resolve_agent_name else None
        sessions[key]["messages"].append(
            {"role": "assistant", "content": content, "timestamp": __import__("time").time(), "agent_name": agent_name}
        )

    def _remember_message(self, msg: InboundMessage) -> None:
        message_id = self._message_id(msg)
        if not message_id:
            return
        self._messages_by_id[f"{msg.channel}:{message_id}"] = {
            "content": msg.content,
            "media": self._extract_media_paths(msg),
            "metadata": dict(msg.metadata or {}),
        }
        if len(self._messages_by_id) > 1000:
            for old_key in list(self._messages_by_id)[:100]:
                self._messages_by_id.pop(old_key, None)

    def _resolve_quoted_message(self, msg: InboundMessage) -> dict[str, Any] | None:
        metadata = msg.metadata or {}
        candidates = [
            metadata.get("reply_to"),
            metadata.get("reply_to_message_id"),
            metadata.get("quoted_message_id"),
            metadata.get("quote_message_id"),
            metadata.get("referenced_message_id"),
            metadata.get("root_id"),
            metadata.get("thread_id"),
            metadata.get("parent_id"),
            (metadata.get("referenced_message") or {}).get("id") if isinstance(metadata.get("referenced_message"), dict) else None,
        ]
        for value in candidates:
            if value is None:
                continue
            found = self._messages_by_id.get(f"{msg.channel}:{value}")
            if found:
                return found
        referenced = metadata.get("referenced_message")
        if isinstance(referenced, dict):
            content = str(referenced.get("content") or "").strip()
            media = [str(p) for p in referenced.get("media", []) if isinstance(p, str) and p.strip()]
            if content or media:
                return {"content": content, "media": media, "metadata": referenced}
        return None

    @staticmethod
    def _state_key(msg: InboundMessage) -> str:
        return f"{msg.channel}:{msg.session_key_override or msg.sender_id}"

    @staticmethod
    def _message_id(msg: InboundMessage) -> str | None:
        value = (msg.metadata or {}).get("message_id")
        return str(value).strip() if value is not None and str(value).strip() else None

    @staticmethod
    def _strip_attachment_markers(content: str) -> str:
        text = ATTACHMENT_RE.sub("", content or "")
        return MEDIA_MARKER_RE.sub("", text).strip()

    @staticmethod
    def _extract_media_paths(msg: InboundMessage) -> list[str]:
        paths: list[str] = []
        for item in msg.media or []:
            if isinstance(item, str) and item.strip():
                paths.append(item.strip())
        for match in ATTACHMENT_RE.findall(msg.content or ""):
            candidate = match.strip()
            if " - " not in candidate:
                paths.append(candidate)
        for match in MEDIA_MARKER_RE.findall(msg.content or ""):
            candidate = match.strip()
            if "/" in candidate or candidate.startswith("."):
                paths.append(candidate)
        for item in (msg.metadata or {}).get("attachments", []) or []:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                paths.append(item["path"].strip())
        return list(dict.fromkeys(p for p in paths if p))

    @staticmethod
    def _extract_outbound_media(text: str, *, base_dir: Path | None = None) -> tuple[str, list[str], dict[str, str]]:
        media: list[str] = []
        modes: dict[str, str] = {}

        def replace(match: re.Match[str]) -> str:
            marker = match.group(1).lower()
            raw_path = match.group(2).strip()
            if " - " in raw_path:
                return match.group(0)
            path = WebConfigSmartChannelBridge._resolve_outbound_media_path(raw_path, base_dir)
            media.append(path)
            if marker == "voice":
                modes[path] = "voice"
            elif marker == "audio-file":
                modes[path] = "file"
            elif marker in {"audio", "media"}:
                modes[path] = "audio"
            elif marker in {"image", "photo"}:
                modes[path] = "image"
            elif marker == "video":
                modes[path] = "video"
            else:
                modes[path] = "file"
            return ""

        cleaned = OUTBOUND_MEDIA_RE.sub(replace, text or "")
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        media = list(dict.fromkeys(p for p in media if p))
        return cleaned, media, {path: modes[path] for path in media if path in modes}

    @staticmethod
    def _resolve_outbound_media_path(path: str, base_dir: Path | None = None) -> str:
        candidate = Path(path).expanduser()
        if candidate.is_absolute():
            if candidate.exists():
                return str(candidate)
            found = WebConfigSmartChannelBridge._find_existing_by_name(candidate.name, base_dir)
            return str(found) if found is not None else str(candidate)
        roots = []
        if base_dir is not None:
            roots.append(base_dir)
        roots.append(Path.cwd())
        for root in roots:
            resolved = (root / candidate).resolve()
            if resolved.exists():
                return str(resolved)
        if base_dir is not None:
            return str((base_dir / candidate).resolve())
        return str(candidate)

    @staticmethod
    def _find_existing_by_name(filename: str, base_dir: Path | None = None) -> Path | None:
        if not filename:
            return None
        roots = []
        if base_dir is not None:
            roots.append(base_dir)
        roots.append(Path.cwd())
        for root in roots:
            try:
                root = root.resolve()
                direct = root / filename
                if direct.is_file():
                    return direct
                for child in root.rglob(filename):
                    if child.is_file():
                        return child.resolve()
            except Exception:
                continue
        return None

    @staticmethod
    def _filter_existing_outbound_media(
        media: list[str],
        modes: dict[str, str],
    ) -> tuple[list[str], dict[str, str], list[str]]:
        existing: list[str] = []
        missing: list[str] = []
        for path in media:
            if Path(path).expanduser().is_file():
                existing.append(path)
            else:
                missing.append(path)
        return existing, {path: modes[path] for path in existing if path in modes}, missing

    @staticmethod
    def _is_unmentioned_group_message(msg: InboundMessage) -> bool:
        metadata = msg.metadata or {}
        chat_type = str(metadata.get("chat_type") or "").lower()
        if chat_type != "group":
            return False
        if bool(metadata.get("mentions_bot")) or bool(metadata.get("was_mentioned")):
            return False
        return msg.channel in {"feishu"}

    @staticmethod
    def _media_item(msg: InboundMessage, paths: list[str]) -> dict[str, Any]:
        return {"content": msg.content, "media": paths, "metadata": dict(msg.metadata or {})}

    def _merge_pending_media(self, existing: list[dict[str, Any]], msg: InboundMessage, paths: list[str]) -> list[dict[str, Any]]:
        return [*existing, self._media_item(msg, paths)]

    @staticmethod
    def _combine_instruction(first: str, second: str) -> str:
        first = first.strip()
        second = second.strip()
        if first and second and first != second:
            return f"{first}\n{second}"
        return first or second

    @staticmethod
    def _looks_like_media_instruction(text: str) -> bool:
        lowered = text.lower()
        return any(word in lowered for word in MEDIA_WORDS) and any(word in lowered for word in ACTION_WORDS)

    def _build_prompt(
        self,
        instruction: str,
        *,
        media_items: list[dict[str, Any]] | None = None,
        quoted: dict[str, Any] | None = None,
    ) -> str:
        parts = [instruction.strip()]
        items = list(media_items or [])
        if quoted is not None:
            items.append(quoted)
            parts.append("\n用户通过引用指定了以下待处理内容：")
        elif items:
            parts.append("\n用户提供了以下待处理文件/多媒体内容：")
        for idx, item in enumerate(items, start=1):
            content = self._strip_attachment_markers(str(item.get("content") or "")).strip()
            media = [str(p) for p in item.get("media", []) if isinstance(p, str) and p.strip()]
            lines = [f"{idx}. " + (content if content else "无附加文字")]
            lines.extend(f"   - [attachment: {path}]" for path in media)
            parts.append("\n".join(lines))
        return "\n".join(p for p in parts if p).strip()

    def _ensure_social_output_dir(self, msg: InboundMessage) -> Path:
        output_dir = (
            Path(self._cwd)
            / ".openharness"
            / "social_outputs"
            / self._safe_path_part(msg.channel)
            / self._safe_path_part(msg.session_key_override or msg.sender_id or msg.chat_id)
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir.resolve()

    def _with_social_output_instructions(self, content: str, output_dir: Path) -> str:
        skill_lines: list[str] = []
        try:
            from openharness.skills import load_skill_registry

            for skill in load_skill_registry(self._cwd).list_skills():
                command_name = skill.command_name or skill.name
                base = f" at {skill.base_dir}" if skill.base_dir else ""
                skill_lines.append(f"- {command_name}{base}: {skill.description}")
        except Exception:
            logger.exception("Failed to load skills for social prompt")

        skill_text = ""
        if skill_lines:
            skill_text = "\n\n可用 skills：\n" + "\n".join(skill_lines[:20])

        return (
            f"{content.rstrip()}{skill_text}{SOCIAL_OUTPUT_INSTRUCTIONS}\n"
            f"本次消息的社交输出目录是：{output_dir}\n"
            "如果调用工具或 MCP 生成音频、图片、压缩包、文档等文件，请把 output/output_path/path/目录参数设置到这个目录下。"
        )

    def _log_tool_started(self, msg: InboundMessage, event: ToolExecutionStarted, output_dir: Path) -> None:
        logger.info(
            "Social tool call start channel=%s chat_id=%s sender=%s tool=%s output_dir=%s input=%s",
            msg.channel,
            msg.chat_id,
            msg.sender_id,
            event.tool_name,
            output_dir,
            self._compact_json(event.tool_input),
        )
        self._social_debug(
            "tool_call_start",
            msg,
            tool=event.tool_name,
            output_dir=str(output_dir),
            input=event.tool_input,
        )

    def _log_tool_completed(self, msg: InboundMessage, event: ToolExecutionCompleted) -> None:
        logger.info(
            "Social tool call done channel=%s chat_id=%s sender=%s tool=%s is_error=%s output=%s metadata=%s",
            msg.channel,
            msg.chat_id,
            msg.sender_id,
            event.tool_name,
            event.is_error,
            self._truncate_log_text(event.output),
            self._compact_json(event.metadata or {}),
        )
        self._social_debug(
            "tool_call_done",
            msg,
            tool=event.tool_name,
            is_error=event.is_error,
            output=self._truncate_log_text(event.output, limit=5000),
            metadata=event.metadata or {},
        )

    def _social_debug(self, event: str, msg: InboundMessage, **fields: Any) -> None:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "event": event,
            "channel": msg.channel,
            "chat_id": msg.chat_id,
            "sender_id": msg.sender_id,
            **fields,
        }
        try:
            log_dir = Path(self._cwd) / ".openharness"
            log_dir.mkdir(parents=True, exist_ok=True)
            with (log_dir / "social_debug.log").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        except Exception:
            logger.exception("Failed to write social debug log")

    @staticmethod
    def _compact_json(value: Any, *, limit: int = 1200) -> str:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
        except Exception:
            text = str(value)
        return WebConfigSmartChannelBridge._truncate_log_text(text, limit=limit)

    @staticmethod
    def _truncate_log_text(text: str, *, limit: int = 1200) -> str:
        text = str(text or "").replace("\n", "\\n")
        if len(text) <= limit:
            return text
        return text[:limit] + "...[truncated]"

    @staticmethod
    def _safe_path_part(value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
        return cleaned.strip("._")[:80] or "unknown"


class WebConfigChannelRuntime:
    """Own the optional long-running channel listeners for web_config."""

    def __init__(self, *, cwd: str | Path | None = None) -> None:
        self._cwd = str(Path(cwd or Path.cwd()).resolve())
        self._bus: MessageBus | None = None
        self._manager: ChannelManager | None = None
        self._manager_task: asyncio.Task | None = None
        self._bridge: WebConfigSmartChannelBridge | None = None
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
        self._patch_channels_for_web_media_capture()
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
                if perm_mode == PermissionMode.DEFAULT:
                    logger.info(
                        "ChannelBridge: social channel agent %s uses full_auto permissions because chat channels cannot answer interactive confirmations",
                        agent_id,
                    )
                    perm_mode = PermissionMode.FULL_AUTO

                permission_settings = PermissionSettings(
                    mode=perm_mode,
                    allowed_tools=list(settings.permission.allowed_tools),
                    denied_tools=list(settings.permission.denied_tools),
                    path_rules=list(settings.permission.path_rules),
                    denied_commands=list(settings.permission.denied_commands),
                )

                engine = QueryEngine(
                    api_client=api_client,
                    tool_registry=tool_registry,
                    permission_checker=PermissionChecker(permission_settings),
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

            self._bridge = WebConfigSmartChannelBridge(
                engine=self._bundle.engine,
                bus=self._bus,
                cwd=self._cwd,
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

    def _patch_channels_for_web_media_capture(self) -> None:
        """Let web_config capture unmentioned Feishu media while bridge filters text."""
        if self._manager is None:
            return
        feishu = self._manager.channels.get("feishu")
        if feishu is None:
            return
        config = getattr(feishu, "config", None)
        if config is None or not hasattr(config, "group_policy"):
            return
        original_policy = getattr(config, "group_policy", None)
        if original_policy != "open":
            try:
                setattr(config, "_web_config_original_group_policy", original_policy)
            except Exception:
                pass
            setattr(config, "group_policy", "open")
            logger.info(
                "WebConfigChannelRuntime enabled Feishu media passthrough for group_policy=%s",
                original_policy,
            )

    @property
    def running_channels(self) -> list[str]:
        if self._manager is None:
            return []
        return self._manager.enabled_channels
