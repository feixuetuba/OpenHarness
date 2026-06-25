"""OpenHarness Web Configuration Manager.

A lightweight FastAPI-based web UI for configuring OpenHarness settings
including providers, models, authentication, permissions, and more.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import shutil
import sys
import time
import traceback
import zipfile
from contextlib import asynccontextmanager
from dataclasses import asdict, is_dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

src_path = Path(__file__).parent.parent / "src"
if src_path.exists() and str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from web_config.channel_runtime import WebConfigChannelRuntime

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime = WebConfigChannelRuntime(cwd=Path.cwd())
    app.state.channel_runtime = runtime
    try:
        await runtime.start(_load_settings())
    except Exception:
        traceback.print_exc()
        # logger.exception("Failed to start OpenHarness channel runtime")
    try:
        yield
    finally:
        await runtime.stop()


app = FastAPI(title="OpenHarness Web Config", lifespan=lifespan)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _load_settings() -> dict[str, Any]:
    """Load current settings from the config file."""
    from openharness.config.paths import get_config_file_path

    config_path = get_config_file_path()
    if config_path.exists():
        data = json.loads(config_path.read_text())
        return data
    return {}


def _save_settings(data: dict[str, Any]) -> None:
    """Save settings to the config file."""
    from openharness.config.paths import get_config_file_path
    from openharness.utils.file_lock import exclusive_file_lock
    from openharness.utils.fs import atomic_write_text

    config_path = get_config_file_path()
    content = json.dumps(data, indent=2, ensure_ascii=False)
    with exclusive_file_lock(config_path):
        atomic_write_text(config_path, content)


def _get_settings_obj():
    """Get the current Settings object."""
    from openharness.config import load_settings
    return load_settings()


def _get_agents_file() -> Path:
    """Return the persisted web-config agent list path."""
    from openharness.config.paths import get_config_dir

    return get_config_dir() / "agents.json"


def _invalidate_runtime_agent(agent_id: str) -> None:
    runtime = getattr(app.state, "channel_runtime", None)
    if runtime is not None:
        runtime.invalidate_agent(agent_id)


def _get_opencad_workspace_file() -> Path:
    """Return the persisted OpenCAD workspace file path."""
    from openharness.config.paths import get_config_dir

    return get_config_dir() / "opencad_workspace.json"


def _get_opencad_workspace_files_dir() -> Path:
    """Return the project-local directory containing materialized OpenCAD files."""
    return Path.cwd() / ".openharness" / "opencad_workspace" / "files"


def _get_opencad_libraries_dir() -> Path:
    """Return the bundled OpenSCAD library directory."""
    return STATIC_DIR / "vendor" / "openscad" / "libraries"


def _get_opencad_workspace_libraries_dir() -> Path:
    """Return the workspace-local OpenSCAD library directory."""
    return _get_opencad_workspace_files_dir()


def _sanitize_opencad_file_name(name: Any) -> str:
    text = re.sub(r'[\\/:*?"<>|]', "_", str(name or "").strip())
    if not text:
        text = "part"
    if not text.lower().endswith(".scad"):
        text = f"{text}.scad"
    return text


def _normalize_opencad_lookup_key(value: Any) -> str:
    text = str(value or "").strip().strip("\"'`“”‘’").strip()
    text = text.lstrip("/")
    return text.lower()


def _opencad_file_path(name: str) -> Path:
    return _get_opencad_workspace_files_dir() / _sanitize_opencad_file_name(name)


def _attach_opencad_file_paths(workspace: dict[str, Any]) -> dict[str, Any]:
    for file in workspace.get("files", []):
        file["local_path"] = str(_opencad_file_path(str(file.get("name") or "part.scad")))
    return workspace


def _materialize_opencad_workspace_files(workspace: dict[str, Any]) -> None:
    from openharness.utils.fs import atomic_write_text

    files_dir = _get_opencad_workspace_files_dir()
    files_dir.mkdir(parents=True, exist_ok=True)
    for file in workspace.get("files", []):
        try:
            atomic_write_text(_opencad_file_path(str(file.get("name") or "part.scad")), str(file.get("code") or ""))
        except Exception:
            traceback.print_exc()
    _materialize_opencad_libraries()


def _materialize_opencad_libraries() -> None:
    source_root = _get_opencad_libraries_dir()
    target_root = _get_opencad_workspace_libraries_dir()
    if not source_root.exists():
        return
    for source in source_root.rglob("*"):
        if not source.is_file():
            continue
        try:
            rel = source.relative_to(source_root)
            target = target_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists() or source.stat().st_mtime_ns > target.stat().st_mtime_ns:
                shutil.copy2(source, target)
        except Exception:
            traceback.print_exc()


def _normalize_opencad_workspace(payload: dict[str, Any] | None) -> dict[str, Any]:
    files: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate((payload or {}).get("files", []) or []):
        if not isinstance(item, dict):
            continue
        name = _sanitize_opencad_file_name(item.get("name") or f"part-{index + 1}.scad")
        file_id = re.sub(r"[^A-Za-z0-9_-]", "_", str(item.get("id") or "").strip())
        if not file_id or file_id in seen_ids:
            file_id = f"file_{index + 1}"
        seen_ids.add(file_id)
        files.append(
            {
                "id": file_id,
                "name": name,
                "code": str(item.get("code") or ""),
            }
        )
    if not files:
        files = [{"id": "file_1", "name": "main.scad", "code": ""}]
    active_file_id = str((payload or {}).get("active_file_id") or "").strip()
    if not any(file["id"] == active_file_id for file in files):
        active_file_id = files[0]["id"]
    return _attach_opencad_file_paths({"files": files, "active_file_id": active_file_id})


def _load_opencad_workspace() -> dict[str, Any]:
    path = _get_opencad_workspace_file()
    if not path.exists():
        return {"files": [], "active_file_id": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        traceback.print_exc()
        return {"files": [], "active_file_id": None}
    workspace = _normalize_opencad_workspace(data)
    _materialize_opencad_workspace_files(workspace)
    return workspace


def _save_opencad_workspace(payload: dict[str, Any]) -> dict[str, Any]:
    from openharness.utils.fs import atomic_write_text

    data = _normalize_opencad_workspace(payload)
    path = _get_opencad_workspace_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False))
    _materialize_opencad_workspace_files(data)
    return data


def _load_agents_payload() -> dict[str, Any]:
    path = _get_agents_file()
    if not path.exists():
        return {"agents": [], "active_agent_id": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        traceback.print_exc()
        return {"agents": [], "active_agent_id": None}
    agents = data.get("agents", [])
    if not isinstance(agents, list):
        agents = []
    active_agent_id = data.get("active_agent_id")
    return {"agents": agents, "active_agent_id": active_agent_id}


def _save_agents_payload(payload: dict[str, Any]) -> None:
    from openharness.utils.fs import atomic_write_text

    path = _get_agents_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False))


def _skill_to_dict(skill) -> dict[str, Any]:
    settings = _get_settings_obj()
    skill_management = getattr(settings, "skill_management", None)
    auto_approve = {
        str(name).strip()
        for name in getattr(skill_management, "auto_approve_skills", []) or []
        if str(name).strip()
    }
    identifiers = _skill_disabled_identifiers(skill)
    return {
        "name": skill.name,
        "command_name": skill.command_name,
        "display_name": skill.display_name,
        "description": skill.description,
        "source": skill.source,
        "path": skill.path,
        "content": skill.content,
        "enabled": getattr(skill, "enabled", True),
        "auto_approve": bool(auto_approve.intersection(identifiers)),
    }


def _skill_disabled_identifiers(skill) -> set[str]:
    return {
        str(value).strip()
        for value in (skill.name, skill.command_name, skill.display_name, *getattr(skill, "aliases", ()))
        if str(value).strip()
    }


def _get_path_aliases() -> dict[str, str]:
    settings = _get_settings_obj()
    skill_management = getattr(settings, "skill_management", None)
    aliases = dict(getattr(skill_management, "path_aliases", {}) or {})

    aliases.setdefault("USKILL", "~/.openharness/skills")
    try:
        from openharness.config.paths import get_data_dir
        aliases.setdefault("UDATA", str(get_data_dir()))
    except Exception:
        traceback.print_exc()
        aliases.setdefault("UDATA", "~/.openharness/data")
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
        path = str(raw_path).strip()
        if name and path:
            normalized[name] = path
    return normalized


def _expanded_path_aliases() -> dict[str, str]:
    return {name: str(Path(path).expanduser().resolve()) for name, path in _get_path_aliases().items()}


def _compress_path_alias(path: str | Path) -> str:
    text = str(path)
    try:
        resolved = str(Path(text).expanduser().resolve())
    except OSError:
        resolved = text
    for name, prefix in sorted(_expanded_path_aliases().items(), key=lambda item: len(item[1]), reverse=True):
        if resolved == prefix:
            return f"${name}"
        if resolved.startswith(prefix + os.sep):
            return f"${name}{resolved[len(prefix):]}"
    return text


def _expand_path_alias(path: str) -> str:
    text = path.strip()
    for name, prefix in _expanded_path_aliases().items():
        token = f"${name}"
        if text == token:
            return prefix
        if text.startswith(token + "/"):
            return prefix + text[len(token):]
    return text


def _model_dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    if is_dataclass(value):
        return _jsonable(asdict(value))
    return dict(value or {})


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value


def _update_settings_section(section: str, values: dict[str, Any]) -> None:
    data = _load_settings()
    current = data.get(section, {})
    if not isinstance(current, dict):
        current = {}
    current.update(values)
    data[section] = current
    _save_settings(data)


def _split_csv_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _sync_social_platforms_to_channels(values: dict[str, Any]) -> None:
    """Keep OpenHarness social settings aligned with runtime channel config."""
    social_file_keys = {"social_file_base_url", "social_file_token", "qq_public_file_base_url"}
    if "qq_enabled" not in values and "wechat_enabled" not in values and not (social_file_keys & set(values)):
        return

    data = _load_settings()
    channels = data.get("channels", {})
    if not isinstance(channels, dict):
        channels = {}

    if "qq_enabled" in values or social_file_keys & set(values):
        qq_config = channels.get("qq", {})
        if not isinstance(qq_config, dict):
            qq_config = {}

        qq_enabled = bool(values.get("qq_enabled", qq_config.get("enabled", False)))
        if qq_enabled:
            qq_config["enabled"] = True
            qq_config["app_id"] = str(values.get("qq_app_id") or qq_config.get("app_id") or "")
            qq_config["app_secret"] = str(
                values.get("qq_app_secret") or qq_config.get("app_secret") or ""
            )
            if "qq_allow_from" in values:
                qq_config["allow_from"] = _split_csv_list(values.get("qq_allow_from"))
            if "qq_sandbox" in values:
                qq_config["sandbox"] = bool(values.get("qq_sandbox"))
            public_file_base_url = (
                values.get("qq_public_file_base_url")
                or values.get("social_file_base_url")
                or qq_config.get("public_file_base_url")
                or ""
            )
            if public_file_base_url:
                qq_config["public_file_base_url"] = str(public_file_base_url)
            public_file_token = values.get("social_file_token") or qq_config.get("public_file_token") or ""
            if public_file_token:
                qq_config["public_file_token"] = str(public_file_token)
            channels["qq"] = qq_config
        else:
            if qq_config:
                qq_config["enabled"] = False
                channels["qq"] = qq_config

    wechat_config = channels.get("wechat", {})
    if not isinstance(wechat_config, dict):
        wechat_config = {}

    if values.get("wechat_enabled"):
        wechat_config["enabled"] = True
        wechat_config["api_url"] = str(values.get("wechat_api_url") or wechat_config.get("api_url") or "")
        wechat_config["app_id"] = str(values.get("wechat_app_id") or wechat_config.get("app_id") or "")
        wechat_config["app_secret"] = str(
            values.get("wechat_app_secret") or wechat_config.get("app_secret") or ""
        )
        wechat_config["token"] = str(values.get("wechat_token") or wechat_config.get("token") or "")
        wechat_config["aes_key"] = str(values.get("wechat_aes_key") or wechat_config.get("aes_key") or "")
        wechat_config.setdefault("allow_from", ["*"])
        channels["wechat"] = wechat_config
    else:
        if wechat_config and "wechat_enabled" in values:
            wechat_config["enabled"] = False
            channels["wechat"] = wechat_config

    data["channels"] = channels
    _save_settings(data)


def _safe_slug(value: str, default: str = "skill") -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip(".-")
    return slug or default


async def _read_multipart_file(request: Request) -> tuple[str, bytes]:
    """Read one uploaded file from multipart/form-data without extra dependencies."""
    from email import policy
    from email.parser import BytesParser

    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type:
        raise HTTPException(status_code=400, detail="Expected multipart/form-data upload")

    body = await request.body()
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
    )
    for part in message.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue
        if part.get_param("name", header="content-disposition") != "file":
            continue
        filename = part.get_filename() or "skill.zip"
        return filename, part.get_payload(decode=True) or b""
    raise HTTPException(status_code=400, detail="No uploaded file field named 'file'")


def _validate_zip_members(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members: list[zipfile.ZipInfo] = []
    for member in zf.infolist():
        path = Path(member.filename)
        if path.is_absolute() or ".." in path.parts:
            raise HTTPException(status_code=400, detail=f"Unsafe zip path: {member.filename}")
        if member.is_dir() or member.filename.startswith("__MACOSX/"):
            continue
        members.append(member)
    if not any(Path(member.filename).name == "SKILL.md" for member in members):
        raise HTTPException(status_code=400, detail="ZIP must contain a SKILL.md file")
    return members


def _zip_skill_root(members: list[zipfile.ZipInfo]) -> Path:
    skill_paths = [Path(member.filename) for member in members if Path(member.filename).name == "SKILL.md"]
    root = skill_paths[0].parent
    return Path(".") if str(root) == "." else root


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

class ProfileUpdate(BaseModel):
    last_model: str | None = None
    default_model: str | None = None
    base_url: str | None = None
    label: str | None = None


class ApiKeyUpdate(BaseModel):
    api_key: str


class SettingsUpdate(BaseModel):
    max_turns: int | None = None
    timeout: float | None = None
    theme: str | None = None
    effort: str | None = None
    passes: int | None = None
    vim_mode: bool | None = None
    fast_mode: bool | None = None
    verbose: bool | None = None
    allow_project_plugins: bool | None = None
    allow_project_skills: bool | None = None


class AgentConfig(BaseModel):
    id: str
    name: str
    system_prompt: str = ""
    profile: str | None = None
    model: str | None = None
    max_turns: int | None = None
    image_profile: str | None = None
    image_model: str | None = None
    audio_profile: str | None = None
    audio_model: str | None = None


class AgentChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    agent_id: str | None = None
    profile: str | None = None
    model: str | None = None
    attachments: list[dict[str, Any]] | None = None


def _validate_agent_attachment_profiles(agent: AgentConfig) -> None:
    """Reject missing profiles and audio transports that cannot carry audio input."""
    profiles = _get_settings_obj().merged_profiles()
    for kind in ("image", "audio"):
        profile_name = str(getattr(agent, f"{kind}_profile") or "").strip()
        model_name = str(getattr(agent, f"{kind}_model") or "").strip()
        if model_name and not profile_name:
            raise HTTPException(
                status_code=400,
                detail=f"{kind}_profile is required when {kind}_model is configured",
            )
        if not profile_name:
            continue
        profile = profiles.get(profile_name)
        if profile is None:
            raise HTTPException(status_code=400, detail=f"Unknown profile: {profile_name}")
        if kind == "audio" and (
            profile.provider == "openai_codex"
            or profile.api_format not in {"openai", "openai_compat", "copilot"}
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Profile '{profile_name}' uses {profile.api_format} and cannot carry "
                    "audio input; choose an OpenAI-compatible profile"
                ),
            )


class OpenCadFile(BaseModel):
    id: str
    name: str
    code: str = ""


class OpenCadWorkspaceUpdate(BaseModel):
    files: list[OpenCadFile]
    active_file_id: str | None = None


@app.get("/")
async def index():
    """Serve the main configuration page."""
    from fastapi.responses import HTMLResponse
    
    html_content = (STATIC_DIR / "index.html").read_text()
    response = HTMLResponse(content=html_content)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/api/opencad/workspace")
async def get_opencad_workspace():
    """Get the persisted OpenCAD workspace."""
    return _load_opencad_workspace()


@app.get("/api/opencad/workspace/summary")
async def get_opencad_workspace_summary():
    """Get a lightweight OpenCAD workspace summary without full source."""
    workspace = _load_opencad_workspace()
    return {
        "active_file_id": workspace.get("active_file_id"),
        "library_root": str(_get_opencad_workspace_libraries_dir()),
        "libraries": [
            {
                "name": path.name,
                "local_path": str(_get_opencad_workspace_libraries_dir() / path.name),
            }
            for path in sorted(_get_opencad_libraries_dir().iterdir())
            if path.is_dir()
        ] if _get_opencad_libraries_dir().exists() else [],
        "files": [
            {
                "id": file.get("id"),
                "name": file.get("name"),
                "local_path": file.get("local_path"),
                "line_count": len(str(file.get("code") or "").splitlines()),
                "char_count": len(str(file.get("code") or "")),
                "active": file.get("id") == workspace.get("active_file_id"),
            }
            for file in workspace.get("files", [])
        ],
    }


@app.get("/api/opencad/workspace/files/{file_key:path}")
async def get_opencad_workspace_file(file_key: str):
    """Get one OpenCAD file by ID or filename."""
    workspace = _load_opencad_workspace()
    key = _normalize_opencad_lookup_key(file_key)
    for file in workspace.get("files", []):
        if _normalize_opencad_lookup_key(file.get("id")) == key or _normalize_opencad_lookup_key(file.get("name")) == key:
            return file
    raise HTTPException(status_code=404, detail=f"OpenCAD file not found: {file_key}")


@app.get("/api/opencad/libraries")
async def get_opencad_libraries():
    """Get OpenSCAD library files for the WASM virtual FS and editor index."""
    files_by_path: dict[str, str] = {}

    def collect_scad_files(root: Path) -> None:
        if not root.exists():
            return
        for path in sorted(root.rglob("*.scad")):
            if not path.is_file():
                continue
            try:
                rel = path.relative_to(root).as_posix()
                files_by_path[rel] = path.read_text(encoding="utf-8")
            except Exception:
                traceback.print_exc()

    collect_scad_files(_get_opencad_libraries_dir())
    collect_scad_files(_get_opencad_workspace_libraries_dir())
    return {
        "files": [
            {"path": path, "content": content}
            for path, content in sorted(files_by_path.items())
        ]
    }


@app.put("/api/opencad/workspace")
async def update_opencad_workspace(req: OpenCadWorkspaceUpdate):
    """Persist the OpenCAD workspace on the server."""
    return _save_opencad_workspace(req.model_dump())


@app.get("/api/settings")
async def get_settings():
    """Get all current settings."""
    from openharness.auth.manager import AuthManager
    from openharness.config.settings import builtin_provider_profile_names

    settings = _get_settings_obj()
    profiles = settings.merged_profiles()
    manager = AuthManager(settings)
    profile_statuses = manager.get_profile_statuses()
    builtin_names = builtin_provider_profile_names()

    # Build profile list with status
    profile_list = []
    for name, profile in profiles.items():
        status = profile_statuses.get(name, {})
        configured = bool(status.get("configured"))
        is_active = name == settings.active_profile
        is_custom = name not in builtin_names
        if not (configured or is_custom):
            continue
        profile_list.append({
            "name": name,
            "label": profile.label,
            "provider": profile.provider,
            "api_format": profile.api_format,
            "auth_source": profile.auth_source,
            "default_model": profile.default_model,
            "last_model": profile.last_model or "",
            "allowed_models": profile.allowed_models,
            "base_url": profile.base_url or "",
            "active": is_active,
            "configured": configured,
            "auth_state": status.get("auth_state", "missing"),
            "builtin": name in builtin_names,
            "credential_slot": profile.credential_slot,
            "credential_configured": configured,
        })

    return {
        "active_profile": settings.active_profile,
        "profiles": profile_list,
        "model": settings.model,
        "max_turns": settings.max_turns,
        "timeout": settings.timeout,
        "theme": settings.theme,
        "effort": settings.effort,
        "passes": settings.passes,
        "vim_mode": settings.vim_mode,
        "fast_mode": settings.fast_mode,
        "verbose": settings.verbose,
        "allow_project_plugins": settings.allow_project_plugins,
        "allow_project_skills": settings.allow_project_skills,
        "permission_mode": settings.permission.mode.value,
        "memory_enabled": settings.memory.enabled,
        "memory_max_files": settings.memory.max_files,
        "sandbox_enabled": settings.sandbox.enabled,
    }


@app.post("/api/profile/{profile_name}/use")
async def use_profile(profile_name: str):
    """Activate a provider profile."""
    from openharness.auth.manager import AuthManager

    manager = AuthManager()
    try:
        manager.use_profile(profile_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "ok", "profile": profile_name}


@app.put("/api/profile/{profile_name}")
async def update_profile(profile_name: str, update: ProfileUpdate):
    """Update a provider profile."""
    from openharness.auth.manager import AuthManager

    manager = AuthManager()
    profiles = manager.list_profiles()
    if profile_name not in profiles:
        raise HTTPException(status_code=404, detail=f"Profile not found: {profile_name}")

    updates = {}
    if update.last_model is not None:
        updates["last_model"] = update.last_model if update.last_model else ""
    if update.default_model is not None:
        updates["default_model"] = update.default_model if update.default_model else ""
    if update.base_url is not None:
        updates["base_url"] = update.base_url if update.base_url else None
    if update.label is not None:
        updates["label"] = update.label

    if updates:
        manager.update_profile(profile_name, **updates)

    return {"status": "ok"}


@app.post("/api/auth/{auth_source}/set-key")
async def set_api_key(auth_source: str, update: ApiKeyUpdate):
    """Set an API key for an auth source."""
    from openharness.auth.manager import AuthManager
    from openharness.auth.storage import store_credential
    from openharness.config.settings import auth_source_provider_name

    manager = AuthManager()
    profiles = manager.list_profiles()

    # Find which profile uses this auth source
    target_profile = None
    for name, profile in profiles.items():
        if profile.auth_source == auth_source:
            target_profile = name
            break

    if target_profile is None:
        # Fall back: store directly under auth_source provider name
        storage_provider = auth_source_provider_name(auth_source)
        store_credential(storage_provider, "api_key", update.api_key)
        return {"status": "ok"}

    # Store the credential using the profile's storage namespace
    manager.store_profile_credential(target_profile, "api_key", update.api_key)

    return {"status": "ok"}


@app.get("/api/profile/{profile_name}/models")
async def get_profile_models(profile_name: str):
    """Get available models for a provider profile."""
    from openharness.config.settings import Settings
    import httpx

    settings = Settings(**_load_settings())
    profiles = settings.merged_profiles()
    profile = profiles.get(profile_name)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Profile not found: {profile_name}")

    models: list[str] = []

    # Try to fetch models from the API first
    try:
        tmp_settings = Settings(**settings.model_dump())
        tmp_settings.active_profile = profile_name
        tmp_settings = tmp_settings.materialize_active_profile()

        api_format = getattr(tmp_settings, "api_format", "openai") or "openai"
        base_url = (getattr(tmp_settings, "base_url", "") or "").strip().rstrip("/")
        resolved_auth = tmp_settings.resolve_auth()
        api_key = resolved_auth.value if resolved_auth else ""

        if base_url:
            url = f"{base_url}/models" if base_url.endswith("/v1") else f"{base_url}/v1/models"
            headers = {"Content-Type": "application/json"}
            if api_format == "anthropic":
                headers["x-api-key"] = api_key
            else:
                headers["Authorization"] = f"Bearer {api_key}"
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                payload = response.json()
            raw_models = payload.get("data") or payload.get("models") or []
            models = [item.get("id") or item.get("name") for item in raw_models if isinstance(item, dict)]
            models = [m for m in models if m]
    except Exception:
        traceback.print_exc()

    # Fall back to known models from profile config
    if not models:
        models = _profile_model_options(profile)

    # Always include the profile's default_model and last_model as fallbacks
    for m in [profile.default_model, profile.last_model]:
        if m and m not in models:
            models.append(m)

    return {"profile": profile_name, "models": models}


@app.get("/api/profiles/all")
async def get_all_profiles():
    """Get all provider profiles for introspection provider selection."""
    from openharness.config.settings import Settings

    settings = Settings(**_load_settings())
    profiles = settings.merged_profiles()
    result = []
    for name, profile in sorted(profiles.items()):
        result.append({
            "name": name,
            "label": getattr(profile, "label", name) or name,
            "default_model": getattr(profile, "default_model", "") or "",
            "provider": getattr(profile, "provider", "") or "",
        })
    return {"profiles": result}


@app.post("/api/profile/{profile_name}/set-key")
async def set_profile_api_key(profile_name: str, update: ApiKeyUpdate):
    """Set an API key for one specific profile."""
    from openharness.auth.manager import AuthManager
    from openharness.config.settings import auth_source_uses_api_key, builtin_provider_profile_names

    manager = AuthManager()
    profiles = manager.list_profiles()
    profile = profiles.get(profile_name)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Profile not found: {profile_name}")
    if not auth_source_uses_api_key(profile.auth_source):
        raise HTTPException(status_code=400, detail=f"Profile {profile_name} does not use API key auth")

    if profile_name not in builtin_provider_profile_names() and not profile.credential_slot:
        manager.update_profile(profile_name, credential_slot=profile_name)

    manager.store_profile_credential(profile_name, "api_key", update.api_key)
    return {"status": "ok", "profile": profile_name}


@app.put("/api/settings")
async def update_settings(update: SettingsUpdate):
    """Update general settings."""
    data = _load_settings()

    updates = {}
    for field in update.model_fields_set:
        value = getattr(update, field)
        if value is not None:
            updates[field] = value

    if updates:
        data.update(updates)
        _save_settings(data)

    return {"status": "ok", "updated": list(updates.keys())}


@app.post("/api/settings/permission-mode")
async def set_permission_mode(mode: str):
    """Set the permission mode."""
    from openharness.permissions.modes import PermissionMode

    try:
        PermissionMode(mode)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid permission mode: {mode}")

    data = _load_settings()

    if "permission" not in data:
        data["permission"] = {}
    data["permission"]["mode"] = mode
    _save_settings(data)

    return {"status": "ok", "mode": mode}


@app.get("/api/providers")
async def list_providers():
    """List all available provider presets."""
    from openharness.config.settings import default_provider_profiles

    profiles = default_provider_profiles()
    suggested_names = {
        "claude-api": "anthropic-api",
        "claude-subscription": "claude-subscription-profile",
        "openai-compatible": "openai-compatible-api",
        "codex": "codex-subscription-profile",
        "qwen": "qwen-dashscope",
    }
    result = []
    for name, profile in profiles.items():
        result.append({
            "name": suggested_names.get(name, f"{name}-profile"),
            "label": profile.label,
            "provider": profile.provider,
            "api_format": profile.api_format,
            "auth_source": profile.auth_source,
            "default_model": profile.default_model,
            "base_url": profile.base_url,
        })
    return result


@app.post("/api/profile/add")
async def add_profile(profile_data: dict):
    """Add a custom provider profile."""
    from openharness.auth.manager import AuthManager
    from openharness.config.settings import ProviderProfile, auth_source_uses_api_key

    name = str(profile_data.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="Profile name is required")
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-")
    if safe_name != name:
        raise HTTPException(status_code=400, detail="Profile name can only contain letters, numbers, '.', '_' and '-'")

    provider = str(profile_data.get("provider", "openai") or "openai").strip()
    api_format = str(profile_data.get("api_format", "openai") or "openai").strip()
    auth_source = str(profile_data.get("auth_source") or "").strip()
    if not auth_source:
        auth_source = f"{provider}_api_key" if api_format == "openai" else "anthropic_api_key"
    credential_slot = profile_data.get("credential_slot")
    if credential_slot is None and auth_source_uses_api_key(auth_source):
        credential_slot = name

    profile = ProviderProfile(
        label=profile_data.get("label", name),
        provider=provider,
        api_format=api_format,
        auth_source=auth_source,
        default_model=str(profile_data.get("default_model") or ""),
        base_url=profile_data.get("base_url") or None,
        credential_slot=credential_slot,
    )

    manager = AuthManager()
    manager.upsert_profile(name, profile)

    return {"status": "ok", "profile": name}


@app.delete("/api/profile/{profile_name}")
async def remove_profile(profile_name: str):
    """Remove a custom provider profile."""
    from openharness.auth.manager import AuthManager
    from openharness.config.settings import builtin_provider_profile_names

    if profile_name in builtin_provider_profile_names():
        raise HTTPException(status_code=400, detail="Cannot remove built-in profiles")

    manager = AuthManager()
    manager.remove_profile(profile_name)

    return {"status": "ok"}


@app.get("/api/auth/status")
async def auth_status():
    """Get authentication status for all sources."""
    from openharness.auth.manager import AuthManager

    manager = AuthManager()
    statuses = manager.get_auth_source_statuses()
    return statuses


@app.get("/api/agents")
async def get_agents():
    """Get all web-config agent presets."""
    return _load_agents_payload()


@app.post("/api/agents")
async def create_agent(agent: AgentConfig):
    """Create a web-config agent preset."""
    _validate_agent_attachment_profiles(agent)
    payload = _load_agents_payload()
    agents = payload["agents"]
    if any(existing.get("id") == agent.id for existing in agents):
        raise HTTPException(status_code=400, detail=f"Agent with ID '{agent.id}' already exists")

    agent_data = agent.model_dump()
    agents.append(agent_data)
    if not payload.get("active_agent_id"):
        payload["active_agent_id"] = agent.id
    _save_agents_payload(payload)
    return {"status": "ok", "agent": agent_data}


@app.put("/api/agents/{agent_id}")
async def update_agent(agent_id: str, agent: AgentConfig):
    """Update a web-config agent preset."""
    _validate_agent_attachment_profiles(agent)
    payload = _load_agents_payload()
    agents = payload["agents"]
    for index, existing in enumerate(agents):
        if existing.get("id") == agent_id:
            agents[index] = agent.model_dump()
            if payload.get("active_agent_id") == agent_id:
                payload["active_agent_id"] = agent.id
            _save_agents_payload(payload)
            _invalidate_runtime_agent(agent_id)
            return {"status": "ok", "agent": agents[index]}
    raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")


@app.delete("/api/agents/{agent_id}")
async def delete_agent(agent_id: str):
    """Delete a web-config agent preset."""
    payload = _load_agents_payload()
    agents = payload["agents"]
    remaining = [agent for agent in agents if agent.get("id") != agent_id]
    if len(remaining) == len(agents):
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    payload["agents"] = remaining
    if payload.get("active_agent_id") == agent_id:
        payload["active_agent_id"] = remaining[0].get("id") if remaining else None
    _save_agents_payload(payload)
    _invalidate_runtime_agent(agent_id)
    return {"status": "ok"}


@app.post("/api/agents/{agent_id}/activate")
async def activate_agent(agent_id: str):
    """Activate a web-config agent preset."""
    payload = _load_agents_payload()
    if not any(agent.get("id") == agent_id for agent in payload["agents"]):
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    payload["active_agent_id"] = agent_id
    _save_agents_payload(payload)
    return {"status": "ok", "active_agent_id": agent_id}


@app.get("/api/skills")
async def list_skills():
    """List available skills."""
    from openharness.skills import load_skill_registry

    registry = load_skill_registry(Path.cwd(), include_disabled=True)
    return [_skill_to_dict(skill) for skill in registry.list_skills()]


@app.get("/api/skills/{skill_name}")
async def get_skill(skill_name: str):
    """Get one skill's details."""
    from openharness.skills import load_skill_registry

    skill = load_skill_registry(Path.cwd(), include_disabled=True).get(skill_name)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")
    return _skill_to_dict(skill)


