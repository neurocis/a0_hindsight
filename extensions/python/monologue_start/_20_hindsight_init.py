"""
Hindsight Initialization Extension
Initializes the Hindsight client when agent starts a monologue.
"""

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
