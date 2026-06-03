"""OpenHarness channel runtime used by the web config app."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

from openharness.channels.bus.events import InboundMessage, OutboundMessage
from openharness.channels.bus.queue import MessageBus
from openharness.channels.impl.base import allocate_social_file, resolve_social_bot_dir
from openharness.channels.impl.manager import ChannelManager
from openharness.config.schema import Config
from openharness.engine.stream_events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    CompactProgressEvent,
    ErrorEvent,
    StatusEvent,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from openharness.engine.query_engine import QueryEngine
from openharness.tools.base import ToolRegistry
from openharness.tools.skill_permission import infer_skill_from_tool_call, skill_is_approved
from openharness.ui.coordinator_drain import (
    format_completed_task_notifications,
    pending_async_agent_entries,
    wait_for_completed_async_agent_entries,
)
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
SOCIAL_ASYNC_AGENT_WAIT_SECONDS = 300.0
RECENT_MEDIA_TTL_SECONDS = 30 * 60
FILE_EXPECTATION_RE = re.compile(r"\[(?:期待文件|等待文件)(?:\s*[:：]\s*(.+?))?\]|\[无需文件\]", re.IGNORECASE)
SOCIAL_OUTPUT_INSTRUCTIONS = (
    "\n\n[社交平台输出约定]\n"
    "生成文件必须保存到本消息指定的输出目录。\n"
    "发送文件写：[attachment: path]；图片：[image: path]。\n"
    "音频语音：[voice: path]；音频文件：[audio-file: path]。\n"
    "能执行就直接执行，确实缺少必要信息时才简短询问"
    # "如果已读取某个 skill，请按该 skill 的 Usage 运行脚本或命令，不要用图像描述/生成工具替代确定性的本地文件处理。\n"
    # "只有确认文件真实存在后才能写发送标记。\n"
    # "不要自我介绍，不要复述这些系统规则；能执行就直接执行，确实缺少必要信息时才简短询问。"
)
FILE_EXPECTATION_INSTRUCTIONS = (
    "\n\n[文件期待标记]\n"
    "回复末尾可加：[期待文件] / [期待文件:描述] / [无需文件]（可选，系统会自动移除）。"
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
        self._active_tasks: set[asyncio.Task] = set()

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
        for task in list(self._active_tasks):
            task.cancel()
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks, return_exceptions=True)
        logger.info("WebConfigSmartChannelBridge stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                msg = await asyncio.wait_for(self._bus.consume_inbound(), timeout=1.0)
                task = asyncio.create_task(self._handle(msg), name=f"social-message-{msg.channel}")
                self._active_tasks.add(task)
                task.add_done_callback(self._active_tasks.discard)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("WebConfigSmartChannelBridge: unhandled error")

    async def _handle(self, msg: InboundMessage) -> None:
        key = self._state_key(msg)
        state = self._states.setdefault(key, self._new_state())

        media_paths = self._extract_media_paths(msg)
        if media_paths:
            media_paths = self._normalize_inbound_media_paths(msg, media_paths)
        self._remember_message(msg, media_paths=media_paths)
        if media_paths:
            state["recent_media"] = self._merge_recent_media(state.get("recent_media", []), msg, media_paths)
            state["msg_counter"] += 1
            state["conversation_files"].append({
                "msg_index": state["msg_counter"],
                "timestamp": time.time(),
                "source": "user",
                "media": list(media_paths),
                "content": msg.content,
            })
        text = self._strip_attachment_markers(msg.content).strip()
        quoted = self._resolve_quoted_message(msg)
        instruction = text if text and text != "[empty message]" else ""
        pending_media = list(state.get("pending_media") or [])

        pending_permission = state.get("pending_permission")
        if isinstance(pending_permission, dict):
            future = pending_permission.get("future")
            if isinstance(future, asyncio.Future) and not future.done():
                response = self._permission_response(instruction)
                if response is None:
                    await self._publish_notice(msg, "请先回复“允许”或“拒绝”，以决定是否执行刚才的工具调用。")
                    return
                future.set_result(response)
                state["pending_permission"] = None
                self._social_debug(
                    "permission_response",
                    msg,
                    tool=pending_permission.get("tool"),
                    allowed=response,
                )
                await self._publish_notice(msg, "已允许，继续执行。" if response else "已拒绝，本次工具调用不会执行。")
                return

        if self._is_unmentioned_group_message(msg) and not media_paths and not pending_media:
            logger.info(
                "Ignoring unmentioned group text after web media capture passthrough: %s/%s",
                msg.channel,
                msg.chat_id,
            )
            return

        if instruction and self._is_continue_request(instruction):
            await self._process_now(msg, instruction, state=state)
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
            state["active_media"] = [*pending_media, current]
            prompt = self._build_prompt(final_instruction, media_items=[*pending_media, current])
            await self._clear_state_and_process(state, msg, prompt)
            return

        if media_paths and not instruction:
            # 检查 LLM 是否期待文件
            expecting = state.get("expecting_file", {})
            if expecting.get("active"):
                current = self._media_item(msg, media_paths)
                state["active_media"] = [current]
                prompt = self._build_prompt_with_timeline(state)
                await self._clear_state_and_process(state, msg, prompt)
                return

            pending_instruction = str(state.get("pending_instruction") or "").strip()
            if pending_instruction:
                pending_media = list(state.get("pending_media") or [])
                current = self._media_item(msg, media_paths)
                state["active_media"] = [*pending_media, current]
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
            state["active_media"] = pending_media
            prompt = self._build_prompt(final_instruction, media_items=pending_media)
            await self._clear_state_and_process(state, msg, prompt)
            return

        active_media = self._recent_media_items(state.get("active_media", []))
        if active_media and instruction:
            pending_instruction = str(state.get("pending_instruction") or "").strip()
            final_instruction = self._combine_instruction(pending_instruction, instruction)
            prompt = self._build_prompt(final_instruction, media_items=active_media)
            await self._clear_state_and_process(state, msg, prompt)
            return

        recent_media = self._recent_media_items(state.get("recent_media", []))
        if recent_media and instruction:
            pending_instruction = str(state.get("pending_instruction") or "").strip()
            final_instruction = self._combine_instruction(pending_instruction, instruction)
            prompt = self._build_prompt(final_instruction, recent_media_items=recent_media)
            await self._clear_state_and_process(state, msg, prompt)
            return

        await self._process_now(msg, msg.content, state=state)

    @staticmethod
    def _new_state() -> dict[str, Any]:
        return {
            "conversation_files": [],
            "msg_counter": 0,
            "pending_media": [],
            "pending_instruction": "",
            "recent_media": [],
            "active_media": [],
            "expecting_file": {"active": False, "description": ""},
            "last_output_snapshot": set(),
        }

    async def _clear_state_and_process(self, state: dict[str, Any], msg: InboundMessage, prompt: str) -> None:
        self._cancel_notice(state)
        state["pending_media"] = []
        state["pending_instruction"] = ""
        await self._process_now(msg, prompt, state=state)

    async def _process_now(self, msg: InboundMessage, content: str, *, state: dict[str, Any] | None = None) -> None:
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
        active_skills: set[str] = set()
        self._configure_engine_permissions_for_message(engine, msg, active_skills)
        tool_call_count = 0
        tool_names: list[str] = []
        tool_input_queue: dict[str, list[dict[str, Any]]] = {}
        tool_errors: list[dict[str, Any]] = []
        full_prompt = self._with_social_output_instructions(content, output_dir)
        input_media_paths = self._resolve_media_paths_from_text(content)
        continuation_requested = self._is_continue_request(content)
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
            if continuation_requested and engine.has_pending_continuation():
                self._social_debug("continue_pending_start", msg, output_dir=str(output_dir))
                stream = engine.continue_pending().__aiter__()
            else:
                # Chat channels keep media continuity in the bridge state. Keep
                # model history short so local 8k-context providers do not carry
                # old tool results into unrelated social messages.
                engine.clear()
                self._social_debug("engine_history_cleared", msg, reason="fresh_social_message")
                stream = engine.submit_message(full_prompt).__aiter__()
            auto_continued_after_empty = False
            async_drain_count = 0
            while True:
                try:
                    event = await asyncio.wait_for(
                        stream.__anext__(),
                        timeout=self._engine_event_timeout_seconds(),
                    )
                except StopAsyncIteration:
                    notification_payload = await self._drain_social_async_agents(
                        engine,
                        msg,
                        drain_index=async_drain_count,
                    )
                    if notification_payload and async_drain_count < 3:
                        async_drain_count += 1
                        self._social_debug(
                            "async_agent_notification_submit",
                            msg,
                            drain_index=async_drain_count,
                            notification=self._truncate_log_text(notification_payload, limit=3000),
                        )
                        stream = engine.submit_message(notification_payload).__aiter__()
                        continue
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
                            input_media=input_media_paths,
                        )
                        outbound_media, media_modes, missing_media = self._filter_existing_outbound_media(
                            outbound_media,
                            media_modes,
                        )
                        outbound_media, media_modes = self._normalize_social_media_paths(msg, outbound_media, media_modes)
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
                    tool_input_queue.setdefault(event.tool_name, []).append(event.tool_input)
                    skill_name = self._skill_name_from_tool_call(event)
                    if skill_name:
                        active_skills.add(skill_name)
                    self._log_tool_started(msg, event, output_dir)
                elif isinstance(event, ToolExecutionCompleted):
                    self._log_tool_completed(msg, event)
                    started_input = None
                    queued_inputs = tool_input_queue.get(event.tool_name)
                    if queued_inputs:
                        started_input = queued_inputs.pop(0)
                    if event.tool_name == "send_message" and isinstance(started_input, dict):
                        forwarded = str(started_input.get("message") or "").strip()
                        if forwarded and OUTBOUND_MEDIA_RE.search(forwarded):
                            reply_parts.append(f"\n{forwarded}\n")
                            self._social_debug(
                                "captured_send_message_media_marker",
                                msg,
                                message=self._truncate_log_text(forwarded, limit=1000),
                                tool_error=event.is_error,
                            )
                    if event.is_error:
                        tool_errors.append({
                            "tool": event.tool_name,
                            "output": self._truncate_log_text(event.output, limit=1200),
                            "metadata": event.metadata or {},
                        })
                elif isinstance(event, ErrorEvent):
                    message = event.message.strip() or "Agent returned an error without details."
                    self._social_debug(
                        "engine_error",
                        msg,
                        message=self._truncate_log_text(message, limit=3000),
                        recoverable=event.recoverable,
                    )
                    if "empty assistant message" in message.lower() and tool_names:
                        if not auto_continued_after_empty and engine.has_pending_continuation():
                            auto_continued_after_empty = True
                            self._social_debug(
                                "auto_continue_pending_after_empty",
                                msg,
                                tool_names=tool_names,
                                output_dir=str(output_dir),
                            )
                            stream = engine.continue_pending(max_turns=3).__aiter__()
                            continue
                        else:
                            reply_parts.append(
                                "任务执行中断：模型在工具调用后返回了空消息。"
                                "请重试一次，或让我继续执行刚才的工具结果。"
                            )
                    else:
                        reply_parts.append(f"任务执行出错：{message}")
                elif isinstance(event, StatusEvent):
                    self._social_debug(
                        "engine_status",
                        msg,
                        message=self._truncate_log_text(event.message, limit=1000),
                    )
                elif isinstance(event, CompactProgressEvent):
                    self._social_debug(
                        "engine_compact_progress",
                        msg,
                        phase=event.phase,
                        trigger=event.trigger,
                        message=self._truncate_log_text(event.message or "", limit=1000),
                    )
        except Exception:
            logger.exception("Channel engine error for %s/%s", msg.channel, msg.chat_id)
            reply_parts = ["[Error: failed to process your message]"]

        reply_text = "".join(reply_parts).strip()

        # 解析并移除文件期待标记
        if state is not None:
            expecting_file, cleaned_reply = self._parse_file_expectation_marker(reply_text)
            state["expecting_file"] = expecting_file
            if cleaned_reply != reply_text:
                reply_text = cleaned_reply
                reply_parts = [reply_text]

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
        outbound_text, outbound_media, media_modes = self._extract_outbound_media(
            reply_text,
            base_dir=Path(self._cwd),
            input_media=input_media_paths,
        )
        outbound_media, media_modes, missing_media = self._filter_existing_outbound_media(outbound_media, media_modes)
        outbound_media, media_modes = self._normalize_social_media_paths(msg, outbound_media, media_modes)
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
                        input_media=input_media_paths,
                    )
                    outbound_media, media_modes, missing_media = self._filter_existing_outbound_media(
                        outbound_media,
                        media_modes,
                    )
                    outbound_media, media_modes = self._normalize_social_media_paths(msg, outbound_media, media_modes)
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
                if tool_names and set(tool_names).issubset({"skill"}):
                    outbound_text = (
                        "任务还没有真正执行：模型只读取了 skill 说明，但没有继续运行对应脚本。"
                        "请回复“继续”，我会接着执行。"
                    )
                else:
                    outbound_text = "任务没有返回可发送的内容。请稍后重试，或补充更明确的处理要求。"

        self._append_assistant_session_message(msg, reply_text or outbound_text, agent_id)

        # 记录 LLM 生成的输出文件到时间线
        if state is not None:
            output_files = self._scan_new_files_in_output_dir(output_dir, state.get("last_output_snapshot", set()))
            if output_files:
                state["msg_counter"] += 1
                state["conversation_files"].append({
                    "msg_index": state["msg_counter"],
                    "timestamp": time.time(),
                    "source": "assistant",
                    "media": output_files,
                    "content": (reply_text or outbound_text)[:200],
                })
                state["last_output_snapshot"] = set(output_files) | state.get("last_output_snapshot", set())

        await self._publish_reply(msg, outbound_text, media=outbound_media, media_modes=media_modes)

    async def _drain_social_async_agents(
        self,
        engine: QueryEngine,
        msg: InboundMessage,
        *,
        drain_index: int,
    ) -> str:
        pending = pending_async_agent_entries(engine.tool_metadata)
        if not pending:
            return ""
        if drain_index >= 3:
            self._social_debug(
                "async_agent_drain_limit",
                msg,
                pending=len(pending),
            )
            return ""
        self._social_debug(
            "async_agent_wait_start",
            msg,
            pending=len(pending),
            timeout_seconds=SOCIAL_ASYNC_AGENT_WAIT_SECONDS,
        )
        try:
            completed = await asyncio.wait_for(
                wait_for_completed_async_agent_entries(engine.tool_metadata),
                timeout=SOCIAL_ASYNC_AGENT_WAIT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Social async agent wait timed out channel=%s chat_id=%s sender=%s pending=%s",
                msg.channel,
                msg.chat_id,
                msg.sender_id,
                len(pending),
            )
            self._social_debug(
                "async_agent_wait_timeout",
                msg,
                pending=len(pending),
                timeout_seconds=SOCIAL_ASYNC_AGENT_WAIT_SECONDS,
            )
            return ""
        notification_payload = format_completed_task_notifications(completed)
        self._social_debug(
            "async_agent_wait_complete",
            msg,
            completed=len(completed),
            notification=self._truncate_log_text(notification_payload, limit=3000),
        )
        return notification_payload

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

    def _normalize_inbound_media_paths(self, msg: InboundMessage, media: list[str]) -> list[str]:
        normalized: list[str] = []
        root = resolve_social_bot_dir(msg.channel).resolve()
        for raw_path in media:
            path = Path(self._expand_path_alias(raw_path)).expanduser().resolve()
            if self._is_short_social_path(path, root):
                normalized.append(str(path))
                continue
            try:
                target = allocate_social_file(msg.channel, path.name, default_ext=path.suffix or ".dat").resolve()
                if path != target:
                    shutil.copy2(path, target)
                normalized.append(str(target))
            except Exception:
                logger.exception("Failed to normalize inbound social media path: %s", path)
                normalized.append(str(path))
        return normalized

    def _normalize_social_media_paths(
        self,
        msg: InboundMessage,
        media: list[str],
        media_modes: dict[str, str],
    ) -> tuple[list[str], dict[str, str]]:
        normalized: list[str] = []
        normalized_modes: dict[str, str] = {}
        root = resolve_social_bot_dir(msg.channel).resolve()
        for raw_path in media:
            path = Path(self._expand_path_alias(raw_path)).expanduser().resolve()
            target = path
            if not self._is_short_social_path(path, root):
                try:
                    target = allocate_social_file(msg.channel, path.name, default_ext=path.suffix or ".dat").resolve()
                    if path != target:
                        shutil.copy2(path, target)
                except Exception:
                    logger.exception("Failed to normalize social media path: %s", path)
                    target = path
            text_target = str(target)
            normalized.append(text_target)
            mode = media_modes.get(raw_path) or media_modes.get(str(path))
            if mode:
                normalized_modes[text_target] = mode
        return normalized, normalized_modes

    @staticmethod
    def _is_short_social_path(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
        except ValueError:
            return False
        return re.fullmatch(r"\d{1,3}(?:\.[A-Za-z0-9]{1,12})?", path.name) is not None

    def _configure_engine_permissions_for_message(
        self,
        engine: QueryEngine,
        msg: InboundMessage,
        active_skills: set[str] | None = None,
    ) -> None:
        try:
            from openharness.config.settings import PermissionSettings, load_settings
            from openharness.permissions.checker import PermissionChecker
            from openharness.permissions.modes import PermissionMode

            settings = load_settings()
            mode = settings.permission.mode
            auto_approve = bool(getattr(settings.social_platforms, "social_auto_approve_tools", False))
            if auto_approve and mode == PermissionMode.DEFAULT:
                mode = PermissionMode.FULL_AUTO
            permission_settings = PermissionSettings(
                mode=mode,
                allowed_tools=list(settings.permission.allowed_tools),
                denied_tools=list(settings.permission.denied_tools),
                path_rules=list(settings.permission.path_rules),
                denied_commands=list(settings.permission.denied_commands),
            )
            engine.set_permission_checker(PermissionChecker(permission_settings))
            engine.set_permission_prompt(None if auto_approve else self._make_permission_prompt(engine, msg, active_skills))
        except Exception:
            logger.exception("Failed to configure social engine permissions for message")

    def _make_permission_prompt(
        self,
        engine: QueryEngine,
        msg: InboundMessage,
        active_skills: set[str] | None = None,
    ):
        async def ask(tool_name: str, reason: str, tool_input: dict[str, object] | None = None) -> bool:
            key = self._state_key(msg)
            state = self._states.setdefault(key, self._new_state())
            if tool_name == "send_message" and isinstance(tool_input, dict):
                message = str(tool_input.get("message") or "")
                if OUTBOUND_MEDIA_RE.search(message):
                    self._social_debug(
                        "permission_auto_approved_send_message_media_marker",
                        msg,
                        tool=tool_name,
                        message=self._truncate_log_text(message, limit=1000),
                    )
                    return True
            skill_name = self._permission_skill_from_tool_call(engine, state, tool_name, tool_input, active_skills)
            if skill_name and self._skill_config_auto_approved(skill_name):
                self._remember_approved_skill(engine, state, skill_name)
                self._social_debug(
                    "permission_auto_approved_by_skill_config",
                    msg,
                    tool=tool_name,
                    skill=skill_name,
                    active_skills=sorted(active_skills or []),
                    reason=self._truncate_log_text(reason, limit=1000),
                )
                return True
            if skill_is_approved(skill_name, engine.tool_metadata):
                self._social_debug(
                    "permission_auto_approved_by_skill",
                    msg,
                    tool=tool_name,
                    skill=skill_name,
                    active_skills=sorted(active_skills or []),
                    reason=self._truncate_log_text(reason, limit=1000),
                )
                return True
            future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
            state["pending_permission"] = {
                "future": future,
                "tool": tool_name,
                "skill": skill_name,
                "reason": reason,
                "created_at": time.time(),
            }
            self._social_debug(
                "permission_request",
                msg,
                tool=tool_name,
                skill=skill_name,
                reason=self._truncate_log_text(reason, limit=1000),
            )
            target = f"skill `{skill_name}`" if skill_name else f"工具 `{tool_name}`"
            await self._publish_reply(
                msg,
                f"{target} 需要执行会修改文件或调用外部服务的操作。\n"
                "回复“允许”继续执行，或回复“拒绝”取消。\n\n"
                f"原因：{reason}",
            )
            try:
                allowed = await asyncio.wait_for(future, timeout=self._permission_response_timeout_seconds())
                if allowed and skill_name:
                    self._remember_approved_skill(engine, state, skill_name)
                if not allowed:
                    engine.tool_metadata["last_permission_denied"] = (
                        f"User denied permission for skill {skill_name}"
                        if skill_name
                        else f"User denied permission for tool {tool_name}"
                    )
                return allowed
            except asyncio.TimeoutError:
                if not future.done():
                    future.cancel()
                if state.get("pending_permission", {}).get("future") is future:
                    state["pending_permission"] = None
                self._social_debug("permission_timeout", msg, tool=tool_name)
                await self._publish_reply(msg, f"等待授权超时，已取消 {target}。")
                return False

        return ask

    def _permission_skill_from_tool_call(
        self,
        engine: QueryEngine,
        state: dict[str, Any],
        tool_name: str,
        tool_input: dict[str, object] | None,
        active_skills: set[str] | None,
    ) -> str | None:
        skill_name = infer_skill_from_tool_call(tool_name, tool_input, self._cwd, engine.tool_metadata)
        if skill_name:
            return skill_name
        if active_skills:
            skill_execution_tools = {"bash", "task_create", "task_output", "task_get", "task_list"}
            if len(active_skills) == 1 and tool_name in skill_execution_tools:
                return next(iter(active_skills))
        approved_state = state.get("approved_social_skills")
        if isinstance(approved_state, list) and len(approved_state) == 1 and tool_name in {"bash", "task_create"}:
            return str(approved_state[0]).strip() or None
        return None

    @staticmethod
    def _remember_approved_skill(engine: QueryEngine, state: dict[str, Any], skill_name: str) -> None:
        normalized = skill_name.strip()
        if not normalized:
            return
        for target in (engine.tool_metadata, state):
            current = target.get("approved_social_skills")
            values = [str(item).strip() for item in current or [] if str(item).strip()] if isinstance(current, list) else []
            if not any(item.lower() == normalized.lower() for item in values):
                values.append(normalized)
            target["approved_social_skills"] = values[-12:]

    def _skill_name_from_tool_call(self, event: ToolExecutionStarted) -> str | None:
        if event.tool_name != "skill":
            return None
        tool_input = event.tool_input if isinstance(event.tool_input, dict) else {}
        for key in ("name", "skill", "skill_name"):
            value = str(tool_input.get(key) or "").strip()
            if value:
                return value
        return None

    def _active_skill_auto_approved(self, active_skills: set[str]) -> bool:
        try:
            from openharness.config.settings import load_settings

            settings = load_settings()
            approved = {
                str(name).strip()
                for name in getattr(settings.skill_management, "auto_approve_skills", []) or []
                if str(name).strip()
            }
            return bool(active_skills.intersection(approved))
        except Exception:
            logger.exception("Failed to check skill auto-approval setting")
            return False

    @staticmethod
    def _skill_config_auto_approved(skill_name: str) -> bool:
        try:
            from openharness.config.settings import load_settings

            settings = load_settings()
            normalized = skill_name.strip().lower()
            return any(
                str(name).strip().lower() == normalized
                for name in getattr(settings.skill_management, "auto_approve_skills", []) or []
            )
        except Exception:
            logger.exception("Failed to check skill auto-approval setting")
            return False

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
                elif isinstance(event, ErrorEvent):
                    message = event.message.strip() or "Diagnostic agent returned an error without details."
                    self._social_debug(
                        "diagnostic_engine_error",
                        msg,
                        message=self._truncate_log_text(message, limit=3000),
                        recoverable=event.recoverable,
                    )
                    reply_parts.append(f"诊断执行出错：{message}")
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

    @staticmethod
    def _permission_response_timeout_seconds() -> float:
        raw = os.environ.get("OPENHARNESS_SOCIAL_PERMISSION_TIMEOUT_SECONDS", "").strip()
        if not raw:
            return 300.0
        try:
            return max(30.0, float(raw))
        except ValueError:
            logger.warning("Invalid OPENHARNESS_SOCIAL_PERMISSION_TIMEOUT_SECONDS=%r", raw)
            return 300.0

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

    def _remember_message(self, msg: InboundMessage, *, media_paths: list[str] | None = None) -> None:
        message_id = self._message_id(msg)
        if not message_id:
            return
        self._messages_by_id[f"{msg.channel}:{message_id}"] = {
            "content": msg.content,
            "media": list(media_paths if media_paths is not None else self._extract_media_paths(msg)),
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
    def _resolve_media_paths_from_text(text: str) -> set[str]:
        paths: set[str] = set()
        for pattern in (ATTACHMENT_RE, MEDIA_MARKER_RE):
            for match in pattern.findall(text or ""):
                raw_path = match.strip()
                if " - " in raw_path:
                    continue
                try:
                    paths.add(str(Path(WebConfigSmartChannelBridge._expand_path_alias(raw_path)).expanduser().resolve()))
                except Exception:
                    continue
        return paths

    @staticmethod
    def _extract_outbound_media(
        text: str,
        *,
        base_dir: Path | None = None,
        input_media: set[str] | None = None,
    ) -> tuple[str, list[str], dict[str, str]]:
        media: list[str] = []
        modes: dict[str, str] = {}
        input_media = input_media or set()

        def replace(match: re.Match[str]) -> str:
            marker = match.group(1).lower()
            raw_path = match.group(2).strip()
            if " - " in raw_path:
                return match.group(0)
            path = WebConfigSmartChannelBridge._resolve_outbound_media_path(raw_path, base_dir)
            try:
                resolved_path = str(Path(WebConfigSmartChannelBridge._expand_path_alias(path)).expanduser().resolve())
            except Exception:
                resolved_path = path
            if resolved_path in input_media:
                return raw_path
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
        candidate = Path(WebConfigSmartChannelBridge._expand_path_alias(path)).expanduser()
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
    def _path_aliases() -> dict[str, str]:
        try:
            from openharness.config.settings import load_settings
            from openharness.config.paths import get_data_dir

            settings = load_settings()
            aliases = dict(getattr(settings.skill_management, "path_aliases", {}) or {})
        except Exception:
            aliases = {}
        aliases.setdefault("USKILL", "~/.openharness/skills")
        try:
            from openharness.config.paths import get_data_dir

            aliases.setdefault("UDATA", str(get_data_dir()))
        except Exception:
            pass
        aliases.setdefault("UPROJ", str(Path.cwd()))
        aliases.setdefault("UWEB", str((Path.cwd() / ".openharness" / "media" / "web").resolve()))
        aliases.setdefault(
            "SOCIAL",
            os.environ.get("OPENHARNESS_SOCIAL_DIR")
            or os.environ.get("OPENHARNESS_SOCIAL_ROOT")
            or "~/.openharness/social",
        )
        normalized: dict[str, str] = {}
        for raw_name, raw_path in aliases.items():
            name = re.sub(r"[^A-Za-z0-9_]", "", str(raw_name).strip().lstrip("$"))
            value = str(raw_path).strip()
            if name and value:
                normalized[name] = str(Path(value).expanduser().resolve())
        return normalized

    @staticmethod
    def _expand_path_alias(path: str) -> str:
        text = path.strip()
        for name, prefix in WebConfigSmartChannelBridge._path_aliases().items():
            token = f"${name}"
            if text == token:
                return prefix
            if text.startswith(token + "/"):
                return prefix + text[len(token):]
        return text

    @staticmethod
    def _compress_path_alias(path: str | Path) -> str:
        try:
            resolved = str(Path(path).expanduser().resolve())
        except OSError:
            resolved = str(path)
        for name, prefix in sorted(
            WebConfigSmartChannelBridge._path_aliases().items(),
            key=lambda item: len(item[1]),
            reverse=True,
        ):
            if resolved == prefix:
                return f"${name}"
            if resolved.startswith(prefix + os.sep):
                return f"${name}{resolved[len(prefix):]}"
        return str(path)

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
        existing_modes: dict[str, str] = {}
        for path in media:
            resolved = WebConfigSmartChannelBridge._expand_path_alias(path)
            if Path(resolved).expanduser().is_file():
                existing.append(resolved)
                mode = modes.get(path) or modes.get(resolved)
                if mode:
                    existing_modes[resolved] = mode
            else:
                missing.append(path)
        return existing, existing_modes, missing

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
        return {
            "content": msg.content,
            "media": paths,
            "metadata": dict(msg.metadata or {}),
            "timestamp": time.time(),
        }

    def _merge_pending_media(self, existing: list[dict[str, Any]], msg: InboundMessage, paths: list[str]) -> list[dict[str, Any]]:
        return [*existing, self._media_item(msg, paths)]

    def _merge_recent_media(self, existing: list[dict[str, Any]], msg: InboundMessage, paths: list[str]) -> list[dict[str, Any]]:
        merged = [*self._recent_media_items(existing), self._media_item(msg, paths)]
        return merged[-6:]

    @staticmethod
    def _is_continue_request(text: str) -> bool:
        normalized = re.sub(r"\s+", "", text or "").lower()
        return normalized in {
            "继续",
            "继续执行",
            "继续生成",
            "接着来",
            "接着执行",
            "继续吧",
            "goon",
            "continue",
        }

    @staticmethod
    def _permission_response(text: str) -> bool | None:
        normalized = re.sub(r"\s+", "", text or "").lower()
        if normalized in {"允许", "同意", "确认", "可以", "批准", "是", "yes", "y", "ok", "approve", "allow"}:
            return True
        if normalized in {"拒绝", "不同意", "取消", "不允许", "否", "no", "n", "deny", "reject", "cancel"}:
            return False
        return None

    @staticmethod
    def _recent_media_items(items: Any) -> list[dict[str, Any]]:
        now = time.time()
        recent: list[dict[str, Any]] = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            timestamp = float(item.get("timestamp") or 0)
            if timestamp and now - timestamp > RECENT_MEDIA_TTL_SECONDS:
                continue
            media = [str(p) for p in item.get("media", []) if isinstance(p, str) and p.strip()]
            media = [p for p in media if Path(p).expanduser().exists()]
            if media:
                copy = dict(item)
                copy["media"] = media
                recent.append(copy)
        return recent

    @staticmethod
    def _combine_instruction(first: str, second: str) -> str:
        first = first.strip()
        second = second.strip()
        if first and second and first != second:
            return f"{first}\n{second}"
        return first or second

    @staticmethod
    def _parse_file_expectation_marker(text: str) -> tuple[dict[str, Any], str]:
        """解析期待标记，返回 (expecting_file, cleaned_text)。"""
        match = FILE_EXPECTATION_RE.search(text)
        if not match:
            return {"active": False, "description": ""}, text
        full_match = match.group(0)
        description = match.group(1) or match.group(2) or ""
        if "无需" in full_match.lower():
            expecting = {"active": False, "description": ""}
        else:
            expecting = {"active": True, "description": description.strip()}
        cleaned = FILE_EXPECTATION_RE.sub("", text).strip()
        return expecting, cleaned

    def _scan_new_files_in_output_dir(self, output_dir: Path, previous_snapshot: set[str]) -> list[str]:
        """扫描 output_dir 中新增的文件。"""
        try:
            current_files = {str(p) for p in output_dir.rglob("*") if p.is_file()}
        except Exception:
            return []
        new_files = current_files - previous_snapshot
        return sorted(new_files)

    def _build_prompt_with_timeline(self, state: dict[str, Any], *, instruction: str | None = None) -> str:
        """使用文件时间线构建 prompt。"""
        parts = []
        if instruction:
            parts.append(instruction.strip())
        files = state.get("conversation_files", [])
        if files:
            parts.append("\n--- 对话文件记录 ---")
            for item in files:
                source_label = "用户发送" if item["source"] == "user" else "助手生成"
                lines = [f"[消息 {item['msg_index']}] {source_label}："]
                for path in item["media"]:
                    lines.append(f"   - {self._compress_path_alias(path)}")
                parts.append("\n".join(lines))
        return "\n".join(p for p in parts if p).strip()

    def _build_prompt(
        self,
        instruction: str,
        *,
        media_items: list[dict[str, Any]] | None = None,
        recent_media_items: list[dict[str, Any]] | None = None,
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
            lines.extend(f"   - [attachment: {self._compress_path_alias(path)}]" for path in media)
            parts.append("\n".join(lines))
        recent_items = list(recent_media_items or [])
        if recent_items:
            parts.append("\n最近收到的文件/多媒体内容如下；如果与当前请求相关，可以使用它们，否则忽略：")
            for idx, item in enumerate(recent_items, start=1):
                content = self._strip_attachment_markers(str(item.get("content") or "")).strip()
                media = [str(p) for p in item.get("media", []) if isinstance(p, str) and p.strip()]
                lines = [f"{idx}. " + (content if content else "无附加文字")]
                lines.extend(f"   - [attachment: {self._compress_path_alias(path)}]" for path in media)
                parts.append("\n".join(lines))
        return "\n".join(p for p in parts if p).strip()

    def _ensure_social_output_dir(self, msg: InboundMessage) -> Path:
        output_dir = resolve_social_bot_dir(msg.channel)
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir.resolve()

    def _with_social_output_instructions(self, content: str, output_dir: Path) -> str:
        skill_lines: list[str] = []
        try:
            from openharness.skills import load_skill_registry

            user_skill_root = Path(os.path.expanduser("~/.openharness/skills")).resolve()
            for skill in load_skill_registry(self._cwd).list_skills():
                if not skill.base_dir:
                    continue
                try:
                    Path(skill.base_dir).expanduser().resolve().relative_to(user_skill_root)
                except ValueError:
                    continue
                command_name = skill.command_name or skill.name
                description = " ".join((skill.description or "").split())
                if len(description) > 120:
                    description = description[:117].rstrip() + "..."
                skill_lines.append(f"- {command_name} at {self._compress_path_alias(skill.base_dir)}: {description}")
        except Exception:
            logger.exception("Failed to load skills for social prompt")

        skill_text = ""
        if skill_lines:
            skill_text = "\n\n可用 skills：\n" + "\n".join(skill_lines[:8])
        alias_lines = [
            f"- ${name} = {prefix}"
            for name, prefix in sorted(self._path_aliases().items())
            if name in {"USKILL", "UDATA", "UPROJ", "UWEB", "SOCIAL"}
        ]
        #别名LLM不需要知道，因为给LLM的路径本身就已经用别名替换了，LLM只要照样输出就可以
        alias_text = "" #"\n\n可用路径别名：\n" + "\n".join(alias_lines) if alias_lines else ""

        return (
            f"{content.rstrip()}{skill_text}{alias_text}{SOCIAL_OUTPUT_INSTRUCTIONS}{FILE_EXPECTATION_INSTRUCTIONS}\n"
            f"本次消息的社交输出目录是：{self._compress_path_alias(output_dir)}\n"
            "工具参数里的 output/output_path/path 请使用此目录；"
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
                agent_id = assignments.get(channel_name) if isinstance(assignments, dict) else None
                if agent_id is None:
                    try:
                        from openharness.config.paths import get_config_dir

                        agents_path = get_config_dir() / "agents.json"
                        if agents_path.exists():
                            agents_data = json.loads(agents_path.read_text(encoding="utf-8"))
                            agent_id = agents_data.get("active_agent_id")
                    except Exception:
                        logger.exception("ChannelBridge: failed to resolve active web agent for %s", channel_name)
                resolved = str(agent_id or "").strip() or None
                logger.info("ChannelBridge: resolved agent for channel %s = %s", channel_name, resolved)
                return resolved

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

                context_window_tokens = settings.context_window_tokens or settings.memory.context_window_tokens
                auto_compact_threshold_tokens = (
                    settings.auto_compact_threshold_tokens
                    or settings.memory.auto_compact_threshold_tokens
                )
                max_tokens = settings.max_tokens
                if context_window_tokens is None and self._looks_like_local_llm_endpoint(getattr(settings, "base_url", "")):
                    context_window_tokens = 8192
                    auto_compact_threshold_tokens = auto_compact_threshold_tokens or 5600
                    max_tokens = min(max_tokens, 2048)
                    logger.info(
                        "ChannelBridge: inferred local LLM context for social agent %s: context_window=%s threshold=%s max_tokens=%s",
                        agent_id,
                        context_window_tokens,
                        auto_compact_threshold_tokens,
                        max_tokens,
                    )

                api_client = _resolve_api_client_from_settings(settings)

                tool_registry = ToolRegistry()
                for tool in self._bundle.tool_registry.list_tools():
                    if tool.name == "send_message":
                        logger.info("ChannelBridge: skipping send_message tool for social agent %s", agent_id)
                        continue
                    if tool.name == "image_to_text" and not self._vision_tool_configured(settings):
                        logger.info("ChannelBridge: skipping image_to_text for social agent %s because vision is not configured", agent_id)
                        continue
                    if yaml_agent_def is None or yaml_agent_def.tools is None or "*" in yaml_agent_def.tools or tool.name in yaml_agent_def.tools:
                        if yaml_agent_def is None or tool.name not in (yaml_agent_def.disallowed_tools or []):
                            tool_registry.register(tool)

                permission_mode = yaml_agent_def.permission_mode if yaml_agent_def and yaml_agent_def.permission_mode else settings.permission.mode.value
                try:
                    perm_mode = PermissionMode(permission_mode)
                except ValueError:
                    perm_mode = settings.permission.mode
                if perm_mode == PermissionMode.DEFAULT and bool(getattr(settings.social_platforms, "social_auto_approve_tools", False)):
                    logger.info(
                        "ChannelBridge: social channel agent %s uses full_auto permissions because social_auto_approve_tools is enabled",
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
                    max_tokens=max_tokens,
                    context_window_tokens=context_window_tokens,
                    auto_compact_threshold_tokens=auto_compact_threshold_tokens,
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

    @staticmethod
    def _looks_like_local_llm_endpoint(base_url: str | None) -> bool:
        value = str(base_url or "").lower()
        return (
            "127.0.0.1" in value
            or "localhost" in value
            or "0.0.0.0" in value
            or value.startswith("http://192.168.")
            or value.startswith("http://10.")
            or value.startswith("http://172.16.")
            or value.startswith("http://172.17.")
            or value.startswith("http://172.18.")
            or value.startswith("http://172.19.")
            or value.startswith("http://172.2")
            or value.startswith("http://172.30.")
            or value.startswith("http://172.31.")
        )

    @staticmethod
    def _vision_tool_configured(settings: Any) -> bool:
        vision = getattr(settings, "vision", None)
        return bool(
            str(getattr(vision, "model", "") or "").strip()
            and str(getattr(vision, "api_key", "") or "").strip()
        )

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
