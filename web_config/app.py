"""OpenHarness Web Configuration Manager.

A lightweight FastAPI-based web UI for configuring OpenHarness settings
including providers, models, authentication, permissions, and more.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import zipfile
from dataclasses import asdict, is_dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

src_path = Path(__file__).parent.parent / "src"
if src_path.exists() and str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="OpenHarness Web Config")

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


@app.get("/")
async def index():
    """Serve the main configuration page."""
    return FileResponse(STATIC_DIR / "index.html")


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
    return {"status": "ok"}


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
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    async def _event_stream():
        import asyncio
        import time

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
            bundle = await build_runtime(
                prompt=message,
                cwd=str(Path.cwd()),
                model=agent.get("model") if agent else None,
                max_turns=agent.get("max_turns") if agent else None,
                system_prompt=agent.get("system_prompt") if agent else None,
                restore_messages=restore_messages,
                restore_tool_metadata=restore_metadata,
                permission_prompt=lambda _tool, _reason: asyncio.sleep(0, result=False),
                ask_user_prompt=lambda _question: asyncio.sleep(0, result=""),
                edit_approval_prompt=lambda _path, _diff, _added, _removed: asyncio.sleep(0, result="reject"),
            )
            bundle.session_id = session_id
            bundle.engine.tool_metadata["session_id"] = session_id

            async for event in bundle.engine.submit_message(message):
                if isinstance(event, AssistantTextDelta):
                    yield sse("text", {"text": event.text})
                elif isinstance(event, ToolExecutionStarted):
                    yield sse("tool_start", {"tool": event.tool_name, "input": event.tool_input})
                elif isinstance(event, ToolExecutionCompleted):
                    yield sse(
                        "tool_complete",
                        {
                            "tool": event.tool_name,
                            "output": event.output,
                            "is_error": event.is_error,
                            "metadata": event.metadata or {},
                        },
                    )
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
                    yield sse("error", {"message": event.message, "recoverable": event.recoverable})
                elif isinstance(event, AssistantTurnComplete):
                    continue

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
