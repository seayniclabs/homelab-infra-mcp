"""Proxy module: Nginx Proxy Manager (NPM). Proxy hosts, redirections, certificates, access lists."""

from __future__ import annotations

from typing import Any, Literal

import httpx
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from homelab_infra_mcp.config import Config
from homelab_infra_mcp.errors import HomelabError
from homelab_infra_mcp.models import Change, page, run_change
from homelab_infra_mcp.modules import ALLOW_WRITES, Module, Setting
from homelab_infra_mcp.runtime import HttpFactory, Runtime
from homelab_infra_mcp import validation

MODULE = "proxy"
DEFAULT_URL = "http://localhost:81"
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITES = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)


class NpmClient:
    """Thin client for the NPM REST API. Logs in with the configured admin account."""

    def __init__(self, config: Config, http: HttpFactory):
        self.config = config
        self.http = http
        self._token: str | None = None

    def _base(self) -> str:
        return (self.config.get(MODULE, "url") or DEFAULT_URL).rstrip("/")

    async def _send(self, client: httpx.AsyncClient, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return await client.request(method, url, **kwargs)
        except httpx.HTTPError as e:
            raise HomelabError(MODULE, "unreachable", f"could not reach Nginx Proxy Manager ({type(e).__name__}).",
                               "check HOMELAB_PROXY_URL and that the proxy is running.")

    async def _login(self) -> str:
        if self._token:
            return self._token
        creds = self.config.require(MODULE, "email", "password")
        async with self.http() as client:
            r = await self._send(client, "POST", f"{self._base()}/api/tokens",
                                 json={"identity": creds["email"], "secret": creds["password"], "scope": "user"})
        if r.status_code in (400, 401, 403):
            raise HomelabError(MODULE, "auth_failed", f"NPM refused the login ({r.status_code}).",
                               "check HOMELAB_PROXY_EMAIL and HOMELAB_PROXY_PASSWORD.")
        if r.status_code >= 400:
            raise HomelabError(MODULE, "api_error", f"NPM returned {r.status_code} at login.")
        self._token = r.json()["token"]
        return self._token

    async def request(self, method: str, path: str, *, json: Any = None, params: dict | None = None,
                      retry: bool = True) -> Any:
        token = await self._login()
        async with self.http() as client:
            r = await self._send(client, method, f"{self._base()}/api/{path}", json=json, params=params,
                                 headers={"Authorization": f"Bearer {token}"})
        if r.status_code == 401 and retry:
            self._token = None
            return await self.request(method, path, json=json, params=params, retry=False)
        if r.status_code in (401, 403):
            raise HomelabError(MODULE, "auth_failed", f"NPM returned {r.status_code}.",
                               "check HOMELAB_PROXY_EMAIL and HOMELAB_PROXY_PASSWORD.")
        if r.status_code >= 400:
            try:
                message = str(r.json().get("message", r.text))
            except ValueError:
                message = r.text
            raise HomelabError(MODULE, "api_error", f"NPM returned {r.status_code}: {message[:200]}")
        return r.json() if r.content else {}


# --- result models -----------------------------------------------------------

class ProxyHost(BaseModel):
    id: int
    domains: list[str]
    forward_host: str | None = None
    forward_port: int | None = None
    ssl: bool = False
    enabled: bool = True


class ProxyHostsResult(BaseModel):
    items: list[ProxyHost] = []
    detail: dict[str, Any] | None = None  # get: the full NPM record
    total: int | None = None
    has_more: bool = False
    change: Change | None = None


class Redirection(BaseModel):
    id: int
    domains: list[str]
    forward_domain: str | None = None
    forward_scheme: str | None = None
    preserve_path: bool = False


class RedirectionsResult(BaseModel):
    items: list[Redirection] = []
    total: int | None = None
    has_more: bool = False
    change: Change | None = None


class Certificate(BaseModel):
    id: int
    domains: list[str]
    provider: str | None = None
    expires_on: str | None = None


class CertificatesResult(BaseModel):
    items: list[Certificate] = []
    total: int | None = None
    has_more: bool = False
    change: Change | None = None


class AccessList(BaseModel):
    id: int
    name: str


class AccessListsResult(BaseModel):
    items: list[AccessList] = []
    total: int | None = None
    has_more: bool = False
    change: Change | None = None


def _host_view(h: dict) -> ProxyHost:
    return ProxyHost(id=h["id"], domains=list(h.get("domain_names") or []), forward_host=h.get("forward_host"),
                     forward_port=h.get("forward_port"), ssl=bool(h.get("certificate_id")),
                     enabled=h.get("enabled", True))


def _host_body(domains: list[str], forward_host: str, forward_port: int, ssl: bool,
               force_ssl: bool, block_exploits: bool) -> dict[str, Any]:
    return {
        "domain_names": domains,
        "forward_scheme": "http",
        "forward_host": forward_host,
        "forward_port": forward_port,
        "block_exploits": block_exploits,
        "allow_websocket_upgrade": True,
        "access_list_id": "0",
        "certificate_id": 0,
        "meta": {"letsencrypt_agree": ssl, "dns_challenge": False},
        "advanced_config": "",
        "locations": [],
        "http2_support": False,
        "hsts_enabled": False,
        "hsts_subdomains": False,
        "ssl_forced": force_ssl,
    }


class ProxyModule(Module):
    def __init__(self) -> None:
        super().__init__(
            name=MODULE,
            summary="Nginx Proxy Manager: proxy hosts, redirections, certificates and access lists.",
            settings=[
                Setting("url", f"Base URL of Nginx Proxy Manager. Default {DEFAULT_URL}.", required=False),
                Setting("email", "NPM admin email (the login used for the API)."),
                Setting("password", "NPM admin password.", secret=True),
                ALLOW_WRITES,
            ],
            tools={
                "proxy_hosts": "List, get, create, update or delete proxy hosts.",
                "proxy_redirections": "List, create or delete HTTP redirections.",
                "proxy_certificates": "List SSL certificates, or request a Let's Encrypt certificate.",
                "proxy_access_lists": "List, create or delete IP access lists.",
            },
        )

    def register(self, mcp: FastMCP, runtime: Runtime) -> None:
        config = runtime.config

        @mcp.tool(annotations=WRITES)
        async def proxy_hosts(
            ctx: Context,
            action: Literal["list", "get", "create", "update", "delete"] = "list",
            host_id: int = 0,
            domain_names: str = "",
            forward_host: str = "",
            forward_port: int = 0,
            ssl: bool = True,
            force_ssl: bool = False,
            block_exploits: bool = True,
            limit: int = 20,
            offset: int = 0,
            dry_run: bool = False,
        ) -> ProxyHostsResult:
            """Proxy hosts. list/get are read-only. create, update and delete change NPM and need the
            person's approval (or HOMELAB_PROXY_ALLOW_WRITES=true). dry_run=true previews without asking."""
            npm = runtime.npm()
            if action == "list":
                rows = await npm.request("GET", "nginx/proxy-hosts")
                items, total, more = page([_host_view(h) for h in rows], limit, offset)
                return ProxyHostsResult(items=items, total=total, has_more=more)
            if action == "get":
                if host_id < 1:
                    raise HomelabError(MODULE, "bad_input", "host_id is required for get.", "pass the proxy host id.")
                raw = await npm.request("GET", f"nginx/proxy-hosts/{host_id}")
                return ProxyHostsResult(items=[_host_view(raw)], detail=raw, total=1)
            if action == "create":
                domains = validation.domains(domain_names, MODULE)
                validation.port(forward_port, MODULE)
                if not forward_host.strip():
                    raise HomelabError(MODULE, "bad_input", "forward_host is required.", "pass the backend host or IP.")
                body = _host_body(domains, forward_host.strip(), forward_port, ssl, force_ssl, block_exploits)
                summary = (f"create proxy host {', '.join(domains)} -> http://{forward_host.strip()}:{forward_port}"
                           f" (SSL {'on' if ssl else 'off'}, force HTTPS {'on' if force_ssl else 'off'})")

                async def perform():
                    res = await npm.request("POST", "nginx/proxy-hosts", json=body)
                    return str(res.get("id")), {"domains": domains}

                change = await run_change(ctx, config, module=MODULE, action=action, summary=summary,
                                          perform=perform, dry_run=dry_run, preview=body)
                return ProxyHostsResult(change=change)
            if host_id < 1:
                raise HomelabError(MODULE, "bad_input", f"host_id is required for {action}.", "pass the proxy host id.")
            current = await npm.request("GET", f"nginx/proxy-hosts/{host_id}")
            domains_now = ", ".join(current.get("domain_names", []))
            if action == "update":
                if not forward_host and not forward_port:
                    raise HomelabError(MODULE, "bad_input", "nothing to update.",
                                       "pass forward_host and/or forward_port.")
                new_host = forward_host or current.get("forward_host")
                new_port = forward_port or current.get("forward_port")
                updated = dict(current, forward_host=new_host, forward_port=new_port)
                summary = (f"update proxy host {host_id} ({domains_now}): forward to "
                           f"http://{new_host}:{new_port}")

                async def perform():
                    await npm.request("PUT", f"nginx/proxy-hosts/{host_id}", json=updated)
                    return str(host_id), None

                change = await run_change(ctx, config, module=MODULE, action=action, summary=summary,
                                          perform=perform, dry_run=dry_run,
                                          preview={"forward_host": new_host, "forward_port": new_port})
                return ProxyHostsResult(change=change)
            summary = f"DELETE proxy host {host_id} ({domains_now}). Its SSL certificate is kept."

            async def perform():
                await npm.request("DELETE", f"nginx/proxy-hosts/{host_id}")
                return str(host_id), None

            change = await run_change(ctx, config, module=MODULE, action=action, summary=summary,
                                      perform=perform, dry_run=dry_run, preview={"id": host_id, "domains": domains_now})
            return ProxyHostsResult(change=change)

        @mcp.tool(annotations=WRITES)
        async def proxy_redirections(
            ctx: Context,
            action: Literal["list", "create", "delete"] = "list",
            redirection_id: int = 0,
            domain_names: str = "",
            forward_domain: str = "",
            forward_scheme: Literal["http", "https"] = "https",
            preserve_path: bool = True,
            limit: int = 20,
            offset: int = 0,
            dry_run: bool = False,
        ) -> RedirectionsResult:
            """HTTP redirections. list is read-only; create and delete need approval (or ALLOW_WRITES)."""
            npm = runtime.npm()
            if action == "list":
                rows = await npm.request("GET", "nginx/redirection-hosts")
                views = [Redirection(id=h["id"], domains=list(h.get("domain_names") or []),
                                     forward_domain=h.get("forward_domain_name"),
                                     forward_scheme=h.get("forward_scheme"),
                                     preserve_path=h.get("preserve_path", False)) for h in rows]
                items, total, more = page(views, limit, offset)
                return RedirectionsResult(items=items, total=total, has_more=more)
            if action == "create":
                domains = validation.domains(domain_names, MODULE)
                target = validation.domain(forward_domain, MODULE)
                body = {
                    "domain_names": domains, "forward_domain_name": target, "forward_scheme": forward_scheme,
                    "preserve_path": preserve_path, "certificate_id": 0, "ssl_forced": False,
                    "block_exploits": True, "http2_support": False, "hsts_enabled": False,
                    "hsts_subdomains": False, "advanced_config": "",
                }
                summary = f"create redirection {', '.join(domains)} -> {forward_scheme}://{target}"

                async def perform():
                    res = await npm.request("POST", "nginx/redirection-hosts", json=body)
                    return str(res.get("id")), None

                change = await run_change(ctx, config, module=MODULE, action=action, summary=summary,
                                          perform=perform, dry_run=dry_run, preview=body)
                return RedirectionsResult(change=change)
            if redirection_id < 1:
                raise HomelabError(MODULE, "bad_input", "redirection_id is required for delete.", "pass the id from list.")
            summary = f"DELETE redirection {redirection_id}."

            async def perform():
                await npm.request("DELETE", f"nginx/redirection-hosts/{redirection_id}")
                return str(redirection_id), None

            change = await run_change(ctx, config, module=MODULE, action=action, summary=summary,
                                      perform=perform, dry_run=dry_run, preview={"id": redirection_id})
            return RedirectionsResult(change=change)

        @mcp.tool(annotations=WRITES)
        async def proxy_certificates(
            ctx: Context,
            action: Literal["list", "request"] = "list",
            domain_names: str = "",
            limit: int = 20,
            offset: int = 0,
            dry_run: bool = False,
        ) -> CertificatesResult:
            """SSL certificates. list is read-only. request asks Let's Encrypt for a new certificate
            (needs approval, or ALLOW_WRITES). Let's Encrypt must be able to reach the domains."""
            npm = runtime.npm()
            if action == "list":
                rows = await npm.request("GET", "nginx/certificates")
                views = [Certificate(id=c["id"], domains=list(c.get("domain_names") or []),
                                     provider=c.get("provider"), expires_on=c.get("expires_on")) for c in rows]
                items, total, more = page(views, limit, offset)
                return CertificatesResult(items=items, total=total, has_more=more)
            domains = validation.domains(domain_names, MODULE)
            body = {"domain_names": domains, "meta": {"letsencrypt_agree": True, "dns_challenge": False},
                    "provider": "letsencrypt"}
            summary = f"request a Let's Encrypt certificate for {', '.join(domains)}"

            async def perform():
                res = await npm.request("POST", "nginx/certificates", json=body)
                return str(res.get("id")), None

            change = await run_change(ctx, config, module=MODULE, action=action, summary=summary,
                                      perform=perform, dry_run=dry_run, preview=body)
            return CertificatesResult(change=change)

        @mcp.tool(annotations=WRITES)
        async def proxy_access_lists(
            ctx: Context,
            action: Literal["list", "create", "delete"] = "list",
            list_id: int = 0,
            name: str = "",
            allow: str = "",
            deny: str = "",
            limit: int = 20,
            offset: int = 0,
            dry_run: bool = False,
        ) -> AccessListsResult:
            """IP access lists. list is read-only. create and delete need approval (or ALLOW_WRITES).
            allow and deny are comma-separated IPs or CIDRs. Deleting a list affects every proxy host that uses it."""
            npm = runtime.npm()
            if action == "list":
                rows = await npm.request("GET", "nginx/access-lists")
                views = [AccessList(id=a["id"], name=a.get("name", "unnamed")) for a in rows]
                items, total, more = page(views, limit, offset)
                return AccessListsResult(items=items, total=total, has_more=more)
            if action == "create":
                if not name.strip():
                    raise HomelabError(MODULE, "bad_input", "name is required.", "pass a name for the list.")
                items = [{"address": ip.strip(), "directive": "allow"} for ip in allow.split(",") if ip.strip()]
                items += [{"address": ip.strip(), "directive": "deny"} for ip in deny.split(",") if ip.strip()]
                body = {"name": name.strip(), "items": items, "clients": [], "satisfy_any": False, "pass_auth": False}
                summary = f"create access list {name.strip()!r} with {len(items)} rule(s)"

                async def perform():
                    res = await npm.request("POST", "nginx/access-lists", json=body)
                    return str(res.get("id")), None

                change = await run_change(ctx, config, module=MODULE, action=action, summary=summary,
                                          perform=perform, dry_run=dry_run, preview=body)
                return AccessListsResult(change=change)
            if list_id < 1:
                raise HomelabError(MODULE, "bad_input", "list_id is required for delete.", "pass the id from list.")
            summary = f"DELETE access list {list_id}. Proxy hosts that use it lose this rule."

            async def perform():
                await npm.request("DELETE", f"nginx/access-lists/{list_id}")
                return str(list_id), None

            change = await run_change(ctx, config, module=MODULE, action=action, summary=summary,
                                      perform=perform, dry_run=dry_run, preview={"id": list_id})
            return AccessListsResult(change=change)
