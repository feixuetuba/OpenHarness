"""Skill loading from bundled, user, compatibility, and project directories."""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from typing import Iterable

from openharness.config.paths import get_config_dir
from openharness.config.settings import load_settings
from openharness.skills._frontmatter import (
    optional_frontmatter_str,
    parse_bool_frontmatter,
    parse_skill_frontmatter,
    parse_skill_metadata,
)
from openharness.skills.bundled import get_bundled_skills
from openharness.skills.registry import SkillRegistry
from openharness.skills.types import SkillDefinition

logger = logging.getLogger(__name__)

_USER_COMPAT_SKILL_DIRS = (
    (".claude", "skills"),
    (".agents", "skills"),
)
_DEFAULT_PROJECT_SKILL_DIRS = (".openharness/skills", ".agents/skills", ".claude/skills")


def get_user_skills_dir() -> Path:
    """Return the OpenHarness user skills directory."""
    path = get_config_dir() / "skills"
    path.mkdir(parents=True, exist_ok=True)
    logger.debug("[skills] User skills directory: %s", path)
    return path


def get_user_skill_dirs() -> list[Path]:
    """Return user-level skill directories loaded by default."""
    dirs = [get_user_skills_dir(), *(Path.home().joinpath(*parts) for parts in _USER_COMPAT_SKILL_DIRS)]
    logger.debug("[skills] User skill directories: %s", dirs)
    return dirs


def load_skill_registry(
    cwd: str | Path | None = None,
    *,
    extra_skill_dirs: Iterable[str | Path] | None = None,
    extra_plugin_roots: Iterable[str | Path] | None = None,
    settings=None,
    include_disabled: bool = False,
) -> SkillRegistry:
    """Load bundled, user-defined, project, and plugin skills."""
    logger.info("[skills] Loading skill registry (cwd=%s, include_disabled=%s)", cwd, include_disabled)

    resolved_settings = settings or load_settings()
    disabled_names = _disabled_skill_names(resolved_settings)

    if disabled_names:
        logger.info("[skills] Disabled skills: %s", disabled_names)

    registry = SkillRegistry()

    # Load bundled skills
    bundled_skills = list(get_bundled_skills())
    logger.info("[skills] Loading %d bundled skills", len(bundled_skills))
    for skill in bundled_skills:
        _register_skill(registry, skill, disabled_names, include_disabled)

    # Load user skills
    user_skills = load_user_skills()
    logger.info("[skills] Loading %d user skills", len(user_skills))
    for skill in user_skills:
        _register_skill(registry, skill, disabled_names, include_disabled)

    # Load extra skill directories
    extra_skills = load_skills_from_dirs(extra_skill_dirs, source="user")
    logger.info("[skills] Loading %d extra skills from directories", len(extra_skills))
    for skill in extra_skills:
        _register_skill(registry, skill, disabled_names, include_disabled)

    # Load project skills
    if cwd is not None and getattr(resolved_settings, "allow_project_skills", True):
        project_dirs = discover_project_skill_dirs(
            cwd,
            getattr(resolved_settings, "project_skill_dirs", list(_DEFAULT_PROJECT_SKILL_DIRS)),
        )
        logger.info("[skills] Found %d project skill directories: %s", len(project_dirs), project_dirs)
        project_skills = load_skills_from_dirs(project_dirs, source="project", create_missing=False)
        logger.info("[skills] Loading %d project skills", len(project_skills))
        for skill in project_skills:
            _register_skill(registry, skill, disabled_names, include_disabled)

    # Load plugin skills
    if cwd is not None:
        from openharness.plugins.loader import load_plugins

        plugins = list(load_plugins(resolved_settings, cwd, extra_roots=extra_plugin_roots))
        enabled_plugins = [p for p in plugins if p.enabled]
        logger.info("[skills] Loading skills from %d plugins (total=%d)", len(enabled_plugins), len(plugins))

        for plugin in enabled_plugins:
            plugin_skills = list(plugin.skills)
            logger.debug("[skills] Plugin '%s' provides %d skills", plugin.name, len(plugin_skills))
            for skill in plugin_skills:
                _register_skill(registry, skill, disabled_names, include_disabled)

    final_skills = registry.list_skills()
    enabled_count = sum(1 for s in final_skills if s.enabled)
    logger.info("[skills] Skill registry loaded: %d total skills (%d enabled)", len(final_skills), enabled_count)

    return registry


