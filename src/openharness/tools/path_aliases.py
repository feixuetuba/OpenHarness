"""Shared path alias helpers for local tools."""

from __future__ import annotations

import os
import re
from pathlib import Path

from openharness.config.paths import get_data_dir
from openharness.config.settings import load_settings


def path_aliases(cwd: Path) -> dict[str, str]:
    """Return normalized aliases such as USKILL, UDATA, UPROJ, UWEB, and SOCIAL."""
    try:
        settings = load_settings()
        aliases = dict(getattr(settings.skill_management, "path_aliases", {}) or {})
    except Exception:
        aliases = {}
    aliases.setdefault("USKILL", "~/.openharness/skills")
    try:
        aliases.setdefault("UDATA", str(get_data_dir()))
    except Exception:
        aliases.setdefault("UDATA", "~/.openharness/data")
    aliases.setdefault("UPROJ", str(Path(cwd).expanduser().resolve()))
    aliases.setdefault("UWEB", str((Path(cwd) / ".openharness" / "media" / "web").resolve()))
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


def expand_path_alias(path: str | None, aliases: dict[str, str]) -> str:
    text = str(path or "").strip()
    for name, prefix in aliases.items():
        token = f"${name}"
        if text == token:
            return prefix
        if text.startswith(token + "/"):
            return prefix + text[len(token):]
    return text


def resolve_path(base: Path, candidate: str | None, aliases: dict[str, str] | None = None) -> Path:
    text = expand_path_alias(candidate, aliases or path_aliases(base))
    path = Path(text or ".").expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def compress_path_alias(path: str | Path, cwd: Path) -> str:
    try:
        resolved = str(Path(path).expanduser().resolve())
    except OSError:
        resolved = str(path)
    for name, prefix in sorted(path_aliases(cwd).items(), key=lambda item: len(item[1]), reverse=True):
        if resolved == prefix:
            return f"${name}"
        if resolved.startswith(prefix + os.sep):
            return f"${name}{resolved[len(prefix):]}"
    return str(path)
