"""
Hindsight Plugin — Framework Lifecycle Hooks

Manages hindsight_client dependency installation and cleanup.
Follows a0_transcribbler pattern: install/uninstall with status tracking.

Called automatically by the Agent Zero plugin system:
- install()      : after plugin is placed in usr/plugins/
- pre_update()   : before plugin code is updated in place
- uninstall()    : before plugin directory is deleted
"""

import subprocess
import sys
import os
import json
from datetime import datetime

from helpers.print_style import PrintStyle

# Plugin directory (where this file lives)
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
STATUS_FILE = os.path.join(PLUGIN_DIR, ".dependency_status.json")

_PACKAGE = "hindsight-client>=0.4.0"


def _write_status(status: dict) -> None:
    """Write dependency status to a JSON file for runtime checks."""
    try:
        with open(STATUS_FILE, "w") as f:
            json.dump(status, f, indent=2)
    except Exception as e:
        PrintStyle.warning(f"a0_hindsight: could not write status file: {e}")


def _check_hindsight_client() -> bool:
    """Check if hindsight_client Python module is importable."""
    try:
        import hindsight_client  # noqa: F401
        return True
    except ImportError:
        return False


def install():
    """Called by the plugin installer after the plugin is placed.
    
    Ensures hindsight_client is installed and creates a status file for runtime checks.
    Returns 0 on success, 0 (non-critical) on failure so plugin can still load.
    """
    PrintStyle.info("a0_hindsight: checking dependencies...")

    status = {
        "checked_at": datetime.now().isoformat(),
        "hindsight_client": False,
        "warnings": [],
        "errors": [],
    }

    # --- Check and install hindsight_client ---
    if _check_hindsight_client():
        PrintStyle.success("a0_hindsight: hindsight_client already installed")
        status["hindsight_client"] = True
    else:
        PrintStyle.info("a0_hindsight: installing hindsight_client...")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", _PACKAGE],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0 and _check_hindsight_client():
            PrintStyle.success("a0_hindsight: hindsight_client installed successfully")
            status["hindsight_client"] = True
        else:
            error_msg = result.stderr[:500] if result.stderr else "Unknown installation error"
            PrintStyle.error(
                f"a0_hindsight: hindsight_client installation failed: {error_msg}"
            )
            status["errors"].append(f"hindsight_client installation failed: {error_msg}")
            # Continue - plugin loads but extensions will check status and skip gracefully

    # --- Summary ---
    if status["errors"]:
        PrintStyle.error(
            f"a0_hindsight: initialization completed with errors. "
            f"Memory retention may be unavailable. Check status file for details."
        )
    elif status["warnings"]:
        PrintStyle.warning(
            f"a0_hindsight: initialization completed with warnings. "
            f"See status file for details."
        )
    else:
        PrintStyle.success("a0_hindsight: dependency check complete")

    # Write status file for runtime checks
    _write_status(status)

    # Return 0 even on partial failure to allow plugin to load
    # Extensions will check status file and handle accordingly
    return 0


def pre_update():
    """Called before the plugin is updated.
    
    Performs pre-update preparation.
    """
    PrintStyle.info("a0_hindsight: preparing for update...")
    
    # Backup current status for reference
    backup_status = None
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, "r") as f:
                backup_status = json.load(f)
            PrintStyle.info("a0_hindsight: backed up current status")
        except Exception as e:
            PrintStyle.warning(f"a0_hindsight: could not backup status: {e}")
    
    PrintStyle.success("a0_hindsight: ready for update")
    return 0


def uninstall():
    """Called when the plugin is being uninstalled.
    
    Cleans up status file. Does NOT uninstall hindsight_client from system Python
    since it may be used by other plugins or the user.
    """
    PrintStyle.info("a0_hindsight: cleaning up...")
    
    # Remove status file
    if os.path.exists(STATUS_FILE):
        try:
            os.remove(STATUS_FILE)
            PrintStyle.success("a0_hindsight: removed status file")
        except Exception as e:
            PrintStyle.error(f"a0_hindsight: failed to remove status file: {e}")
            return 1
    
    PrintStyle.success("a0_hindsight: uninstall complete")
    return 0
