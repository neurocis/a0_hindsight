"""
Hindsight Retain Extension
After the core memory plugin memorizes fragments, this extension
also retains them to Hindsight for semantic enrichment.

Runs at priority _52 (after _50_memorize_fragments and _51_memorize_solutions).

Uses asyncio.create_task() instead of DeferredTask to avoid
'Timeout context manager should be used inside a task' errors.
DeferredTask creates a separate background event loop thread,
which causes asyncio.timeout() (used internally by httpx/aiohttp
in Python 3.11+) to fail because the HTTP client sessions and
asyncio timeout contexts are bound to the main loop.
"""

import asyncio
import os
import sys
from helpers import errors, plugins
from helpers.extension import Extension
from helpers.dirty_json import DirtyJson
from helpers.history import output_text as history_output_text
from agent import LoopData

# Fix import path for hindsight plugin helpers
# Add /a0 to sys.path so that 'usr.plugins.a0_hindsight' can be resolved
plugin_base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
if plugin_base not in sys.path:
    sys.path.insert(0, plugin_base)

from usr.plugins.a0_hindsight.helpers import hindsight_helper

class HindsightRetain(Extension):

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
        if not config.get("hindsight_retain_enabled", True):
            return

        # Run retention as a fire-and-forget task on the SAME event loop.
        # Using asyncio.create_task() instead of DeferredTask because:
        # - DeferredTask creates a separate background event loop thread
        # - The LLM client (httpx) and Hindsight SDK (aiohttp) use
        #   asyncio.timeout() internally, which requires being inside a
        #   proper asyncio Task on the current running loop
        # - Running on a different loop causes:
        #   'Timeout context manager should be used inside a task'
        try:
            asyncio.create_task(
                self._retain_to_hindsight(
                    self.agent,
                    context,
                    loop_data,
                    config,
                )
            )
        except RuntimeError:
            # No running event loop - should not happen in extension context,
            # but handle gracefully
            pass

    @staticmethod
    async def _retain_to_hindsight(agent, context, loop_data, config):
        """Background task: extract knowledge and store in Hindsight.
        
        Only processes NEW messages since the last retain cycle to avoid
        O(N²) token growth and duplicate memories (GitHub #2 Bug 2).
        """
        try:
            log_item = context.log.log(
                type="util",
                heading="Retaining to Hindsight...",
            )

            # Delta tracking: only extract from messages added since last retain
            if not hasattr(context, '_hindsight'):
                context._hindsight = {}
            last_idx = context._hindsight.get('last_retain_idx', 0)
            
            # Get only new messages since last retain
            # agent.history is a History object; .messages is the underlying list
            all_messages = agent.history.messages
            if last_idx >= len(all_messages):
                log_item.update(heading="No new messages to retain to Hindsight.")
                return
            
            new_messages = all_messages[last_idx:]
            if not new_messages:
                log_item.update(heading="No new messages to retain to Hindsight.")
                return

            # Format new messages as text
            # Note: agent.concat_messages() ignores its argument and always uses
            # the full history, so we format the delta directly
            system = agent.read_prompt("hindsight.retain_extract.sys.md")
            new_outputs = [o for msg in new_messages for o in msg.output()]
            msgs_text = history_output_text(new_outputs)
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
            
            # Update delta tracking index after successful retention
            context._hindsight['last_retain_idx'] = len(all_messages)
            
            log_item.update(
                heading=f"Hindsight: {retained} memories retained to bank '{bank_id}'",
                content=f"Retained: {retained}, Failed: {failed}, New msgs processed: {len(new_messages)}",
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
