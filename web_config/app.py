"""OpenHarness Web Configuration Manager.

A lightweight FastAPI-based web UI for configuring OpenHarness settings
including providers, models, authentication, permissions, and more.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Add src directory to path for imports
src_path = Path(__file__).parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from fastapi import FastAPI, HTTPException
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


AGENTS_FILE = Path(__file__).parent.parent / "src" / "openharness" / "config" / "agents.json"


def _load_agents() -> list[dict[str, Any]]:
    """Load agent configurations from agents.json."""
    if AGENTS_FILE.exists():
        data = json.loads(AGENTS_FILE.read_text())
        return data.get("agents", [])
    return []


def _save_agents(agents: list[dict[str, Any]]) -> None:
    """Save agent configurations to agents.json."""
    content = json.dumps({"agents": agents}, indent=2, ensure_ascii=False)
    AGENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    AGENTS_FILE.write_text(content)


def _load_active_agent_id() -> str | None:
    """Load the active agent ID."""
    if AGENTS_FILE.exists():
        data = json.loads(AGENTS_FILE.read_text())
        return data.get("active_agent_id")
    return None


def _save_active_agent_id(agent_id: str | None) -> None:
    """Save the active agent ID."""
    agents = _load_agents()
    content = json.dumps({"agents": agents, "active_agent_id": agent_id}, indent=2, ensure_ascii=False)
    AGENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    AGENTS_FILE.write_text(content)


def _get_agent_by_id(agent_id: str) -> dict[str, Any] | None:
    """Get an agent config by ID."""
    agents = _load_agents()
    for agent in agents:
        if agent.get("id") == agent_id:
            return agent
    return None


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


class AgentsUpdate(BaseModel):
    agents: list[AgentConfig]
    active_agent_id: str | None = None


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
        "agents": _load_agents(),
        "active_agent_id": _load_active_agent_id(),
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


# Social Platforms
@app.get("/api/social-platforms")
async def get_social_platforms():
    """Get social platform configuration."""
    settings = _get_settings_obj()
    return settings.social_platforms.dict()


@app.put("/api/social-platforms")
async def update_social_platforms(data: dict):
    """Update social platform configuration."""
    settings = _get_settings_obj()
    settings.social_platforms = settings.social_platforms.model_copy(update=data)
    _save_settings_obj(settings)
    return {"status": "ok"}


# Agent Management
@app.get("/api/agents")
async def get_agents():
    """Get all agent configurations."""
    agents = _load_agents()
    active_agent_id = _load_active_agent_id()
    return {
        "agents": agents,
        "active_agent_id": active_agent_id,
    }


@app.post("/api/agents")
async def create_agent(agent: AgentConfig):
    """Create a new agent configuration."""
    agents = _load_agents()
    
    for existing in agents:
        if existing.get("id") == agent.id:
            raise HTTPException(status_code=400, detail=f"Agent with ID '{agent.id}' already exists")
    
    agent_data = agent.model_dump()
    agents.append(agent_data)
    _save_agents(agents)
    
    if not _load_active_agent_id():
        _save_active_agent_id(agent.id)
    
    return {"status": "ok", "agent": agent_data}


@app.put("/api/agents/{agent_id}")
async def update_agent(agent_id: str, agent: AgentConfig):
    """Update an agent configuration."""
    agents = _load_agents()
    
    for i, existing in enumerate(agents):
        if existing.get("id") == agent_id:
            agents[i] = agent.model_dump()
            _save_agents(agents)
            return {"status": "ok", "agent": agent.model_dump()}
    
    raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")


@app.delete("/api/agents/{agent_id}")
async def delete_agent(agent_id: str):
    """Delete an agent configuration."""
    agents = _load_agents()
    new_agents = [a for a in agents if a.get("id") != agent_id]
    
    if len(new_agents) == len(agents):
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    
    _save_agents(new_agents)
    
    active_agent_id = _load_active_agent_id()
    if active_agent_id == agent_id:
        new_active = new_agents[0]["id"] if new_agents else None
        _save_active_agent_id(new_active)
    
    return {"status": "ok"}


@app.post("/api/agents/{agent_id}/activate")
async def activate_agent(agent_id: str):
    """Activate an agent configuration."""
    agent = _get_agent_by_id(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    
    _save_active_agent_id(agent_id)
    return {"status": "ok", "active_agent_id": agent_id}


@app.put("/api/agents/batch")
async def update_agents_batch(update: AgentsUpdate):
    """Batch update all agents and set active agent."""
    agents = [agent.model_dump() for agent in update.agents]
    _save_agents(agents)
    _save_active_agent_id(update.active_agent_id)
    return {"status": "ok"}


# Search API
@app.get("/api/search-api")
async def get_search_api():
    """Get search API configuration."""
    settings = _get_settings_obj()
    return settings.search_api.dict()


@app.put("/api/search-api")
async def update_search_api(data: dict):
    """Update search API configuration."""
    settings = _get_settings_obj()
    settings.search_api = settings.search_api.model_copy(update=data)
    _save_settings_obj(settings)
    return {"status": "ok"}


# Skill Management
@app.get("/api/skill-management")
async def get_skill_management():
    """Get skill management configuration."""
    settings = _get_settings_obj()
    return settings.skill_management.dict()


@app.put("/api/skill-management")
async def update_skill_management(data: dict):
    """Update skill management configuration."""
    settings = _get_settings_obj()
    settings.skill_management = settings.skill_management.model_copy(update=data)
    _save_settings_obj(settings)
    return {"status": "ok"}


# Session Management
@app.get("/api/session-management")
async def get_session_management():
    """Get session management configuration."""
    settings = _get_settings_obj()
    return settings.session_management.dict()


@app.put("/api/session-management")
async def update_session_management(data: dict):
    """Update session management configuration."""
    settings = _get_settings_obj()
    settings.session_management = settings.session_management.model_copy(update=data)
    _save_settings_obj(settings)
    return {"status": "ok"}


# Memory Settings
@app.get("/api/memory-settings")
async def get_memory_settings():
    """Get memory settings configuration."""
    settings = _get_settings_obj()
    return settings.memory.dict()


@app.put("/api/memory-settings")
async def update_memory_settings(data: dict):
    """Update memory settings configuration."""
    settings = _get_settings_obj()
    settings.memory = settings.memory.model_copy(update=data)
    _save_settings_obj(settings)
    return {"status": "ok"}


class TestConnectionRequest(BaseModel):
    base_url: str
    api_format: str = "openai"
    api_key: str | None = None


@app.post("/api/test-connection")
async def test_connection(req: TestConnectionRequest):
    """Test connection to a model server and fetch available models."""
    import httpx

    base_url = req.base_url.strip().rstrip("/")
    api_format = req.api_format.lower()
    api_key = req.api_key or "sk-placeholder"

    try:
        if api_format == "openai":
            # OpenAI-compatible API
            # Handle both cases: base_url with or without /v1
            if base_url.endswith("/v1"):
                url = f"{base_url}/models"
            else:
                url = f"{base_url}/v1/models"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                
                if "data" in data:
                    models = [m["id"] for m in data["data"]]
                elif "models" in data:
                    models = [m["id"] for m in data["models"]]
                else:
                    models = []
                
                return {
                    "success": True,
                    "message": "Connection successful",
                    "models": models,
                    "api_format": "openai"
                }
        
        elif api_format == "anthropic":
            # Anthropic-compatible API
            url = f"{base_url}/v1/models"
            headers = {
                "x-api-key": api_key,
                "Content-Type": "application/json"
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                
                if "models" in data:
                    models = [m["name"] for m in data["models"]]
                else:
                    models = []
                
                return {
                    "success": True,
                    "message": "Connection successful",
                    "models": models,
                    "api_format": "anthropic"
                }
        
        else:
            return {"success": False, "message": f"Unsupported API format: {api_format}"}
    
    except httpx.HTTPError as e:
        return {"success": False, "message": f"HTTP error: {str(e)}"}
    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)}"}


# ---------------------------------------------------------------------------
# Agent Loop Chat API
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    message: str
    session_id: str | None = None
    agent_id: str | None = None


@app.post("/api/chat/agent")
async def chat_with_agent(req: ChatMessage):
    """Chat endpoint with full Agent Loop (Tools + Skills + Sessions)."""
    from openharness.config import load_settings
    from openharness.api.client import AnthropicApiClient
    from openharness.api.openai_client import OpenAICompatibleClient
    from openharness.tools import create_default_tool_registry
    from openharness.permissions.checker import PermissionChecker
    from openharness.engine.query_engine import QueryEngine
    from openharness.engine.messages import ConversationMessage
    from openharness.engine.stream_events import (
        AssistantTextDelta,
        ToolExecutionStarted,
        ToolExecutionCompleted,
        AssistantTurnComplete,
    )
    from openharness.services.session_backend import OpenHarnessSessionBackend
    from openharness.skills import load_skill_registry
    from openharness.mcp.client import McpClientManager

    settings = load_settings().materialize_active_profile()
    
    try:
        auth = settings.resolve_auth()
        api_key = auth.value
    except Exception:
        api_key = ""

    if not api_key:
        return StreamingResponse(
            iter([f"event: error\ndata: {json.dumps({'message': 'API key not configured'})}\n\n"]),
            media_type="text/event-stream",
        )

    base_url = settings.base_url or ""
    model = settings.model or "gpt-4"
    api_format = settings.api_format or "openai"

    active_agent_id = req.agent_id or _load_active_agent_id()
    agent_config = _get_agent_by_id(active_agent_id) if active_agent_id else None
    system_prompt = agent_config.get("system_prompt") if agent_config else None
    if agent_config and agent_config.get("model"):
        model = agent_config["model"]

    session_id = req.session_id or "default"
    cwd = Path.cwd()

    async def agent_stream():
        try:
            if api_format in ("openai", "openai_compat"):
                api_client = OpenAICompatibleClient(
                    api_key=api_key,
                    base_url=base_url,
                    timeout=settings.timeout,
                )
            else:
                api_client = AnthropicApiClient(
                    api_key=api_key,
                    base_url=base_url,
                )

            mcp_manager = McpClientManager(settings.mcp_servers)
            await mcp_manager.connect_all()

            tool_registry = create_default_tool_registry(mcp_manager)

            skill_registry = load_skill_registry()

            permission_checker = PermissionChecker(settings.permission)

            engine = QueryEngine(
                api_client=api_client,
                tool_registry=tool_registry,
                permission_checker=permission_checker,
                cwd=cwd,
                model=model,
                system_prompt=system_prompt or "",
                settings=settings,
                tool_metadata={
                    "session_id": session_id,
                    "skill_registry": skill_registry,
                },
            )

            session_backend = OpenHarnessSessionBackend()
            if session_id != "default":
                snapshot = session_backend.load_by_id(cwd, session_id)
                if snapshot and snapshot.get("messages"):
                    from openharness.engine.messages import sanitize_conversation_messages
                    restored = sanitize_conversation_messages(
                        [ConversationMessage.model_validate(m) for m in snapshot["messages"]]
                    )
                    engine.load_messages(restored)

            user_message = ConversationMessage.from_user_text(req.message)
            
            async for event in engine.submit_message(user_message):
                if isinstance(event, AssistantTextDelta):
                    yield f"event: text\ndata: {json.dumps({'text': event.text})}\n\n"
                elif isinstance(event, ToolExecutionStarted):
                    tool_data = {
                        'tool': event.tool_name,
                        'input': event.tool_input if hasattr(event, 'tool_input') else {},
                    }
                    yield f"event: tool_start\ndata: {json.dumps(tool_data)}\n\n"
                elif isinstance(event, ToolExecutionCompleted):
                    tool_data = {
                        'tool': event.tool_name,
                        'output': str(event.output) if hasattr(event, 'output') else "",
                    }
                    yield f"event: tool_complete\ndata: {json.dumps(tool_data)}\n\n"
                elif isinstance(event, AssistantTurnComplete):
                    yield f"event: done\ndata: {json.dumps({})}\n\n"

            if settings.memory.session_memory_enabled:
                session_backend.save_snapshot(
                    cwd=cwd,
                    model=model,
                    system_prompt=system_prompt or "",
                    messages=engine.messages,
                    usage=engine.total_usage,
                    session_id=session_id,
                )

            await mcp_manager.close()

        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

    return StreamingResponse(
        agent_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Tools API
# ---------------------------------------------------------------------------

@app.get("/api/tools")
async def list_tools():
    """List all available tools."""
    from openharness.tools import create_default_tool_registry

    registry = create_default_tool_registry()
    tools = []
    for tool in registry.list_tools():
        tools.append({
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_model.model_json_schema() if hasattr(tool, 'input_model') else {},
        })
    return tools


@app.get("/api/tools/{tool_name}")
async def get_tool(tool_name: str):
    """Get tool details by name."""
    from openharness.tools import create_default_tool_registry

    registry = create_default_tool_registry()
    tool = registry.get(tool_name)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool not found: {tool_name}")
    
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_model.model_json_schema() if hasattr(tool, 'input_model') else {},
    }


@app.get("/api/tools/schema")
async def get_tools_schema():
    """Get all tools schema for API usage."""
    from openharness.tools import create_default_tool_registry

    registry = create_default_tool_registry()
    return registry.to_api_schema()


# ---------------------------------------------------------------------------
# Skills API
# ---------------------------------------------------------------------------

@app.get("/api/skills")
async def list_skills():
    """List all available skills."""
    try:
        from openharness.skills.bundled import get_bundled_skills
        from openharness.skills.registry import SkillRegistry

        registry = SkillRegistry()
        for skill in get_bundled_skills():
            registry.register(skill)
        
        try:
            from openharness.skills import load_skill_registry
            full_registry = load_skill_registry()
            for skill in full_registry.list_skills():
                if skill.name not in registry._skills:
                    registry.register(skill)
        except OSError:
            pass
        
        skills = []
        for skill in registry.list_skills():
            skills.append({
                "name": skill.name,
                "description": skill.description,
                "source": skill.source,
                "path": str(skill.path) if hasattr(skill, 'path') and skill.path else "",
                "user_invocable": skill.user_invocable,
            })
        return skills
    except Exception as e:
        return {"error": str(e), "skills": []}


@app.get("/api/skills/{skill_name}")
async def get_skill(skill_name: str):
    """Get skill details by name."""
    from openharness.skills import load_skill_registry

    registry = load_skill_registry()
    skill = registry.get(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")
    
    content = ""
    if hasattr(skill, 'path') and skill.path:
        try:
            content = skill.path.read_text(encoding="utf-8")
        except Exception:
            pass
    
    return {
        "name": skill.name,
        "description": skill.description,
        "source": skill.source,
        "path": str(skill.path) if hasattr(skill, 'path') and skill.path else "",
        "user_invocable": skill.user_invocable,
        "content": content,
    }


@app.post("/api/skills/reload")
async def reload_skills():
    """Reload all skills from disk."""
    from openharness.skills import load_skill_registry

    registry = load_skill_registry()
    skills = registry.list_skills()
    return {
        "status": "ok",
        "message": f"Reloaded {len(skills)} skills",
        "count": len(skills),
    }


# ---------------------------------------------------------------------------
# Plugins API
# ---------------------------------------------------------------------------

@app.get("/api/plugins")
async def list_plugins():
    """List all installed plugins."""
    from openharness.config import load_settings
    from openharness.plugins import load_plugins

    settings = load_settings()
    plugins = load_plugins(settings, str(Path.cwd()))
    result = []
    for plugin in plugins:
        result.append({
            "name": plugin.manifest.name,
            "version": plugin.manifest.version,
            "description": plugin.manifest.description,
            "enabled": plugin.enabled,
            "path": str(plugin.path),
            "skills_count": len(plugin.skills),
            "commands_count": len(plugin.commands),
            "agents_count": len(plugin.agents),
            "mcp_servers_count": len(plugin.mcp_servers),
        })
    return result


@app.get("/api/plugins/{plugin_name}")
async def get_plugin(plugin_name: str):
    """Get plugin details by name."""
    from openharness.config import load_settings
    from openharness.plugins import load_plugins

    settings = load_settings()
    plugins = load_plugins(settings, str(Path.cwd()))
    plugin = next((p for p in plugins if p.manifest.name == plugin_name), None)
    if not plugin:
        raise HTTPException(status_code=404, detail=f"Plugin not found: {plugin_name}")
    
    return {
        "name": plugin.manifest.name,
        "version": plugin.manifest.version,
        "description": plugin.manifest.description,
        "enabled": plugin.enabled,
        "path": str(plugin.path),
        "skills": [{"name": s.name, "description": s.description} for s in plugin.skills],
        "commands": [{"name": c.name, "description": c.description} for c in plugin.commands],
        "agents": [{"name": a.name, "description": a.description} for a in plugin.agents],
        "mcp_servers": list(plugin.mcp_servers.keys()),
    }


@app.post("/api/plugins/{plugin_name}/toggle")
async def toggle_plugin(plugin_name: str):
    """Enable or disable a plugin."""
    from openharness.config import load_settings, save_settings

    settings = load_settings()
    current_enabled = settings.enabled_plugins.get(plugin_name, None)
    
    if current_enabled is None:
        settings.enabled_plugins[plugin_name] = False
    else:
        settings.enabled_plugins[plugin_name] = not current_enabled
    
    save_settings(settings)
    return {
        "status": "ok",
        "enabled": settings.enabled_plugins[plugin_name],
    }


@app.delete("/api/plugins/{plugin_name}")
async def uninstall_plugin(plugin_name: str):
    """Uninstall a plugin."""
    from openharness.plugins.installer import uninstall_plugin as do_uninstall
    from openharness.plugins.loader import get_user_plugins_dir

    plugins_dir = get_user_plugins_dir()
    plugin_path = plugins_dir / plugin_name
    
    if not plugin_path.exists():
        raise HTTPException(status_code=404, detail=f"Plugin not found: {plugin_name}")
    
    try:
        do_uninstall(plugin_name)
        return {"status": "ok", "message": f"Uninstalled plugin: {plugin_name}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to uninstall plugin: {str(e)}")


@app.post("/api/plugins/install")
async def install_plugin(plugin_data: dict):
    """Install a plugin from a path or URL."""
    from pathlib import Path as PathLib
    from openharness.plugins.installer import install_plugin_from_path

    plugin_path = plugin_data.get("path", "")
    if not plugin_path:
        raise HTTPException(status_code=400, detail="Plugin path is required")
    
    try:
        path = PathLib(plugin_path)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Plugin path not found: {plugin_path}")
        
        install_plugin_from_path(path)
        return {"status": "ok", "message": f"Installed plugin from: {plugin_path}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to install plugin: {str(e)}")


@app.post("/api/plugins/{plugin_name}/reload")
async def reload_plugin(plugin_name: str):
    """Reload a plugin."""
    from openharness.config import load_settings
    from openharness.plugins import load_plugins

    settings = load_settings()
    plugins = load_plugins(settings, str(Path.cwd()))
    plugin = next((p for p in plugins if p.manifest.name == plugin_name), None)
    if not plugin:
        raise HTTPException(status_code=404, detail=f"Plugin not found: {plugin_name}")
    
    return {
        "status": "ok",
        "message": f"Reloaded plugin: {plugin_name}",
    }


# ---------------------------------------------------------------------------
# MCP API
# ---------------------------------------------------------------------------

@app.get("/api/mcp/servers")
async def list_mcp_servers():
    """List all configured MCP servers."""
    from openharness.config import load_settings

    settings = load_settings()
    servers = []
    for name, config in settings.mcp_servers.items():
        servers.append({
            "name": name,
            "command": config.get("command", ""),
            "args": config.get("args", []),
            "env": {k: "***" for k in config.get("env", {}).keys()},
            "enabled": config.get("enabled", True),
        })
    return servers


@app.post("/api/mcp/servers")
async def add_mcp_server(server_data: dict):
    """Add a new MCP server configuration."""
    from openharness.config import load_settings, save_settings

    settings = load_settings()
    name = server_data.get("name", "")
    if not name:
        raise HTTPException(status_code=400, detail="Server name is required")
    
    settings.mcp_servers[name] = {
        "command": server_data.get("command", ""),
        "args": server_data.get("args", []),
        "env": server_data.get("env", {}),
        "enabled": server_data.get("enabled", True),
    }
    save_settings(settings)
    return {"status": "ok", "message": f"Added MCP server: {name}"}


@app.delete("/api/mcp/servers/{server_name}")
async def delete_mcp_server(server_name: str):
    """Delete an MCP server configuration."""
    from openharness.config import load_settings, save_settings

    settings = load_settings()
    if server_name not in settings.mcp_servers:
        raise HTTPException(status_code=404, detail=f"MCP server not found: {server_name}")
    
    del settings.mcp_servers[server_name]
    save_settings(settings)
    return {"status": "ok", "message": f"Deleted MCP server: {server_name}"}


@app.post("/api/mcp/servers/{server_name}/toggle")
async def toggle_mcp_server(server_name: str):
    """Enable or disable an MCP server."""
    from openharness.config import load_settings, save_settings

    settings = load_settings()
    if server_name not in settings.mcp_servers:
        raise HTTPException(status_code=404, detail=f"MCP server not found: {server_name}")
    
    current = settings.mcp_servers[server_name].get("enabled", True)
    settings.mcp_servers[server_name]["enabled"] = not current
    save_settings(settings)
    return {"status": "ok", "enabled": not current}


@app.get("/api/mcp/tools")
async def list_mcp_tools():
    """List all tools from connected MCP servers."""
    from openharness.config import load_settings
    from openharness.mcp.client import McpClientManager

    settings = load_settings()
    manager = McpClientManager(settings.mcp_servers)
    try:
        await manager.connect_all()
        tools = manager.list_tools()
        return tools
    finally:
        await manager.close()


@app.get("/api/mcp/resources")
async def list_mcp_resources():
    """List all resources from connected MCP servers."""
    from openharness.config import load_settings
    from openharness.mcp.client import McpClientManager

    settings = load_settings()
    manager = McpClientManager(settings.mcp_servers)
    try:
        await manager.connect_all()
        resources = manager.list_resources()
        return resources
    finally:
        await manager.close()


# ---------------------------------------------------------------------------
# Memory API
# ---------------------------------------------------------------------------

@app.get("/api/memory/entries")
async def list_memory_entries():
    """List all memory entries."""
    try:
        from openharness.memory import scan_memory_files

        entries = []
        for header in scan_memory_files(Path.cwd(), max_files=200):
            entries.append({
                "id": header.id,
                "title": header.title,
                "description": header.description,
                "type": header.memory_type,
                "path": str(header.path),
                "modified_at": header.modified_at,
                "importance": header.importance,
                "tags": list(header.tags) if hasattr(header, 'tags') else [],
            })
        return entries
    except Exception as e:
        return {"error": str(e), "entries": []}


@app.get("/api/memory/entries/{entry_name}")
async def get_memory_entry(entry_name: str):
    """Get a memory entry by name."""
    try:
        from openharness.memory import scan_memory_files

        for header in scan_memory_files(Path.cwd(), max_files=200):
            if entry_name in {header.path.stem, header.path.name, header.title, header.id}:
                return {
                    "id": header.id,
                    "title": header.title,
                    "description": header.description,
                    "path": str(header.path),
                    "type": header.memory_type,
                    "modified_at": header.modified_at,
                }
        raise HTTPException(status_code=404, detail=f"Memory entry not found: {entry_name}")
    except HTTPException:
        raise
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/memory/entries")
async def add_memory_entry(entry_data: dict):
    """Add a new memory entry."""
    try:
        from openharness.memory import add_memory_entry

        title = entry_data.get("title", entry_data.get("name", ""))
        content = entry_data.get("content", "")
        if not title:
            raise HTTPException(status_code=400, detail="Memory entry title is required")
        
        path = add_memory_entry(Path.cwd(), title, content)
        return {"status": "ok", "message": f"Added memory entry: {title}", "path": str(path)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/memory/entries/{entry_name}")
async def delete_memory_entry(entry_name: str):
    """Delete a memory entry."""
    try:
        from openharness.memory import remove_memory_entry

        success = remove_memory_entry(Path.cwd(), entry_name)
        if not success:
            raise HTTPException(status_code=404, detail=f"Memory entry not found: {entry_name}")
        return {"status": "ok", "message": f"Deleted memory entry: {entry_name}"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/memory/search")
async def search_memory(q: str):
    """Search memory entries."""
    try:
        from openharness.memory import find_relevant_memories

        memories = find_relevant_memories(q, Path.cwd())
        return {
            "query": q,
            "results": [
                {
                    "title": m.header.title,
                    "description": m.header.description,
                    "freshness": m.freshness,
                    "path": str(m.header.path),
                }
                for m in memories
            ]
        }
    except Exception as e:
        return {"error": str(e), "results": []}


@app.get("/api/memory/md")
async def get_memory_md():
    """Get MEMORY.md content."""
    try:
        from openharness.memory.paths import get_memory_entrypoint

        entrypoint = get_memory_entrypoint(Path.cwd())
        content = entrypoint.read_text(encoding="utf-8") if entrypoint.exists() else ""
        return {"content": content}
    except Exception as e:
        return {"error": str(e), "content": ""}


@app.post("/api/memory/md")
async def update_memory_md(data: dict):
    """Update MEMORY.md content."""
    try:
        from openharness.memory.paths import get_memory_entrypoint
        from openharness.utils.fs import atomic_write_text

        entrypoint = get_memory_entrypoint(Path.cwd())
        content = data.get("content", "")
        atomic_write_text(entrypoint, content)
        return {"status": "ok", "message": "Updated MEMORY.md"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Sessions API
# ---------------------------------------------------------------------------

@app.get("/api/sessions")
async def list_sessions():
    """List all saved sessions."""
    try:
        from openharness.services import session_storage

        sessions = session_storage.list_session_snapshots(Path.cwd(), limit=50)
        return sessions
    except Exception as e:
        return {"error": str(e), "sessions": []}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """Get session details."""
    try:
        from openharness.services import session_storage

        snapshot = session_storage.load_session_by_id(Path.cwd(), session_id)
        if not snapshot:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
        
        return snapshot
    except HTTPException:
        raise
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/sessions/{session_id}/restore")
async def restore_session(session_id: str):
    """Restore a session."""
    try:
        from openharness.services import session_storage

        snapshot = session_storage.load_session_by_id(Path.cwd(), session_id)
        if not snapshot:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
        
        return {
            "status": "ok",
            "message": f"Restored session: {session_id}",
            "messages": snapshot.get("messages", []),
        }
    except HTTPException:
        raise
    except Exception as e:
        return {"error": str(e)}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session."""
    try:
        from openharness.services import session_storage
        from openharness.config.paths import get_sessions_dir
        from pathlib import Path
        import shutil

        session_dir = session_storage.get_project_session_dir(Path.cwd())
        path = session_dir / f"session-{session_id}.json"
        if not path.exists():
            path = session_dir / "latest.json"
            if not path.exists():
                raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
        
        path.unlink()
        return {"status": "ok", "message": f"Deleted session: {session_id}"}
    except HTTPException:
        raise
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/sessions/latest")
async def get_latest_session():
    """Get the latest session."""
    try:
        from openharness.services import session_storage

        latest = session_storage.load_session_snapshot(Path.cwd())
        if not latest:
            return {"session": None}
        
        return {
            "session": latest
        }
    except Exception as e:
        return {"error": str(e), "session": None}


