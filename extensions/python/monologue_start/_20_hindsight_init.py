"""
Hindsight Initialization Extension
Initializes the Hindsight client when agent starts a monologue.
Also performs auto-install of missing dependencies on first run.
"""

import subprocess
import sys
from agent import AgentContext
from helpers.extension import Extension
from usr.plugins.a0_hindsight.helpers import hindsight_helper


class HindsightInit(Extension):

    def execute(self, **kwargs):
        """Initialize Hindsight integration for this agent context."""
        context: AgentContext = self.agent.context

        if not hasattr(context, "agent0"):
            return

        try:
            # Step 1: Auto-install missing dependencies (on first extension run)
            # This handles the case where hooks.py install() was never called (e.g. on backend reload)
            if not hindsight_helper.is_hindsight_client_available():
                self._auto_install_dependencies(context)
            
            # Step 2: Initialize Hindsight client if configured
            if not hindsight_helper.is_configured(context):
                return

            client = hindsight_helper.get_client(context)
            if client:
                bank_id = hindsight_helper.get_bank_id(context)
                hindsight_helper._log(
                    context,
                    f"Integration enabled for bank: {bank_id}",
                    "util",
                )

                if not hasattr(context, "_hindsight"):
                    context._hindsight = {}
                context._hindsight["enabled"] = True
                context._hindsight["bank_id"] = bank_id
        except Exception as e:
            hindsight_helper._log(context, f"Init error: {e}", "error")

    @staticmethod
    def _auto_install_dependencies(context: AgentContext) -> None:
        """Auto-install hindsight_client if missing (fallback for missing hooks.py install()).
        
        This runs on first extension execution after backend reload, ensuring dependencies
        are available before the extensions try to use them. Logs results clearly so users
        can see what happened.
        """
        hindsight_helper._log(
            context,
            "hindsight_client not available — auto-installing...",
            "warning",
        )
        
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--quiet", "hindsight-client>=0.4.0"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            
            if result.returncode == 0:
                # Verify the import works
                try:
                    from hindsight_client import Hindsight  # noqa: F401
                    hindsight_helper._log(
                        context,
                        "hindsight_client auto-installed successfully",
                        "util",
                    )
                    # Update status file to reflect successful installation
                    hindsight_helper._update_status_file_success(context)
                except ImportError:
                    hindsight_helper._log(
                        context,
                        "hindsight_client auto-install completed but import failed",
                        "error",
                    )
            else:
                error_msg = result.stderr[:200] if result.stderr else "Unknown error"
                hindsight_helper._log(
                    context,
                    f"hindsight_client auto-install failed: {error_msg}",
                    "error",
                )
        except subprocess.TimeoutExpired:
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
