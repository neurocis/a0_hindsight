"""
Hindsight Integration Helper for Agent Zero

Handles Hindsight client management, memory retention,
recall, and reflect operations for persistent memory augmentation.

Uses async variants (aretain, arecall, areflect) since Agent Zero
extensions run inside an async event loop.
"""

import os
import time

if TYPE_CHECKING:
    from agent import AgentContext

try:
    from hindsight_client import Hindsight
    HINDSIGHT_AVAILABLE = True
except ImportError:
    HINDSIGHT_AVAILABLE = False
    Hindsight = None  # type: ignore[assignment,misc]

# Module-level caches
_client_cache: Dict[str, Any] = {}
_reflect_cache: Dict[str, tuple] = {}  # bank_id -> (timestamp, content)

# Default configuration values
_DEFAULTS: Dict[str, Any] = {
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
        config = get_plugin_config("hindsight", agent=agent) or {}
    except Exception:
        config = {}

    for key, default in _DEFAULTS.items():
        if key not in config:
            config[key] = default
    return config


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


def get_base_url(context: Optional["AgentContext"] = None) -> Optional[str]:
    """Retrieve HINDSIGHT_BASE_URL from environment variable.
    
    Reads from os.environ.get("HINDSIGHT_BASE_URL") for non-sensitive configuration.
    """
    url = os.environ.get("HINDSIGHT_BASE_URL", "").strip()
    return url if url else None


def get_api_key(context: Optional["AgentContext"] = None) -> Optional[str]:
    """Retrieve HINDSIGHT_API_KEY from A0 secrets (optional)."""
    key = _get_secret("HINDSIGHT_API_KEY", "", context)
    return key if key else None


def is_configured(context: Optional["AgentContext"] = None) -> bool:
    """Check if Hindsight SDK is available and base URL is set."""
    if not HINDSIGHT_AVAILABLE:
        return False
    return bool(get_base_url(context))


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
    """
    agent0 = getattr(context, "agent0", None)
    config = _get_plugin_config(agent0) if agent0 else {}
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
        _log(context, f"Recall error: {e}", "error")
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
