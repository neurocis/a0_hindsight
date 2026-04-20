"""
Hindsight Integration Helper for Agent Zero

Handles Hindsight client management, memory retention,
recall, and reflect operations for persistent memory augmentation.

Uses async variants (aretain, arecall, areflect) since Agent Zero
extensions run inside an async event loop.
"""

import os
import time
from typing import Optional, Dict, Any, TYPE_CHECKING
if TYPE_CHECKING:
    from agent import AgentContext

try:
    from hindsight_client import Hindsight
    HINDSIGHT_AVAILABLE = True
except ImportError:
    # Auto-install: if install() hook wasn't called (manual placement),
    # pip install the dependency so extensions don't silently fail.
    import subprocess
    import sys
    import logging as _logging
    _logger = _logging.getLogger(__name__)
    _logger.warning(
        "[Hindsight] hindsight_client not available — attempting auto-install..."
    )
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "hindsight-client>=0.4.0"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        # Re-import after installation
        from hindsight_client import Hindsight
        HINDSIGHT_AVAILABLE = True
        _logger.info("[Hindsight] hindsight_client auto-installed and loaded successfully.")
    except subprocess.TimeoutExpired:
        _logger.error("[Hindsight] Auto-install timed out (>30s)")
        HINDSIGHT_AVAILABLE = False
        Hindsight = None  # type: ignore[assignment,misc]
    except subprocess.CalledProcessError as _e:
        _logger.error(f"[Hindsight] Auto-install failed: pip returned {_e.returncode}")
        if _e.stderr:
            _logger.error(f"[Hindsight] pip stderr: {_e.stderr}")
        HINDSIGHT_AVAILABLE = False
        Hindsight = None  # type: ignore[assignment,misc]
    except Exception as _e:
        _logger.error(f"[Hindsight] Auto-install error: {_e}")
        HINDSIGHT_AVAILABLE = False
        Hindsight = None  # type: ignore[assignment,misc]

# Module-level caches
_client_cache: Dict[str, Any] = {}
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


def _get_plugin_config(agent: Any) -> Dict[str, Any]:
    """Read plugin settings from A0's config system with fallbacks."""
    try:
        from helpers.plugins import get_plugin_config
        config = get_plugin_config("a0_hindsight", agent=agent) or {}
    except Exception:
        config = {}

    for key, default in _DEFAULTS.items():
        if key not in config:
            config[key] = default
    return config


def is_hindsight_client_available() -> bool:
    """Runtime check for hindsight_client availability.
    
    Fast path: reads .dependency_status.json file created by hooks.py install().
    Slow path: performs live import check if status file missing (self-healing).
    
    Returns True if hindsight_client is available, False otherwise.
    """
    import os
    import json
    
    plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    status_file = os.path.join(plugin_dir, ".dependency_status.json")
    
    # Fast path: check cached status file from installation
    if os.path.isfile(status_file):
        try:
            with open(status_file, "r") as f:
                status = json.load(f)
                if status.get("hindsight_client"):
                    return True
        except Exception:
            pass
    
    # Slow path: live check (status file missing or invalid)
    available = HINDSIGHT_AVAILABLE
    
    if available:
        # Self-heal: create the status file so future checks are instant
        try:
            status_data = {
                "checked_at": _get_timestamp(),
                "hindsight_client": True,
                "warnings": ["auto-created by lazy init (hooks.install was not run)"],
                "errors": [],
            }
            os.makedirs(plugin_dir, exist_ok=True)
            with open(status_file, "w") as f:
                json.dump(status_data, f, indent=2)
        except Exception:
            pass  # Status file creation failed, but hindsight_client is available
    
    return available


def _get_timestamp() -> str:
    """Return current timestamp in ISO format."""
    from datetime import datetime


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
    if not HINDSIGHT_AVAILABLE:
        return False
    agent = getattr(context, "agent0", None) if context else None
    return bool(get_base_url(context, agent))


def get_client(context: Optional["AgentContext"] = None) -> Optional[Any]:
    """Get or create a cached Hindsight client."""
    if not HINDSIGHT_AVAILABLE:
        return None

    base_url = get_base_url(context)
    if not base_url:
        return None

    api_key = get_api_key(context)

    cache_key = f"{base_url}:{api_key or 'none'}"
    if cache_key in _client_cache:
        return _client_cache[cache_key]

    try:
        kwargs: Dict[str, Any] = {"base_url": base_url}
        if api_key:
            kwargs["api_key"] = api_key
        client = Hindsight(**kwargs)
        _client_cache[cache_key] = client
        _log(context, f"Connected to Hindsight at: {base_url}", "util")
        return client
    except Exception as e:
        _log(context, f"Client creation error: {e}", "error")
        return None


def get_bank_id(context: "AgentContext") -> str:
    """Derive a Hindsight bank ID from the agent context.

    Uses the bank prefix + project name (if active) for memory isolation.
    Falls back to prefix + 'default' if no project is active.
    
    NEW: if hindsight_bank_id is explicitly set in config, use that instead.
    """
    agent0 = getattr(context, "agent0", None)
    config = _get_plugin_config(agent0) if agent0 else {}
    
    # Explicit override takes priority
    explicit_id = config.get("hindsight_bank_id", "").strip()
    if explicit_id:
        return explicit_id
    
    prefix = config.get("hindsight_bank_prefix", "a0")

    # Try to get project name for isolation
    project_name = None
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
    config = _get_plugin_config(agent0) if agent0 else {}
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
    config = _get_plugin_config(agent0) if agent0 else {}
    if not config.get("hindsight_recall_enabled", True):
        return None

    client = get_client(context)
    if not client:
        return None

    bank_id = get_bank_id(context)
    try:
        # Validate query before sending
        if not query or not query.strip():
            _log(context, "Recall query is empty after validation", "debug")
            return None
        
        result = await client.arecall(
            bank_id=bank_id,
            query=query,
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
    config = _get_plugin_config(agent0) if agent0 else {}
    if not config.get("hindsight_reflect_enabled", True):
        return None

    bank_id = get_bank_id(context)

    # Check cache
    cache_key = f"{bank_id}:{query[:100]}"
    cache_ttl = config.get("hindsight_cache_ttl", 120)
    if cache_key in _reflect_cache:
        cached_time, cached_content = _reflect_cache[cache_key]
        if time.time() - cached_time < cache_ttl:
            return cached_content

    client = get_client(context)
    if not client:
        return None

    try:
        result = await client.areflect(
            bank_id=bank_id,
            query=query,
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
        _client_cache.clear()
