"""
Hindsight Recall Extension
Enriches memory recall with Hindsight semantic search results.

Runs at priority _51 (after _50_recall_memories from core memory plugin).
Injects Hindsight recall results into the agent's extras for system prompt.
"""

import asyncio
import os
import sys
from helpers.extension import Extension
from agent import LoopData
from helpers import errors, plugins

# Fix import path for hindsight plugin helpers
# Add /a0 to sys.path so that 'usr.plugins.a0_hindsight' can be resolved
plugin_base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
if plugin_base not in sys.path:
    sys.path.insert(0, plugin_base)

from usr.plugins.a0_hindsight.helpers import hindsight_helper
import importlib
importlib.reload(hindsight_helper)  # ensure fresh signatures across hot-reloads

SEARCH_TIMEOUT = 30


class HindsightRecall(Extension):

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        if not self.agent:
            return

        context = self.agent.context
        if not hasattr(context, "agent0"):
            return
        # Check if hindsight_client is available before proceeding
        if not hindsight_helper.is_hindsight_client_available():
            return

        if not hindsight_helper.is_configured(context):
            return

        config = hindsight_helper._get_plugin_config(self.agent)
        if not config.get("hindsight_recall_enabled", True):
            return

        # Get the core memory plugin's recall interval setting
        core_config = plugins.get_plugin_config("_memory", self.agent) or {}
        interval = core_config.get("memory_recall_interval", 3)

        # Only run on the same iterations as the core recall
        # Clear stale memories on skip iterations (GitHub #2 Bug 3)
        if loop_data.iteration % interval != 0:
            loop_data.extras_persistent.pop("hindsight_memories", None)
            return

        log_item = self.agent.context.log.log(
            type="util",
            heading="Searching Hindsight memories...",
        )

        try:
            # Build query from user message and recent history
            user_instruction = (
                loop_data.user_message.output_text() if loop_data.user_message else ""
            )
            history_len = core_config.get("memory_recall_history_len", 10000)
            history = self.agent.history.output_text()[-history_len:] if self.agent.history else ""
            
            # Build query: prioritize user instruction, fallback to history, ensure non-empty
            query = user_instruction.strip() if user_instruction else ""
            if not query and history:
                query = history.strip()
            
            # Truncate query to stay within Hindsight's 500-token query limit
            # ~1500 chars is safely under 500 tokens for most tokenizers (GitHub #1 Bug 3)
            if query:
                query = query[:1500]
            
            # Validate query is not empty or too short
            if not query or len(query.strip()) < 3:
                log_item.update(heading="Insufficient query for Hindsight recall (need at least 3 chars)")
                return

            recall_result = await hindsight_helper.recall_memories(context, query, agent=self.agent)

            if recall_result and recall_result.strip():
                log_item.update(
                    heading="Hindsight memories found",
                    content=recall_result[:500],
                )

                # Inject into extras for system prompt
                extras = loop_data.extras_persistent
                hindsight_prompt = self.agent.read_prompt(
                    "hindsight.recall.md",
                    hindsight_memories=recall_result,
                )
                extras["hindsight_memories"] = hindsight_prompt
            else:
                log_item.update(heading="No Hindsight memories found")
                # Clear stale memories when recall finds nothing (GitHub #2 Bug 3)
                loop_data.extras_persistent.pop("hindsight_memories", None)

        except asyncio.TimeoutError:
            log_item.update(heading="Hindsight recall timed out")
        except Exception as e:
            err = errors.format_error(e)
            self.agent.context.log.log(
                type="warning",
                heading="Hindsight recall extension error",
                content=err,
            )
