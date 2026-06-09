"""Introspection engine - main orchestration logic."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from openharness.introspection.analyzer import SessionAnalyzer
from openharness.introspection.config import IntrospectionConfig
from openharness.introspection.experience_store import ExperienceStore
from openharness.introspection.logging import log_event, sanitize_text, utc_now_iso, write_event
from openharness.introspection.prompts import REFLECTION_PROMPT, TASK_TYPE_CLASSIFICATION_PROMPT
from openharness.introspection.sources import build_session_summary
from openharness.introspection.types import (
    AnalysisResult,
    ExperienceQuery,
    ExperienceRecord,
    IntrospectionSource,
    ReflectionReport,
)

log = logging.getLogger("openharness.introspection.engine")


class IntrospectionEngine:
    """Main introspection engine that orchestrates reflection and experience retrieval."""

    def __init__(
        self,
        cwd: str | Path,
        config: IntrospectionConfig,
        api_client: Any | None = None,
        default_model: str = "claude-sonnet-4-6",
        hook_executor: Any | None = None,
    ) -> None:
        self._cwd = str(Path(cwd).resolve())
        self._config = config
        self._api_client = api_client
        self._default_model = default_model
        self._hook_executor = hook_executor
        self._analyzer = SessionAnalyzer()
        self._store = ExperienceStore(cwd, config)

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    async def reflect_on_session(
        self,
        source: IntrospectionSource,
    ) -> ReflectionReport | None:
        """Run reflection on a completed session.

        This is the main entry point called from SESSION_END hook.
        """
        if not self._config.enabled:
            log.info("Introspection disabled, skipping reflection")
            return None

        if not self._config.is_source_enabled(source.kind):
            log.info("Source kind %s disabled, skipping reflection", source.kind)
            return None

        reflection_id = f"refl_{uuid4().hex[:8]}"
        events_path = self._config.get_events_path(self._cwd)

        log_event(
            log, "INFO", "Starting reflection",
            reflection_id=reflection_id,
            source_id=source.id,
        )
        write_event(
            events_path, "reflection_started",
            reflection_id=reflection_id,
            source_id=source.id,
            source_kind=source.kind,
            summary=f"开始分析 {source.kind} 来源 {source.id}",
        )

        # Check minimum tool calls threshold
        if len(source.tool_events) < self._config.min_tool_calls_for_reflection:
            reason = f"Session has only {len(source.tool_events)} tool calls (min: {self._config.min_tool_calls_for_reflection})"
            log_event(log, "INFO", reason, reflection_id=reflection_id)
            write_event(
                events_path, "reflection_skipped",
                reflection_id=reflection_id,
                source_id=source.id,
                source_kind=source.kind,
                display_text=reason,
            )
            return None

        try:
            # Step 1: Analyze session
            analysis = self._analyzer.analyze(source)
            log_event(
                log, "INFO",
                f"Analysis complete: completion={analysis.completion}, tools={analysis.tool_calls_count}",
                reflection_id=reflection_id,
            )

            # Step 2: Build session summary
            session_summary = build_session_summary(source)

            # Step 3: Generate reflection via LLM (with timeout)
            report = await asyncio.wait_for(
                self._generate_reflection(
                    analysis=analysis,
                    session_summary=session_summary,
                    reflection_id=reflection_id,
                    source=source,
                    events_path=events_path,
                ),
                timeout=self._config.reflection_timeout_seconds,
            )

            if report is None:
                return None

            # Step 4: Save experience candidates
            memory_ids = await self._save_experiences(
                report=report,
                events_path=events_path,
            )

            # Step 5: Write reflection JSON
            await self._write_reflection_json(report)

            # Step 6: Emit completion event
            write_event(
                events_path, "reflection_completed",
                reflection_id=reflection_id,
                source_id=source.id,
                source_kind=source.kind,
                summary=f"反思完成: outcome={report.outcome}, 写入 {len(memory_ids)} 条经验",
                metadata={"memory_ids": memory_ids, "outcome": report.outcome},
            )

            # Step 7: Dispatch POST_SESSION_REFLECT hook
            await self._dispatch_hook(
                "post_session_reflect",
                data={
                    "reflection_id": reflection_id,
                    "source_id": source.id,
                    "source_kind": source.kind,
                    "outcome": report.outcome,
                    "memory_ids": memory_ids,
                    "cwd": self._cwd,
                },
            )

            log_event(
                log, "INFO",
                f"Reflection complete: outcome={report.outcome}, memories={len(memory_ids)}",
                reflection_id=reflection_id,
            )
            return report

        except asyncio.TimeoutError:
            log_event(log, "WARNING", "Reflection timed out", reflection_id=reflection_id)
            write_event(
                events_path, "reflection_timeout",
                reflection_id=reflection_id,
                source_id=source.id,
                source_kind=source.kind,
                display_text="反思超时",
            )
            return None
        except Exception as exc:
            log_event(log, "ERROR", f"Reflection failed: {exc}", reflection_id=reflection_id)
            write_event(
                events_path, "reflection_error",
                reflection_id=reflection_id,
                source_id=source.id,
                source_kind=source.kind,
                display_text=f"反思失败: {sanitize_text(str(exc))}",
            )
            return None

    async def retrieve_experiences(
        self,
        task_text: str,
        task_type: str | None = None,
    ) -> list[ExperienceRecord]:
        """Retrieve relevant experiences for the current task."""
        if not self._config.enabled:
            return []

        if self._config.injection_mode == "off":
            return []

        # Classify task type if not provided
        if task_type is None and self._api_client is not None:
            task_type = await self._classify_task_type(task_text)

        query = ExperienceQuery(
            task_type=task_type,
            min_confidence=self._config.min_confidence,
        )

        experiences = self._store.retrieve_experiences(query)

        events_path = self._config.get_events_path(self._cwd)
        if experiences:
            write_event(
                events_path, "experiences_retrieved",
                summary=f"检索到 {len(experiences)} 条相关经验",
                metadata={"count": len(experiences), "task_type": task_type},
            )
            log.info("Retrieved %d experiences for task type %s", len(experiences), task_type)
            await self._dispatch_hook(
                "experience_retrieved",
                data={
                    "count": len(experiences),
                    "task_type": task_type,
                    "task_text": task_text[:200],
                    "cwd": self._cwd,
                },
            )
        else:
            log.debug("No relevant experiences found for task type %s", task_type)

        return experiences

    def format_experiences_for_prompt(
        self,
        experiences: list[ExperienceRecord],
        task_text: str,
    ) -> str:
        """Format retrieved experiences for injection into system prompt."""
        if not experiences:
            return ""

        from openharness.introspection.prompts import EXPERIENCE_INJECTION_PROMPT

        parts = []
        for i, exp in enumerate(experiences, 1):
            lesson_text = "\n".join(exp.lessons)
            parts.append(
                f"### Experience {i} (confidence: {exp.confidence:.2f})\n"
                f"Type: {exp.task_type}\n"
                f"Outcome: {exp.outcome}\n"
                f"Lesson: {lesson_text}\n"
            )

        experiences_text = "\n".join(parts)
        return EXPERIENCE_INJECTION_PROMPT.format(
            experiences=experiences_text,
            task_text=task_text[:500],
        )

    async def _generate_reflection(
        self,
        analysis: AnalysisResult,
        session_summary: str,
        reflection_id: str,
        source: IntrospectionSource,
        events_path: Path,
    ) -> ReflectionReport | None:
        """Use LLM to generate a reflection report."""
        if self._api_client is None:
            log.warning("No API client available, skipping LLM reflection")
            return self._fallback_reflection(analysis, session_summary, reflection_id, source)

        prompt = REFLECTION_PROMPT.format(
            session_summary=session_summary[:3000],
            analysis=json.dumps(analysis.to_dict(), indent=2, ensure_ascii=False),
        )

        model = self._config.reflection_model or self._default_model

        try:
            from openharness.api.client import ApiMessageRequest
            from openharness.engine.messages import ConversationMessage

            request = ApiMessageRequest(
                model=model,
                messages=[ConversationMessage.from_user_text(prompt)],
                system_prompt="You are an introspection engine. Output ONLY valid JSON.",
                max_tokens=2048,
            )

            # Collect full response
            text_chunks: list[str] = []
            async for event in self._api_client.stream_message(request):
                text_chunks.append(event.text)

            response_text = "".join(text_chunks)
            log_event(
                log, "DEBUG",
                f"LLM response preview: {sanitize_text(response_text, max_length=200)}",
                reflection_id=reflection_id,
            )

            # Parse JSON response
            report_data = self._parse_reflection_json(response_text)
            if report_data is None:
                log.warning("Failed to parse LLM reflection response")
                return self._fallback_reflection(analysis, session_summary, reflection_id, source)

            # Emit reasoning events
            thinking_steps = report_data.get("thinking_steps", [])
            for step in thinking_steps:
                write_event(
                    events_path, "reflection_reasoning",
                    reflection_id=reflection_id,
                    source_id=source.id,
                    source_kind=source.kind,
                    display_text=step.get("display_text", ""),
                    metadata={"step": step.get("step", "")},
                )

            # Emit experience candidate events
            candidates = report_data.get("experience_candidates", [])
            for candidate in candidates:
                write_event(
                    events_path, "experience_candidate",
                    reflection_id=reflection_id,
                    source_id=source.id,
                    source_kind=source.kind,
                    display_text=candidate.get("lesson", ""),
                    metadata={"confidence": candidate.get("confidence", 0)},
                )

            return ReflectionReport(
                session_id=source.session_id or source.id,
                reflection_id=reflection_id,
                source_id=source.id,
                source_kind=source.kind,
                duration_seconds=analysis.duration_seconds,
                task_summary=report_data.get("task_summary", ""),
                outcome=report_data.get("outcome", "unknown"),
                tools_efficiency=report_data.get("tools_efficiency", {}),
                errors=report_data.get("errors", []),
                patterns_identified=report_data.get("patterns_identified", []),
                recommendations=report_data.get("recommendations", []),
                thinking_steps=thinking_steps,
                experience_candidates=candidates,
                metadata={"model": model},
            )

        except Exception as exc:
            log.warning("LLM reflection failed: %s, using fallback", exc)
            return self._fallback_reflection(analysis, session_summary, reflection_id, source)

    def _fallback_reflection(
        self,
        analysis: AnalysisResult,
        session_summary: str,
        reflection_id: str,
        source: IntrospectionSource,
    ) -> ReflectionReport:
        """Generate a basic reflection without LLM."""
        outcome = "unknown"
        if analysis.completion >= 0.9:
            outcome = "success"
        elif analysis.completion >= 0.5:
            outcome = "partial"
        elif analysis.completion > 0:
            outcome = "failure"

        return ReflectionReport(
            session_id=source.session_id or source.id,
            reflection_id=reflection_id,
            source_id=source.id,
            source_kind=source.kind,
            duration_seconds=analysis.duration_seconds,
            task_summary=session_summary[:200],
            outcome=outcome,
            tools_efficiency=analysis.tool_efficiency,
            errors=analysis.error_patterns,
            patterns_identified=analysis.patterns_identified,
            recommendations=[],
            metadata={"model": "fallback"},
        )

    def _parse_reflection_json(self, text: str) -> dict[str, Any] | None:
        """Parse JSON from LLM response, handling markdown fences."""
        cleaned = text.strip()
        # Remove markdown fences if present
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()

        try:
            data = json.loads(cleaned)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

        # Try to find JSON object in text
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                pass

        return None

    async def _save_experiences(
        self,
        report: ReflectionReport,
        events_path: Path,
    ) -> list[str]:
        """Save experience candidates from reflection report."""
        memory_ids = []
        for candidate in report.experience_candidates:
            confidence = float(candidate.get("confidence", 0.5))
            if confidence < self._config.min_confidence:
                continue

            lesson = candidate.get("lesson", "")
            if not lesson.strip():
                continue

            evidence = candidate.get("evidence", [])
            if isinstance(evidence, str):
                evidence = [evidence]

            experience = ExperienceRecord(
                id=f"exp_{uuid4().hex[:8]}",
                task_type=report.task_summary[:50] or "general",
                timestamp=utc_now_iso(),
                context={"session_id": report.session_id, "reflection_id": report.reflection_id},
                source_kind=report.source_kind,  # type: ignore[arg-type]
                outcome=report.outcome,
                metrics={"confidence": confidence},
                lessons=[lesson],
                tools_used=list(report.tools_efficiency.keys()),
                evidence=[str(e) for e in evidence],
                confidence=confidence,
            )

            mem_path = self._store.save_experience(experience)
            if mem_path:
                # Extract the real memory ID from the saved file's metadata
                memory_id = self._extract_memory_id_from_path(mem_path)
                memory_ids.append(memory_id)
                write_event(
                    events_path, "memory_written",
                    reflection_id=report.reflection_id,
                    source_id=report.source_id,
                    source_kind=report.source_kind,
                    summary=f"写入经验: {lesson[:100]}",
                    memory_id=memory_id,
                )

        return memory_ids

    @staticmethod
    def _extract_memory_id_from_path(path: Path) -> str:
        """Read the memory file and extract its schema id."""
        try:
            from openharness.memory.schema import split_memory_file

            content = path.read_text(encoding="utf-8")
            metadata, _, _, _ = split_memory_file(content)
            mid = metadata.get("id")
            if mid:
                return str(mid)
        except Exception:
            pass
        # Fallback: use the file stem (e.g. "mem-20260608-103000-abcd1234")
        return path.stem

    async def _write_reflection_json(self, report: ReflectionReport) -> None:
        """Write reflection report to JSON file."""
        reflections_dir = self._config.get_reflections_dir(self._cwd)
        reflections_dir.mkdir(parents=True, exist_ok=True)

        # Use timestamp-based filename
        ts = utc_now_iso().replace(":", "-").replace("T", "_").replace("Z", "")
        filename = f"{ts}_{report.reflection_id}.json"
        filepath = reflections_dir / filename

        try:
            import json
            content = json.dumps(report.to_dict(), indent=2, ensure_ascii=False)
            filepath.write_text(content, encoding="utf-8")
            log.debug("Wrote reflection to %s", filepath)
        except OSError as exc:
            log.warning("Failed to write reflection JSON: %s", exc)

    async def _classify_task_type(self, task_text: str) -> str | None:
        """Classify task type using LLM."""
        if self._api_client is None:
            return None

        prompt = TASK_TYPE_CLASSIFICATION_PROMPT.format(task_text=task_text[:500])

        try:
            from openharness.api.client import ApiMessageRequest
            from openharness.engine.messages import ConversationMessage

            request = ApiMessageRequest(
                model=self._default_model,
                messages=[ConversationMessage.from_user_text(prompt)],
                system_prompt="Output ONLY the category name, nothing else.",
                max_tokens=32,
            )

            text_chunks: list[str] = []
            async for event in self._api_client.stream_message(request):
                text_chunks.append(event.text)

            result = "".join(text_chunks).strip().lower()
            valid_types = {
                "code_review", "bug_fix", "feature_dev", "refactoring",
                "documentation", "testing", "debugging", "maintenance",
                "configuration", "other",
            }
            if result in valid_types:
                return result
            return "other"

        except Exception as exc:
            log.debug("Task classification failed: %s", exc)
            return None

    async def _dispatch_hook(self, event: str, data: dict[str, Any]) -> None:
        """Dispatch a hook event if a hook executor is available."""
        if self._hook_executor is None:
            return
        try:
            from openharness.hooks import HookEvent

            hook_event = HookEvent(event)
            await self._hook_executor.execute(
                hook_event,
                {"event": event, **data},
            )
        except Exception as exc:
            log.debug("Hook dispatch failed for %s: %s", event, exc)