@app.post("/api/skills/reload")
async def reload_skills():
    """Reload skills by rebuilding the registry."""
    from openharness.skills import load_skill_registry

    skills = load_skill_registry(Path.cwd()).list_skills()
    return {"status": "ok", "count": len(skills)}


@app.post("/api/skills/{skill_name}/toggle")
async def toggle_skill(skill_name: str, data: dict):
    """Enable or disable a skill for model/tool discovery."""
    from openharness.skills import load_skill_registry

    skill = load_skill_registry(Path.cwd(), include_disabled=True).get(skill_name)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")

    enabled = bool(data.get("enabled", True))
    settings_data = _load_settings()
    skill_management = dict(settings_data.get("skill_management") or {})
    disabled = {
        str(name).strip()
        for name in skill_management.get("disabled_skills", [])
        if str(name).strip()
    }
    identifiers = _skill_disabled_identifiers(skill)
    disabled.difference_update(identifiers)
    if not enabled:
        disabled.add(skill.command_name or skill.name)
    skill_management["disabled_skills"] = sorted(disabled)
    settings_data["skill_management"] = skill_management
    _save_settings(settings_data)
    return {"status": "ok", "skill": skill.command_name or skill.name, "enabled": enabled}


@app.post("/api/skills/{skill_name}/auto-approve")
async def toggle_skill_auto_approve(skill_name: str, data: dict):
    """Allow or deny automatic tool approval after a skill is used in social channels."""
    from openharness.skills import load_skill_registry

    skill = load_skill_registry(Path.cwd(), include_disabled=True).get(skill_name)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")

    enabled = bool(data.get("enabled", True))
    settings_data = _load_settings()
    skill_management = dict(settings_data.get("skill_management") or {})
    approved = {
        str(name).strip()
        for name in skill_management.get("auto_approve_skills", [])
        if str(name).strip()
    }
    identifiers = _skill_disabled_identifiers(skill)
    approved.difference_update(identifiers)
    if enabled:
        approved.add(skill.command_name or skill.name)
    skill_management["auto_approve_skills"] = sorted(approved)
    settings_data["skill_management"] = skill_management
    _save_settings(settings_data)
    return {"status": "ok", "skill": skill.command_name or skill.name, "auto_approve": enabled}


