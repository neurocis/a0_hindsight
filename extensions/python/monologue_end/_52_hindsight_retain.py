"""
Hindsight Retain Extension
After the core memory plugin memorizes fragments, this extension
also retains them to Hindsight for semantic enrichment.

Runs at priority _52 (after _50_memorize_fragments and _51_memorize_solutions).
"""

import asyncio
from helpers import errors, plugins
from helpers.extension import Extension
from helpers.dirty_json import DirtyJson
from agent import LoopData
from helpers.defer import DeferredTask, THREAD_BACKGROUND

from usr.plugins.a0_hindsight.helpers import hindsight_helper


class HindsightRetain(Extension):

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        if not self.agent:
            return

        context = self.agent.context
        if not hasattr(context, "agent0"):
            return

        if not hindsight_helper.is_configured(context):
            return

        config = hindsight_helper._get_plugin_config(self.agent)
        if not config.get("hindsight_retain_enabled", True):
            return

        # Run retention in background to avoid blocking
        # Using DeferredTask with async function directly (same pattern as cognee retain)
        DeferredTask(
            self._retain_to_hindsight,
            self.agent,
            context,
            loop_data,
            config,
            thread_group=THREAD_BACKGROUND,
        )

    @staticmethod
    async def _retain_to_hindsight(agent, context, loop_data, config):
        """Background task: extract knowledge and store in Hindsight."""
        try:
            log_item = context.log.log(
                type="util",
                heading="Retaining to Hindsight...",
            )

            # Get the conversation history to extract what should be retained
            system = agent.read_prompt("hindsight.retain_extract.sys.md")
            msgs_text = agent.concat_messages(agent.history)

            # Call utility LLM to extract key information from conversation
            memories_json = await agent.call_utility_model(
                system=system,
                message=msgs_text,
                background=True,
            )

            if not memories_json or not isinstance(memories_json, str):
                log_item.update(heading="No content to retain to Hindsight.")
                return

            memories_json = memories_json.strip()
            if not memories_json:
                log_item.update(heading="Empty response for Hindsight retain.")
                return

            try:
                memories = DirtyJson.parse_string(memories_json)
            except Exception as e:
                log_item.update(heading=f"Failed to parse retain content: {e}")
                return

            if memories is None:
                log_item.update(heading="No valid content to retain.")
                return

            if not isinstance(memories, list):
                if isinstance(memories, (str, dict)):
                    memories = [memories]
                else:
                    log_item.update(heading="Invalid retain content format.")
                    return

            if len(memories) == 0:
                log_item.update(heading="No useful information to retain to Hindsight.")
                return

            # Retain each memory to Hindsight
            retained = 0
            failed = 0
            for memory in memories:
                content = str(memory).strip()
                if not content:
                    continue

                success = await hindsight_helper.retain_memory(
                    context=context,
                    content=content,
                )
                if success:
                    retained += 1
                else:
                    failed += 1

            bank_id = hindsight_helper.get_bank_id(context)
            log_item.update(
                heading=f"Hindsight: {retained} memories retained to bank '{bank_id}'",
                content=f"Retained: {retained}, Failed: {failed}",
            )

        except Exception as e:
            try:
                err = errors.format_error(e)
                context.log.log(
                    type="warning",
                    heading="Hindsight retain background error",
                    content=err,
                )
            except Exception:
                pass
