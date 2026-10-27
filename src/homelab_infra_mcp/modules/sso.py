"""Authentik module (opt-in, off by default): applications and proxy providers, and one-step setup for a host.

Checked 2026-10-27 against goauthentik/authentik ``schema.yml`` (main), API base ``/api/v3``, auth
``Authorization: Bearer <token>``:
- ``GET /api/v3/core/applications/`` and ``POST`` (ApplicationRequest: name, slug, provider).
- ``GET /api/v3/providers/proxy/`` and ``POST`` (ProxyProviderRequest: name, authorization_flow,
  invalidation_flow, external_host, mode; mode is ``forward_single`` or ``forward_domain``).
- ``GET /api/v3/flows/instances/?slug=`` and ``?designation=invalidation`` to find flow ids.
- ``GET /api/v3/core/users/me/`` for the connection check in ``--doctor``.
A proxy provider is created first, then an application that points at it.
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

MODULE = "sso"
DEFAULT_FLOW = "default-provider-authorization-implicit-consent"
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)


class SsoClient:
    def __init__(self, config: Config, http: HttpFactory):
        self.config = config
        self.http = http

    def base(self) -> str:
        return self.config.require(MODULE, "url")["url"].rstrip("/") + "/api/v3"

    async def request(self, method: str, path: str, *, json: Any = None, params: dict | None = None) -> Any:
        token = self.config.require(MODULE, "token")["token"]
        try:
            async with self.http() as client:
                r = await client.request(method, f"{self.base()}{path}", json=json, params=params,
                                         headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as e:
            raise HomelabError(MODULE, "unreachable", f"could not reach Authentik ({type(e).__name__}).",
                               "check HOMELAB_SSO_URL and that Authentik is running.")
        if r.status_code in (401, 403):
            raise HomelabError(MODULE, "auth_failed", f"Authentik returned {r.status_code}.",
                               "check HOMELAB_SSO_TOKEN: create an API token for a user with admin rights.")
        if r.status_code >= 400:
            raise HomelabError(MODULE, "api_error", f"Authentik returned {r.status_code}: {r.text[:200]}")
        return r.json() if r.content else {}


class SsoApp(BaseModel):
    pk: int | str | None = None
    name: str
    slug: str | None = None
    provider: int | str | None = None
    launch_url: str | None = None


class SsoProvider(BaseModel):
    pk: int | str | None = None
    name: str
    external_host: str | None = None
    mode: str | None = None


class SsoResult(BaseModel):
    applications: list[SsoApp] = []
    providers: list[SsoProvider] = []
    detail: dict[str, Any] | None = None
    change: Change | None = None


def _slug(host: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", host.lower()).strip("-")


class SsoModule(Module):
    def __init__(self) -> None:
        super().__init__(
            name=MODULE,
            summary="Authentik: list applications and proxy providers; put a login in front of a host. Off by default.",
            default_enabled=False,
            settings=[
                Setting("url", "Base URL of Authentik, e.g. https://auth.example.com."),
                Setting("token", "Authentik API token (admin user).", secret=True),
                Setting("flow_slug", f"Authorization flow slug. Default {DEFAULT_FLOW}.", required=False),
                ALLOW_WRITES,
            ],
            tools={
                "sso_applications": "List Authentik applications and proxy providers; create a proxy provider and "
                                    "application for a host (approval).",
            },
        )

    def register(self, mcp: FastMCP, runtime: Runtime) -> None:
        config = runtime.config

        @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
        async def sso_applications(
            ctx: Context,
            action: Literal["list", "create"] = "list",
            host: str = "",
            name: str = "",
            mode: Literal["forward_single", "forward_domain"] = "forward_single",
            dry_run: bool = False,
        ) -> SsoResult:
            """Authentik applications and proxy providers. list is read-only. create makes a proxy provider for https://host
            and an application for it, so a login page sits in front of the host (use it with an expose_service
            host). create needs host and needs the person's approval (or HOMELAB_SSO_ALLOW_WRITES=true). The Nginx Proxy Manager
            host still has to route to the Authentik outpost; that step is not automated."""
            sso = runtime.sso()
            if action == "list":
                apps = await sso.request("GET", "/core/applications/", params={"page_size": 100})
                provs = await sso.request("GET", "/providers/proxy/", params={"page_size": 100})
                return SsoResult(
                    applications=[SsoApp(pk=a.get("pk"), name=a.get("name", ""), slug=a.get("slug"),
                                         provider=a.get("provider"), launch_url=a.get("meta_launch_url") or None)
                                  for a in apps.get("results", [])],
                    providers=[SsoProvider(pk=p.get("pk"), name=p.get("name", ""),
                                           external_host=p.get("external_host"), mode=p.get("mode"))
                               for p in provs.get("results", [])],
                )
            if action != "create":
                raise HomelabError(MODULE, "bad_input", f"unknown action {action!r}.", "use list or create.")
            if not host.strip():
                raise HomelabError(MODULE, "bad_input", "create needs host.", "for example host=app.example.com.")
            h = validation.domain(host, MODULE)
            label = name.strip() or h
            slug = _slug(h)
            flow_slug = config.get(MODULE, "flow_slug") or DEFAULT_FLOW
            summary = (f"create Authentik proxy provider '{label}' ({mode}) for https://{h} and application "
                       f"'{label}' (slug {slug}, authorization flow {flow_slug})")

            async def perform():
                flows = await sso.request("GET", "/flows/instances/", params={"slug": flow_slug})
                auth_flow = next((f["pk"] for f in flows.get("results", [])), None)
                if auth_flow is None:
                    raise HomelabError(MODULE, "not_found", f"no Authentik flow with slug {flow_slug}.",
                                       "set HOMELAB_SSO_FLOW_SLUG to an authorization flow slug from Authentik.")
                inv = await sso.request("GET", "/flows/instances/", params={"designation": "invalidation"})
                inv_flow = next((f["pk"] for f in inv.get("results", [])), None)
                provider = await sso.request("POST", "/providers/proxy/", json={
                    "name": label, "authorization_flow": auth_flow, "invalidation_flow": inv_flow,
                    "external_host": f"https://{h}", "mode": mode,
                })
                app = await sso.request("POST", "/core/applications/", json={
                    "name": label, "slug": slug, "provider": provider.get("pk"),
                })
                return str(app.get("pk")), {"provider_pk": provider.get("pk"), "application_slug": slug}

            change = await run_change(ctx, config, module=MODULE, action=action, summary=summary,
                                      perform=perform, dry_run=dry_run,
                                      preview={"name": label, "slug": slug, "external_host": f"https://{h}",
                                               "mode": mode, "authorization_flow_slug": flow_slug})
            return SsoResult(change=change)