@app.post("/api/skills/install")
async def install_skill(data: dict):
    """Return a clear response for web installs that require a CLI-capable workflow."""
    url = str(data.get("url", "")).strip()
    if not url:
        raise HTTPException(status_code=400, detail="Skill URL is required")
    raise HTTPException(
        status_code=501,
        detail="Skill installation from URL is not implemented in the web config server yet.",
    )


@app.post("/api/skills/upload-zip")
async def upload_skill_zip(request: Request):
    """Install a user skill from an uploaded ZIP archive."""
    from openharness.skills.loader import get_user_skills_dir, load_skills_from_dirs

    filename, content = await _read_multipart_file(request)
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Uploaded file must be a ZIP archive")
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded ZIP is empty")

    try:
        zf = zipfile.ZipFile(BytesIO(content))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid ZIP archive")

    with zf:
        members = _validate_zip_members(zf)
        source_root = _zip_skill_root(members)
        skill_name = _safe_slug(source_root.name if str(source_root) != "." else Path(filename).stem)
        target_dir = get_user_skills_dir() / skill_name
        if target_dir.exists():
            raise HTTPException(status_code=409, detail=f"Skill already exists: {skill_name}")

        target_dir.mkdir(parents=True, exist_ok=False)
        try:
            for member in members:
                member_path = Path(member.filename)
                if source_root != Path("."):
                    try:
                        relative_path = member_path.relative_to(source_root)
                    except ValueError:
                        continue
                else:
                    relative_path = member_path
                if str(relative_path) == ".":
                    continue
                destination = target_dir / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(zf.read(member))
        except Exception:
            shutil.rmtree(target_dir, ignore_errors=True)
            raise

    installed = [
        skill
        for skill in load_skills_from_dirs([target_dir.parent], source="user", create_missing=False)
        if Path(skill.base_dir or "").resolve() == target_dir.resolve()
    ]
    if not installed:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="ZIP did not install a loadable skill")

    skill = installed[0]
    return {
        "status": "ok",
        "message": f"Installed skill: {skill.name}",
        "skill": _skill_to_dict(skill),
    }


@app.delete("/api/skills/{skill_name}")
async def delete_skill(skill_name: str):
    """Delete a user skill."""
    from openharness.skills import load_skill_registry
    from openharness.skills.loader import get_user_skill_dirs

    skill = load_skill_registry(Path.cwd(), include_disabled=True).get(skill_name)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")
    if skill.source != "user" or not skill.path:
        raise HTTPException(status_code=400, detail="Only user skills can be deleted")

    target = Path(skill.path).expanduser().resolve()
    allowed_roots = [path.expanduser().resolve() for path in get_user_skill_dirs()]
    if not any(target == root or root in target.parents for root in allowed_roots):
        raise HTTPException(status_code=400, detail="Refusing to delete a skill outside user skill dirs")
    if target.is_dir():
        shutil.rmtree(target)
    elif target.exists():
        target.unlink()
    return {"status": "ok", "message": f"Deleted skill: {skill_name}"}


@app.get("/api/skills/{skill_name}/download")
async def download_skill(skill_name: str):
    """Download a skill as a zip file."""
    from openharness.skills import load_skill_registry

    skill = load_skill_registry(Path.cwd(), include_disabled=True).get(skill_name)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        if skill.path and Path(skill.path).exists():
            source = Path(skill.path)
            if source.is_dir():
                for item in source.rglob("*"):
                    if item.is_file():
                        archive.write(item, item.relative_to(source.parent))
            else:
                archive.write(source, source.name)
        else:
            archive.writestr("SKILL.md", skill.content)
    buffer.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="{skill.name}.zip"'}
    return StreamingResponse(buffer, media_type="application/zip", headers=headers)


