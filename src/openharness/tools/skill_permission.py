"""Helpers for mapping tool calls to skill-level permission grants."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from openharness.skills import load_skill_registry


def approved_skill_names(metadata: dict[str, Any] | None) -> set[str]:
    value = metadata.get("approved_social_skills") if isinstance(metadata, dict) else None
    return {str(item).strip() for item in value or [] if str(item).strip()} if isinstance(value, list) else set()


def infer_skill_from_text(text: str, cwd: str | Path, metadata: dict[str, Any] | None = None) -> str | None:
    haystack = text.lower()
    if not haystack.strip():
        return None
    try:
        skills = list(load_skill_registry(cwd).list_skills())
    except Exception:
        skills = []
    candidates: list[tuple[int, str, list[str]]] = []
    for skill in skills:
        names = {
            str(skill.name or "").strip(),
            str(skill.command_name or "").strip(),
        }
        if skill.base_dir:
            base = Path(skill.base_dir).expanduser()
            names.add(str(base))
            names.add(base.name)
        aliases = [name for name in names if name]
        if aliases:
            canonical = str(skill.command_name or skill.name).strip()
            candidates.append((max(len(alias) for alias in aliases), canonical, aliases))
    for _length, canonical, aliases in sorted(candidates, reverse=True):
        for alias in aliases:
            if _contains_token(haystack, alias.lower()):
                return canonical
    return None


def infer_skill_from_tool_call(
    tool_name: str,
    tool_input: dict[str, object] | None,
    cwd: str | Path,
    metadata: dict[str, Any] | None = None,
) -> str | None:
    payload = tool_input if isinstance(tool_input, dict) else {}
    if tool_name == "skill":
        value = str(payload.get("name") or payload.get("skill") or payload.get("skill_name") or "").strip()
        return value or None
    text_parts = [tool_name]
    for key in ("prompt", "description", "command", "cwd", "path", "output_path"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            text_parts.append(value)
    if payload:
        try:
            text_parts.append(json.dumps(payload, ensure_ascii=False, default=str))
        except TypeError:
            pass
    return infer_skill_from_text("\n".join(text_parts), cwd, metadata)


def skill_is_approved(skill_name: str | None, metadata: dict[str, Any] | None) -> bool:
    if not skill_name:
        return False
    normalized = skill_name.strip().lower()
    return any(item.lower() == normalized for item in approved_skill_names(metadata))


def _contains_token(haystack: str, needle: str) -> bool:
    if not needle:
        return False
    if "/" in needle or "\\" in needle:
        return needle in haystack
    pattern = r"(?<![A-Za-z0-9_-])" + re.escape(needle) + r"(?![A-Za-z0-9_-])"
    return re.search(pattern, haystack) is not None