def _disabled_skill_names(settings) -> set[str]:
    skill_management = getattr(settings, "skill_management", None)
    names = getattr(skill_management, "disabled_skills", None) if skill_management is not None else None
    result = {str(name).strip() for name in names or [] if str(name).strip()}
    return result


def _skill_identifiers(skill: SkillDefinition) -> set[str]:
    return {
        str(value).strip()
        for value in (skill.name, skill.command_name, skill.display_name, *skill.aliases)
        if str(value).strip()
    }


def _register_skill(
    registry: SkillRegistry,
    skill: SkillDefinition,
    disabled_names: set[str],
    include_disabled: bool,
) -> None:
    disabled = bool(_skill_identifiers(skill) & disabled_names)
    if disabled and not include_disabled:
        logger.debug("[skills] Skipping disabled skill '%s'", skill.name)
        return
    registry.register(replace(skill, enabled=not disabled))


def load_user_skills() -> list[SkillDefinition]:
    """Load markdown skills from user-level OpenHarness and compatibility directories."""
    logger.debug("[skills] Loading user skills from directories")
    return load_skills_from_dirs(get_user_skill_dirs(), source="user")


def discover_project_skill_dirs(
    cwd: str | Path,
    project_skill_dirs: Iterable[str] | None = None,
) -> list[Path]:
    """Return existing project skill directories from cwd up to the git root.

    Directories are ordered from least-specific to most-specific so later registry
    entries can override broader project or user skills deterministically.
    """
    start = Path(cwd).expanduser().resolve()
    if not start.exists():
        start = start.parent
    if start.is_file():
        start = start.parent

    relative_dirs = _valid_project_skill_dirs(project_skill_dirs or _DEFAULT_PROJECT_SKILL_DIRS)
    git_root = _find_git_root(start)
    home = Path.home().resolve()
    current = start
    levels: list[Path] = []
    while True:
        levels.append(current)
        if git_root is not None and current == git_root:
            break
        if git_root is None and current == home:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent

    roots: list[Path] = []
    seen: set[Path] = set()
    for base in reversed(levels):
        for rel in relative_dirs:
            candidate = (base / rel).resolve()
            if candidate in seen or not candidate.is_dir():
                continue
            seen.add(candidate)
            roots.append(candidate)

    logger.debug("[skills] Discovered %d project skill directories", len(roots))
    return roots


def _valid_project_skill_dirs(project_skill_dirs: Iterable[str]) -> list[Path]:
    """Return safe relative project skill paths."""
    paths: list[Path] = []
    for raw in project_skill_dirs:
        value = str(raw).strip()
        if not value:
            continue
        rel = Path(value)
        if rel.is_absolute() or ".." in rel.parts:
            logger.warning("[skills] Ignoring unsafe project skill dir: %s", raw)
            continue
        paths.append(rel)
    return paths


