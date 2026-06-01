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
        logger.exception("Failed to start OpenHarness channel runtime")
    try:
        yield
    finally:
        await runtime.stop()


app = FastAPI(title="OpenHarness Web Config", lifespan=lifespan)

STATIC_DIR = Path(__file__).parent / "static"


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


def _load_agents_payload() -> dict[str, Any]:
    path = _get_agents_file()
    if not path.exists():
        return {"agents": [], "active_agent_id": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
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
    return {
        "name": skill.name,
        "description": skill.description,
        "source": skill.source,
        "path": skill.path,
        "content": skill.content,
    }


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
    model: str | None = None
    max_turns: int | None = None


class AgentChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    agent_id: str | None = None
    attachments: list[dict[str, Any]] | None = None


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


@app.get("/api/settings")
async def get_settings():
    """Get all current settings."""
    settings = _get_settings_obj()
    profiles = settings.merged_profiles()

    # Build profile list with status
    profile_list = []
    for name, profile in profiles.items():
        profile_list.append({
            "name": name,
            "label": profile.label,
            "provider": profile.provider,
            "api_format": profile.api_format,
            "auth_source": profile.auth_source,
            "default_model": profile.default_model,
            "last_model": profile.last_model or "",
            "base_url": profile.base_url or "",
            "active": name == settings.active_profile,
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
    result = []
    for name, profile in profiles.items():
        result.append({
            "name": name,
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
    from openharness.config.settings import ProviderProfile

    name = profile_data.get("name", "")
    if not name:
        raise HTTPException(status_code=400, detail="Profile name is required")

    profile = ProviderProfile(
        label=profile_data.get("label", name),
        provider=profile_data.get("provider", "openai"),
        api_format=profile_data.get("api_format", "openai"),
        auth_source=profile_data.get("auth_source", "openai_api_key"),
        default_model=profile_data.get("default_model", "gpt-4"),
        base_url=profile_data.get("base_url") or None,
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
    payload = _load_agents_payload()
    agents = payload["agents"]
    for index, existing in enumerate(agents):
        if existing.get("id") == agent_id:
            agents[index] = agent.model_dump()
            if payload.get("active_agent_id") == agent_id:
                payload["active_agent_id"] = agent.id
            _save_agents_payload(payload)
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

    registry = load_skill_registry(Path.cwd())
    return [_skill_to_dict(skill) for skill in registry.list_skills()]


@app.get("/api/skills/{skill_name}")
async def get_skill(skill_name: str):
    """Get one skill's details."""
    from openharness.skills import load_skill_registry

    skill = load_skill_registry(Path.cwd()).get(skill_name)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")
    return _skill_to_dict(skill)


@app.post("/api/skills/reload")
async def reload_skills():
    """Reload skills by rebuilding the registry."""
    from openharness.skills import load_skill_registry

    skills = load_skill_registry(Path.cwd()).list_skills()
    return {"status": "ok", "count": len(skills)}


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

    skill = load_skill_registry(Path.cwd()).get(skill_name)
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

    skill = load_skill_registry(Path.cwd()).get(skill_name)
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
    return _model_dump(_get_settings_obj().skill_management)


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
    api_key = str(req.get("api_key") or "sk-placeholder")
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

        def sse(event: str, data: dict[str, Any]) -> str:
            return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        bundle = None

        try:
            payload = _load_agents_payload()
            agent = None
            agent_id = (req.agent_id or payload.get("active_agent_id") or "").strip()
            if agent_id:
                agent = next((item for item in payload["agents"] if item.get("id") == agent_id), None)

            session_id = (req.session_id or "").strip() or f"session_{int(time.time() * 1000)}"
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
            debug_log(f"Original message: {message}")

            def use_path_only_images_for_current_provider() -> bool:
                try:
                    from urllib.parse import urlsplit

                    settings = _get_settings_obj().materialize_active_profile()
                    api_format = str(settings.api_format or "").lower()
                    host = (urlsplit(settings.base_url or "").hostname or "").lower()
                    return api_format in {"openai", "openai_compat"} and host in {"localhost", "127.0.0.1", "::1"}
                except Exception as exc:
                    debug_log(f"Failed to inspect provider for image mode: {exc}")
                    return False

            path_only_images = use_path_only_images_for_current_provider()
            debug_log(f"Image context mode: {'path-only' if path_only_images else 'inline-image'}")
            
            prompt_message = message
            continuation_keywords = ("继续", "继续执行", "继续生成", "默认", "按默认", "按照默认", "可以", "开始")
            web_output_dir = (Path.cwd() / ".openharness" / "media" / "web" / "outputs" / session_id).resolve()
            web_output_dir.mkdir(parents=True, exist_ok=True)
            debug_log(f"Web output directory: {web_output_dir}")
            
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
                    if msg.get("role") == "user":
                        content = msg.get("content", [])
                        if isinstance(content, list):
                            debug_log(f"  User message with {len(content)} content blocks")
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "image":
                                    debug_log(f"  Found image block in session: keys={list(block.keys())}")
                                    if path_only_images:
                                        source_path = str(block.get("source_path") or "").strip()
                                        if source_path and Path(source_path).exists():
                                            abs_path = str(Path(source_path).expanduser().resolve())
                                            if abs_path not in saved_image_paths:
                                                saved_image_paths.append(abs_path)
                                                attachment_notes.append(f"[image: {abs_path}]")
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
                                        media_dir = Path.cwd() / ".openharness" / "media" / "web"
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
                                                attachment_notes.append(f"[image: {abs_path}]")
                                                debug_log(f"Restored image from session: {abs_path}, size={target_path.stat().st_size}")
                                        except Exception as e:
                                            debug_log(f"Failed to restore image from session: {e}")
                                else:
                                    debug_log(f"  Content block type: {block.get('type', 'unknown')}")
            
            if saved_image_paths:
                debug_log(f"Total restored images: {len(saved_image_paths)}")
                for p in saved_image_paths:
                    debug_log(f"  Restored: {p}")
            
            if image_attachments:
                import mimetypes as mimetypes_lib
                media_dir = Path.cwd() / ".openharness" / "media" / "web"
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
                        attachment_notes.append(f"[image: {abs_path}]")
                        file_size = target_path.stat().st_size
                        debug_log(f"Image saved: {abs_path}, size={file_size} bytes")
                    except Exception as e:
                        attachment_notes.append(f"[image: {att_name} - save failed: {e}]")
                        debug_log(f"Failed to save image: {e}")
            
            if file_attachments:
                for att in file_attachments:
                    att_type = att.get("type", "file")
                    att_name = att.get("name", "unknown")
                    if att_type == "voice":
                        attachment_notes.append(f"[voice: {att_name}]")
                    else:
                        attachment_notes.append(f"[file: {att_name}]")
            
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
            
            import os
            skills_dir = Path(os.path.expanduser("~/.openharness/skills"))
            if skills_dir.exists():
                skill_paths = list(skills_dir.glob("*/SKILL.md"))
                if skill_paths:
                    skill_info_lines = []
                    for skill_md in skill_paths:
                        skill_name = skill_md.parent.name
                        skill_dir = str(skill_md.parent)
                        skill_info_lines.append(f"- Skill '{skill_name}' is installed at: {skill_dir}")
                    if skill_info_lines:
                        prompt_message = prompt_message + "\n\nAvailable skills:\n" + "\n".join(skill_info_lines)
            
            output_instructions = (
                "\n\nWeb output requirements:\n"
                f"- If you generate any image, document, audio, archive, or other file, save it under: {web_output_dir}\n"
                "- To send a generated file to the user, include a standalone marker in the final response, for example:\n"
                f"  [image: {web_output_dir}/result.jpg]\n"
                f"  [attachment: {web_output_dir}/result.zip]\n"
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
            
            bundle = await build_runtime(
                prompt="[Session initialized]",
                cwd=str(Path.cwd()),
                model=agent.get("model") if agent else None,
                max_turns=agent.get("max_turns") if agent else None,
                system_prompt=agent.get("system_prompt") if agent else None,
                restore_messages=restore_messages,
                restore_tool_metadata=restore_metadata,
                permission_prompt=lambda _tool, _reason: asyncio.sleep(0, result=True),
                ask_user_prompt=lambda _question: asyncio.sleep(0, result=""),
                edit_approval_prompt=lambda _path, _diff, _added, _removed: asyncio.sleep(0, result="accept"),
            )
            bundle.session_id = session_id
            bundle.engine.tool_metadata["session_id"] = session_id
            
            logger.info(f"[DEBUG] Submitting user message to engine...")
            
            accumulated_text = []
            response_text_parts = []
            tool_errors = []
            tool_names = []
            sent_file_paths = []
            expects_generated_media = bool(saved_image_paths or image_attachments) and any(
                keyword in message for keyword in (
                    "生成", "证件照", "图片", "照片", "photo", "image", *continuation_keywords
                )
            )

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
                        for generated_path in collect_generated_files(str(event.output)):
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
                            
                            path = Path(raw_path).expanduser()
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

            if not "".join(response_text_parts).strip() and tool_errors:
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
            yield sse("error", {"message": str(exc) or "Runtime initialization failed"})
        except Exception as exc:
            yield sse("error", {"message": str(exc) or exc.__class__.__name__})
        finally:
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
            "agent_id": bot_agent_assignments.get(name),
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
