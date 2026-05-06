"""
Hindsight Reflect Context Injection Extension
Injects disposition-aware context from Hindsight reflect
into the agent's system prompt.
"""

import asyncio
import os
import sys
from agent import AgentContext
from helpers.extension import Extension
from helpers import errors

# Fix import path for hindsight plugin helpers
# Add /a0 to sys.path so that 'usr.plugins.a0_hindsight' can be resolved
plugin_base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
if plugin_base not in sys.path:
    sys.path.insert(0, plugin_base)

from usr.plugins.a0_hindsight.helpers import hindsight_helper

REFLECT_TIMEOUT = 15


class HindsightReflect(Extension):

    async def execute(self, system_prompt: list[str] = [], **kwargs):
        """Add Hindsight reflect context to system prompt."""
        context: AgentContext = self.agent.context

        if not hasattr(context, "agent0"):
            return

        if not hindsight_helper.is_configured(context):
            return

        try:
            config = hindsight_helper._get_plugin_config(self.agent)
            if not config.get("hindsight_reflect_enabled", True):
                return

            # Build a query from recent history for reflect
            history_text = self.agent.history.output_text()[-2000:]
            if not history_text or len(history_text.strip()) <= 3:
                return

            query = f"Based on the current conversation, what relevant context should I know?\n\n{history_text}"

            reflect_result = await asyncio.wait_for(
                hindsight_helper.reflect_context(context, query, agent=self.agent),
                timeout=REFLECT_TIMEOUT,
            )

            if reflect_result and reflect_result.strip():
                prompt = self.agent.read_prompt(
                    "hindsight.reflect.md",
                    hindsight_context=reflect_result,
                )
                system_prompt.append(prompt)

        except asyncio.TimeoutError:
            pass  # Silently skip on timeout
        except Exception as e:
            hindsight_helper._log(context, f"Reflect context error (non-fatal): {e}", "error")
