"""
Hindsight Integration Helper for Agent Zero

Handles Hindsight client management, memory retention,
recall, and reflect operations for persistent memory augmentation.

Uses async variants (aretain, arecall, areflect) since Agent Zero
extensions run inside an async event loop.
"""
import os
import sys
import time
from typing import Optional, Dict, Any, TYPE_CHECKING, List
if TYPE_CHECKING:
    from agent import AgentContext

# Add vendor directory to sys.path BEFORE importing hindsight_client
# This allows the plugin to use hindsight-client from its own vendor/
# directory instead of relying on system-wide pip installation (which is
# ephemeral in Docker and lost on container restart).
plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
vendor_dir = os.path.join(plugin_dir, "vendor")
if vendor_dir not in sys.path:
    sys.path.insert(0, vendor_dir)

try:
    from hindsight_client import Hindsight
    HINDSIGHT_AVAILABLE = True
except ImportError:
    # Do NOT auto-install at module import time — it blocks the main thread
    # for up to 30s (GitHub #2 Bug 5). Let the init extension handle
    # installation asynchronously instead.
    import logging as _logging
    _logging.getLogger(__name__).info(
        "[Hindsight] hindsight_client not available at import time — "
        "init extension will handle installation if needed."
    )
    HINDSIGHT_AVAILABLE = False
    Hindsight = None  # type: ignore[assignment,misc]

# Module-level caches
_reflect_cache: Dict[str, tuple] = {}  # bank_id -> (timestamp, content)

# Default configuration values
_DEFAULTS: Dict[str, Any] = {
    "hindsight_bank_id": "",  # Explicit bank ID override; empty = use derived format (prefix-projectname)
    "hindsight_bank_prefix": "a0",
    "hindsight_retain_enabled": True,
    "hindsight_recall_enabled": True,
    "hindsight_reflect_enabled": True,
    "hindsight_recall_max_tokens": 4096,
    "hindsight_recall_budget": "mid",
    "hindsight_reflect_budget": "low",
    "hindsight_reflect_max_tokens": 500,
    "hindsight_cache_ttl": 120,
    "hindsight_debug": False,
    "hindsight_agent_memory_enabled": False,
    "hindsight_agent_bank_id": "",
    "hindsight_agent_retain_to_project": False,
}


def _log(context: Optional["AgentContext"], msg: str, log_type: str = "info") -> None:
    """Log using A0's logging system via context.log."""
    try:
        if context and hasattr(context, "log"):
            context.log.log(type=log_type, heading=f"[Hindsight] {msg}")
        else:
            print(f"[Hindsight] {msg}")
    except Exception:
        print(f"[Hindsight] {msg}")


# Settings that are GLOBAL (shared across all projects)
_GLOBAL_SETTINGS = {"hindsight_base_url", "hindsight_bank_prefix"}

# Settings that are meaningful only at agent-profile scope.
_AGENT_SETTINGS = {
    "hindsight_agent_memory_enabled",
    "hindsight_agent_bank_id",
    "hindsight_agent_retain_to_project",
}


def _get_plugin_config(agent: Any) -> Dict[str, Any]:
    """Read plugin settings with global/project/agent merge.

    Global settings (base URL and bank prefix) are always taken from the
    global scope. Project settings control normal Hindsight operation. Agent
    settings only control whether the active agent writes to its own bank and
    whether those writes are also copied to the project bank.

    Explicit False values are valid and must be preserved; never use truthiness
    checks when merging user settings.
    """
    config: Dict[str, Any] = {}

    if agent is not None:
        try:
            from helpers.plugins import get_plugin_config

            # With per_agent_config enabled, this resolves the most specific
            # project+agent scope available, falling back through project,
            # agent, global/default according to the framework search order.
            config = get_plugin_config("a0_hindsight", agent=agent) or {}

            # Always force global-only connection/naming settings from global.
            global_config = get_plugin_config(
                "a0_hindsight",
                agent=agent,
                project_name="",
                agent_profile="",
            ) or {}
            for key in _GLOBAL_SETTINGS:
                if key in global_config:
                    config[key] = global_config[key]

            # Agent memory controls should come from the active agent profile
            # scope, not from a project/default fallback accidentally.
            agent_profile = _get_agent_profile(agent)
            if agent_profile:
                agent_config = get_plugin_config(
                    "a0_hindsight",
                    agent=agent,
                    project_name="",
                    agent_profile=agent_profile,
                ) or {}
                for key in _AGENT_SETTINGS:
                    if key in agent_config:
                        config[key] = agent_config[key]
        except Exception as e:
            print(f"[HINDSIGHT DEBUG] _get_plugin_config() framework API failed: {type(e).__name__}: {e}")
            config = {}

    # Fallback: read config.json directly from plugin directory.
    if not config or not config.get("hindsight_base_url"):
        try:
            import json
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "config.json"
            )
            if os.path.isfile(config_path):
                with open(config_path, "r") as f:
                    file_config = json.load(f)
                for k, v in file_config.items():
                    if k not in config:
                        config[k] = v
        except Exception as e:
            print(f"[HINDSIGHT DEBUG] _get_plugin_config() config.json fallback failed: {e}")

    for key, default in _DEFAULTS.items():
        if key not in config:
            config[key] = default
    return config