@app.get("/api/sessions")
async def list_sessions():
    """List saved sessions for the server working directory."""
    from openharness.services import session_storage

    return session_storage.list_session_snapshots(Path.cwd(), limit=50)


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """Get a saved session."""
    from openharness.services import session_storage

    session = session_storage.load_session_by_id(Path.cwd(), session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return session


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a saved session."""
    from openharness.services import session_storage

    session_dir = session_storage.get_project_session_dir(Path.cwd())
    deleted = False
    session_path = session_dir / f"session-{session_id}.json"
    if session_path.exists():
        session_path.unlink()
        deleted = True

    latest_path = session_dir / "latest.json"
    if latest_path.exists():
        try:
            latest = json.loads(latest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            latest = {}
        if session_id == "latest" or latest.get("session_id") == session_id:
            latest_path.unlink()
            deleted = True

    if not deleted:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return {"status": "ok"}


@app.get("/api/sessions/{session_id}/user-messages")
async def list_session_user_messages(session_id: str):
    """List user messages in a saved session."""
    from openharness.services.session_storage import list_user_messages_in_session

    return {"user_messages": list_user_messages_in_session(Path.cwd(), session_id)}


@app.post("/api/sessions/{session_id}/fork")
async def fork_session(session_id: str, data: dict):
    """Fork a saved session at a user-selected message index."""
    from openharness.services.session_storage import fork_session_from_message

    message_index = data.get("message_index")
    if message_index is None:
        raise HTTPException(status_code=400, detail="message_index is required")
    result = fork_session_from_message(
        cwd=Path.cwd(),
        source_session_id=session_id,
        fork_at_message_index=int(message_index),
        new_session_id=data.get("new_session_id") or None,
    )
    if result is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    forked_session_id = (data.get("new_session_id") or result.stem.replace("session-", ""))
    return {
        "status": "ok",
        "forked_session_id": forked_session_id,
        "source_session_id": session_id,
        "forked_at_index": int(message_index),
    }


@app.get("/api/social-platforms")
async def get_social_platforms():
    """Get social platform settings."""
    return _model_dump(_get_settings_obj().social_platforms)


@app.put("/api/social-platforms")
async def update_social_platforms(data: dict):
    """Update social platform settings."""
    if "social_context_max_messages" in data:
        try:
            context_max_messages = int(data["social_context_max_messages"])
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400,
                detail="social_context_max_messages must be a non-negative integer",
            )
        if context_max_messages < 0:
            raise HTTPException(
                status_code=400,
                detail="social_context_max_messages must be a non-negative integer",
            )
        data = {**data, "social_context_max_messages": context_max_messages}
    _update_settings_section("social_platforms", data)
    _sync_social_platforms_to_channels(data)
    runtime = getattr(app.state, "channel_runtime", None)
    if runtime is not None:
        try:
            await runtime.restart(_load_settings())
        except Exception:
            logger.exception("Failed to restart OpenHarness channel runtime")
            raise HTTPException(status_code=500, detail="Saved config, but failed to restart channels")
    return {"status": "ok"}


@app.get("/api/social/files/{encoded_path:path}")
async def download_social_file(encoded_path: str, token: str = ""):
    """Serve generated social files through a constrained, tokenable URL."""
    expected_token = os.environ.get("OPENHARNESS_SOCIAL_FILE_TOKEN", "").strip()
    if expected_token and token != expected_token:
        raise HTTPException(status_code=403, detail="Invalid token")

    try:
        padding = "=" * (-len(encoded_path) % 4)
        raw_path = base64.urlsafe_b64decode((encoded_path + padding).encode("ascii")).decode("utf-8")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file reference")

    path = Path(raw_path).expanduser().resolve()
    allowed_roots = [
        (Path.cwd() / ".openharness" / "social_outputs").resolve(),
        (Path(os.environ.get("OPENHARNESS_SOCIAL_DIR") or os.environ.get("OPENHARNESS_SOCIAL_ROOT") or "~/.openharness/social").expanduser()).resolve(),
    ]
    try:
        from openharness.config.paths import get_data_dir

        allowed_roots.append((get_data_dir() / "media").resolve())
    except Exception:
        logger.debug("Unable to include OpenHarness data media root", exc_info=True)

    if not any(path.is_relative_to(root) for root in allowed_roots):
        raise HTTPException(status_code=403, detail="File is outside social output roots")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=path.name)


@app.post("/api/social-platforms/{platform_name}/test")
async def test_social_platform(platform_name: str, data: dict = None):
    """Test connection to a social platform."""
    from openharness.channels.social_sdk import SDKRegistry
    
    if data is None:
        data = {}
    
    try:
        settings = _get_settings_obj()
        current_config = settings.social_platforms
        
        if platform_name == "feishu":
            from openharness.channels.social_sdk import FeishuConfig
            config = FeishuConfig(
                enabled=data.get("enabled", current_config.feishu_enabled),
                api_url=data.get("api_url", current_config.feishu_api_url),
                app_id=data.get("app_id", current_config.feishu_app_id),
                app_secret=data.get("app_secret", current_config.feishu_app_secret),
                encrypt_key=data.get("encrypt_key", ""),
                verification_token=data.get("verification_token", ""),
                domain=data.get("domain", data.get("api_url", "") or "https://open.feishu.cn"),
            )
        elif platform_name == "wechat":
            from openharness.channels.social_sdk import WechatConfig
            config = WechatConfig(
                enabled=data.get("enabled", current_config.wechat_enabled),
                api_url=data.get("api_url", current_config.wechat_api_url),
                app_id=data.get("app_id", ""),
                app_secret=data.get("app_secret", ""),
                token=data.get("token", current_config.wechat_token),
                aes_key=data.get("aes_key", current_config.wechat_aes_key),
            )
        elif platform_name == "qq":
            from openharness.channels.social_sdk import QQConfig
            config = QQConfig(
                enabled=data.get("enabled", current_config.qq_enabled),
                api_url=data.get("api_url", current_config.qq_api_url),
                app_id=data.get("app_id", current_config.qq_app_id),
                app_secret=data.get("app_secret", current_config.qq_app_secret),
                redirect_uri=data.get("redirect_uri", ""),
            )
        elif platform_name == "dingtalk":
            from openharness.channels.social_sdk import DingtalkConfig
            config = DingtalkConfig(
                enabled=data.get("enabled", False),
                api_url=data.get("api_url", ""),
                app_key=data.get("app_key", ""),
                app_secret=data.get("app_secret", ""),
                robot_code=data.get("robot_code", ""),
            )
        else:
            raise HTTPException(status_code=404, detail=f"Unknown platform: {platform_name}")
        
        sdk = SDKRegistry.create_sdk(platform_name, config)
        if sdk is None:
            raise HTTPException(status_code=404, detail=f"No SDK adapter for platform: {platform_name}")
        
        if not sdk.is_sdk_available():
            return {
                "success": False,
                "message": f"{platform_name} SDK not installed",
                "error": f"Please install the required SDK package for {platform_name}",
            }
        
        result = await sdk.test_connection()
        
        return {
            "success": result.success,
            "message": result.message,
            "details": result.details,
            "error": result.error,
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Test failed: {str(e)}")


@app.get("/api/channels/status")
async def get_channels_status():
    """Get runtime channel status for the web-config process."""
    runtime = getattr(app.state, "channel_runtime", None)
    if runtime is None:
        return {"running_channels": [], "channels": {}}
    manager = getattr(runtime, "_manager", None)
    return {
        "running_channels": runtime.running_channels,
        "channels": manager.get_status() if manager is not None else {},
    }


@app.get("/api/social/wechat/callback")
async def verify_wechat_callback(request: Request):
    """Verify WeChat Official Account callback URL."""
    runtime = getattr(app.state, "channel_runtime", None)
    manager = getattr(runtime, "_manager", None) if runtime is not None else None
    channel = manager.get_channel("wechat") if manager is not None else None
    if channel is None:
        raise HTTPException(status_code=404, detail="WeChat channel is not enabled")

    params = dict(request.query_params)
    if not channel.verify_signature(
        params.get("signature", ""),
        params.get("timestamp", ""),
        params.get("nonce", ""),
    ):
        raise HTTPException(status_code=403, detail="Invalid WeChat signature")
    return Response(content=params.get("echostr", ""), media_type="text/plain")


@app.post("/api/social/wechat/callback")
async def receive_wechat_callback(request: Request):
    """Receive WeChat Official Account message callbacks."""
    runtime = getattr(app.state, "channel_runtime", None)
    manager = getattr(runtime, "_manager", None) if runtime is not None else None
    channel = manager.get_channel("wechat") if manager is not None else None
    if channel is None:
        raise HTTPException(status_code=404, detail="WeChat channel is not enabled")

    params = dict(request.query_params)
    if not channel.verify_signature(
        params.get("signature", ""),
        params.get("timestamp", ""),
        params.get("nonce", ""),
    ):
        raise HTTPException(status_code=403, detail="Invalid WeChat signature")
    result = await channel.handle_callback_xml(await request.body(), params)
    return Response(content=result, media_type="text/plain")


@app.get("/api/skill-management")
async def get_skill_management():
    """Get skill management settings."""
    data = _model_dump(_get_settings_obj().skill_management)
    aliases = dict(data.get("path_aliases") or {})
    for name, path in _get_path_aliases().items():
        aliases.setdefault(name, path)
    data["path_aliases"] = aliases
    return data


@app.put("/api/skill-management")
async def update_skill_management(data: dict):
    """Update skill management settings."""
    _update_settings_section("skill_management", data)
    return {"status": "ok"}


@app.get("/api/memory-settings")
async def get_memory_settings():
    """Get memory settings."""
    return _model_dump(_get_settings_obj().memory)


@app.put("/api/memory-settings")
async def update_memory_settings(data: dict):
    """Update memory settings."""
    _update_settings_section("memory", data)
    return {"status": "ok"}


@app.get("/api/memory/entries")
async def list_memory_entries():
    """List memory entries."""
    try:
        from openharness.memory import scan_memory_files

        return [
            {
                "id": header.id,
                "title": header.title,
                "description": header.description,
                "type": header.memory_type,
                "path": str(header.path),
                "modified_at": header.modified_at,
                "importance": header.importance,
            }
            for header in scan_memory_files(Path.cwd(), max_files=200)
        ]
    except Exception as exc:
        return {"error": str(exc), "entries": []}


@app.post("/api/memory/entries")
async def add_memory_entry(entry_data: dict):
    """Add a memory entry."""
    try:
        from openharness.memory import add_memory_entry

        title = str(entry_data.get("title") or entry_data.get("name") or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="Memory entry title is required")
        path = add_memory_entry(Path.cwd(), title, str(entry_data.get("content", "")))
        return {"status": "ok", "path": str(path)}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/api/memory/entries/{entry_name}")
async def delete_memory_entry(entry_name: str):
    """Delete a memory entry."""
    try:
        from openharness.memory import remove_memory_entry

        if not remove_memory_entry(Path.cwd(), entry_name):
            raise HTTPException(status_code=404, detail=f"Memory entry not found: {entry_name}")
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/memory/md")
async def get_memory_md():
    """Get MEMORY.md content."""
    from openharness.memory.paths import get_memory_entrypoint

    entrypoint = get_memory_entrypoint(Path.cwd())
    return {"content": entrypoint.read_text(encoding="utf-8") if entrypoint.exists() else ""}


@app.post("/api/memory/md")
async def update_memory_md(data: dict):
    """Update MEMORY.md content."""
    from openharness.memory.paths import get_memory_entrypoint
    from openharness.utils.fs import atomic_write_text

    atomic_write_text(get_memory_entrypoint(Path.cwd()), str(data.get("content", "")))
    return {"status": "ok"}


def _introspection_events_path() -> Path:
    from openharness.introspection.config import IntrospectionConfig

    return IntrospectionConfig.from_settings(_get_settings_obj()).get_events_path(Path.cwd())


class IntrospectionSettingsUpdate(BaseModel):
    """Update introspection settings."""
    enabled: bool | None = None
    auto_reflect: bool | None = None
    reflection_provider: str | None = None
    reflection_model: str | None = None
    min_confidence_threshold: float | None = None
    top_k_experiences: int | None = None
    reflection_timeout_seconds: float | None = None
    injection_mode: str | None = None
    min_tool_calls_for_reflection: int | None = None


@app.get("/api/introspection/settings")
async def get_introspection_settings():
    """Get current introspection settings."""
    settings = _get_settings_obj()
    intro = getattr(settings, "introspection", None)
    if intro is None:
        return {
            "enabled": False,
            "auto_reflect": False,
            "reflection_provider": "",
            "reflection_model": "",
            "min_confidence_threshold": 0.7,
            "top_k_experiences": 5,
            "reflection_timeout_seconds": 60.0,
            "injection_mode": "reference",
            "min_tool_calls_for_reflection": 2,
        }
    return {
        "enabled": getattr(intro, "enabled", False),
        "auto_reflect": getattr(intro, "auto_reflect", False),
        "reflection_provider": getattr(intro, "reflection_provider", ""),
        "reflection_model": getattr(intro, "reflection_model", ""),
        "min_confidence_threshold": getattr(intro, "min_confidence_threshold", 0.7),
        "top_k_experiences": getattr(intro, "top_k_experiences", 5),
        "reflection_timeout_seconds": getattr(intro, "reflection_timeout_seconds", 60.0),
        "injection_mode": getattr(intro, "injection_mode", "reference"),
        "min_tool_calls_for_reflection": getattr(intro, "min_tool_calls_for_reflection", 2),
    }


@app.put("/api/introspection/settings")
async def update_introspection_settings(update: IntrospectionSettingsUpdate):
    """Update introspection settings."""
    data = _load_settings()
    intro = data.get("introspection", {})

    for field in update.model_fields_set:
        value = getattr(update, field)
        if value is not None:
            intro[field] = value

    data["introspection"] = intro
    _save_settings(data)
    return {"status": "ok", "updated": list(update.model_fields_set)}


@app.get("/api/introspection/events")
async def list_introspection_events(
    limit: int = 200,
    source_kind: str | None = None,
    reflection_id: str | None = None,
    level: str | None = None,
):
    """List web-safe introspection events."""
    from openharness.introspection.web import load_events

    safe_limit = max(1, min(int(limit), 1000))
    events = load_events(
        _introspection_events_path(),
        limit=safe_limit,
        source_kind=source_kind or None,
        reflection_id=reflection_id or None,
        level=level or None,
    )
    return {"events": [_model_dump(event) for event in events]}


@app.get("/api/introspection/reflections")
async def list_introspection_reflections(limit: int = 50):
    """List introspection reflection run summaries."""
    from openharness.introspection.web import get_reflection_summaries

    safe_limit = max(1, min(int(limit), 500))
    return {
        "reflections": get_reflection_summaries(
            _introspection_events_path(),
            limit=safe_limit,
        )
    }


@app.get("/api/introspection/reflections/{reflection_id}")
async def get_introspection_reflection(reflection_id: str):
    """Get details for a single introspection reflection run."""
    from openharness.introspection.web import get_reflection_detail

    detail = get_reflection_detail(_introspection_events_path(), reflection_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Reflection not found: {reflection_id}")
    return detail


@app.get("/api/introspection/memories")
async def list_introspection_memories(limit: int = 100):
    """List durable memories written by introspection."""
    from openharness.introspection.web import get_introspection_memories

    safe_limit = max(1, min(int(limit), 500))
    return {
        "memories": get_introspection_memories(
            _introspection_events_path(),
            limit=safe_limit,
        )
    }


@app.get("/api/plugins")
async def list_plugins():
    """List project plugins."""
    from openharness.plugins.loader import load_plugins

    plugins = []
    for plugin in load_plugins(_get_settings_obj(), Path.cwd()):
        plugins.append({
            "name": plugin.name,
            "version": plugin.version,
            "description": plugin.description,
            "enabled": plugin.enabled,
        })
    return plugins


@app.post("/api/plugins/install")
async def install_plugin(data: dict):
    """Return a clear response for plugin installs that are not wired yet."""
    if not str(data.get("path", "")).strip():
        raise HTTPException(status_code=400, detail="Plugin path is required")
    raise HTTPException(status_code=501, detail="Plugin installation is not implemented in the web config server yet.")


@app.post("/api/plugins/{plugin_name}/toggle")
async def toggle_plugin(plugin_name: str):
    """Toggle a plugin enablement flag."""
    data = _load_settings()
    enabled = data.setdefault("enabled_plugins", {})
    if not isinstance(enabled, dict):
        enabled = {}
        data["enabled_plugins"] = enabled
    enabled[plugin_name] = not bool(enabled.get(plugin_name, True))
    _save_settings(data)
    return {"status": "ok", "enabled": enabled[plugin_name]}


@app.delete("/api/plugins/{plugin_name}")
async def uninstall_plugin(plugin_name: str):
    """Return a clear response for plugin uninstall."""
    raise HTTPException(status_code=501, detail="Plugin uninstall is not implemented in the web config server yet.")


def _mcp_servers_list() -> list[dict[str, Any]]:
    settings = _get_settings_obj()
    servers = []
    raw_enabled = _load_settings().get("enabled_mcp_servers", {})
    enabled_flags = raw_enabled if isinstance(raw_enabled, dict) else {}
    for name, config in settings.mcp_servers.items():
        payload = _model_dump(config)
        payload["name"] = name
        payload["enabled"] = bool(enabled_flags.get(name, True))
        servers.append(payload)
    return servers


@app.get("/api/mcp/servers")
async def list_mcp_servers_alias():
    """List configured MCP servers."""
    return _mcp_servers_list()


@app.post("/api/mcp/servers")
async def add_mcp_server(server_data: dict):
    """Add an MCP server entry."""
    name = str(server_data.get("name", "")).strip()
    command = str(server_data.get("command", "")).strip()
    if not name or not command:
        raise HTTPException(status_code=400, detail="name and command are required")
    data = _load_settings()
    mcp_servers = data.setdefault("mcp_servers", {})
    if not isinstance(mcp_servers, dict):
        mcp_servers = {}
        data["mcp_servers"] = mcp_servers
    mcp_servers[name] = {
        "type": "stdio",
        "command": command,
        "args": server_data.get("args") or [],
    }
    _save_settings(data)
    return {"status": "ok", "name": name}


@app.post("/api/mcp/servers/{server_name}/toggle")
async def toggle_mcp_server(server_name: str):
    """Toggle an MCP server enablement flag."""
    data = _load_settings()
    enabled = data.setdefault("enabled_mcp_servers", {})
    if not isinstance(enabled, dict):
        enabled = {}
        data["enabled_mcp_servers"] = enabled
    enabled[server_name] = not bool(enabled.get(server_name, True))
    _save_settings(data)
    return {"status": "ok", "enabled": enabled[server_name]}


@app.delete("/api/mcp/servers/{server_name}")
async def delete_mcp_server(server_name: str):
    """Delete an MCP server entry."""
    data = _load_settings()
    mcp_servers = data.get("mcp_servers", {})
    if not isinstance(mcp_servers, dict) or server_name not in mcp_servers:
        raise HTTPException(status_code=404, detail=f"MCP server not found: {server_name}")
    del mcp_servers[server_name]
    _save_settings(data)
    return {"status": "ok"}


@app.get("/api/tasks")
async def list_tasks():
    """List background tasks."""
    try:
        from openharness.tasks import get_task_manager

        return [
            _model_dump(task)
            for task in get_task_manager().list_tasks()
        ]
    except Exception as exc:
        return {"error": str(exc), "tasks": []}


@app.post("/api/test-connection")
async def test_connection(req: dict):
    """Test a model server by requesting its model list."""
    import httpx

    base_url = str(req.get("base_url", "")).strip().rstrip("/")
    if not base_url:
        return {"success": False, "message": "base_url is required", "models": []}
    api_key = str(req.get("api_key") or "").strip()
    profile_name = str(req.get("profile_name") or "").strip()
    if not api_key and profile_name:
        try:
            settings = _get_settings_obj()
            profile_settings = settings.model_copy(update={"active_profile": profile_name}).materialize_active_profile()
            api_key = profile_settings.resolve_auth().value
        except Exception:
            api_key = ""
    if not api_key:
        api_key = "sk-placeholder"
    api_format = str(req.get("api_format") or "openai").lower()
    url = f"{base_url}/models" if base_url.endswith("/v1") else f"{base_url}/v1/models"
    headers = {"Content-Type": "application/json"}
    if api_format == "anthropic":
        headers["x-api-key"] = api_key
    else:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
        raw_models = payload.get("data") or payload.get("models") or []
        models = [item.get("id") or item.get("name") for item in raw_models if isinstance(item, dict)]
        return {"success": True, "message": "Connection successful", "models": [m for m in models if m]}
    except Exception as exc:
        return {"success": False, "message": str(exc), "models": []}


@app.post("/api/chat/agent")
async def chat_with_agent(req: AgentChatRequest):
    """Stream a web chat turn through the OpenHarness query engine."""
    message = req.message.strip()
    if not message and not req.attachments:
        raise HTTPException(status_code=400, detail="message is required")

    async def _event_stream():
        import asyncio
        import base64
        import time

        from openharness.engine.messages import ConversationMessage, ImageBlock, TextBlock
        from openharness.engine.stream_events import (
            AssistantTextDelta,
            AssistantTurnComplete,
            CompactProgressEvent,
            ErrorEvent,
            StatusEvent,
            ToolExecutionCompleted,
            ToolExecutionStarted,
        )
        from openharness.services import session_storage
        from openharness.ui.runtime import build_runtime, close_runtime
        from openharness.utils.conversation_log import (
            ConversationSource,
            init_context_conversation_logger,
            reset_conversation_logger,
        )

        def sse(event: str, data: dict[str, Any]) -> str:
            return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        bundle = None

        try:
            payload = _load_agents_payload()
            agent = None
            agent_id = (req.agent_id or payload.get("active_agent_id") or "").strip()
            if agent_id:
                agent = next((item for item in payload["agents"] if item.get("id") == agent_id), None)
            profile_override = (req.profile or "").strip() or None
            model_override = (req.model or "").strip() or None

            session_id = (req.session_id or "").strip() or f"session_{int(time.time() * 1000)}"
            conversation_token = None
            conv_logger, conversation_token = init_context_conversation_logger(
                ConversationSource.WEB,
                session_id=session_id,
            )
            conv_logger.log_metadata(
                "web_chat",
                {
                    "session_id": session_id,
                    "agent_id": agent_id or None,
                    "agent_name": agent.get("name") if agent else None,
                    "agent_profile": profile_override or (agent.get("profile") if agent else None),
                    "agent_model": model_override or (agent.get("model") if agent else None),
                },
            )
            saved_session = session_storage.load_session_by_id(Path.cwd(), session_id)
            restore_messages = saved_session.get("messages") if saved_session else None
            restore_metadata = saved_session.get("tool_metadata") if saved_session else None

            yield sse("status", {"message": "Starting agent session..."})
            
            debug_log_path = Path.cwd() / ".openharness" / "web_outputs.txt"
            
            def debug_log(msg: str) -> None:
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                log_line = f"[{timestamp}] {msg}\n"
                try:
                    with open(debug_log_path, "a", encoding="utf-8") as f:
                        f.write(log_line)
                except Exception:
                    pass
            
            debug_log("=" * 80)
            debug_log("NEW CHAT REQUEST STARTED")
            debug_log(f"Session ID: {session_id}")
            debug_log(f"Agent ID: {agent_id or '(default)'}")
            if agent:
                debug_log(f"Agent profile: {agent.get('profile') or '(default)'}, model: {agent.get('model') or '(default)'}")
            if profile_override or model_override:
                debug_log(f"Request overrides: profile={profile_override or '(default)'}, model={model_override or '(default)'}")
            debug_log(f"Original message: {message}")

            # Attachments are intentionally lazy: the main model receives only
            # local path markers and must call read_attachment when needed.
            path_only_images = True
            debug_log("Image context mode: path-only (Agent media model routing)")
            
            prompt_message = message
            continuation_keywords = ("继续", "继续执行", "继续生成", "默认", "按默认", "按照默认", "可以", "开始")
            web_output_dir = (Path.cwd() / ".openharness" / "media" / "web" / "outputs" / session_id).resolve()
            web_output_dir.mkdir(parents=True, exist_ok=True)
            debug_log(f"Web output directory: {web_output_dir}")

            def compress_web_path(path: str | Path) -> str:
                try:
                    resolved = Path(path).expanduser().resolve()
                    relative = resolved.relative_to(web_output_dir)
                    return "$UWEB" if not str(relative) else f"$UWEB/{relative.as_posix()}"
                except Exception:
                    return _compress_path_alias(path)

            def expand_web_path(path: str) -> str:
                text = path.strip()
                if text == "$UWEB":
                    return str(web_output_dir)
                if text.startswith("$UWEB/"):
                    return str(web_output_dir / text[len("$UWEB/"):])
                return _expand_path_alias(text)
            
            attachments = req.attachments or []
            
            debug_log(f"Attachments received: {len(attachments) if attachments else 0}")
            if attachments:
                for i, att in enumerate(attachments):
                    att_type = att.get("type", "unknown")
                    att_name = att.get("name", "unnamed")
                    has_data = "data" in att
                    data_preview = ""
                    if has_data:
                        data = att.get("data", "")
                        data_preview = f", data_length={len(data)}, starts_with_data_prefix={data[:50] if len(data) > 50 else data}"
                    debug_log(f"  Attachment {i}: type={att_type}, name={att_name}, has_data={has_data}{data_preview}")
            
            image_attachments = [att for att in attachments if att.get("type") == "image"] if attachments else []
            file_attachments = [att for att in attachments if att.get("type") != "image"] if attachments else []
            
            debug_log(f"Image attachments: {len(image_attachments)}, File attachments: {len(file_attachments)}")
            
            attachment_notes = []
            saved_image_paths = []
            
            if restore_messages:
                debug_log(f"Restoring messages from session: {len(restore_messages)} messages")
                for msg in restore_messages:
                    # 处理用户消息和助手消息中的图片路径
                    if msg.get("role") in ("user", "assistant"):
                        content = msg.get("content", [])
                        if isinstance(content, list):
                            debug_log(f"  {msg.get('role').capitalize()} message with {len(content)} content blocks")
                            for block in content:
                                # 处理图片块
                                if isinstance(block, dict) and block.get("type") == "image":
                                    debug_log(f"  Found image block in session: keys={list(block.keys())}")
                                    if path_only_images:
                                        source_path = str(block.get("source_path") or "").strip()
                                        if source_path and Path(source_path).exists():
                                            abs_path = str(Path(source_path).expanduser().resolve())
                                            if abs_path not in saved_image_paths:
                                                saved_image_paths.append(abs_path)
                                                attachment_notes.append(f"[image: {compress_web_path(abs_path)}]")
                                                debug_log(f"Restored image path from session: {abs_path}")
                                        continue
                                    media_type = block.get("media_type", "image/jpeg")
                                    data = block.get("data", "")
                                    if not data:
                                        source = block.get("source", {})
                                        if isinstance(source, dict):
                                            media_type = source.get("media_type", media_type)
                                            data = source.get("data", "")
                                    
                                    if data:
                                        import mimetypes as mimetypes_lib
                                        media_dir = web_output_dir / "inputs"
                                        media_dir.mkdir(parents=True, exist_ok=True)
                                        
                                        ext = mimetypes_lib.guess_extension(media_type.split(";")[0].strip()) or ".jpg"
                                        import hashlib
                                        data_hash = hashlib.md5(data[:100].encode()).hexdigest()[:8]
                                        safe_name = f"restored_{data_hash}{ext}"
                                        
                                        target_path = media_dir / safe_name
                                        counter = 1
                                        while target_path.exists():
                                            target_path = media_dir / f"restored_{data_hash}_{counter}{ext}"
                                            counter += 1
                                        
                                        try:
                                            target_path.write_bytes(base64.b64decode(data))
                                            abs_path = str(target_path.resolve())
                                            if abs_path not in saved_image_paths:
                                                saved_image_paths.append(abs_path)
                                                attachment_notes.append(f"[image: {compress_web_path(abs_path)}]")
                                                debug_log(f"Restored image from session: {abs_path}, size={target_path.stat().st_size}")
                                        except Exception as e:
                                            debug_log(f"Failed to restore image from session: {e}")
                                # 处理文本块中的图片路径标记（如 [image: /path/to/image.jpg]）
                                elif isinstance(block, dict) and block.get("type") == "text":
                                    text = block.get("text", "")
                                    # 匹配 [image: /path/to/image.jpg] 格式的路径
                                    image_pattern = r'\[image:\s*([^\]]+\.(?:jpg|jpeg|png|webp|gif))\]'
                                    matches = re.findall(image_pattern, text, re.IGNORECASE)
                                    for match in matches:
                                        img_path = match.strip()
                                        expanded_img_path = expand_web_path(img_path)
                                        if Path(expanded_img_path).exists():
                                            abs_path = str(Path(expanded_img_path).expanduser().resolve())
                                            if abs_path not in saved_image_paths:
                                                saved_image_paths.append(abs_path)
                                                debug_log(f"Found image path in text block: {abs_path}")
                                else:
                                    debug_log(f"  Content block type: {block.get('type', 'unknown')}")
            
            if saved_image_paths:
                debug_log(f"Total restored images: {len(saved_image_paths)}")
                for p in saved_image_paths:
                    debug_log(f"  Restored: {p}")
            
            if image_attachments:
                import mimetypes as mimetypes_lib
                media_dir = web_output_dir / "inputs"
                media_dir.mkdir(parents=True, exist_ok=True)
                debug_log(f"Media directory: {media_dir}")
                
                for idx, att in enumerate(image_attachments, start=1):
                    att_name = att.get("name", f"image-{idx}")
                    img_data = att.get("data", "")
                    debug_log(f"Processing image {idx}: name={att_name}, data_length={len(img_data)}, starts_with_data={img_data.startswith('data:')}")
                    if img_data.startswith("data:"):
                        header_end = img_data.find(",")
                        if header_end != -1:
                            mime_header = img_data[5:header_end]
                            img_data = img_data[header_end + 1:]
                            debug_log(f"  MIME header: {mime_header}, data after header length: {len(img_data)}")
                        else:
                            mime_header = "image/jpeg"
                    else:
                        mime_header = att.get("mimeType", "image/jpeg")
                        debug_log(f"  No data: prefix, using mimeType: {mime_header}")
                    
                    ext = mimetypes_lib.guess_extension(mime_header.split(";")[0].strip()) or ".jpg"
                    safe_name = re.sub(r'[^\w\-_\.]', '_', att_name)
                    if not safe_name.endswith(ext):
                        safe_name = f"{safe_name}{ext}"
                    
                    target_path = media_dir / safe_name
                    counter = 1
                    while target_path.exists():
                        stem = target_path.stem
                        target_path = media_dir / f"{stem}_{counter}{ext}"
                        counter += 1
                    
                    try:
                        target_path.write_bytes(base64.b64decode(img_data))
                        abs_path = str(target_path.resolve())
                        saved_image_paths.append(abs_path)
                        attachment_notes.append(f"[image: {compress_web_path(abs_path)}]")
                        file_size = target_path.stat().st_size
                        debug_log(f"Image saved: {abs_path}, size={file_size} bytes")
                    except Exception as e:
                        attachment_notes.append(f"[image: {att_name} - save failed: {e}]")
                        debug_log(f"Failed to save image: {e}")
            
            if file_attachments:
                import mimetypes as mimetypes_lib
                media_dir = web_output_dir / "inputs"
                media_dir.mkdir(parents=True, exist_ok=True)
                for index, att in enumerate(file_attachments, start=1):
                    att_type = att.get("type", "file")
                    att_name = att.get("name", f"attachment-{index}")
                    encoded = str(att.get("data") or "")
                    mime_type = str(att.get("mimeType") or "application/octet-stream")
                    if encoded.startswith("data:"):
                        header, _, encoded = encoded.partition(",")
                        declared_mime = header[5:].split(";", 1)[0].strip()
                        if declared_mime:
                            mime_type = declared_mime
                    extension = (
                        mimetypes_lib.guess_extension(mime_type)
                        or Path(att_name).suffix
                        or ".bin"
                    )
                    safe_stem = (
                        re.sub(r"[^\w\-.]", "_", Path(att_name).stem)
                        or f"attachment-{index}"
                    )
                    target_path = media_dir / f"{safe_stem}{extension}"
                    counter = 1
                    while target_path.exists():
                        target_path = media_dir / f"{safe_stem}_{counter}{extension}"
                        counter += 1
                    try:
                        target_path.write_bytes(base64.b64decode(encoded))
                        compact_path = compress_web_path(target_path.resolve())
                        marker = (
                            "audio"
                            if mime_type.startswith("audio/") or att_type == "voice"
                            else "file"
                        )
                        attachment_notes.append(f"[{marker}: {compact_path}]")
                        debug_log(
                            f"Attachment saved: {target_path.resolve()}, mime={mime_type}, "
                            f"size={target_path.stat().st_size}"
                        )
                    except Exception as exc:
                        traceback.print_exc()
                        attachment_notes.append(f"[file: {att_name} - save failed: {exc}]")
                        debug_log(f"Failed to save attachment {att_name}: {exc}")
            
            if attachment_notes:
                if prompt_message:
                    prompt_message = prompt_message + "\n\n" + "\n".join(attachment_notes)
                else:
                    prompt_message = "\n".join(attachment_notes)
            
            if saved_image_paths and any(keyword in message for keyword in continuation_keywords):
                prompt_message = (
                    f"{message}\n\n"
                    "This is a continuation of the previous unfinished file-generation request. "
                    "Use the restored attachment above as the input and continue the requested task."
                )
                prompt_message = prompt_message + "\n\n" + "\n".join(attachment_notes)
            
            try:
                from openharness.skills import load_skill_registry

                skill_info_lines = []
                user_skill_root = Path(os.path.expanduser("~/.openharness/skills")).resolve()
                for skill in load_skill_registry(Path.cwd()).list_skills():
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
                    skill_info_lines.append(
                        f"- {command_name} at {_compress_path_alias(skill.base_dir)}: {description}"
                    )
                if skill_info_lines:
                    prompt_message = prompt_message + "\n\nAvailable skills:\n" + "\n".join(skill_info_lines[:8])
            except Exception:
                logger.exception("Failed to load skills for web prompt")
            
            compact_output_dir = "$UWEB"
            output_instructions = (
                "\n\nWeb output requirements:\n"
                "- $UWEB is the writable output directory for this web chat session. "
                "Do not expand it to an absolute path; the web server resolves it.\n"
                f"- If you generate any image, document, audio, archive, or other file, save it under: {compact_output_dir}\n"
                "- To send a generated file to the user, include a standalone marker in the final response, for example:\n"
                f"  [image: {compact_output_dir}/result.jpg]\n"
                f"  [attachment: {compact_output_dir}/result.zip]\n"
                "- Path aliases in markers are expanded by the web server.\n"
                "- Do not say the task is complete or ask the user to view the result unless the file was actually generated and the final response includes its marker.\n"
            )
            prompt_message = prompt_message + output_instructions
            
            debug_log(f"Final prompt_message (first 500 chars): {prompt_message[:500]}")
            
            from openharness.engine.messages import ConversationMessage, ImageBlock, TextBlock
            
            user_content_blocks = []
            if prompt_message:
                user_content_blocks.append(TextBlock(text=prompt_message))
                debug_log(f"Added TextBlock with length: {len(prompt_message)}")
            
            for img_path in saved_image_paths:
                if path_only_images:
                    debug_log(f"Skipped ImageBlock for local provider; using path only: {img_path}")
                    continue
                try:
                    image_block = ImageBlock.from_path(img_path)
                    user_content_blocks.append(image_block)
                    debug_log(f"Added ImageBlock from: {img_path}")
                except Exception as e:
                    debug_log(f"Failed to create ImageBlock from {img_path}: {e}")
                    pass
            
            debug_log(f"Total content blocks: {len(user_content_blocks)}")
            
            user_message = ConversationMessage.from_user_content(user_content_blocks) if user_content_blocks else ConversationMessage.from_user_text("[Attachment only message]")
            debug_log(f"User message created with {len(user_message.content)} content blocks")
            for i, block in enumerate(user_message.content):
                if isinstance(block, TextBlock):
                    debug_log(f"  Block {i}: TextBlock, text_length={len(block.text)}")
                elif isinstance(block, ImageBlock):
                    source_info = "unknown"
                    if hasattr(block, 'source'):
                        source = block.source
                        source_info = f"type={type(source).__name__}"
                        if hasattr(source, 'media_type'):
                            source_info += f", media_type={source.media_type}"
                        if hasattr(source, 'data'):
                            source_info += f", data_length={len(source.data) if source.data else 0}"
                    debug_log(f"  Block {i}: ImageBlock, {source_info}")
            
            debug_log(f"Submitting user message to engine...")
            
            from openharness.tools.read_attachment_tool import (
                attachment_model_configs_from_agent,
            )

            bundle = await build_runtime(
                prompt="[Session initialized]",
                cwd=str(Path.cwd()),
                active_profile=profile_override or (agent.get("profile") if agent else None),
                model=model_override or (agent.get("model") if agent else None),
                max_turns=agent.get("max_turns") if agent else None,
                system_prompt=agent.get("system_prompt") if agent else None,
                restore_messages=restore_messages,
                restore_tool_metadata=restore_metadata,
                permission_prompt=lambda _tool, _reason: asyncio.sleep(0, result=True),
                ask_user_prompt=lambda _question: asyncio.sleep(0, result=""),
                edit_approval_prompt=lambda _path, _diff, _added, _removed: asyncio.sleep(0, result="accept"),
                attachment_model_configs=attachment_model_configs_from_agent(agent),
            )
            debug_log("Runtime built successfully")
            bundle.session_id = session_id
            bundle.engine.tool_metadata["session_id"] = session_id
            bundle.engine.tool_metadata["path_aliases"] = {
                **_expanded_path_aliases(),
                "UWEB": str(web_output_dir),
            }
            debug_log(
                "Runtime model/profile: "
                f"model={bundle.engine.model}, "
                f"image_generation_configured={bool((bundle.engine.tool_metadata.get('image_generation_config') or {}).get('api_key') or (bundle.engine.tool_metadata.get('image_generation_config') or {}).get('codex_auth_token'))}"
            )
            
            logger.info(f"[DEBUG] Submitting user message to engine...")
            
            accumulated_text = []
            response_text_parts = []
            tool_errors = []
            tool_names = []
            sent_file_paths = []
            generated_media_keywords = (
                "生成",
                "绘制",
                "画图",
                "画一",
                "图片",
                "照片",
                "图像",
                "photo",
                "image",
                "draw",
                "paint",
                *continuation_keywords,
            )
            expects_generated_media = bool(saved_image_paths or image_attachments) or any(
                keyword in message.lower() for keyword in generated_media_keywords
            )

            def next_generated_image_path(suffix: str = ".png") -> Path:
                image_path = web_output_dir / f"generated_image{suffix}"
                counter = 1
                while image_path.exists():
                    image_path = web_output_dir / f"generated_image_{counter}{suffix}"
                    counter += 1
                return image_path

            async def try_direct_image_generation() -> list[str] | None:
                if not agent or not expects_generated_media:
                    return None
                model_name = str(agent.get("model") or "").strip()
                profile_name = str(agent.get("profile") or "").strip()
                if "image" not in model_name.lower() or not profile_name:
                    return None

                import httpx
                from openharness.api.usage import UsageSnapshot

                settings = _get_settings_obj()
                profile_settings = settings.model_copy(
                    update={"active_profile": profile_name}
                ).materialize_active_profile()
                auth = profile_settings.resolve_auth()
                base_url = (profile_settings.base_url or "").rstrip("/")
                if not base_url:
                    raise RuntimeError(f"Profile {profile_name} has no Base URL")
                image_url = f"{base_url}/images/generations" if base_url.endswith("/v1") else f"{base_url}/v1/images/generations"
                prompt = message.strip()
                debug_log(f"Direct image generation: profile={profile_name}, model={model_name}, url={image_url}")
                conv_logger.log_request(
                    model=model_name,
                    messages=[{"role": "user", "content": prompt}],
                    system_prompt=agent.get("system_prompt") or None,
                    tools=[],
                    source="web_direct_image_generation",
                    profile=profile_name,
                )
                async with httpx.AsyncClient(timeout=120.0) as client:
                    response = await client.post(
                        image_url,
                        headers={
                            "Authorization": f"Bearer {auth.value}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": model_name,
                            "prompt": prompt,
                            "n": 1,
                        },
                    )
                    response.raise_for_status()
                    payload = response.json()

                    data_items = payload.get("data") if isinstance(payload, dict) else None
                    if not isinstance(data_items, list) or not data_items:
                        raise RuntimeError("image generation returned no data")
                    first = data_items[0] if isinstance(data_items[0], dict) else {}
                    image_b64 = str(first.get("b64_json") or "")
                    image_bytes: bytes | None = None
                    if image_b64:
                        image_bytes = base64.b64decode(image_b64)
                    else:
                        result_url = str(first.get("url") or "")
                        if result_url.startswith("data:image/") and ";base64," in result_url:
                            image_bytes = base64.b64decode(result_url.split(";base64,", 1)[1])
                        elif result_url:
                            image_response = await client.get(result_url)
                            image_response.raise_for_status()
                            image_bytes = image_response.content
                    if not image_bytes:
                        raise RuntimeError("image generation returned no image bytes")

                image_path = next_generated_image_path()
                image_path.write_bytes(image_bytes)
                encoded = base64.b64encode(image_bytes).decode("ascii")
                text = f"已生成图片：{image_path.name}"
                conv_logger.log_response(
                    model=model_name,
                    content=text,
                    finish_reason="image_generated",
                    source="web_direct_image_generation",
                    profile=profile_name,
                    image_path=str(image_path),
                )
                events = [sse("text", {"text": text})]
                events.append(sse(
                    "file",
                    {
                        "path": str(image_path),
                        "name": image_path.name,
                        "type": "image",
                        "data": encoded,
                        "size": len(image_bytes),
                    },
                ))
                assistant_message = ConversationMessage(
                    role="assistant",
                    content=[TextBlock(text=f"{text}\n[image: {image_path}]")],
                )
                session_storage.save_session_snapshot(
                    cwd=Path.cwd(),
                    model=model_name,
                    system_prompt=agent.get("system_prompt") or "",
                    messages=[user_message, assistant_message],
                    usage=UsageSnapshot(),
                    session_id=session_id,
                    tool_metadata={
                        "session_id": session_id,
                        "agent_id": agent_id,
                        "agent_profile": profile_name,
                    },
                )
                sent_file_paths.append(str(image_path))
                response_text_parts.append(text)
                return events

            debug_log("Checking direct image-generation shortcut")
            direct_image_events = await try_direct_image_generation()
            if direct_image_events:
                debug_log("Direct image-generation shortcut returned events")
                for event_payload in direct_image_events:
                    yield event_payload
                yield sse("done", {"session_id": session_id})
                return
            debug_log("Entering engine.submit_message event loop")

            def format_tool_failure(tool_errors: list[dict[str, Any]]) -> str:
                last = tool_errors[-1] if tool_errors else {}
                tool = str(last.get("tool") or "tool")
                output = str(last.get("output") or "").strip()
                if len(output) > 1200:
                    output = output[:1200].rstrip() + "..."
                if "can't open file" in output and "No such file or directory" in output:
                    return (
                        f"处理没有完成：`{tool}` 执行脚本时找不到文件。\n\n"
                        f"最近错误：{output}\n\n"
                        "请确认命令使用了脚本的绝对路径，或先 `cd` 到对应 skill 目录后再运行。"
                    )
                if output:
                    return f"处理没有完成：`{tool}` 执行失败。\n\n最近错误：{output}"
                return f"处理没有完成：`{tool}` 执行失败，但没有返回可用错误信息。"

            generated_file_re = re.compile(r"(/[^\s'\"`\]\)]+?\.(?:jpg|jpeg|png|webp|gif|pdf|zip|mp3|wav|m4a|mp4))", re.IGNORECASE)

            def collect_generated_files(text: str) -> list[Path]:
                paths: list[Path] = []
                for raw_path in generated_file_re.findall(text or ""):
                    path = Path(raw_path).expanduser()
                    try:
                        resolved = path.resolve()
                    except Exception:
                        continue
                    if not resolved.is_file():
                        continue
                    try:
                        resolved.relative_to(web_output_dir)
                    except ValueError:
                        continue
                    if resolved not in paths:
                        paths.append(resolved)
                return paths

            def unique_web_output_path(source: Path) -> Path:
                web_output_dir.mkdir(parents=True, exist_ok=True)
                candidate = web_output_dir / source.name
                if not candidate.exists():
                    return candidate
                stem = source.stem or "generated"
                suffix = source.suffix
                counter = 1
                while True:
                    candidate = web_output_dir / f"{stem}_{counter}{suffix}"
                    if not candidate.exists():
                        return candidate
                    counter += 1

            def move_into_web_output(path: Path) -> Path:
                resolved = path.expanduser().resolve()
                try:
                    resolved.relative_to(web_output_dir)
                    return resolved
                except ValueError:
                    pass
                target = unique_web_output_path(resolved)
                shutil.move(str(resolved), str(target))
                return target.resolve()

            def collect_tool_generated_files(
                tool_name: str,
                output: str,
                metadata: dict[str, Any] | None,
            ) -> list[Path]:
                paths = collect_generated_files(output)
                if not isinstance(metadata, dict):
                    return paths

                raw_paths = metadata.get("paths")
                if isinstance(raw_paths, (str, Path)):
                    candidates = [raw_paths]
                elif isinstance(raw_paths, list):
                    candidates = raw_paths
                else:
                    candidates = []

                for raw_path in candidates:
                    if not raw_path:
                        continue
                    path = Path(str(raw_path)).expanduser()
                    try:
                        resolved = path.resolve()
                    except Exception:
                        continue
                    if not resolved.is_file() or resolved in paths:
                        continue
                    if tool_name == "image_generation":
                        try:
                            resolved = move_into_web_output(resolved)
                        except Exception as exc:
                            debug_log(f"Failed to move image_generation output into web output dir: {resolved}: {exc}")
                            continue
                    else:
                        try:
                            resolved.relative_to(web_output_dir)
                        except ValueError:
                            continue
                    paths.append(resolved)
                return paths

            def marker_for_path(path: Path) -> str:
                if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
                    return "image"
                if path.suffix.lower() in {".mp3", ".wav", ".m4a"}:
                    return "audio"
                if path.suffix.lower() == ".mp4":
                    return "video"
                return "file"

            def is_context_too_long(message: str) -> bool:
                normalized = message.lower()
                return any(
                    needle in normalized
                    for needle in (
                        "prompt too long",
                        "context_length_exceeded",
                        "context length",
                        "exceeds the available context size",
                        "exceed_context",
                        "n_ctx",
                    )
                )

            async for event in bundle.engine.submit_message(user_message):
                debug_log(f"Engine event: {event.__class__.__name__}")
                if isinstance(event, AssistantTextDelta):
                    accumulated_text.append(event.text)
                    response_text_parts.append(event.text)
                    yield sse("text", {"text": event.text})
                elif isinstance(event, ToolExecutionStarted):
                    tool_names.append(event.tool_name)
                    yield sse("tool_start", {"tool": event.tool_name, "input": event.tool_input})
                elif isinstance(event, ToolExecutionCompleted):
                    debug_log(f"ToolExecutionCompleted: tool={event.tool_name}, is_error={event.is_error}, output_length={len(str(event.output))}")
                    debug_log(f"  Tool output (first 500 chars): {str(event.output)[:500]}")
                    if event.is_error:
                        tool_errors.append({
                            "tool": event.tool_name,
                            "output": str(event.output),
                            "metadata": event.metadata or {},
                        })
                    yield sse(
                        "tool_complete",
                        {
                            "tool": event.tool_name,
                            "output": event.output,
                            "is_error": event.is_error,
                            "metadata": event.metadata or {},
                        },
                    )
                    if not event.is_error:
                        generated_paths = collect_tool_generated_files(
                            event.tool_name,
                            str(event.output),
                            event.metadata,
                        )
                        if event.tool_name == "image_generation" and generated_paths and not "".join(response_text_parts).strip():
                            text = "已生成图片：" + "、".join(path.name for path in generated_paths)
                            response_text_parts.append(text)
                            yield sse("text", {"text": text})
                        for generated_path in generated_paths:
                            file_path = str(generated_path)
                            if file_path in sent_file_paths:
                                continue
                            file_data = generated_path.read_bytes()
                            import base64 as b64
                            encoded_data = b64.b64encode(file_data).decode("ascii")
                            sent_file_paths.append(file_path)
                            debug_log(f"Sending generated file from tool output: {file_path}")
                            yield sse("file", {
                                "path": file_path,
                                "name": generated_path.name,
                                "type": marker_for_path(generated_path),
                                "data": encoded_data,
                                "size": len(file_data),
                            })
                elif isinstance(event, StatusEvent):
                    yield sse("status", {"message": event.message})
                elif isinstance(event, CompactProgressEvent):
                    yield sse(
                        "status",
                        {
                            "message": event.message or event.phase,
                            "phase": event.phase,
                            "trigger": event.trigger,
                        },
                    )
                elif isinstance(event, ErrorEvent):
                    if "empty assistant message" in event.message:
                        if not "".join(response_text_parts).strip():
                            fallback_text = format_tool_failure(tool_errors) if tool_errors else (
                                "本轮模型没有返回可发送的文本。会话已保持可继续状态，请重试一次或补充更具体的要求。"
                            )
                            response_text_parts.append(fallback_text)
                            debug_log(f"Empty assistant message converted to text reply: {fallback_text[:500]}")
                            yield sse("text", {"text": fallback_text})
                        else:
                            debug_log("Ignored empty assistant message after text was already sent")
                        continue
                    if sent_file_paths and is_context_too_long(event.message):
                        note = "\n\n生成文件已发送。本轮后续总结因为上下文过长被跳过，会话仍可继续。"
                        response_text_parts.append(note)
                        debug_log(f"Context-too-long after file delivery suppressed: {event.message[:500]}")
                        yield sse("text", {"text": note})
                        continue
                    yield sse("error", {"message": event.message, "recoverable": event.recoverable})
                elif isinstance(event, AssistantTurnComplete):
                    message_text = event.message.text
                    if message_text and message_text.strip():
                        debug_log(f"AssistantTurnComplete message text: {message_text[:500]}")
                        
                        outbound_media_re = re.compile(
                            r"\[(attachment|file|document|image|photo|video|audio|voice|audio-file|media):\s*([^\]\n]+?)\s*\]",
                            re.IGNORECASE,
                        )
                        
                        files_to_send = []
                        def extract_and_remove_media(match: re.Match[str]) -> str:
                            marker = match.group(1).lower()
                            raw_path = match.group(2).strip()
                            if " - " in raw_path:
                                return match.group(0)
                            
                            path = Path(expand_web_path(raw_path)).expanduser()
                            if path.is_absolute() and path.exists():
                                files_to_send.append({"path": str(path), "type": marker})
                                return ""
                            
                            return match.group(0)
                        
                        cleaned_text = outbound_media_re.sub(extract_and_remove_media, message_text)
                        cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text).strip()
                        
                        already_sent = "".join(accumulated_text)
                        if cleaned_text and cleaned_text not in already_sent:
                            response_text_parts.append(cleaned_text)
                            yield sse("text", {"text": cleaned_text})
                        
                        if files_to_send:
                            for file_info in files_to_send:
                                file_path = file_info["path"]
                                file_type = file_info["type"]
                                if file_path in sent_file_paths:
                                    continue
                                debug_log(f"Sending file to user: {file_path}, type={file_type}")
                                
                                try:
                                    path_obj = Path(file_path)
                                    if path_obj.exists():
                                        file_data = path_obj.read_bytes()
                                        import base64 as b64
                                        encoded_data = b64.b64encode(file_data).decode("ascii")
                                        yield sse("file", {
                                            "path": file_path,
                                            "name": path_obj.name,
                                            "type": file_type,
                                            "data": encoded_data,
                                            "size": len(file_data),
                                        })
                                        sent_file_paths.append(file_path)
                                except Exception as e:
                                    debug_log(f"Failed to send file {file_path}: {e}")
                        
                        accumulated_text = []
                    else:
                        debug_log(f"AssistantTurnComplete with empty text, tool_uses: {len(event.message.tool_uses) if hasattr(event.message, 'tool_uses') else 'N/A'}")
                        accumulated_text = []

            if expects_generated_media and tool_errors and not sent_file_paths:
                fallback_text = format_tool_failure(tool_errors)
                visible_text = fallback_text if not "".join(response_text_parts).strip() else f"\n\n{fallback_text}"
                response_text_parts.append(visible_text)
                debug_log(f"Generated-media tool error surfaced to user: {fallback_text[:500]}")
                yield sse("text", {"text": visible_text})
            elif not "".join(response_text_parts).strip() and tool_errors:
                fallback_text = format_tool_failure(tool_errors)
                debug_log(f"Fallback tool error reply: {fallback_text[:500]}")
                yield sse("text", {"text": fallback_text})
            elif expects_generated_media and not "".join(response_text_parts).strip() and not sent_file_paths:
                fallback_text = (
                    "本轮没有返回可发送的内容，也没有检测到生成图片。"
                    "请重试，或明确要求 agent 运行 `id-photo-generator` 脚本并返回 `[image: /absolute/path]`。"
                )
                response_text_parts.append(fallback_text)
                debug_log(
                    "Generated-media turn ended with no text and no file: "
                    f"tool_names={tool_names}, tool_errors={tool_errors[-3:]}"
                )
                yield sse("text", {"text": fallback_text})
            elif expects_generated_media and not sent_file_paths:
                final_text = "".join(response_text_parts)
                completion_claim = any(
                    phrase in final_text
                    for phrase in ("任务完成", "生成完成", "请查看生成结果", "请查看结果", "处理完成")
                )
                only_loaded_skill = tool_names and set(tool_names).issubset({"skill"})
                if completion_claim or only_loaded_skill:
                    debug_log(
                        "Generated-media completion without file marker: "
                        f"tool_names={tool_names}, sent_file_paths={sent_file_paths}"
                    )
                    warning_text = (
                        "\n\n未检测到可发送的生成文件。本轮没有收到有效的图片附件标记，"
                        "也没有确认生成脚本产出了结果文件；请让 agent 继续执行生成命令。"
                    )
                    response_text_parts.append(warning_text)
                    yield sse("text", {"text": warning_text})

            settings = bundle.current_settings()
            bundle.session_backend.save_snapshot(
                cwd=bundle.cwd,
                model=bundle.engine.model or settings.model,
                system_prompt=bundle.engine.system_prompt,
                messages=bundle.engine.messages,
                usage=bundle.engine.total_usage,
                session_id=session_id,
                tool_metadata=bundle.engine.tool_metadata,
            )
            yield sse("done", {"session_id": session_id})
        except SystemExit as exc:
            if 'debug_log' in locals():
                debug_log(f"SystemExit in chat stream: {str(exc) or 'Runtime initialization failed'}")
            yield sse("error", {"message": str(exc) or "Runtime initialization failed"})
        except Exception as exc:
            if 'debug_log' in locals():
                debug_log(f"Exception in chat stream: {exc.__class__.__name__}: {exc}")
            logger.exception("Web chat stream failed")
            yield sse("error", {"message": str(exc) or exc.__class__.__name__})
        finally:
            if 'conversation_token' in locals() and conversation_token is not None:
                try:
                    reset_conversation_logger(conversation_token)
                except Exception:
                    pass
            if bundle is not None:
                try:
                    await close_runtime(bundle)
                except Exception:
                    pass

    return StreamingResponse(_event_stream(), media_type="text/event-stream")


@app.get("/api/mcp-servers")
async def get_mcp_servers():
    """Get configured MCP servers."""
    settings = _get_settings_obj()
    servers = []
    for name, config in settings.mcp_servers.items():
        servers.append({
            "name": name,
            "type": getattr(config, "type", "unknown"),
            "command": getattr(config, "command", ""),
            "url": getattr(config, "url", ""),
        })
    return servers


class SearchApiUpdate(BaseModel):
    enabled: bool = False
    provider: str = "tavily"
    api_key: str = ""
    use_sdk: bool = True
    base_url: str = ""
    max_results: int = 5


@app.get("/api/search-api")
async def get_search_api():
    """Get web search API configuration."""
    data = _load_settings()
    search_config = data.get("search_api", {})
    return {
        "enabled": search_config.get("enabled", False),
        "provider": search_config.get("provider", "tavily"),
        "api_key": search_config.get("api_key", ""),
        "use_sdk": search_config.get("use_sdk", True),
        "base_url": search_config.get("base_url", ""),
        "max_results": search_config.get("max_results", 5),
    }


@app.post("/api/search-api")
async def update_search_api(update: SearchApiUpdate):
    """Update web search API configuration."""
    data = _load_settings()
    data["search_api"] = {
        "enabled": update.enabled,
        "provider": update.provider,
        "api_key": update.api_key,
        "use_sdk": update.use_sdk,
        "base_url": update.base_url,
        "max_results": update.max_results,
    }
    _save_settings(data)
    return {"status": "ok"}


@app.post("/api/search-api/test")
async def test_search_api(data: dict):
    """Test the web search configuration."""
    import os
    import httpx
    import logging
    from openharness.utils.network_guard import fetch_public_http_response
    
    logger = logging.getLogger(__name__)
    query = data.get("query", "test")
    settings_data = _load_settings()
    search_config = settings_data.get("search_api", {})
    
    provider = search_config.get("provider", "tavily")
    api_key = search_config.get("api_key", "")
    use_sdk = search_config.get("use_sdk", True)
    base_url = search_config.get("base_url", "")
    
    logger.info(f"Testing search: provider={provider}, use_sdk={use_sdk}, has_api_key={bool(api_key)}")
    
    try:
        if provider == "tavily" and api_key:
            if use_sdk:
                try:
                    from tavily import TavilyClient
                    client = TavilyClient(api_key=api_key)
                    response = client.search(query=query, max_results=3)
                    results = response.get("results", [])
                except ImportError:
                    raise HTTPException(
                        status_code=400,
                        detail="tavily-python SDK not installed. Install with: pip install tavily-python"
                    )
            else:
                endpoint = base_url or "https://api.tavily.com/search"
                headers = {"Content-Type": "application/json"}
                response = await httpx.AsyncClient().post(
                    endpoint,
                    json={"query": query, "api_key": api_key, "max_results": 3},
                    headers=headers,
                    timeout=20.0,
                )
                response.raise_for_status()
                results = response.json().get("results", [])
            
            if results:
                output_lines = [f"Search results for: {query}"]
                for i, r in enumerate(results[:3], 1):
                    output_lines.append(f"{i}. {r.get('title', 'N/A')}")
                    output_lines.append(f"   URL: {r.get('url', 'N/A')}")
                    output_lines.append(f"   {r.get('content', '')[:200]}")
                return {"output": "\n".join(output_lines)}
            return {"output": "No results found"}
        elif provider in ("bing", "google") and api_key:
            endpoint = base_url
            if not endpoint:
                if provider == "bing":
                    endpoint = "https://api.bing.microsoft.com/v7.0/search"
                elif provider == "google":
                    endpoint = "https://www.googleapis.com/customsearch/v1"
            
            if provider == "bing":
                response = await httpx.AsyncClient().get(
                    endpoint,
                    params={"q": query, "count": 3},
                    headers={"Ocp-Apim-Subscription-Key": api_key},
                    timeout=20.0,
                )
            elif provider == "google":
                response = await httpx.AsyncClient().get(
                    endpoint,
                    params={
                        "q": query,
                        "key": api_key,
                        "cx": os.environ.get("GOOGLE_SEARCH_CX", ""),
                        "num": 3,
                    },
                    timeout=20.0,
                )
            response.raise_for_status()
            data = response.json()
            results = data.get("webPages", {}).get("value", []) if provider == "bing" else data.get("items", [])
            if results:
                output_lines = [f"Search results for: {query}"]
                for i, r in enumerate(results[:3], 1):
                    output_lines.append(f"{i}. {r.get('name' if provider == 'bing' else 'title', 'N/A')}")
                    output_lines.append(f"   URL: {r.get('url' if provider == 'bing' else 'link', 'N/A')}")
                    output_lines.append(f"   {r.get('snippet', '')[:200]}")
                return {"output": "\n".join(output_lines)}
            return {"output": "No results found"}
        else:
            endpoint = base_url or "https://html.duckduckgo.com/html/"
            response = await fetch_public_http_response(
                endpoint,
                params={"q": query},
                headers={"User-Agent": "OpenHarness/0.1"},
                timeout=20.0,
            )
            response.raise_for_status()
            return {"output": f"Search endpoint reachable. HTML response length: {len(response.text)}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Search test failed: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Search test failed: {str(e)}")


class BotAgentSwitch(BaseModel):
    agent_id: str | None = None


@app.get("/api/bots/channels")
async def get_bot_channels():
    """Get all enabled bot channels with their status and sessions."""
    runtime = getattr(app.state, "channel_runtime", None)
    if runtime is None or runtime._manager is None:
        return {"channels": []}

    channel_status = runtime._manager.get_status()
    settings = _load_settings()
    channels_config = settings.get("channels", {})
    bot_agent_assignments = settings.get("bot_agent_assignments", {})
    active_agent_id = _load_agents_payload().get("active_agent_id")
    channels = []

    for name, status in channel_status.items():
        channel_cfg = channels_config.get(name, {})
        if not isinstance(channel_cfg, dict):
            channel_cfg = {}

        channel_info = {
            "name": name,
            "type": name,
            "running": status.get("running", False),
            "online": status.get("online"),
            "last_error": status.get("last_error"),
            "agent_id": bot_agent_assignments.get(name) or active_agent_id,
            "agent_assignment": bot_agent_assignments.get(name),
            "session_count": 0,
            "sessions": [],
            **channel_cfg,
        }
        for secret_key in (
            "app_secret",
            "token",
            "aes_key",
            "encrypt_key",
            "verification_token",
        ):
            if channel_info.get(secret_key):
                channel_info[f"has_{secret_key}"] = True
                channel_info[secret_key] = ""

        channel_obj = runtime._manager.get_channel(name)
        if channel_obj is not None:
            try:
                sessions = getattr(channel_obj, "sessions", {})
                if isinstance(sessions, dict):
                    channel_info["session_count"] = len(sessions)
                    channel_info["sessions"] = [
                        {
                            "sender_id": sid,
                            "sender_name": sess.get("sender_name", sid),
                            "last_message": sess.get("last_message", ""),
                            "message_count": sess.get("message_count", 0),
                        }
                        for sid, sess in sessions.items()
                    ][:10]
            except Exception:
                pass

        channels.append(channel_info)

    return {"channels": channels}


@app.post("/api/bots/{channel_name}/agent")
async def switch_bot_agent(channel_name: str, req: BotAgentSwitch):
    """Switch the agent for a specific bot channel."""
    agent_id = (req.agent_id or "").strip()
    payload = _load_agents_payload()
    agents = payload.get("agents", [])
    if agent_id and not any(agent.get("id") == agent_id for agent in agents):
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")

    data = _load_settings()
    bot_configs = data.get("bot_agent_assignments", {})
    if not isinstance(bot_configs, dict):
        bot_configs = {}
    if agent_id:
        bot_configs[channel_name] = agent_id
    else:
        bot_configs.pop(channel_name, None)
    data["bot_agent_assignments"] = bot_configs
    _save_settings(data)

    runtime = getattr(app.state, "channel_runtime", None)
    if runtime is not None:
        runtime.set_bot_agent_assignment(channel_name, agent_id or None)

    return {"status": "ok", "channel": channel_name, "agent_id": agent_id or None}


@app.get("/api/bots/{channel_name}/chat/{sender_id}")
async def get_bot_chat(channel_name: str, sender_id: str):
    """Get chat messages between a bot channel and a specific user."""
    runtime = getattr(app.state, "channel_runtime", None)
    if runtime is None or runtime._manager is None:
        return {"messages": []}

    channel_obj = runtime._manager.get_channel(channel_name)
    if channel_obj is None:
        return {"messages": []}

    try:
        sessions = getattr(channel_obj, "sessions", {})
        if isinstance(sessions, dict) and sender_id in sessions:
            session = sessions[sender_id]
            messages = session.get("messages", [])
            return {
                "messages": [
                    {
                        "role": msg.get("role", "user"),
                        "content": msg.get("content", ""),
                        "agent_name": msg.get("agent_name"),
                        "timestamp": msg.get("timestamp"),
                    }
                    for msg in messages
                ]
            }
    except Exception:
        pass

    return {"messages": []}


class BotConfigUpdate(BaseModel):
    app_id: str | None = None
    app_secret: str | None = None
    api_url: str | None = None
    token: str | None = None
    aes_key: str | None = None
    allow_from: list[str] | None = None
    sandbox: bool | None = None
    encrypt_key: str | None = None
    verification_token: str | None = None


@app.post("/api/bots/{channel_name}/config")
async def update_bot_config(channel_name: str, req: BotConfigUpdate):
    """Update configuration for a specific bot channel."""
    data = _load_settings()
    channels = data.get("channels", {})
    if not isinstance(channels, dict):
        channels = {}

    channel_config = channels.get(channel_name, {})
    if not isinstance(channel_config, dict):
        channel_config = {}

    if req.app_id is not None:
        channel_config["app_id"] = req.app_id
    if req.app_secret is not None:
        channel_config["app_secret"] = req.app_secret
    if req.api_url is not None:
        channel_config["api_url"] = req.api_url
    if req.token is not None:
        channel_config["token"] = req.token
    if req.aes_key is not None:
        channel_config["aes_key"] = req.aes_key
    if req.allow_from is not None:
        channel_config["allow_from"] = req.allow_from
    if req.sandbox is not None:
        channel_config["sandbox"] = req.sandbox
    if req.encrypt_key is not None:
        channel_config["encrypt_key"] = req.encrypt_key
    if req.verification_token is not None:
        channel_config["verification_token"] = req.verification_token

    channels[channel_name] = channel_config
    data["channels"] = channels
    _save_settings(data)

    return {"status": "ok", "channel": channel_name}


# ---------------------------------------------------------------------------
# Tool Management APIs
# ---------------------------------------------------------------------------

from openharness.tools.restrictions import normalize_restricted_keywords, tool_restriction_config

# Tools that require provider configuration
_PROVIDER_TOOLS = {
    "image_generation": {
        "config_keys": ["profile", "model"],
        "description": "Generate or edit raster images using configurable image generation providers.",
    },
    "image_to_text": {
        "config_keys": ["profile", "model"],
        "description": "Convert images to text descriptions using a vision-capable model.",
    },
    "web_search": {
        "config_keys": ["api_key", "engine", "base_url"],
        "description": "Search the web for real-time information.",
    },
}

def _profile_model_options(profile: Any, selected_model: str = "") -> list[str]:
    """Return model choices already known for a provider profile."""
    models: list[str] = []
    for value in [
        *(getattr(profile, "allowed_models", []) or []),
        getattr(profile, "last_model", "") or "",
        getattr(profile, "default_model", "") or "",
        selected_model,
    ]:
        text = str(value or "").strip()
        if text and text not in models:
            models.append(text)
    return models


def _profile_supports_tool(profile: Any, tool_name: str) -> bool:
    provider = str(getattr(profile, "provider", "") or "").strip()
    api_format = str(getattr(profile, "api_format", "") or "").strip()
    if tool_name == "image_generation":
        return provider == "openai_codex" or api_format == "openai"
    if tool_name == "image_to_text":
        return api_format == "openai" and provider not in {"openai_codex", "copilot"}
    return True


def _configured_tool_profiles(tool_name: str, selected_model: str = "") -> list[dict[str, Any]]:
    from openharness.auth.manager import AuthManager
    from openharness.config import load_settings

    settings = load_settings()
    manager = AuthManager(settings)
    statuses = manager.get_profile_statuses()
    profiles = []
    for name, profile in settings.merged_profiles().items():
        if not statuses.get(name, {}).get("configured"):
            continue
        if not _profile_supports_tool(profile, tool_name):
            continue
        profiles.append(
            {
                "name": name,
                "label": profile.label,
                "provider": profile.provider,
                "api_format": profile.api_format,
                "base_url": profile.base_url or "",
                "models": _profile_model_options(profile, selected_model),
            }
        )
    return profiles


def _get_tool_config() -> dict[str, Any]:
    """Get current tool configuration from settings."""
    data = _load_settings()
    return data.get("tools", {})


def _save_tool_config(config: dict[str, Any]) -> None:
    """Save tool configuration to settings."""
    data = _load_settings()
    data["tools"] = config
    _save_settings(data)


def _get_builtin_tools() -> list[dict[str, Any]]:
    """Get list of all built-in tools with their current config."""
    from openharness.tools import create_default_tool_registry

    registry = create_default_tool_registry()
    tool_config = _get_tool_config()
    tools = []

    for tool in registry.list_tools():
        name = tool.name
        cfg = tool_config.get(name, {})
        if not isinstance(cfg, dict):
            cfg = {}

        # Determine if this is a provider-dependent tool
        is_provider_tool = name in _PROVIDER_TOOLS
        selected_profile = str(cfg.get("profile") or cfg.get("provider") or "").strip()
        selected_model = str(cfg.get("model") or "").strip()
        available_profiles = _configured_tool_profiles(name, selected_model) if is_provider_tool else []
        model_options: list[str] = []
        for profile in available_profiles:
            if profile["name"] == selected_profile:
                model_options = profile["models"]
                break
        if selected_model and selected_model not in model_options:
            model_options.append(selected_model)

        # Check if tool is enabled (default: true)
        enabled_raw = cfg.get("enabled", True)
        if isinstance(enabled_raw, str):
            enabled = enabled_raw.strip().lower() in {"true", "1", "yes"}
        else:
            enabled = bool(enabled_raw)

        # Get custom description if set
        custom_description = cfg.get("description")
        original_description = tool.description
        restriction_config = tool_restriction_config(name, cfg)

        tool_info = {
            "name": name,
            "description": custom_description or original_description,
            "original_description": original_description,
            "has_custom_description": custom_description is not None,
            "enabled": enabled,
            "is_provider_tool": is_provider_tool,
            "provider_config": (
                {k: cfg.get(k, "") for k in _PROVIDER_TOOLS.get(name, {}).get("config_keys", [])}
                if is_provider_tool and name not in {"image_generation", "image_to_text"}
                else ({"profile": selected_profile, "model": selected_model} if is_provider_tool else None)
            ),
            "available_profiles": available_profiles,
            "model_options": model_options,
            "restricted_keywords": restriction_config["restricted_keywords"],
            "restriction_message": restriction_config["restriction_message"],
            "has_custom_restrictions": not restriction_config["uses_default"],
        }
        tools.append(tool_info)

    return tools


@app.get("/api/tools")
async def list_tools():
    """List all built-in tools with their configuration."""
    tools = _get_builtin_tools()
    return {"tools": tools}


@app.get("/api/tools/{tool_name}")
async def get_tool(tool_name: str):
    """Get details for a specific tool."""
    tools = _get_builtin_tools()
    for tool in tools:
        if tool["name"] == tool_name:
            return tool
    raise HTTPException(status_code=404, detail=f"Tool not found: {tool_name}")


@app.put("/api/tools/{tool_name}")
async def update_tool(tool_name: str, data: dict[str, Any]):
    """Update tool configuration (enabled status, description, provider config)."""
    tools = _get_builtin_tools()
    tool_found = False
    for tool in tools:
        if tool["name"] == tool_name:
            tool_found = True
            break

    if not tool_found:
        raise HTTPException(status_code=404, detail=f"Tool not found: {tool_name}")

    tool_config = _get_tool_config()
    if tool_name not in tool_config:
        tool_config[tool_name] = {}

    cfg = tool_config[tool_name]

    # Update enabled status
    if "enabled" in data:
        cfg["enabled"] = bool(data["enabled"])

    # Update custom description
    if "description" in data:
        desc = str(data["description"]).strip()
        if desc:
            cfg["description"] = desc
        elif "description" in cfg:
            del cfg["description"]

    # Update provider config for provider-dependent tools
    if tool_name in _PROVIDER_TOOLS and "provider_config" in data:
        provider_cfg = data["provider_config"]
        if isinstance(provider_cfg, dict):
            if tool_name in {"image_generation", "image_to_text"}:
                profiles = {profile["name"] for profile in _configured_tool_profiles(tool_name)}
                if "profile" in provider_cfg:
                    profile_name = str(provider_cfg.get("profile") or "").strip()
                    if profile_name and profile_name not in profiles:
                        raise HTTPException(status_code=400, detail=f"Profile is not available for {tool_name}: {profile_name}")
                    if profile_name:
                        cfg["profile"] = profile_name
                    else:
                        cfg.pop("profile", None)
                if "model" in provider_cfg:
                    model = str(provider_cfg.get("model") or "").strip()
                    if model:
                        cfg["model"] = model
                    else:
                        cfg.pop("model", None)
                for legacy_key in (
                    "provider",
                    "api_key",
                    "base_url",
                    "codex_auth_token",
                    "codex_base_url",
                    "codex_model",
                ):
                    cfg.pop(legacy_key, None)
            else:
                for key in _PROVIDER_TOOLS[tool_name]["config_keys"]:
                    if key in provider_cfg:
                        value = provider_cfg[key]
                        if value is not None and str(value).strip():
                            cfg[key] = str(value).strip()
                        elif key in cfg:
                            del cfg[key]

    if "restricted_keywords" in data:
        cfg["restricted_keywords"] = normalize_restricted_keywords(data.get("restricted_keywords"))

    if "restriction_message" in data:
        cfg["restriction_message"] = str(data.get("restriction_message") or "").strip()

    tool_config[tool_name] = cfg
    _save_tool_config(tool_config)

    return {"status": "ok", "tool": tool_name}


@app.post("/api/tools/{tool_name}/toggle")
async def toggle_tool(tool_name: str, data: dict[str, Any]):
    """Enable or disable a tool."""
    tools = _get_builtin_tools()
    tool_found = False
    for tool in tools:
        if tool["name"] == tool_name:
            tool_found = True
            break

    if not tool_found:
        raise HTTPException(status_code=404, detail=f"Tool not found: {tool_name}")

    tool_config = _get_tool_config()
    if tool_name not in tool_config:
        tool_config[tool_name] = {}

    enabled = bool(data.get("enabled", True))
    tool_config[tool_name]["enabled"] = enabled
    _save_tool_config(tool_config)

    return {"status": "ok", "tool": tool_name, "enabled": enabled}


@app.delete("/api/tools/{tool_name}/description")
async def reset_tool_description(tool_name: str):
    """Reset tool description to original."""
    tool_config = _get_tool_config()
    if tool_name in tool_config and "description" in tool_config[tool_name]:
        del tool_config[tool_name]["description"]
        _save_tool_config(tool_config)
    return {"status": "ok", "tool": tool_name}


@app.delete("/api/tools/{tool_name}/restrictions")
async def reset_tool_restrictions(tool_name: str):
    """Reset tool restrictions to defaults."""
    tool_config = _get_tool_config()
    cfg = tool_config.get(tool_name)
    if isinstance(cfg, dict):
        changed = False
        for key in ("restricted_keywords", "restriction_message"):
            if key in cfg:
                del cfg[key]
                changed = True
        if changed:
            tool_config[tool_name] = cfg
            _save_tool_config(tool_config)
    return {"status": "ok", "tool": tool_name}


# ---------------------------------------------------------------------------
# Cron Job API Routes
# ---------------------------------------------------------------------------

def _load_cron_jobs() -> list[dict[str, Any]]:
    from openharness.services.cron import load_cron_jobs as _load
    return _load()


def _save_cron_jobs(jobs: list[dict[str, Any]]) -> None:
    from openharness.services.cron import save_cron_jobs as _save
    _save(jobs)


def _cron_job_to_api(job: dict[str, Any]) -> dict[str, Any]:
    """Convert internal cron job to API-safe representation."""
    result = dict(job)
    # Mask sensitive fields in payload if any
    result.pop("last_run", None)
    result.pop("last_status", None)
    result.pop("next_run", None)
    return result


@app.get("/api/cron/jobs")
async def get_cron_jobs():
    """List all cron jobs."""
    from openharness.services.cron import load_cron_jobs
    from openharness.services.cron_scheduler import scheduler_status

    jobs = load_cron_jobs()
    status = scheduler_status()

    return {
        "jobs": jobs,
        "scheduler_running": status["running"],
        "scheduler_pid": status.get("pid"),
    }


@app.post("/api/cron/jobs")
async def create_cron_job(data: dict[str, Any]):
    """Create or update a cron job."""
    from openharness.services.cron import upsert_cron_job, validate_cron_expression, validate_timezone

    name = str(data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Job name is required")

    schedule = str(data.get("schedule") or "").strip()
    if not schedule:
        raise HTTPException(status_code=400, detail="Schedule (cron expression) is required")

    if not validate_cron_expression(schedule):
        raise HTTPException(status_code=400, detail=f"Invalid cron expression: {schedule!r}")

    timezone_val = str(data.get("timezone") or "").strip()
    if timezone_val and not validate_timezone(timezone_val):
        raise HTTPException(status_code=400, detail=f"Invalid timezone: {timezone_val!r}")

    command = data.get("command")
    message = data.get("message")
    task_type = data.get("task_type", "command")

    job: dict[str, Any] = {
        "name": name,
        "schedule": schedule,
        "enabled": bool(data.get("enabled", True)),
    }

    if timezone_val:
        job["timezone"] = timezone_val

    cwd = str(data.get("cwd") or ".").strip()
    if cwd:
        job["cwd"] = cwd

    if task_type == "agent" and message:
        payload: dict[str, Any] = {
            "kind": "agent_turn",
            "message": str(message),
        }
        profile = data.get("profile")
        if profile:
            payload["profile"] = str(profile)
        job["payload"] = payload
    elif command:
        job["command"] = str(command)
    else:
        raise HTTPException(status_code=400, detail="Task requires either command or message")

    # Notification config
    notify_type = str(data.get("notify_type") or "").strip()
    notify_target = str(data.get("notify_target") or "").strip()
    if notify_type and notify_target:
        notify: dict[str, Any] = {"type": notify_type}
        if notify_type == "feishu_dm":
            notify["user_open_id"] = notify_target
        elif notify_type == "qq":
            notify["open_id"] = notify_target
        elif notify_type == "wechat":
            notify["chat_id"] = notify_target
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported notify type: {notify_type}")
        job["notify"] = notify

    upsert_cron_job(job)
    return {"status": "ok", "name": name}


@app.put("/api/cron/jobs/{job_name}")
async def update_cron_job(job_name: str, data: dict[str, Any]):
    """Update an existing cron job."""
    from openharness.services.cron import get_cron_job, upsert_cron_job, validate_cron_expression, validate_timezone

    existing = get_cron_job(job_name)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_name}")

    schedule = str(data.get("schedule") or existing.get("schedule") or "").strip()
    if not validate_cron_expression(schedule):
        raise HTTPException(status_code=400, detail=f"Invalid cron expression: {schedule!r}")

    timezone_val = data.get("timezone", existing.get("timezone"))
    if timezone_val and not validate_timezone(str(timezone_val)):
        raise HTTPException(status_code=400, detail=f"Invalid timezone: {timezone_val!r}")

    job: dict[str, Any] = {
        "name": job_name,
        "schedule": schedule,
        "enabled": bool(data.get("enabled", existing.get("enabled", True))),
        "created_at": existing.get("created_at"),
    }

    if timezone_val:
        job["timezone"] = str(timezone_val)

    cwd = data.get("cwd", existing.get("cwd"))
    if cwd:
        job["cwd"] = str(cwd)

    task_type = data.get("task_type")
    command = data.get("command")
    message = data.get("message")

    if task_type == "agent" or message is not None:
        msg = message if message is not None else (existing.get("payload", {}).get("message") if isinstance(existing.get("payload"), dict) else "")
        if msg:
            payload: dict[str, Any] = {"kind": "agent_turn", "message": str(msg)}
            profile = data.get("profile") or (existing.get("payload", {}).get("profile") if isinstance(existing.get("payload"), dict) else None)
            if profile:
                payload["profile"] = str(profile)
            job["payload"] = payload
        elif existing.get("payload"):
            job["payload"] = existing["payload"]
    elif command is not None:
        job["command"] = str(command)
    elif existing.get("command"):
        job["command"] = existing["command"]
    elif existing.get("payload"):
        job["payload"] = existing["payload"]

    # Notification
    notify_type = data.get("notify_type")
    notify_target = data.get("notify_target")
    if notify_type is not None:
        notify_type = str(notify_type).strip()
        notify_target = str(notify_target or "").strip()
        if notify_type and notify_target:
            notify: dict[str, Any] = {"type": notify_type}
            if notify_type == "feishu_dm":
                notify["user_open_id"] = notify_target
            elif notify_type == "qq":
                notify["open_id"] = notify_target
            elif notify_type == "wechat":
                notify["chat_id"] = notify_target
            else:
                raise HTTPException(status_code=400, detail=f"Unsupported notify type: {notify_type}")
            job["notify"] = notify
        elif notify_type == "":
            job.pop("notify", None)
    elif existing.get("notify"):
        job["notify"] = existing["notify"]

    upsert_cron_job(job)
    return {"status": "ok", "name": job_name}


@app.delete("/api/cron/jobs/{job_name}")
async def delete_cron_job(job_name: str):
    """Delete a cron job."""
    from openharness.services.cron import delete_cron_job as _delete

    if not _delete(job_name):
        raise HTTPException(status_code=404, detail=f"Job not found: {job_name}")
    return {"status": "ok", "name": job_name}


@app.post("/api/cron/jobs/{job_name}/toggle")
async def toggle_cron_job(job_name: str):
    """Enable or disable a cron job."""
    from openharness.services.cron import get_cron_job, set_job_enabled

    job = get_cron_job(job_name)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_name}")

    new_enabled = not job.get("enabled", True)
    set_job_enabled(job_name, new_enabled)
    return {"status": "ok", "name": job_name, "enabled": new_enabled}


@app.post("/api/cron/jobs/{job_name}/run")
async def run_cron_job_now(job_name: str):
    """Manually trigger a cron job immediately."""
    import asyncio
    from openharness.services.cron import get_cron_job
    from openharness.services.cron_scheduler import execute_job

    job = get_cron_job(job_name)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_name}")

    try:
        result = await execute_job(job)
        return {"status": "ok", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Execution failed: {str(e)}")


@app.get("/api/cron/history")
async def get_cron_history(job_name: str | None = None, limit: int = 50):
    """Get cron execution history."""
    from openharness.services.cron_scheduler import load_history

    history = load_history(job_name=job_name, limit=min(limit, 200))
    return {"history": history}


@app.get("/api/cron/status")
async def get_cron_status():
    """Get cron scheduler status."""
    from openharness.services.cron_scheduler import scheduler_status

    return scheduler_status()


@app.post("/api/cron/scheduler/start")
async def start_cron_scheduler():
    """Start the cron scheduler daemon."""
    from openharness.services.cron_scheduler import start_daemon

    try:
        pid = start_daemon()
        return {"status": "ok", "pid": pid}
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/cron/scheduler/stop")
async def stop_cron_scheduler():
    """Stop the cron scheduler daemon."""
    from openharness.services.cron_scheduler import stop_scheduler

    if stop_scheduler():
        return {"status": "ok"}
    raise HTTPException(status_code=400, detail="Scheduler is not running")


@app.get("/api/cron/presets")
async def get_cron_presets():
    """Get common cron expression presets."""
    return {
        "presets": [
            {"label": "每1分钟", "value": "* * * * *"},
            {"label": "每5分钟", "value": "*/5 * * * *"},
            {"label": "每10分钟", "value": "*/10 * * * *"},
            {"label": "每30分钟", "value": "*/30 * * * *"},
            {"label": "每小时", "value": "0 * * * *"},
            {"label": "每6小时", "value": "0 */6 * * *"},
            {"label": "每天 0:00", "value": "0 0 * * *"},
            {"label": "每天 9:00", "value": "0 9 * * *"},
            {"label": "工作日 9:00", "value": "0 9 * * 1-5"},
            {"label": "每周一 9:00", "value": "0 9 * * 1"},
            {"label": "每月1号 0:00", "value": "0 0 1 * *"},
        ]
    }
