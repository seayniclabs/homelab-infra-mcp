"""Cloudflare Tunnel module (opt-in, off by default): tunnels and their public hostname routes.

Checked 2026-10-27 against the Cloudflare OpenAPI schema (cloudflare/api-schemas, openapi.json):
- ``GET /accounts/{account_id}/cfd_tunnel``: list tunnels.
- ``GET /accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations``: result.config.ingress.
- ``PUT /accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations``: body ``{"config": {...}}``.
  The ingress list must end with a catch-all rule that has no hostname.

PUT replaces the whole configuration, so the client reads the current config first and changes
only ``ingress``. A route does not create DNS: point a proxied CNAME at ``<tunnel-id>.cfargotunnel.com``
yourself (``dns_records``), as the summary says.
"""

from __future__ import annotations

import re
from typing import Any, Literal

import httpx
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from homelab_infra_mcp import validation
from homelab_infra_mcp.config import Config
from homelab_infra_mcp.errors import HomelabError
from homelab_infra_mcp.models import Change, run_change
from homelab_infra_mcp.modules import ALLOW_WRITES, Module, Setting
from homelab_infra_mcp.runtime import HttpFactory, Runtime

MODULE = "tunnel"
CF_API = "https://api.cloudflare.com/client/v4"
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
CHANGES = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True)
_SERVICE_RE = re.compile(r"^(https?://[A-Za-z0-9.\-]+(:\d{1,5})?|http_status:\d{3}|unix:[^\s]+)$")