def is_hindsight_client_available() -> bool:
    """Runtime check for hindsight_client availability.

    The dependency status file is advisory only.  It can become stale when the
    plugin was installed/checked from a different Python runtime than the
    Agent Zero backend.  The authoritative check is always a live import in the
    current process.  When the import succeeds, refresh the module-level
    Hindsight reference so later calls to get_client() work without a restart.
    """
    import os
    import json

    global HINDSIGHT_AVAILABLE, Hindsight

    plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    status_file = os.path.join(plugin_dir, ".dependency_status.json")

    try:
        from hindsight_client import Hindsight as _Hindsight
        Hindsight = _Hindsight
        HINDSIGHT_AVAILABLE = True
        available = True
    except Exception as exc:
        Hindsight = None  # type: ignore[assignment]
        HINDSIGHT_AVAILABLE = False
        available = False
        # Mark the cached status as stale/failed so init can auto-install.
        try:
            status_data = {
                "checked_at": _get_timestamp(),
                "hindsight_client": False,
                "warnings": [],
                "errors": [f"live import failed in current runtime: {type(exc).__name__}: {exc}"],
            }
            os.makedirs(plugin_dir, exist_ok=True)
            with open(status_file, "w") as f:
                json.dump(status_data, f, indent=2)
        except Exception:
            pass
        return False

    # Self-heal status file after a successful live import.
    try:
        status_data = {
            "checked_at": _get_timestamp(),
            "hindsight_client": True,
            "warnings": [],
            "errors": [],
        }
        os.makedirs(plugin_dir, exist_ok=True)
        with open(status_file, "w") as f:
            json.dump(status_data, f, indent=2)
    except Exception:
        pass

    return available


def _get_timestamp() -> str:
    """Return current timestamp in ISO format."""
    from datetime import datetime
    return datetime.now().isoformat()


def _update_status_file_success(context: Optional["AgentContext"] = None) -> None:
    """Update .dependency_status.json to reflect successful installation.
    
    Called after auto-install succeeds, to update the status file so future
    is_hindsight_client_available() checks use the fast path.
    """
    import os
    import json
    
    try:
        plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        status_file = os.path.join(plugin_dir, ".dependency_status.json")
        
        status_data = {
            "checked_at": _get_timestamp(),
            "hindsight_client": True,
            "warnings": [],
            "errors": [],
        }
        os.makedirs(plugin_dir, exist_ok=True)
        with open(status_file, "w") as f:
            json.dump(status_data, f, indent=2)
    except Exception as e:
        if context:
            _log(context, f"Could not update status file: {e}", "warning")



def _get_secret(key: str, default: str = "", context: Optional["AgentContext"] = None) -> str:
    """Retrieve a secret value from A0 secrets manager."""
    try:
        from helpers.secrets import get_secrets_manager
        secrets_mgr = get_secrets_manager(context)
        secrets = secrets_mgr.load_secrets()
        return secrets.get(key, "").strip() or default
    except Exception as e:
        _log(context, f"Error loading secret {key}: {e}", "error")
        return default


def get_base_url(context: Optional["AgentContext"] = None, agent: Any = None) -> Optional[str]:
    """Retrieve HINDSIGHT_BASE_URL with fallback chain.
    
    Priority order:
    1. Environment variable HINDSIGHT_BASE_URL (recommended)
    2. Plugin config hindsight_base_url (legacy, for migration)
    3. None if neither is set
    """
    # First: check environment variable (recommended)
    url = os.environ.get("HINDSIGHT_BASE_URL", "").strip()
    if url:
        return url
    
    # Second: fallback to plugin config (for migration compatibility)
    try:
        config = _get_plugin_config(agent)
        url = config.get("hindsight_base_url", "").strip()
        if url:
            return url
    except Exception as e:
        _log(context, f"Error reading plugin config: {e}", "debug")
    
    return None