# ---------------------------------------------------------------------------
# Tasks API
# ---------------------------------------------------------------------------

@app.get("/api/tasks")
async def list_tasks():
    """List all tasks."""
    try:
        from openharness.tasks import get_task_manager

        manager = get_task_manager()
        tasks = manager.list_tasks()
        return [
            {
                "id": t.id,
                "type": t.type,
                "status": t.status,
                "description": t.description,
                "cwd": t.cwd,
                "command": t.command,
                "created_at": t.created_at,
                "started_at": t.started_at,
                "ended_at": t.ended_at,
                "return_code": t.return_code,
            }
            for t in tasks
        ]
    except Exception as e:
        return {"error": str(e), "tasks": []}


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    """Get task details."""
    try:
        from openharness.tasks import get_task_manager

        manager = get_task_manager()
        task = manager.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
        
        return {
            "id": task.id,
            "type": task.type,
            "status": task.status,
            "description": task.description,
            "cwd": task.cwd,
            "command": task.command,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "ended_at": task.ended_at,
            "return_code": task.return_code,
            "metadata": task.metadata,
        }
    except HTTPException:
        raise
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/tasks/{task_id}/output")
async def get_task_output(task_id: str):
    """Get task output."""
    try:
        from openharness.tasks import get_task_manager

        manager = get_task_manager()
        output = manager.read_task_output(task_id)
        return {"output": output}
    except Exception as e:
        return {"error": str(e), "output": ""}


