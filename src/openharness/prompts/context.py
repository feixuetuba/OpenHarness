"""Higher-level system prompt assembly."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from openharness.config.paths import (
    get_project_active_repo_context_path,
    get_project_issue_file,
    get_project_pr_comments_file,
)
from openharness.config.settings import Settings
from openharness.coordinator.coordinator_mode import get_coordinator_system_prompt, is_coordinator_mode
from openharness.memory import load_memory_prompt
from openharness.memory.relevance import format_relevant_memories, select_relevant_memories
from openharness.memory.usage import mark_memory_used
from openharness.personalization.rules import load_local_rules
from openharness.permissions.modes import PermissionMode
from openharness.prompts.claudemd import load_claude_md_prompt
from openharness.prompts.system_prompt import build_system_prompt
from openharness.skills.index import SkillIndex
from openharness.skills.loader import load_skill_registry
from openharness.skills.types import SkillCandidate, SkillDefinition
from openharness.utils.conversation_log import get_or_init_conversation_logger


_DEFAULT_SKILL_CANDIDATE_LIMIT = 5


def _candidate_from_skill(skill: SkillDefinition) -> SkillCandidate:
    return SkillCandidate(
        skill_name=skill.command_name or skill.name,
        description=skill.trigger or skill.description,
        trigger=skill.trigger,
        negative_trigger=skill.negative_trigger,
        source=skill.source,
        trust_level=None,
        score=0.0,
        match_type="fallback",
    )


def _format_skill_candidate(candidate: SkillCandidate) -> str:
    details = [candidate.trigger or candidate.description]
    if candidate.negative_trigger:
        details.append(f"Do not use when: {candidate.negative_trigger}")
    if candidate.source:
        source = candidate.source
        if candidate.trust_level:
            source = f"{source}, trust={candidate.trust_level}"
        details.append(f"source={source}")
    return f"- **{candidate.skill_name}**: " + " ".join(part for part in details if part)


def _candidate_log_record(candidate: SkillCandidate) -> dict[str, object]:
    return {
        "skill_name": candidate.skill_name,
        "description": candidate.description,
        "trigger": candidate.trigger,
        "negative_trigger": candidate.negative_trigger,
        "source": candidate.source,
        "trust_level": candidate.trust_level,
        "score": candidate.score,
        "match_type": candidate.match_type,
    }


def _build_skills_section(
    cwd: str | Path,
    *,
    latest_user_prompt: str | None = None,
    extra_skill_dirs: Iterable[str | Path] | None = None,
    extra_plugin_roots: Iterable[str | Path] | None = None,
    settings: Settings | None = None,
) -> str | None:
    """Build a system prompt section with lightweight recalled skill candidates."""
    registry = load_skill_registry(
        cwd,
        extra_skill_dirs=extra_skill_dirs,
        extra_plugin_roots=extra_plugin_roots,
        settings=settings,
    )
    skills = [skill for skill in registry.list_skills() if not skill.disable_model_invocation]
    if not skills:
        return None

    debug_mode = False
    skill_management = getattr(settings, "skill_management", None) if settings is not None else None
    if skill_management is not None:
        debug_mode = bool(getattr(skill_management, "debug_mode", False))

    candidates: list[SkillCandidate]
    if latest_user_prompt:
        index = SkillIndex()
        index.build(skills, debug_mode=debug_mode)
        candidates = index.recall(latest_user_prompt, top_k=_DEFAULT_SKILL_CANDIDATE_LIMIT)
    else:
        candidates = [
            _candidate_from_skill(skill)
            for skill in skills[:_DEFAULT_SKILL_CANDIDATE_LIMIT]
        ]

    if not candidates:
        conv_logger = get_or_init_conversation_logger()
        if conv_logger:
            conv_logger.log_skill_recall(
                latest_user_prompt,
                [],
                source="prompt",
                reason="no_candidates",
            )
        lines = [
            "# Available Skill Candidates",
            "",
            "No high-confidence skill candidates were recalled for the current request. "
            "If a skill would help, call `skill_search(query=\"...\")` to search available skills.",
        ]
        return "\n".join(lines)

    shown_names = [candidate.skill_name for candidate in candidates]
    conv_logger = get_or_init_conversation_logger()
    if conv_logger:
        conv_logger.log_skill_recall(
            latest_user_prompt,
            [_candidate_log_record(candidate) for candidate in candidates],
            source="prompt",
        )
    lines = [
        "# Available Skill Candidates",
        "",
        "The following lightweight skill candidates were recalled for the current request. "
        "Only call `skill(name=\"<skill_name>\")` when the user's request clearly matches "
        "a candidate's trigger "
        "and does not match its negative trigger. "
        "If these candidates are insufficient, call "
        f"`skill_search(query=\"...\", exclude_names={shown_names!r})` to search more skills.",
        "",
    ]
    lines.extend(_format_skill_candidate(candidate) for candidate in candidates)
    return "\n".join(lines)


def _build_delegation_section() -> str:
    """Build a concise section describing delegation and worker usage."""
    return "\n".join(
        [
            "# Delegation And Subagents",
            "",
            "OpenHarness can delegate background work with the `agent` tool.",
            "Use it when the user explicitly asks for a subagent, background worker, or parallel investigation, "
            "or when the task clearly benefits from splitting off a focused worker.",
            "",
            "Default pattern:",
            '- Spawn with `agent(description=..., prompt=..., subagent_type=\"worker\")`.',
            "- Inspect running or recorded workers with `/agents`.",
            "- Inspect one worker in detail with `/agents show TASK_ID`.",
            "- Send follow-up instructions with `send_message(task_id=..., message=...)`.",
            "- Read worker output with `task_output(task_id=...)`.",
            "",
            "Prefer a normal direct answer for simple tasks. Use subagents only when they materially help.",
        ]
    )


def _build_permission_mode_section(settings: Settings) -> str:
    """Build current permission-mode guidance for the model."""
    mode = settings.permission.mode
    if mode == PermissionMode.PLAN:
        guidance = (
            "Plan mode is enabled. Treat this session as read-only planning and analysis. "
            "Do not call mutating tools such as file writes, edits, package installs, "
            "state-changing shell commands, or task-spawning actions unless the user exits plan mode."
        )
    elif mode == PermissionMode.FULL_AUTO:
        guidance = (
            "Full-auto permission mode is enabled. You may use mutating tools when they are necessary "
            "for the user's request, while still keeping changes scoped and intentional."
        )
    else:
        guidance = (
            "Default permission mode is enabled. Read-only tools can run directly; mutating tools "
            "may require explicit user approval."
        )
    return f"# Current Permission Mode\n{guidance}"


def build_runtime_system_prompt(
    settings: Settings,
    *,
    cwd: str | Path,
    latest_user_prompt: str | None = None,
    extra_skill_dirs: Iterable[str | Path] | None = None,
    extra_plugin_roots: Iterable[str | Path] | None = None,
    include_project_memory: bool = True,
) -> str:
    """Build the runtime system prompt with project instructions and memory."""
    if is_coordinator_mode():
        sections = [get_coordinator_system_prompt()]
    else:
        sections = [build_system_prompt(custom_prompt=settings.system_prompt, cwd=str(cwd))]

    if not is_coordinator_mode() and settings.system_prompt is None:
        sections[0] = build_system_prompt(cwd=str(cwd))

    sections.append(_build_permission_mode_section(settings))

    if settings.fast_mode:
        sections.append(
            "# Session Mode\nFast mode is enabled. Prefer concise replies, minimal tool use, and quicker progress over exhaustive exploration."
        )

    sections.append(
        "# Reasoning Settings\n"
        f"- Effort: {settings.effort}\n"
        f"- Passes: {settings.passes}\n"
        "Adjust depth and iteration count to match these settings while still completing the task."
    )

    skills_section = _build_skills_section(
        cwd,
        latest_user_prompt=latest_user_prompt,
        extra_skill_dirs=extra_skill_dirs,
        extra_plugin_roots=extra_plugin_roots,
        settings=settings,
    )
    if skills_section and not is_coordinator_mode():
        sections.append(skills_section)

    if not is_coordinator_mode():
        sections.append(_build_delegation_section())

    claude_md = load_claude_md_prompt(cwd)
    if claude_md:
        sections.append(claude_md)

    local_rules = load_local_rules()
    if local_rules:
        sections.append(f"# Local Environment Rules\n\n{local_rules}")

    for title, path in (
        ("Issue Context", get_project_issue_file(cwd)),
        ("Pull Request Comments", get_project_pr_comments_file(cwd)),
        ("Active Repo Context", get_project_active_repo_context_path(cwd)),
    ):
        if path.exists():
            content = path.read_text(encoding="utf-8", errors="replace").strip()
            if content:
                sections.append(f"# {title}\n\n```md\n{content[:12000]}\n```")

    if include_project_memory and settings.memory.enabled:
        memory_section = load_memory_prompt(
            cwd,
            max_entrypoint_lines=settings.memory.max_entrypoint_lines,
            max_entrypoint_bytes=settings.memory.max_entrypoint_bytes,
        )
        if memory_section:
            sections.append(memory_section)

        if latest_user_prompt:
            relevant = select_relevant_memories(
                latest_user_prompt,
                cwd,
                max_results=settings.memory.max_files,
            )
            if relevant:
                try:
                    headers = [item.header for item in relevant]
                    mark_memory_used(cwd, headers, memory_dir=headers[0].path.parent)
                except OSError:
                    pass
                sections.append(format_relevant_memories(relevant))

    return "\n\n".join(section for section in sections if section.strip())