def get_api_key(context: Optional["AgentContext"] = None) -> Optional[str]:
    """Retrieve HINDSIGHT_API_KEY from A0 secrets (optional)."""
    key = _get_secret("HINDSIGHT_API_KEY", "", context)
    return key if key else None


def is_configured(context: Optional["AgentContext"] = None) -> bool:
    """Check if Hindsight SDK is available and base URL is set."""
    if not is_hindsight_client_available():
        return False
    agent = getattr(context, "agent0", None) if context else None
    return bool(get_base_url(context, agent))


def get_client(context: Optional["AgentContext"] = None) -> Optional[Any]:
    """Create a fresh Hindsight client for this call.
    
    A new client is created each time to avoid stale aiohttp ClientSession
    issues across different async contexts or event loops (see GitHub #1).
    """
    if not is_hindsight_client_available():
        return None

    agent = getattr(context, "agent0", None) if context else None
    base_url = get_base_url(context, agent)
    if not base_url:
        print(f"[HINDSIGHT DEBUG] get_client(): base_url is None. agent={agent is not None}, env={bool(os.environ.get('HINDSIGHT_BASE_URL'))}")
        return None

    api_key = get_api_key(context)

    try:
        kwargs: Dict[str, Any] = {"base_url": base_url}
        if api_key:
            kwargs["api_key"] = api_key
        client = Hindsight(**kwargs)
        _log(context, f"Connected to Hindsight at: {base_url}", "util")
        return client
    except Exception as e:
        _log(context, f"Client creation error: {e}", "error")
        return None


def _sanitize_bank_part(value: Any, fallback: str = "default") -> str:
    """Sanitize a project/profile value for use in a derived bank ID."""
    import re
    text = str(value or "").strip()
    if not text:
        text = fallback
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^A-Za-z0-9_.:-]+", "-", text)
    text = text.strip("-._:")
    return text or fallback


def _get_agent_profile(agent: Any = None, context: Optional["AgentContext"] = None) -> str:
    """Return the active agent profile key, falling back to agent0."""
    try:
        if agent is None and context is not None:
            agent = getattr(context, "agent0", None)
        profile = getattr(getattr(agent, "config", None), "profile", "")
        return str(profile or "agent0").strip() or "agent0"
    except Exception:
        return "agent0"


def _get_project_name(context: Optional["AgentContext"]) -> str:
    """Return the active project name, if any."""
    project_name = None
    try:
        from helpers.projects import get_context_project_name
        project_name = get_context_project_name(context) if context else None
    except Exception:
        pass
    if not project_name and context is not None:
        try:
            if hasattr(context, "project") and context.project:
                project_name = getattr(context.project, "name", None)
        except Exception:
            pass
    return str(project_name or "").strip()


def get_project_bank_id(context: "AgentContext") -> str:
    """Derive the shared project/default Hindsight bank ID."""
    agent0 = getattr(context, "agent0", None)
    config = _get_plugin_config(agent0)

    explicit_id = config.get("hindsight_bank_id", "").strip()
    if explicit_id:
        return explicit_id

    prefix = _sanitize_bank_part(config.get("hindsight_bank_prefix", "a0"), "a0")
    project_name = _get_project_name(context)
    if project_name:
        return f"{prefix}-{_sanitize_bank_part(project_name)}"
    return f"{prefix}-default"


def get_agent_bank_id(context: "AgentContext") -> str:
    """Return the active agent's Hindsight bank ID.

    Explicit agent bank ID wins. If blank, default to the active agent profile
    name exactly enough to be recognizable, sanitized only for safety.
    """
    agent0 = getattr(context, "agent0", None)
    config = _get_plugin_config(agent0)
    explicit_id = str(config.get("hindsight_agent_bank_id", "") or "").strip()
    if explicit_id:
        return explicit_id
    return _sanitize_bank_part(_get_agent_profile(agent0, context), "agent0")


def is_agent_memory_enabled(context: "AgentContext") -> bool:
    agent0 = getattr(context, "agent0", None)
    config = _get_plugin_config(agent0)
    return bool(config.get("hindsight_agent_memory_enabled", False))


