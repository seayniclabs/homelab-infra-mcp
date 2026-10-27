"""Home Assistant module (opt-in, off by default): entities, automations and scripts, system info.

Every change (service call, turn on/off/toggle, trigger, reload) needs the person's approval, or
HOMELAB_HOME_ASSISTANT_ALLOW_WRITES=true. Home Assistant has no API to create automations, so
action=create only returns the YAML for you to paste into automations.yaml.
"""

from __future__ import annotations

from typing import Any, Literal

import httpx
import yaml
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from homelab_infra_mcp.config import Config
from homelab_infra_mcp import validation
from homelab_infra_mcp.errors import HomelabError
from homelab_infra_mcp.models import Change, page, run_change
from homelab_infra_mcp.modules import ALLOW_WRITES, Module, Setting
from homelab_infra_mcp.runtime import HttpFactory, Runtime

MODULE = "home_assistant"
DEFAULT_URL = "http://homeassistant.local:8123"
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)


class HomeAssistantClient:
    def __init__(self, config: Config, http: HttpFactory):
        self.config = config
        self.http = http

    def base(self) -> str:
        return (self.config.get(MODULE, "url") or DEFAULT_URL).rstrip("/")

    async def request(self, method: str, path: str, *, data: Any = None, params: dict | None = None) -> Any:
        token = self.config.require(MODULE, "token")["token"]
        try:
            async with self.http() as client:
                r = await client.request(method, f"{self.base()}{path}", json=data, params=params,
                                         headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as e:
            raise HomelabError(MODULE, "unreachable", f"could not reach Home Assistant ({type(e).__name__}).",
                               "check HOMELAB_HOME_ASSISTANT_URL and that Home Assistant is running.")
        if r.status_code in (401, 403):
            raise HomelabError(MODULE, "auth_failed", f"Home Assistant returned {r.status_code}.",
                               "check HOMELAB_HOME_ASSISTANT_TOKEN (a long-lived access token).")
        if r.status_code >= 400:
            raise HomelabError(MODULE, "api_error", f"Home Assistant returned {r.status_code}: {r.text[:200]}")
        return r.json() if r.content else {}


class Entity(BaseModel):
    entity_id: str
    state: str | None = None
    name: str | None = None


class EntitiesResult(BaseModel):
    items: list[Entity] = []
    detail: dict[str, Any] | None = None  # get: the full state, with attributes
    total: int | None = None
    has_more: bool = False
    change: Change | None = None


class AutomationsResult(BaseModel):
    items: list[Entity] = []
    yaml: str | None = None  # action=create: the YAML to paste into automations.yaml or scripts.yaml
    total: int | None = None
    has_more: bool = False
    change: Change | None = None


class SystemResult(BaseModel):
    action: str
    data: Any = None


def _entity(s: dict) -> Entity:
    return Entity(entity_id=s.get("entity_id", ""), state=s.get("state"),
                  name=(s.get("attributes") or {}).get("friendly_name"))


def _domain_of(entity_id: str) -> str:
    return entity_id.split(".", 1)[0] if "." in entity_id else "homeassistant"


class HomeAssistantModule(Module):
    def __init__(self) -> None:
        super().__init__(
            name=MODULE,
            summary="Home Assistant: entities, automations and scripts, and system info. Off by default.",
            default_enabled=False,
            settings=[
                Setting("url", f"Base URL of Home Assistant. Default {DEFAULT_URL}.", required=False),
                Setting("token", "Long-lived access token from your Home Assistant profile.", secret=True),
                ALLOW_WRITES,
            ],
            tools={
                "ha_entities": "List, get or search entities; call a service; turn on, off or toggle an entity.",
                "ha_automations": "List automations or scripts; trigger or reload them; preview automation YAML.",
                "ha_system": "Read the Home Assistant config, the available services, or check the config.",
            },
        )

    def register(self, mcp: FastMCP, runtime: Runtime) -> None:
        config = runtime.config

        @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
        async def ha_entities(
            ctx: Context,
            action: Literal["list", "get", "search", "call_service", "turn_on", "turn_off", "toggle"] = "list",
            entity_id: str = "",
            domain: str = "",
            query: str = "",
            service: str = "",
            service_data: dict[str, Any] | None = None,
            limit: int = 20,
            offset: int = 0,
            dry_run: bool = False,
        ) -> EntitiesResult:
            """Entities. list, get and search are read-only. call_service, turn_on, turn_off and toggle change
            devices and need the person's approval (or HOMELAB_HOME_ASSISTANT_ALLOW_WRITES=true).
            call_service needs domain and service; turn_on, turn_off and toggle need entity_id."""
            ha = runtime.home_assistant()
            if action in ("list", "search", "get"):
                states = await ha.request("GET", "/api/states")
                if action == "get":
                    if not entity_id:
                        raise HomelabError(MODULE, "bad_input", "entity_id is required for get.", "pass e.g. light.kitchen.")
                    validation.ha_entity(entity_id, MODULE)
                    raw = next((s for s in states if s.get("entity_id") == entity_id), None)
                    if raw is None:
                        raise HomelabError(MODULE, "not_found", f"no entity {entity_id}.", "use action=search to find it.")
                    return EntitiesResult(items=[_entity(raw)], detail=raw, total=1)
                rows = states
                if domain:
                    validation.ha_name(domain, MODULE, "domain")
                    rows = [s for s in rows if s.get("entity_id", "").startswith(f"{domain}.")]
                if action == "search":
                    q = query.lower()
                    rows = [s for s in rows if q in s.get("entity_id", "").lower()
                            or q in ((s.get("attributes") or {}).get("friendly_name") or "").lower()]
                items, total, more = page([_entity(s) for s in rows], limit, offset)
                return EntitiesResult(items=items, total=total, has_more=more)

            data = dict(service_data or {})
            if action == "call_service":
                if not (domain and service):
                    raise HomelabError(MODULE, "bad_input", "call_service needs domain and service.",
                                       "for example domain=light service=turn_on entity_id=light.kitchen.")
                svc_domain = validation.ha_name(domain, MODULE, "domain")
                svc = validation.ha_name(service, MODULE, "service")
            else:
                if not entity_id:
                    raise HomelabError(MODULE, "bad_input", f"{action} needs entity_id.", "pass e.g. switch.fan.")
                validation.ha_entity(entity_id, MODULE)
                svc_domain, svc = _domain_of(entity_id), action
            if entity_id:
                validation.ha_entity(entity_id, MODULE)
                data["entity_id"] = entity_id
            summary = f"call Home Assistant service {svc_domain}.{svc}" + (f" on {entity_id}" if entity_id else "") \
                + (f" with {data}" if len(data) > (1 if entity_id else 0) else "")

            async def perform():
                res = await ha.request("POST", f"/api/services/{svc_domain}/{svc}", data=data)
                return None, {"changed_states": len(res) if isinstance(res, list) else None}

            change = await run_change(ctx, config, module=MODULE, action=action, summary=summary,
                                      perform=perform, dry_run=dry_run, preview={"service": f"{svc_domain}.{svc}", "data": data})
            return EntitiesResult(change=change)

        @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
        async def ha_automations(
            ctx: Context,
            action: Literal["list", "trigger", "create", "reload"] = "list",
            kind: Literal["automation", "script"] = "automation",
            entity_id: str = "",
            automation_id: str = "",
            alias: str = "",
            triggers: list[dict[str, Any]] | None = None,
            conditions: list[dict[str, Any]] | None = None,
            actions: list[dict[str, Any]] | None = None,
            service_data: dict[str, Any] | None = None,
            limit: int = 20,
            offset: int = 0,
            dry_run: bool = False,
        ) -> AutomationsResult:
            """Automations or scripts. list is read-only. trigger runs one now (scripts take service_data as
            variables). reload re-reads the YAML files. create never writes: it returns the automation YAML
            for you to save. trigger and reload need the person's approval (or ALLOW_WRITES=true)."""
            ha = runtime.home_assistant()
            prefix = f"{kind}."
            if action == "list":
                states = await ha.request("GET", "/api/states")
                rows = [_entity(s) for s in states if s.get("entity_id", "").startswith(prefix)]
                items, total, more = page(rows, limit, offset)
                return AutomationsResult(items=items, total=total, has_more=more)
            if action == "create":
                if not automation_id.strip() or not alias.strip() or not triggers or not actions:
                    raise HomelabError(MODULE, "bad_input", "create needs automation_id, alias, triggers and actions.",
                                       "pass all four; the result is YAML to paste into automations.yaml.")
                cfg: dict[str, Any] = {"id": automation_id.strip(), "alias": alias.strip(), "trigger": triggers,
                                       "action": actions}
                if conditions:
                    cfg["condition"] = conditions
                return AutomationsResult(yaml=yaml.safe_dump([cfg], sort_keys=False))
            if action == "trigger":
                validation.ha_entity(entity_id, MODULE)
                if not entity_id.startswith(prefix):
                    raise HomelabError(MODULE, "bad_input", f"entity_id must start with {prefix!r}.",
                                       f"for example {prefix}morning.")
                if kind == "automation":
                    path, data = "/api/services/automation/trigger", {"entity_id": entity_id}
                else:
                    path, data = "/api/services/script/turn_on", {"entity_id": entity_id, **(service_data or {})}
                summary = f"run {kind} {entity_id}" + (f" with {service_data}" if service_data else "")

                async def perform():
                    await ha.request("POST", path, data=data)
                    return None, None

                change = await run_change(ctx, config, module=MODULE, action=action, summary=summary,
                                          perform=perform, dry_run=dry_run, preview={"path": path, "data": data})
                return AutomationsResult(change=change)
            path = f"/api/services/{kind}/reload"
            summary = f"reload {kind} configuration from the YAML files"

            async def perform():
                await ha.request("POST", path)
                return None, None

            change = await run_change(ctx, config, module=MODULE, action=action, summary=summary,
                                      perform=perform, dry_run=dry_run, preview={"path": path})
            return AutomationsResult(change=change)

        @mcp.tool(annotations=READ_ONLY)
        async def ha_system(
            action: Literal["config", "services", "check_config"] = "config",
        ) -> SystemResult:
            """Read-only system information: the Home Assistant config, the services available, or whether the
            current configuration is valid (check_config changes nothing)."""
            ha = runtime.home_assistant()
            if action == "config":
                return SystemResult(action=action, data=await ha.request("GET", "/api/config"))
            if action == "services":
                return SystemResult(action=action, data=await ha.request("GET", "/api/services"))
            return SystemResult(action=action,
                                data=await ha.request("POST", "/api/services/homeassistant/check_config"))
