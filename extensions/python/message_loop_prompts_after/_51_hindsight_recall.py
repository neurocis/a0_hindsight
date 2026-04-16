"""
Hindsight Recall Extension
Enriches memory recall with Hindsight semantic search results.

Runs at priority _51 (after _50_recall_memories from core memory plugin).
Injects Hindsight recall results into the agent's extras for system prompt.
"""

import asyncio
from helpers.extension import Extension
from agent import LoopData
from helpers import errors, plugins

from usr.plugins.a0_hindsight.helpers import hindsight_helper


SEARCH_TIMEOUT = 30


class HindsightRecall(Extension):

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        if not self.agent:
            return

        context = self.agent.context
        if not hasattr(context, "agent0"):
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
        if loop_data.iteration % interval != 0:
            return

        log_item = self.agent.context.log.log(
            type="util",
            heading="Searching Hindsight memories...",
        )

        try:
            # Build query from user message and recent history
            user_instruction = (
                loop_data.user_message.output_text() if loop_data.user_message else "None"
            )
            history_len = core_config.get("memory_recall_history_len", 10000)
            history = self.agent.history.output_text()[-history_len:]
            query = f"{user_instruction}\n\n{history}"

            # Truncate query to reasonable size for Hindsight
            query = query[:4000]

            if not query or len(query.strip()) <= 3:
                log_item.update(heading="No query for Hindsight recall")
                return

            # Run recall with timeout
            recall_result = await asyncio.wait_for(
                hindsight_helper.recall_memories(context, query),
                timeout=SEARCH_TIMEOUT,
            )

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

        except asyncio.TimeoutError:
            log_item.update(heading="Hindsight recall timed out")
        except Exception as e:
            err = errors.format_error(e)
            self.agent.context.log.log(
                type="warning",
                heading="Hindsight recall extension error",
                content=err,
            )