def _has_project_memory_intent(content: str) -> bool:
    """Detect explicit user intent to remember something for the project."""
    text = (content or "").lower()
    phrases = (
        "remember this for the project",
        "remember for this project",
        "remember x for this project",
        "store this in project memory",
        "save this to project memory",
        "add this to project memory",
        "remember this in project memory",
        "remember this for everyone",
        "remember for everyone",
        "shared project memory",
        "for this project remember",
    )
    return any(phrase in text for phrase in phrases)


def get_retain_bank_ids(context: "AgentContext", content: str = "") -> List[str]:
    """Return bank IDs to retain into for this memory content."""
    agent0 = getattr(context, "agent0", None)
    config = _get_plugin_config(agent0)

    project_bank = get_project_bank_id(context)
    if not config.get("hindsight_agent_memory_enabled", False):
        return [project_bank]

    banks = [get_agent_bank_id(context)]
    if config.get("hindsight_agent_retain_to_project", False) or _has_project_memory_intent(content):
        banks.append(project_bank)
    return _dedupe_bank_ids(banks)


def get_recall_bank_ids(context: "AgentContext") -> List[str]:
    """Return layered recall/reflect bank IDs in priority order."""
    agent0 = getattr(context, "agent0", None)
    config = _get_plugin_config(agent0)
    project_bank = get_project_bank_id(context)
    if not config.get("hindsight_agent_memory_enabled", False):
        return [project_bank]
    return _dedupe_bank_ids([get_agent_bank_id(context), project_bank])


def get_bank_id(context: "AgentContext") -> str:
    """Backward-compatible primary retain bank ID."""
    banks = get_retain_bank_ids(context)
    return banks[0] if banks else get_project_bank_id(context)


