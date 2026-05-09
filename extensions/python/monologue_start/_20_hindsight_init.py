"""
Hindsight Initialization Extension
Initializes the Hindsight client when agent starts a monologue.
Also performs auto-install of missing dependencies on first run.

Uses async subprocess to avoid blocking the main thread during
pip install (GitHub #2 Bug 5).
"""

import asyncio
import sys
import os
from agent import AgentContext
from helpers.extension import Extension

# Fix import path for hindsight plugin helpers
# Add /a0 to sys.path so that 'usr.plugins.a0_hindsight' can be resolved
plugin_base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
if plugin_base not in sys.path:
    sys.path.insert(0, plugin_base)

from usr.plugins.a0_hindsight.helpers import hindsight_helper
import importlib
importlib.reload(hindsight_helper)  # ensure fresh signatures across hot-reloads

# Track whether auto-install has been attempted this process lifetime
_install_attempted = False


class HindsightInit(Extension):

    async def execute(self, **kwargs):
        """Initialize Hindsight integration for this agent context."""
        context: AgentContext = self.agent.context

        if not hasattr(context, "agent0"):
            return

        try:
            # Step 1: Auto-install missing dependencies (once per process)
            # Uses async subprocess to avoid blocking the agent loop (GitHub #2 Bug 5)
            global _install_attempted
            if not _install_attempted and not hindsight_helper.is_hindsight_client_available():
                _install_attempted = True
                await self._async_auto_install(context)

            client_available = hindsight_helper.is_hindsight_client_available()
            configured = hindsight_helper.is_configured(context)

            # Step 2: Initialize Hindsight client if configured
            if not configured:
                # Still emit a verbose init event so operators can see why
                # Hindsight is silent (e.g. unconfigured base URL).
                hindsight_helper.emit_verbose_event(
                    context,
                    "init",
                    {
                        "client_available": client_available,
                        "configured": False,
                        "enabled": False,
                        "success": False,
                    },
                    agent=self.agent,
                )
                return

            client = hindsight_helper.get_client(context)
            bank_id = None
            if client:
                bank_id = hindsight_helper.get_bank_id(context, agent=self.agent)
                hindsight_helper._log(
                    context,
                    f"Integration enabled for bank: {bank_id}",
                    "util",
                )

                if not hasattr(context, "_hindsight"):
                    context._hindsight = {}
                context._hindsight["enabled"] = True
                context._hindsight["bank_id"] = bank_id

            # Emit verbose init event (no-op when verbose mode disabled)
            hindsight_helper.emit_verbose_event(
                context,
                "init",
                {
                    "bank_id": bank_id,
                    "client_available": client_available,
                    "configured": configured,
                    "enabled": bool(client),
                    "success": bool(client),
                },
                agent=self.agent,
            )
        except Exception as e:
            hindsight_helper._log(context, f"Init error: {e}", "error")
            try:
                hindsight_helper.emit_verbose_event(
                    context,
                    "init",
                    {
                        "success": False,
                        "error": str(e),
                    },
                    agent=self.agent,
                )
            except Exception:
                pass

    @staticmethod
    async def _async_auto_install(context: AgentContext) -> None:
        """Auto-install hindsight_client if missing, using async subprocess.

        Non-blocking alternative to subprocess.run() — prevents the agent
        loop from stalling for up to 60s on first startup (GitHub #2 Bug 5).
        """
        hindsight_helper._log(
            context,
            "hindsight_client not available \u2014 auto-installing (async)...",
            "warning",
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pip", "install", "--quiet",
                "hindsight-client>=0.4.0",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=60
            )

            if proc.returncode == 0:
                # Verify the import works
                try:
                    from hindsight_client import Hindsight  # noqa: F401
                    hindsight_helper._log(
                        context,
                        "hindsight_client auto-installed successfully",
                        "util",
                    )
                    # Update module-level flag so get_client() works
                    hindsight_helper.HINDSIGHT_AVAILABLE = True
                    hindsight_helper.Hindsight = Hindsight
                    # Update status file for fast-path checks
                    hindsight_helper._update_status_file_success(context)
                except ImportError:
                    hindsight_helper._log(
                        context,
                        "hindsight_client auto-install completed but import failed",
                        "error",
                    )
            else:
                error_msg = stderr.decode()[:200] if stderr else "Unknown error"
                hindsight_helper._log(
                    context,
                    f"hindsight_client auto-install failed: {error_msg}",
                    "error",
                )
        except asyncio.TimeoutError:
            hindsight_helper._log(
                context,
                "hindsight_client auto-install timed out (>60s)",
                "error",
            )
        except Exception as e:
            hindsight_helper._log(
                context,
                f"hindsight_client auto-install error: {e}",
                "error",
            )
