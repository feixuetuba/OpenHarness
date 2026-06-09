"""Tests for introspection module — types, config, sources, analyzer, engine, store, logging, web, prompts."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from openharness.introspection.types import (
    AnalysisResult,
    ExperienceQuery,
    ExperienceRecord,
    IntrospectionSource,
    ReflectionReport,
)
from openharness.introspection.config import IntrospectionConfig
from openharness.introspection.sources import (
    build_session_summary,
    hash_actor,
    sanitize_message,
    source_from_bot_chat,
    source_from_cron,
    source_from_interactive_session,
    source_from_remote_trigger,
    source_from_subtask,
)
from openharness.introspection.analyzer import SessionAnalyzer
from openharness.introspection.engine import IntrospectionEngine
from openharness.introspection.experience_store import ExperienceStore
from openharness.introspection.logging import (
    log_event,
    make_safe_display_text,
    sanitize_text,
    utc_now_iso,
    write_event,
)
from openharness.introspection.web import (
    get_introspection_memories,
    get_reflection_detail,
    get_reflection_summaries,
    load_events,
)
from openharness.introspection.prompts import (
    EXPERIENCE_INJECTION_PROMPT,
    REFLECTION_PROMPT,
    TASK_TYPE_CLASSIFICATION_PROMPT,
)


# ============================================================
#  types
# ============================================================

class TestIntrospectionSource:
    def test_defaults(self):
        src = IntrospectionSource(
            id="id1", kind="interactive", timestamp="2026-06-09T00:00:00Z", cwd="/tmp"
        )
        assert src.session_id is None
        assert src.channel is None
        assert src.messages == []
        assert src.tool_events == []
        assert src.metadata == {}

    def test_full_fields(self):
        src = IntrospectionSource(
            id="id2",
            kind="bot_chat",
            timestamp="2026-06-09T00:00:00Z",
            cwd="/tmp",
            session_id="sess_abc",
            channel="qq",
            actor_hash="abc123",
            task_id="task_x",
            messages=[{"role": "user", "content": "hello"}],
            tool_events=[{"tool_name": "read_file", "success": True}],
            usage={"total_tokens": 100},
            metadata={"outcome": "success"},
        )
        assert src.channel == "qq"
        assert src.actor_hash == "abc123"
        assert len(src.messages) == 1


class TestReflectionReport:
    def test_to_dict(self):
        report = ReflectionReport(
            session_id="s1",
            reflection_id="r1",
            source_id="src1",
            source_kind="interactive",
            duration_seconds=30.0,
            task_summary="test",
            outcome="success",
            tools_efficiency={"read_file": 1.0},
            errors=[],
            patterns_identified=[],
            recommendations=[],
            thinking_steps=[{"step": "evidence_review", "display_text": "ok"}],
            experience_candidates=[{"lesson": "do x", "confidence": 0.9}],
            metadata={"model": "gpt-4"},
        )
        d = report.to_dict()
        assert d["outcome"] == "success"
        assert len(d["thinking_steps"]) == 1
        assert d["thinking_steps"][0]["step"] == "evidence_review"


class TestExperienceRecord:
    def test_to_dict(self):
        exp = ExperienceRecord(
            id="e1",
            task_type="bug_fix",
            timestamp="2026-01-01T00:00:00Z",
            context={"session_id": "s1"},
            source_kind="interactive",
            outcome="success",
            metrics={"duration_seconds": 10},
            lessons=["always check x"],
            tools_used=["grep"],
            evidence=["test_passed"],
            confidence=0.9,
            use_count=2,
            last_used="2026-01-02T00:00:00Z",
        )
        d = exp.to_dict()
        assert d["confidence"] == 0.9
        assert d["use_count"] == 2


class TestExperienceQuery:
    def test_defaults(self):
        q = ExperienceQuery()
        assert q.min_confidence == 0.7
        assert q.tools == []
        assert q.keywords == []


# ============================================================
#  config
# ============================================================

class TestIntrospectionConfig:
    def test_defaults(self):
        cfg = IntrospectionConfig()
        assert cfg.enabled is False
        assert cfg.auto_reflect is False
        assert cfg.min_confidence == 0.7
        assert cfg.max_experience_top_k == 5
        assert cfg.min_tool_calls_for_reflection == 2
        assert cfg.injection_mode == "reference"
        assert cfg.learn_from_interactive is True
        assert cfg.learn_from_bot_chat is True
        assert cfg.learn_from_cron is True
        assert cfg.learn_from_remote_trigger is True
        assert cfg.learn_from_subtask is False

    def test_is_source_enabled(self):
        cfg = IntrospectionConfig()
        assert cfg.is_source_enabled("interactive") is True
        assert cfg.is_source_enabled("bot_chat") is True
        cfg.learn_from_bot_chat = False
        assert cfg.is_source_enabled("bot_chat") is False

    def test_from_settings_disabled(self):
        class FakeSettings:
            class introspection:
                enabled = False
        cfg = IntrospectionConfig.from_settings(FakeSettings())
        assert cfg.enabled is False

    def test_from_settings_custom(self):
        class FakeSettings:
            class introspection:
                enabled = True
                auto_reflect = True
                min_confidence = 0.85
                max_experience_top_k = 3
                reflection_timeout_seconds = 30.0
                injection_mode = "auto"
                min_tool_calls_for_reflection = 1
        cfg = IntrospectionConfig.from_settings(FakeSettings())
        assert cfg.auto_reflect is True
        assert cfg.min_confidence == 0.85
        assert cfg.max_experience_top_k == 3
        assert cfg.reflection_timeout_seconds == 30.0
        assert cfg.injection_mode == "auto"
        assert cfg.min_tool_calls_for_reflection == 1

    def test_events_path_uses_custom(self, tmp_path):
        cfg = IntrospectionConfig(events_log_path=Path("/tmp/events.jsonl"))
        assert cfg.get_events_path(tmp_path) == Path("/tmp/events.jsonl")

    def test_reflections_dir_uses_custom(self, tmp_path):
        cfg = IntrospectionConfig(reflections_dir=Path("/tmp/reflections"))
        assert cfg.get_reflections_dir(tmp_path) == Path("/tmp/reflections")


# ============================================================
#  sources
# ============================================================

class TestHashActor:
    def test_returns_none_for_none(self):
        assert hash_actor(None) is None

    def test_returns_hex(self):
        h = hash_actor("user123")
        assert isinstance(h, str)
        assert len(h) == 12

    def test_deterministic(self):
        assert hash_actor("user123") == hash_actor("user123")

    def test_different_inputs_different_hash(self):
        assert hash_actor("a") != hash_actor("b")


class TestSanitizeMessage:
    def test_removes_sensitive_keys(self):
        msg = {"role": "user", "content": "hi", "sender_id": "secret", "sender_name": "Alice", "email": "a@b.com", "phone": "123"}
        sanitized = sanitize_message(msg)
        assert "sender_id" not in sanitized
        assert "sender_name" not in sanitized
        assert "email" not in sanitized
        assert "phone" not in sanitized
        assert sanitized["role"] == "user"

    def test_preserves_other_keys(self):
        msg = {"role": "assistant", "content": "ok", "extra": 1}
        sanitized = sanitize_message(msg)
        assert sanitized["extra"] == 1


class TestSourceFromInteractiveSession:
    def test_basic(self):
        src = source_from_interactive_session("sess_1", "/tmp")
        assert src.kind == "interactive"
        assert src.channel == "cli"
        assert src.id == "sess_sess_1"
        assert src.session_id == "sess_1"

    def test_with_messages_and_tool_events(self):
        msgs = [{"role": "user", "content": "hello", "sender_id": "x"}]
        tools = [{"tool_name": "grep", "success": True}]
        src = source_from_interactive_session("s2", "/tmp", messages=msgs, tool_events=tools, usage={"total_tokens": 100})
        assert len(src.messages) == 1
        assert "sender_id" not in src.messages[0]
        assert src.tool_events == tools
        assert src.usage["total_tokens"] == 100


class TestSourceFromBotChat:
    def test_hides_sender(self):
        src = source_from_bot_chat("chat1", "qq", "/tmp", sender_raw="user@qq.com")
        assert src.kind == "bot_chat"
        assert src.channel == "qq"
        assert src.actor_hash is not None
        assert src.actor_hash != "user@qq.com"
        assert "chat1" not in src.id
        assert src.metadata.get("chat_hash")


class TestSourceFromCron:
    def test_basic(self):
        src = source_from_cron("job1", "/tmp", schedule="0 * * * *", exit_code=1, output_summary="timeout")
        assert src.kind == "cron"
        assert src.task_id == "job1"
        assert src.metadata["schedule"] == "0 * * * *"
        assert src.metadata["exit_code"] == 1
        assert "timeout" in src.metadata["output_summary"]

    def test_output_truncation(self):
        src = source_from_cron("job2", "/tmp", output_summary="x" * 1000)
        assert len(src.metadata["output_summary"]) == 500


class TestSourceFromRemoteTrigger:
    def test_basic(self):
        src = source_from_remote_trigger("trig1", "/tmp", result={"ok": True})
        assert src.kind == "remote_trigger"
        assert "ok" in src.metadata["result_summary"]


class TestSourceFromSubtask:
    def test_basic(self):
        src = source_from_subtask("task1", "/tmp", session_id="sess_x", outcome="failure")
        assert src.kind == "subtask"
        assert src.metadata["outcome"] == "failure"


class TestBuildSessionSummary:
    def test_includes_source_info(self):
        src = source_from_interactive_session("s1", "/tmp", messages=[{"role": "user", "content": "hello"}])
        summary = build_session_summary(src)
        assert "interactive" in summary
        assert "sess_s1" in summary
        assert "hello" in summary

    def test_handles_tool_events(self):
        src = source_from_interactive_session(
            "s2", "/tmp", tool_events=[{"tool_name": "grep", "success": True}]
        )
        summary = build_session_summary(src)
        assert "grep" in summary


# ============================================================
#  analyzer
# ============================================================

class TestSessionAnalyzer:
    def test_completion_success_by_metadata(self):
        src = IntrospectionSource(id="1", kind="interactive", timestamp="t", cwd="/tmp", metadata={"outcome": "success"})
        analyzer = SessionAnalyzer()
        result = analyzer.analyze(src)
        assert result.completion == 1.0

    def test_completion_partial_by_metadata(self):
        src = IntrospectionSource(id="1", kind="interactive", timestamp="t", cwd="/tmp", metadata={"outcome": "partial"})
        result = SessionAnalyzer().analyze(src)
        assert result.completion == 0.5

    def test_completion_failure_by_metadata(self):
        src = IntrospectionSource(id="1", kind="interactive", timestamp="t", cwd="/tmp", metadata={"outcome": "failure"})
        result = SessionAnalyzer().analyze(src)
        assert result.completion == 0.0

    def test_completion_heuristic(self):
        src = IntrospectionSource(
            id="1", kind="interactive", timestamp="t", cwd="/tmp",
            tool_events=[
                {"tool_name": "grep", "success": True},
                {"tool_name": "read_file", "success": False},
            ],
        )
        result = SessionAnalyzer().analyze(src)
        assert result.completion == 0.5

    def test_completion_all_success(self):
        src = IntrospectionSource(
            id="1", kind="interactive", timestamp="t", cwd="/tmp",
            tool_events=[{"tool_name": "grep", "success": True}] * 3,
        )
        result = SessionAnalyzer().analyze(src)
        assert result.completion == 1.0

    def test_tool_efficiency(self):
        src = IntrospectionSource(
            id="1", kind="interactive", timestamp="t", cwd="/tmp",
            tool_events=[
                {"tool_name": "grep", "success": True},
                {"tool_name": "grep", "success": False},
                {"tool_name": "edit", "success": True},
            ],
        )
        result = SessionAnalyzer().analyze(src)
        assert result.tool_efficiency["grep"] == 0.5
        assert result.tool_efficiency["edit"] == 1.0

    def test_error_patterns(self):
        src = IntrospectionSource(
            id="1", kind="interactive", timestamp="t", cwd="/tmp",
            tool_events=[
                {"tool_name": "grep", "success": False, "error": "not found", "error_type": "tool_error"},
            ],
        )
        result = SessionAnalyzer().analyze(src)
        assert len(result.error_patterns) == 1
        assert result.error_patterns[0]["tool"] == "grep"

    def test_success_patterns(self):
        src = IntrospectionSource(
            id="1", kind="interactive", timestamp="t", cwd="/tmp",
            tool_events=[{"tool_name": "edit", "success": True}] * 4,
        )
        result = SessionAnalyzer().analyze(src)
        assert any("edit" in p for p in result.success_patterns)


# ============================================================
#  engine (unit: min_tool_calls threshold, fallback, timeout)
# ============================================================

class TestIntrospectionEngine:
    def test_disabled_config_skips(self):
        cfg = IntrospectionConfig(enabled=False)
        engine = IntrospectionEngine(cwd="/tmp", config=cfg)
        assert engine.enabled is False

    async def test_reflect_skips_below_min_tool_calls(self):
        cfg = IntrospectionConfig(enabled=True, min_tool_calls_for_reflection=5)
        engine = IntrospectionEngine(cwd="/tmp", config=cfg)
        src = IntrospectionSource(id="x", kind="interactive", timestamp="t", cwd="/tmp")
        report = await engine.reflect_on_session(src)
        assert report is None  # 0 tool calls < 5

    async def test_reflect_skips_disabled_source_kind(self):
        cfg = IntrospectionConfig(enabled=True, learn_from_bot_chat=False)
        engine = IntrospectionEngine(cwd="/tmp", config=cfg)
        src = IntrospectionSource(
            id="x", kind="bot_chat", timestamp="t", cwd="/tmp",
            tool_events=[{"tool_name": "grep", "success": True}] * 3,
        )
        report = await engine.reflect_on_session(src)
        assert report is None

    def test_reflect_timeout(self):
        """Verify that reflect_on_session handles asyncio.TimeoutError gracefully."""
        import asyncio

        cfg = IntrospectionConfig(enabled=True)
        engine = IntrospectionEngine(cwd="/tmp", config=cfg)
        src = IntrospectionSource(
            id="x", kind="interactive", timestamp="t", cwd="/tmp",
            tool_events=[{"tool_name": "grep", "success": True}] * 3,
        )

        async def _run():
            # Simulate timeout by patching _generate_reflection
            original = engine._generate_reflection
            async def _fake_gen(*args, **kwargs):
                raise asyncio.TimeoutError("simulated")
            engine._generate_reflection = _fake_gen
            try:
                report = await engine.reflect_on_session(src)
                assert report is None
            finally:
                engine._generate_reflection = original

        asyncio.run(_run())

    def test_fallback_reflection(self):
        cfg = IntrospectionConfig(enabled=True)
        engine = IntrospectionEngine(cwd="/tmp", config=cfg)
        from openharness.introspection.types import AnalysisResult
        analysis = AnalysisResult(
            completion=0.95, tool_efficiency={}, error_patterns=[],
            patterns_identified=[], success_patterns=[], failure_patterns=[],
            tool_calls_count=3, duration_seconds=10.0, total_tokens=100,
        )
        report = engine._fallback_reflection(analysis, "summary", "r1", IntrospectionSource(
            id="x", kind="interactive", timestamp="t", cwd="/tmp"))
        assert report.outcome == "success"
        assert report.metadata["model"] == "fallback"

    def test_parse_reflection_json_valid(self):
        engine = IntrospectionEngine(cwd="/tmp", config=IntrospectionConfig())
        result = engine._parse_reflection_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_reflection_json_fences(self):
        engine = IntrospectionEngine(cwd="/tmp", config=IntrospectionConfig())
        result = engine._parse_reflection_json('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_parse_reflection_json_in_text(self):
        engine = IntrospectionEngine(cwd="/tmp", config=IntrospectionConfig())
        result = engine._parse_reflection_json('prefix {"key": "value"} suffix')
        assert result == {"key": "value"}

    def test_format_experiences_for_prompt(self):
        cfg = IntrospectionConfig()
        engine = IntrospectionEngine(cwd="/tmp", config=cfg)
        exps = [
            ExperienceRecord(
                id="e1", task_type="bug_fix", timestamp="t", context={},
                source_kind="interactive", outcome="success", metrics={},
                lessons=["check x first"], tools_used=["grep"], evidence=[],
            ),
        ]
        text = engine.format_experiences_for_prompt(exps, "fix a bug")
        assert "check x first" in text
        assert "bug_fix" in text
        assert "fix a bug" in text

    def test_format_experiences_empty(self):
        cfg = IntrospectionConfig()
        engine = IntrospectionEngine(cwd="/tmp", config=cfg)
        assert engine.format_experiences_for_prompt([], "task") == ""


# ============================================================
#  experience_store
# ============================================================

class TestExperienceStore:
    def test_save_and_retrieve(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
        cfg = IntrospectionConfig(min_confidence=0.0)
        store = ExperienceStore(tmp_path, cfg)
        exp = ExperienceRecord(
            id="e1", task_type="bug_fix", timestamp=utc_now_iso(),
            context={}, source_kind="interactive", outcome="success",
            metrics={}, lessons=["always test first"], tools_used=["bash"],
            evidence=["tests_pass"],
        )
        path = store.save_experience(exp)
        assert path is not None
        assert "experience_bug_fix" in str(path) and str(path).endswith(".md")

        query = ExperienceQuery(task_type="bug_fix", min_confidence=0.0)
        results = store.retrieve_experiences(query)
        assert len(results) >= 1
        assert any("test first" in r.lessons[0] for r in results)


# ============================================================
#  logging
# ============================================================

class TestSanitizeText:
    def test_removes_secrets(self):
        assert "REDACTED" in sanitize_text("api_key=12345678901234567890")
        assert "REDACTED" in sanitize_text("sk-12345678901234567890abc")
        assert "REDACTED" in sanitize_text("ghp_123456789012345678901234567890abcdef")

    def test_truncates(self):
        assert sanitize_text("a" * 300, max_length=50).endswith("...")

    def test_empty(self):
        assert sanitize_text("") == ""

    def test_preserves_normal_text(self):
        assert sanitize_text("hello world") == "hello world"


class TestMakeSafeDisplayText:
    def test_removes_newlines(self):
        result = make_safe_display_text("line1\nline2\nline3")
        assert "\n" not in result


class TestUtcNowIso:
    def test_format(self):
        ts = utc_now_iso()
        assert ts.endswith("Z")
        assert "T" in ts


class TestWriteEvent:
    def test_appends_jsonl(self, tmp_path):
        events_path = tmp_path / "events.jsonl"
        write_event(events_path, "test_event", reflection_id="r1", source_id="s1", source_kind="interactive", display_text="hello")
        assert events_path.exists()
        lines = events_path.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["event"] == "test_event"
        assert data["reflection_id"] == "r1"
        assert "hello" in data["display_text"]


class TestLogEvent:
    def test_no_exception(self, caplog):
        import logging
        logger = logging.getLogger("test.introspection")
        caplog.set_level(logging.INFO)
        log_event(logger, "INFO", "test message", reflection_id="r1")
        assert "test message" in caplog.text


# ============================================================
#  web
# ============================================================

class TestWeb:
    def test_load_events_empty(self, tmp_path):
        events_path = tmp_path / "events.jsonl"
        assert load_events(events_path) == []

    def test_load_events_reads(self, tmp_path):
        events_path = tmp_path / "events.jsonl"
        write_event(events_path, "reflection_started", reflection_id="r1", source_id="s1", source_kind="interactive")
        write_event(events_path, "reflection_completed", reflection_id="r1", source_id="s1", source_kind="interactive")
        events = load_events(events_path)
        assert len(events) == 2
        # most recent first
        assert events[0].event == "reflection_completed"

    def test_load_events_filter_source_kind(self, tmp_path):
        events_path = tmp_path / "events.jsonl"
        write_event(events_path, "reflection_started", reflection_id="r1", source_id="s1", source_kind="interactive")
        write_event(events_path, "reflection_started", reflection_id="r2", source_id="s2", source_kind="cron")
        events = load_events(events_path, source_kind="cron")
        assert len(events) == 1
        assert events[0].source_kind == "cron"

    def test_load_events_limit(self, tmp_path):
        events_path = tmp_path / "events.jsonl"
        for i in range(5):
            write_event(events_path, "test", reflection_id=f"r{i}")
        events = load_events(events_path, limit=3)
        assert len(events) == 3

    def test_get_reflection_summaries(self, tmp_path):
        events_path = tmp_path / "events.jsonl"
        write_event(events_path, "reflection_started", reflection_id="r1", source_id="s1", source_kind="interactive")
        write_event(events_path, "reflection_completed", reflection_id="r1", source_id="s1", source_kind="interactive", metadata={"outcome": "success", "memory_ids": ["m1"]})
        summaries = get_reflection_summaries(events_path)
        assert len(summaries) == 1
        assert summaries[0]["status"] == "completed"
        assert summaries[0]["outcome"] == "success"

    def test_get_introspection_memories_filters(self, tmp_path):
        events_path = tmp_path / "events.jsonl"
        write_event(events_path, "memory_written", reflection_id="r1", memory_id="mem-abc", summary="write x")
        write_event(events_path, "reflection_started", reflection_id="r1")  # not memory_written
        memories = get_introspection_memories(events_path)
        assert len(memories) == 1
        assert memories[0]["memory_id"] == "mem-abc"

    def test_get_reflection_detail(self, tmp_path):
        events_path = tmp_path / "events.jsonl"
        write_event(events_path, "reflection_started", reflection_id="r1", source_id="s1", source_kind="interactive")
        write_event(events_path, "reflection_reasoning", reflection_id="r1", display_text="thinking...", metadata={"step": "evidence_review"})
        write_event(events_path, "experience_candidate", reflection_id="r1", display_text="lesson x", metadata={"confidence": 0.8})
        write_event(events_path, "reflection_completed", reflection_id="r1", source_id="s1", source_kind="interactive", metadata={"outcome": "success"})
        detail = get_reflection_detail(events_path, "r1")
        assert detail is not None
        assert len(detail["thinking_steps"]) == 1
        assert len(detail["experience_candidates"]) == 1


# ============================================================
#  prompts
# ============================================================

class TestPrompts:
    def test_reflection_prompt_formats(self):
        text = REFLECTION_PROMPT.format(session_summary="sum", analysis="ana")
        assert "sum" in text
        assert "ana" in text

    def test_experience_injection_formats(self):
        text = EXPERIENCE_INJECTION_PROMPT.format(experiences="exp", task_text="task")
        assert "exp" in text
        assert "task" in text

    def test_task_classification_formats(self):
        text = TASK_TYPE_CLASSIFICATION_PROMPT.format(task_text="fix a bug")
        assert "fix a bug" in text