def _dedupe_bank_ids(bank_ids: List[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for bank_id in bank_ids:
        key = str(bank_id or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(key)
    return result


def _response_text(result: Any) -> Optional[str]:
    """Extract useful text from a Hindsight SDK response."""
    if result is None:
        return None
    for attr in ("content", "text", "response"):
        value = getattr(result, attr, None)
        if value:
            return str(value)
    facts = getattr(result, "facts", None)
    if facts:
        facts_text = []
        for fact in facts:
            for attr in ("content", "text"):
                value = getattr(fact, attr, None)
                if value:
                    facts_text.append(str(value))
                    break
            else:
                facts_text.append(str(fact))
        return "\n".join(facts_text) if facts_text else None
    result_str = str(result)
    return result_str if result_str and result_str != "None" else None


def _normalize_memory_text(text: str) -> str:
    import re
    normalized = str(text or "").lower().strip()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"^[\-•*\s]+", "", normalized)
    normalized = re.sub(r"\s*[.;]+$", "", normalized)
    return normalized


def _dedupe_recall_sections(sections: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = set()
    deduped: List[Dict[str, str]] = []
    for section in sections:
        text = section.get("text", "")
        lines = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            key = _normalize_memory_text(line)
            if not key or key in seen:
                continue
            seen.add(key)
            lines.append(line)
        if lines:
            deduped.append({**section, "text": "\n".join(lines)})
    return deduped


def _format_layered_recall(sections: List[Dict[str, str]]) -> Optional[str]:
    if not sections:
        return None
    parts = []
    for section in sections:
        label = section.get("label") or section.get("bank_id") or "memory"
        text = section.get("text", "").strip()
        if text:
            parts.append(f"[{label}]\n{text}")
    return "\n\n".join(parts) if parts else None


async def retain_memory(context: "AgentContext", content: str, metadata: Optional[Dict[str, str]] = None) -> bool:
    """Store a memory in one or more Hindsight banks via async retain."""
    if not is_configured(context):
        return False

    agent0 = getattr(context, "agent0", None)
    config = _get_plugin_config(agent0)
    if not config.get("hindsight_retain_enabled", True):
        return False

    client = get_client(context)
    if not client:
        return False

    bank_ids = get_retain_bank_ids(context, content)
    if not bank_ids:
        return False

    retained = 0
    for bank_id in bank_ids:
        try:
            kwargs: Dict[str, Any] = {
                "bank_id": bank_id,
                "content": content[:10000],  # Limit content size
            }
            meta = dict(metadata or {})
            if len(bank_ids) > 1:
                meta["hindsight_retain_targets"] = ",".join(bank_ids)
            if meta:
                kwargs["metadata"] = meta

            await client.aretain(**kwargs)
            retained += 1
            if config.get("hindsight_debug", False):
                _log(context, f"Retained memory to bank '{bank_id}': {content[:80]}...", "util")
        except Exception as e:
            _log(context, f"Retain error for bank '{bank_id}': {e}", "error")

    return retained > 0


async def recall_memories(context: "AgentContext", query: str) -> Optional[str]:
    """Search Hindsight memories via async layered recall."""
    if not is_configured(context):
        return None

    agent0 = getattr(context, "agent0", None)
    config = _get_plugin_config(agent0)
    if not config.get("hindsight_recall_enabled", True):
        return None

    client = get_client(context)
    if not client:
        return None

    try:
        if not query or not query.strip():
            _log(context, "Recall query is empty after validation", "debug")
            return None
        safe_query = query.strip()[:1500]

        bank_ids = get_recall_bank_ids(context)
        sections: List[Dict[str, str]] = []
        for index, bank_id in enumerate(bank_ids):
            try:
                result = await client.arecall(
                    bank_id=bank_id,
                    query=safe_query,
                    max_tokens=config.get("hindsight_recall_max_tokens", 4096),
                    budget=config.get("hindsight_recall_budget", "mid"),
                )
                text = _response_text(result)
                if text and text.strip():
                    sections.append({
                        "bank_id": bank_id,
                        "label": "agent" if index == 0 and is_agent_memory_enabled(context) else "project",
                        "text": text.strip(),
                    })
            except Exception as e:
                error_msg = str(e)
                if "400" in error_msg or "Bad Request" in error_msg:
                    _log(context, f"Recall 400 Bad Request: {error_msg[:200]}. Query length: {len(query) if query else 0}. Bank: {bank_id}", "warning")
                else:
                    _log(context, f"Recall error for bank '{bank_id}': {error_msg}", "error")

        return _format_layered_recall(_dedupe_recall_sections(sections))

    except Exception as e:
        _log(context, f"Recall error: {e}", "error")
        return None


async def reflect_context(context: "AgentContext", query: str) -> Optional[str]:
    """Generate disposition-aware context from Hindsight via layered reflect."""
    if not is_configured(context):
        return None

    agent0 = getattr(context, "agent0", None)
    config = _get_plugin_config(agent0)
    if not config.get("hindsight_reflect_enabled", True):
        return None

    bank_ids = get_recall_bank_ids(context)
    bank_key = "+".join(bank_ids)

    # Check cache
    cache_key = f"{bank_key}:{getattr(context, 'id', 'default')}"
    cache_ttl = config.get("hindsight_cache_ttl", 120)
    if cache_key in _reflect_cache:
        cached_time, cached_content = _reflect_cache[cache_key]
        if time.time() - cached_time < cache_ttl:
            return cached_content

    client = get_client(context)
    if not client:
        return None

    try:
        safe_query = query.strip()[:1500] if query else ""
        if not safe_query:
            return None

        sections: List[Dict[str, str]] = []
        for index, bank_id in enumerate(bank_ids):
            try:
                result = await client.areflect(
                    bank_id=bank_id,
                    query=safe_query,
                    budget=config.get("hindsight_reflect_budget", "low"),
                    max_tokens=config.get("hindsight_reflect_max_tokens", 500),
                )
                text = _response_text(result)
                if text and text.strip():
                    sections.append({
                        "bank_id": bank_id,
                        "label": "agent" if index == 0 and is_agent_memory_enabled(context) else "project",
                        "text": text.strip(),
                    })
            except Exception as e:
                _log(context, f"Reflect error for bank '{bank_id}': {e}", "error")

        content = _format_layered_recall(_dedupe_recall_sections(sections))
        _reflect_cache[cache_key] = (time.time(), content)
        return content

    except Exception as e:
        _log(context, f"Reflect error: {e}", "error")
        return None


def clear_cache(bank_id: Optional[str] = None) -> None:
    """Clear cached reflect contexts."""
    global _reflect_cache
    if bank_id:
        keys_to_remove = [k for k in _reflect_cache if k.startswith(f"{bank_id}:")]
        for k in keys_to_remove:
            del _reflect_cache[k]
    else:
        _reflect_cache = {}


def cleanup(context: Optional["AgentContext"] = None) -> None:
    """Cleanup caches for a specific context or all."""
    if context:
        bank_id = get_bank_id(context)
        clear_cache(bank_id)
    else:
        clear_cache()