def _find_git_root(start: Path) -> Path | None:
    """Find the nearest git root containing start, if any."""
    current = start
    while True:
        if (current / ".git").exists():
            logger.debug("[skills] Found git root: %s", current)
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def load_skills_from_dirs(
    directories: Iterable[str | Path] | None,
    *,
    source: str = "user",
    create_missing: bool = True,
) -> list[SkillDefinition]:
    """Load markdown skills from one or more directories.

    Supported layout:
    - ``<root>/<skill-dir>/SKILL.md``
    """
    skills: list[SkillDefinition] = []
    if not directories:
        logger.debug("[skills] No directories provided for loading skills")
        return skills

    seen: set[Path] = set()
    loaded_count = 0
    skipped_count = 0

    for directory in directories:
        root = Path(directory).expanduser().resolve()
        if create_missing:
            root.mkdir(parents=True, exist_ok=True)
        elif not root.is_dir():
            logger.debug("[skills] Directory does not exist or is not a dir: %s", root)
            continue

        candidates: list[Path] = []
        try:
            for child in sorted(root.iterdir()):
                if child.is_dir():
                    skill_path = child / "SKILL.md"
                    if skill_path.exists():
                        candidates.append(skill_path)
        except PermissionError:
            logger.warning("[skills] Permission denied when accessing directory: %s", root)
            continue

        logger.debug("[skills] Found %d skill candidates in %s", len(candidates), root)

        for path in candidates:
            if path in seen:
                skipped_count += 1
                continue
            seen.add(path)

            try:
                content = path.read_text(encoding="utf-8")
                default_name = path.parent.name
                metadata = _parse_skill_metadata(default_name, content)
                name = metadata["name"]
                description = metadata["description"]
                display_name = name if name != default_name else None

                skills.append(
                    SkillDefinition(
                        name=name,
                        description=description,
                        content=content,
                        source=source,
                        path=str(path),
                        base_dir=str(path.parent),
                        command_name=default_name,
                        display_name=display_name,
                        user_invocable=metadata["user_invocable"],
                        disable_model_invocation=metadata["disable_model_invocation"],
                        model=metadata["model"],
                        argument_hint=metadata["argument_hint"],
                        keywords=metadata["keywords"],
                        trigger=metadata["trigger"],
                        negative_trigger=metadata["negative_trigger"],
                        requires=metadata["requires"],
                        bm25_search_keywords=metadata["bm25_search_keywords"],
                    )
                )
                loaded_count += 1
                logger.debug("[skills] Loaded skill '%s' from %s", name, path)
            except Exception as e:
                logger.error("[skills] Failed to load skill from %s: %s", path, e)

    logger.info("[skills] Loaded %d skills from directories (skipped %d duplicates)", loaded_count, skipped_count)
    return skills


def _parse_skill_markdown(default_name: str, content: str) -> tuple[str, str]:
    """Parse name and description from a skill markdown file with YAML frontmatter support."""
    return parse_skill_frontmatter(default_name, content, fallback_template="Skill: {name}")


def _parse_skill_metadata(default_name: str, content: str) -> dict:
    from openharness.skills._frontmatter import (
        optional_frontmatter_str,
        parse_bool_frontmatter,
        parse_frontmatter_list,
        parse_skill_metadata as _parse_skill_frontmatter,
    )

    parsed = _parse_skill_frontmatter(default_name, content, fallback_template="Skill: {name}")
    frontmatter = parsed.get("frontmatter")
    if not isinstance(frontmatter, dict):
        frontmatter = {}
    return {
        "name": str(parsed["name"]),
        "description": str(parsed["description"]),
        "user_invocable": parse_bool_frontmatter(frontmatter.get("user-invocable"), default=True),
        "disable_model_invocation": parse_bool_frontmatter(
            frontmatter.get("disable-model-invocation"),
            default=False,
        ),
        "model": optional_frontmatter_str(frontmatter.get("model")),
        "argument_hint": optional_frontmatter_str(frontmatter.get("argument-hint")),
        # New fields for skill management
        "keywords": parse_frontmatter_list(frontmatter.get("keywords")),
        "trigger": optional_frontmatter_str(frontmatter.get("trigger")),
        "negative_trigger": optional_frontmatter_str(frontmatter.get("negative-trigger")),
        "requires": parse_frontmatter_list(frontmatter.get("requires")),
        "bm25_search_keywords": parse_frontmatter_list(frontmatter.get("bm25-search-keywords")),
    }