@app.post("/api/tasks/{task_id}/stop")
async def stop_task_endpoint(task_id: str):
    """Stop a running task."""
    try:
        from openharness.tasks import get_task_manager
        import asyncio

        manager = get_task_manager()
        await manager.stop_task(task_id)
        return {"status": "ok", "message": f"Stopped task: {task_id}"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    """Delete a task."""
    try:
        from openharness.tasks import get_task_manager

        manager = get_task_manager()
        task = manager.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
        
        manager._tasks.pop(task_id, None)
        return {"status": "ok", "message": f"Deleted task: {task_id}"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Commands API
# ---------------------------------------------------------------------------

@app.get("/api/commands")
async def list_commands():
    """List all available slash commands."""
    try:
        from openharness.commands import create_default_command_registry

        registry = create_default_command_registry()
        commands = []
        for cmd in registry.list_commands():
            commands.append({
                "name": cmd.name,
                "description": cmd.description,
                "aliases": cmd.aliases,
            })
        return commands
    except Exception as e:
        return {"error": str(e), "commands": []}


@app.get("/api/commands/{command_name}")
async def get_command(command_name: str):
    """Get command details."""
    try:
        from openharness.commands import create_default_command_registry

        registry = create_default_command_registry()
        cmd = registry.lookup(f"/{command_name}")
        if not cmd:
            raise HTTPException(status_code=404, detail=f"Command not found: {command_name}")
        
        return {
            "name": cmd.name,
            "description": cmd.description,
            "aliases": cmd.aliases,
        }
    except HTTPException:
        raise
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Bridge API
# ---------------------------------------------------------------------------

@app.get("/api/bridge/sessions")
async def list_bridge_sessions():
    """List all bridge sessions."""
    try:
        from openharness.bridge import get_bridge_manager

        manager = get_bridge_manager()
        sessions = manager.list_sessions()
        return [
            {
                "session_id": s.session_id,
                "command": s.command,
                "cwd": s.cwd,
                "pid": s.pid,
                "status": s.status,
                "started_at": s.started_at,
                "output_path": str(s.output_path),
            }
            for s in sessions
        ]
    except Exception as e:
        return {"error": str(e), "sessions": []}


@app.get("/api/bridge/sessions/{session_id}/output")
async def get_bridge_session_output(session_id: str):
    """Get bridge session output."""
    try:
        from openharness.bridge import get_bridge_manager

        manager = get_bridge_manager()
        output = manager.read_output(session_id)
        return {"output": output}
    except Exception as e:
        return {"error": str(e), "output": ""}


@app.post("/api/bridge/sessions")
async def create_bridge_session(data: dict):
    """Create a new bridge session."""
    try:
        from openharness.bridge import get_bridge_manager
        import asyncio

        manager = get_bridge_manager()
        session_id = data.get("session_id", "")
        command = data.get("command", "")
        cwd = data.get("cwd", str(Path.cwd()))
        
        if not session_id or not command:
            raise HTTPException(status_code=400, detail="session_id and command are required")
        
        handle = await manager.spawn(session_id=session_id, command=command, cwd=cwd)
        return {
            "status": "ok",
            "session_id": handle.session_id,
            "pid": handle.process.pid,
            "message": f"Created bridge session: {session_id}",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/bridge/sessions/{session_id}/stop")
async def stop_bridge_session(session_id: str):
    """Stop a bridge session."""
    try:
        from openharness.bridge import get_bridge_manager
        import asyncio

        manager = get_bridge_manager()
        await manager.stop(session_id)
        return {"status": "ok", "message": f"Stopped bridge session: {session_id}"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Cron API
# ---------------------------------------------------------------------------

@app.get("/api/cron/jobs")
async def list_cron_jobs():
    """List all cron jobs."""
    # Cron jobs are not yet implemented in Settings model
    return []


@app.post("/api/cron/jobs")
async def create_cron_job(data: dict):
    """Create a new cron job."""
    raise HTTPException(status_code=501, detail="Cron job management is not yet implemented")


@app.get("/api/cron/jobs/{job_id}")
async def get_cron_job(job_id: str):
    """Get cron job details."""
    raise HTTPException(status_code=404, detail="Cron job not found")


@app.delete("/api/cron/jobs/{job_id}")
async def delete_cron_job(job_id: str):
    """Delete a cron job."""
    raise HTTPException(status_code=404, detail="Cron job not found")


@app.post("/api/cron/jobs/{job_id}/toggle")
async def toggle_cron_job(job_id: str):
    """Enable or disable a cron job."""
    raise HTTPException(status_code=404, detail="Cron job not found")
