"""Save Hindsight per-agent memory settings for a context's active agent profile."""
from __future__ import annotations

from helpers.api import ApiHandler, Request, Response
from helpers import plugins
from agent import AgentContext


class HindsightAgentConfigSet(ApiHandler):
    @classmethod
    def get_methods(cls) -> list[str]:
        return ["POST"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        ctxid = (input.get("ctxid") or input.get("context") or "").strip()
        context = AgentContext.get(ctxid) if ctxid else AgentContext.current()
        if not context:
            return {"ok": False, "error": "Missing or unknown ctxid"}

        settings = input.get("settings") or {}
        if not isinstance(settings, dict):
            return {"ok": False, "error": "settings must be an object"}

        try:
            from usr.plugins.a0_hindsight.helpers import hindsight_helper

            agent = getattr(context, "agent0", None)
            agent_profile = hindsight_helper._get_agent_profile(agent, context)
            if not agent_profile:
                return {"ok": False, "error": "Could not resolve active agent profile"}

            existing = plugins.get_plugin_config(
                "a0_hindsight",
                agent=agent,
                project_name="",
                agent_profile=agent_profile,
            ) or {}
            existing.update({
                "hindsight_agent_memory_enabled": bool(settings.get("hindsight_agent_memory_enabled", False)),
                "hindsight_agent_bank_id": str(settings.get("hindsight_agent_bank_id", "") or "").strip(),
                "hindsight_agent_retain_to_project": bool(settings.get("hindsight_agent_retain_to_project", False)),
            })
            plugins.save_plugin_config(
                "a0_hindsight",
                project_name="",
                agent_profile=agent_profile,
                settings=existing,
            )
            hindsight_helper.clear_cache()
            return {
                "ok": True,
                "ctxid": context.id,
                "agent_profile": agent_profile,
                "agent_display_name": hindsight_helper._get_agent_display_name(agent, context),
                "agent_default_bank_id": hindsight_helper.get_agent_default_bank_id(context),
                "settings": existing,
                "agent_bank_id": hindsight_helper.get_agent_bank_id(context),
                "retain_bank_ids": hindsight_helper.get_retain_bank_ids(context),
                "recall_bank_ids": hindsight_helper.get_recall_bank_ids(context),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}
