"""Get effective Hindsight per-agent memory settings for a context."""
from __future__ import annotations

from helpers.api import ApiHandler, Request, Response
from helpers import plugins
from agent import AgentContext


class HindsightAgentConfigGet(ApiHandler):
    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET", "POST"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        ctxid = (input.get("ctxid") or input.get("context") or "").strip()
        context = AgentContext.get(ctxid) if ctxid else AgentContext.current()
        if not context:
            return {"ok": False, "error": "Missing or unknown ctxid"}

        try:
            from usr.plugins.a0_hindsight.helpers import hindsight_helper

            agent = getattr(context, "agent0", None)
            project_name = hindsight_helper._get_project_name(context)
            agent_profile = hindsight_helper._get_agent_profile(agent, context)
            agent_display_name = hindsight_helper._get_agent_display_name(agent, context)
            agent_default_bank_id = hindsight_helper.get_agent_default_bank_id(context)

            agent_settings = plugins.get_plugin_config(
                "a0_hindsight",
                agent=agent,
                project_name="",
                agent_profile=agent_profile,
            ) or {}
            effective = hindsight_helper._get_plugin_config(agent)

            return {
                "ok": True,
                "ctxid": context.id,
                "project_name": project_name,
                "agent_profile": agent_profile,
                "agent_display_name": agent_display_name,
                "agent_default_bank_id": agent_default_bank_id,
                "settings": {
                    "hindsight_agent_memory_enabled": bool(effective.get("hindsight_agent_memory_enabled", False)),
                    "hindsight_agent_bank_id": str(effective.get("hindsight_agent_bank_id", "") or ""),
                    "hindsight_agent_retain_to_project": bool(effective.get("hindsight_agent_retain_to_project", False)),
                },
                "agent_scope_settings": {
                    "hindsight_agent_memory_enabled": bool(agent_settings.get("hindsight_agent_memory_enabled", False)),
                    "hindsight_agent_bank_id": str(agent_settings.get("hindsight_agent_bank_id", "") or ""),
                    "hindsight_agent_retain_to_project": bool(agent_settings.get("hindsight_agent_retain_to_project", False)),
                },
                "project_bank_id": hindsight_helper.get_project_bank_id(context),
                "agent_bank_id": hindsight_helper.get_agent_bank_id(context),
                "retain_bank_ids": hindsight_helper.get_retain_bank_ids(context),
                "recall_bank_ids": hindsight_helper.get_recall_bank_ids(context),
                "is_configured": hindsight_helper.is_configured(context),
                "hindsight_client_available": hindsight_helper.is_hindsight_client_available(),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}
