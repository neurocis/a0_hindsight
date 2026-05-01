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
from typing import Optional, Dict, Any, TYPE_CHECKING
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


def _get_plugin_config(agent: Any) -> Dict[str, Any]:
    """Read plugin settings with global/per-project merge.
    
    Global settings (hindsight_base_url, hindsight_bank_prefix) are always
    read from the global (no-project) scope, then per-project settings are
    layered on top. This ensures server connection info is shared while
    feature toggles and operational settings can vary per project.
    
    Priority:
    1. A0 framework get_plugin_config() (resolves project/agent scope)
    2. Global config for global-only settings (base_url, bank_prefix)
    3. Direct config.json file read (Docker-safe fallback)
    4. _DEFAULTS only
    """
    config = {}
    
    # Try A0 framework config API first (requires valid agent reference)
    if agent is not None:
        try:
            from helpers.plugins import get_plugin_config
            # Read project-scoped config (all settings for this project)
            config = get_plugin_config("a0_hindsight", agent=agent) or {}
            
            # Always force global settings from global scope
            # (base_url and bank_prefix must not vary per project)
            global_config = get_plugin_config("a0_hindsight", agent=agent, project_name="") or {}
            for key in _GLOBAL_SETTINGS:
                if key in global_config:
                    config[key] = global_config[key]
        except Exception as e:
            import traceback
            print(f"[HINDSIGHT DEBUG] _get_plugin_config() framework API failed: {type(e).__name__}: {e}")
            config = {}
    
    # Fallback: read config.json directly from plugin directory (Docker-persistent)
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
                # Merge: file values only fill truly missing keys
                # (not False booleans, which are valid user choices)
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


def get_bank_id(context: "AgentContext") -> str:
    """Derive a Hindsight bank ID from the agent context.

    Uses the bank prefix + project name (if active) for memory isolation.
    Always uses the actual project name when a project is active,
    even if the project has no per-project settings defined.
    Only falls back to prefix + 'default' when no project is active at all.
    
    If hindsight_bank_id is explicitly set in config, that takes priority.
    """
    agent0 = getattr(context, "agent0", None)
    config = _get_plugin_config(agent0)
    
    # Explicit override takes priority
    explicit_id = config.get("hindsight_bank_id", "").strip()
    if explicit_id:
        return explicit_id
    
    prefix = config.get("hindsight_bank_prefix", "a0")

    # Resolve project name using the framework's context data.
    # This always returns the active project name when one is active,
    # even if the project has no per-project plugin settings defined.
    project_name = None
    try:
        from helpers.projects import get_context_project_name
        project_name = get_context_project_name(context)
    except Exception:
        pass

    # Fallback: try context.project.name (less reliable)
    if not project_name:
        try:
            if hasattr(context, "project") and context.project:
                project_name = getattr(context.project, "name", None)
        except Exception:
            pass

    if project_name:
        return f"{prefix}-{project_name}"
    return f"{prefix}-default"


async def retain_memory(context: "AgentContext", content: str, metadata: Optional[Dict[str, str]] = None) -> bool:
    """Store a memory in Hindsight via async retain."""
    if not is_configured(context):
        return False

    agent0 = getattr(context, "agent0", None)
    config = _get_plugin_config(agent0)
    if not config.get("hindsight_retain_enabled", True):
        return False

    client = get_client(context)
    if not client:
        return False

    bank_id = get_bank_id(context)

    try:
        kwargs: Dict[str, Any] = {
            "bank_id": bank_id,
            "content": content[:10000],  # Limit content size
        }
        if metadata:
            kwargs["metadata"] = metadata

        await client.aretain(**kwargs)

        if config.get("hindsight_debug", False):
            _log(context, f"Retained memory to bank '{bank_id}': {content[:80]}...", "util")
        return True
    except Exception as e:
        _log(context, f"Retain error: {e}", "error")
        return False


async def recall_memories(context: "AgentContext", query: str) -> Optional[str]:
    """Search Hindsight memories via async recall."""
    if not is_configured(context):
        return None

    agent0 = getattr(context, "agent0", None)
    config = _get_plugin_config(agent0)
    if not config.get("hindsight_recall_enabled", True):
        return None

    client = get_client(context)
    if not client:
        return None
    bank_id = get_bank_id(context)

    try:
        # Validate and truncate query before sending
        # Hindsight service enforces a 500-token query limit.
        # ~1500 chars is safely under 500 tokens for most tokenizers (GitHub #1 Bug 3).
        if not query or not query.strip():
            _log(context, "Recall query is empty after validation", "debug")
            return None
        
        safe_query = query.strip()[:1500]
        
        result = await client.arecall(
            bank_id=bank_id,
            query=safe_query,
            max_tokens=config.get("hindsight_recall_max_tokens", 4096),
            budget=config.get("hindsight_recall_budget", "mid"),
        )

        # Extract text content from recall response
        if hasattr(result, "content") and result.content:
            return result.content
        elif hasattr(result, "text") and result.text:
            return result.text
        elif hasattr(result, "facts") and result.facts:
            # Format facts into readable text
            facts_text = []
            for fact in result.facts:
                if hasattr(fact, "content"):
                    facts_text.append(fact.content)
                elif hasattr(fact, "text"):
                    facts_text.append(fact.text)
                else:
                    facts_text.append(str(fact))
            return "\n".join(facts_text) if facts_text else None
        else:
            # Try converting to string as last resort
            result_str = str(result)
            return result_str if result_str and result_str != "None" else None

    except Exception as e:
        error_msg = str(e)
        # Log more detailed error info for debugging
        if "400" in error_msg or "Bad Request" in error_msg:
            _log(context, f"Recall 400 Bad Request: {error_msg[:200]}. Query length: {len(query) if query else 0}. Bank: {bank_id}", "warning")
        else:
            _log(context, f"Recall error: {error_msg}", "error")
        return None


async def reflect_context(context: "AgentContext", query: str) -> Optional[str]:
    """Generate disposition-aware context from Hindsight via async reflect."""
    if not is_configured(context):
        return None

    agent0 = getattr(context, "agent0", None)
    config = _get_plugin_config(agent0)
    if not config.get("hindsight_reflect_enabled", True):
        return None

    bank_id = get_bank_id(context)

    # Check cache
    cache_key = f"{bank_id}:{getattr(context, 'id', 'default')}"
    cache_ttl = config.get("hindsight_cache_ttl", 120)
    if cache_key in _reflect_cache:
        cached_time, cached_content = _reflect_cache[cache_key]
        if time.time() - cached_time < cache_ttl:
            return cached_content

    client = get_client(context)
    if not client:
        return None

    try:
        # Truncate query to stay within Hindsight's 500-token query limit (GitHub #1 Bug 3)
        safe_query = query.strip()[:1500] if query else ""
        if not safe_query:
            return None
        
        result = await client.areflect(
            bank_id=bank_id,
            query=safe_query,
            budget=config.get("hindsight_reflect_budget", "low"),
            max_tokens=config.get("hindsight_reflect_max_tokens", 500),
        )

        content = None
        if hasattr(result, "content") and result.content:
            content = result.content
        elif hasattr(result, "text") and result.text:
            content = result.text
        elif hasattr(result, "response") and result.response:
            content = result.response
        else:
            result_str = str(result)
            if result_str and result_str != "None":
                content = result_str

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