class TunnelClient:
    def __init__(self, config: Config, http: HttpFactory):
        self.config = config
        self.http = http

    async def _json(self, method: str, path: str, json: Any = None) -> Any:
        token = self.config.require(MODULE, "api_token")["api_token"]
        try:
            async with self.http() as client:
                r = await client.request(method, f"{CF_API}/{path}", json=json,
                                         headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as e:
            raise HomelabError(MODULE, "unreachable", f"could not reach Cloudflare ({type(e).__name__}).",
                               "check network access to api.cloudflare.com.")
        if r.status_code in (401, 403):
            raise HomelabError(MODULE, "auth_failed", f"Cloudflare returned {r.status_code}.",
                               "check HOMELAB_TUNNEL_API_TOKEN: it needs Account > Cloudflare Tunnel > Edit.")
        if r.status_code >= 400:
            try:
                errors = r.json().get("errors") or []
                message = "; ".join(str(e.get("message", "")) for e in errors) or r.text
            except ValueError:
                message = r.text
            raise HomelabError(MODULE, "api_error", f"Cloudflare returned {r.status_code}: {message[:200]}")
        return r.json().get("result")

    def _account(self) -> str:
        return validation.cf_id(self.config.require(MODULE, "account_id")["account_id"], MODULE, "account_id")

    def _tunnel(self, override: str = "") -> str:
        tid = override or self.config.require(MODULE, "tunnel_id")["tunnel_id"]
        return validation.cf_id(tid, MODULE, "tunnel_id")

    async def tunnels(self) -> list[dict]:
        return await self._json("GET", f"accounts/{self._account()}/cfd_tunnel?is_deleted=false") or []

    async def config_of(self, tunnel_id: str) -> dict:
        res = await self._json("GET", f"accounts/{self._account()}/cfd_tunnel/{tunnel_id}/configurations") or {}
        return res.get("config") or {}

    async def put_config(self, tunnel_id: str, config: dict) -> None:
        await self._json("PUT", f"accounts/{self._account()}/cfd_tunnel/{tunnel_id}/configurations",
                         json={"config": config})


class Tunnel(BaseModel):
    id: str
    name: str
    status: str | None = None


class Route(BaseModel):
    hostname: str | None = None  # None for the catch-all rule
    service: str
    path: str | None = None


class TunnelRoutesResult(BaseModel):
    tunnels: list[Tunnel] = []
    tunnel_id: str | None = None
    routes: list[Route] = []
    change: Change | None = None


def _route(rule: dict) -> Route:
    return Route(hostname=rule.get("hostname"), service=rule.get("service", ""), path=rule.get("path"))


def _with_catch_all(ingress: list[dict]) -> list[dict]:
    """Keep exactly one catch-all rule, last."""
    rules = [r for r in ingress if r.get("hostname")]
    rules.append({"service": "http_status:404"})
    return rules


class TunnelModule(Module):
    def __init__(self) -> None:
        super().__init__(
            name=MODULE,
            summary="Cloudflare Tunnel: list tunnels and their public hostname routes; add or remove a route. Off by default.",
            default_enabled=False,
            settings=[
                Setting("api_token", "Cloudflare API token with Account > Cloudflare Tunnel > Edit.", secret=True),
                Setting("account_id", "Cloudflare account id (32 hex characters)."),
                Setting("tunnel_id", "Id of the tunnel whose routes this module edits (32 hex characters)."),
                ALLOW_WRITES,
            ],
            tools={
                "tunnel_routes": "List tunnels and routes; add or remove a public hostname route (approval).",
            },
        )

    def register(self, mcp: FastMCP, runtime: Runtime) -> None:
        config = runtime.config

        @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True))
        async def tunnel_routes(
            ctx: Context,
            action: Literal["list", "add", "remove"] = "list",
            hostname: str = "",
            service: str = "",
            dry_run: bool = False,
        ) -> TunnelRoutesResult:
            """Cloudflare Tunnel routes. list is read-only and shows the account's tunnels and the routes of the
            configured tunnel. add needs hostname and service (for example http://nginx:80); remove needs hostname.
            add and remove need the person's approval (or HOMELAB_TUNNEL_ALLOW_WRITES=true). A route does not create
            DNS: add a proxied CNAME to <tunnel-id>.cfargotunnel.com with dns_records."""
            cf = runtime.tunnel()
            if action == "list":
                tunnels = [Tunnel(id=t["id"], name=t.get("name", ""), status=t.get("status"))
                           for t in await cf.tunnels()]
                tid = cf._tunnel()
                routes = [_route(r) for r in (await cf.config_of(tid)).get("ingress", [])]
                return TunnelRoutesResult(tunnels=tunnels, tunnel_id=tid, routes=routes)

            tid = cf._tunnel()
            host = validation.domain(hostname, MODULE) if hostname else ""
            current = await cf.config_of(tid)
            ingress = list(current.get("ingress") or [])
            if action == "add":
                if not (host and service.strip()):
                    raise HomelabError(MODULE, "bad_input", "add needs hostname and service.",
                                       "for example hostname=app.example.com service=http://nginx:80.")
                if not _SERVICE_RE.match(service.strip()):
                    raise HomelabError(MODULE, "bad_input", f"service {service!r} is not a valid origin.",
                                       "use http://host:port, https://host:port, or http_status:404.")
                if any(r.get("hostname") == host for r in ingress):
                    raise HomelabError(MODULE, "conflict", f"a route for {host} already exists.",
                                       "remove it first with action=remove, or change it in Cloudflare.")
                new_rules = [r for r in ingress if r.get("hostname")] + [{"hostname": host, "service": service.strip()}]
                summary = f"add Cloudflare Tunnel route {host} -> {service.strip()} on tunnel {tid}"
            elif action == "remove":
                if not host:
                    raise HomelabError(MODULE, "bad_input", "remove needs hostname.", "use action=list to see routes.")
                if not any(r.get("hostname") == host for r in ingress):
                    raise HomelabError(MODULE, "not_found", f"no route for {host} on tunnel {tid}.",
                                       "use action=list to see the routes.")
                new_rules = [r for r in ingress if r.get("hostname") and r.get("hostname") != host]
                summary = f"remove Cloudflare Tunnel route {host} from tunnel {tid}"
            else:
                raise HomelabError(MODULE, "bad_input", "action must be list, add or remove.", "")
            new_config = {**current, "ingress": _with_catch_all(new_rules)}
            preview = {"tunnel_id": tid, "ingress": new_config["ingress"]}

            async def perform():
                await cf.put_config(tid, new_config)
                return tid, None

            change = await run_change(ctx, config, module=MODULE, action=action, summary=summary,
                                      perform=perform, dry_run=dry_run, preview=preview)
            return TunnelRoutesResult(tunnel_id=tid, change=change)
