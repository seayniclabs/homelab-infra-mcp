"""AdGuard Home module (opt-in, off by default): status, query log, blocked services and custom rules.

Checked 2026-10-27 against AdguardTeam/AdGuardHome ``openapi/openapi.yaml`` (master). The API is
served under ``/control``, with HTTP Basic auth:
- ``GET /control/status``, ``GET /control/stats``
- ``GET /control/querylog?limit=&offset=``: paged; each row has ``question.name``, ``client``, ``reason``.
- ``GET /control/filtering/status``: ``user_rules`` holds the custom rules.
- ``POST /control/filtering/set_rules`` with ``{"rules": [...]}``: replaces ALL custom rules, so the
  client reads the list, changes it, and writes the whole list back.
- ``GET /control/blocked_services/list``: ids of the services currently blocked.

Blocked-service changes are not offered in 2.1: the update endpoint takes a schedule object that
we have not exercised against a live server.
"""

from __future__ import annotations

from typing import Any, Literal

import httpx
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from homelab_infra_mcp.config import Config
from homelab_infra_mcp.errors import HomelabError
from homelab_infra_mcp.models import Change, run_change
from homelab_infra_mcp.modules import ALLOW_WRITES, Module, Setting
from homelab_infra_mcp.runtime import HttpFactory, Runtime

MODULE = "dns_filter"
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
MAX_RULE = 500


class DnsFilterClient:
    def __init__(self, config: Config, http: HttpFactory):
        self.config = config
        self.http = http

    def base(self) -> str:
        return self.config.require(MODULE, "url")["url"].rstrip("/") + "/control"

    async def request(self, method: str, path: str, *, json: Any = None, params: dict | None = None) -> Any:
        creds = self.config.require(MODULE, "username", "password")
        try:
            async with self.http() as client:
                r = await client.request(method, f"{self.base()}{path}", json=json, params=params,
                                         auth=httpx.BasicAuth(creds["username"], creds["password"]))
        except httpx.HTTPError as e:
            raise HomelabError(MODULE, "unreachable", f"could not reach AdGuard Home ({type(e).__name__}).",
                               "check HOMELAB_DNS_FILTER_URL and that AdGuard Home is running.")
        if r.status_code in (401, 403):
            raise HomelabError(MODULE, "auth_failed", f"AdGuard Home returned {r.status_code}.",
                               "check HOMELAB_DNS_FILTER_USERNAME and HOMELAB_DNS_FILTER_PASSWORD.")
        if r.status_code >= 400:
            raise HomelabError(MODULE, "api_error", f"AdGuard Home returned {r.status_code}: {r.text[:200]}")
        return r.json() if r.content else {}


class FilterStatusResult(BaseModel):
    status: dict[str, Any] = {}
    stats: dict[str, Any] = {}


class QueryRow(BaseModel):
    time: str | None = None
    client: str | None = None
    domain: str | None = None
    type: str | None = None
    reason: str | None = None
    blocked: bool = False


class QueriesResult(BaseModel):
    items: list[QueryRow] = []
    offset: int = 0
    has_more: bool = False
    note: str | None = None


class RulesResult(BaseModel):
    action: str
    user_rules: list[str] = []
    blocked_services: list[str] = []
    change: Change | None = None


def _clean_rule(rule: str) -> str:
    r = rule.strip()
    if not r or "\n" in r or "\r" in r or len(r) > MAX_RULE:
        raise HomelabError(MODULE, "bad_input", "a rule must be one non-empty line of at most 500 characters.",
                           "for example ||ads.example.com^ to block a host, or @@||example.com^ to allow it.")
    return r


class DnsFilterModule(Module):
    def __init__(self) -> None:
        super().__init__(
            name=MODULE,
            summary="AdGuard Home: filtering status, query log, blocked services and custom rules. Off by default.",
            default_enabled=False,
            settings=[
                Setting("url", "Base URL of AdGuard Home, e.g. http://adguard:3000."),
                Setting("username", "AdGuard Home admin user (HTTP Basic auth)."),
                Setting("password", "AdGuard Home admin password.", secret=True),
                ALLOW_WRITES,
            ],
            tools={
                "dns_filter_status": "AdGuard Home status and query counts. Read-only.",
                "dns_filter_queries": "Paged DNS query log, optionally only blocked queries or one domain. Read-only.",
                "dns_filter_rules": "List custom rules and blocked services; add or remove a custom rule (approval).",
            },
        )

    def register(self, mcp: FastMCP, runtime: Runtime) -> None:
        config = runtime.config

        @mcp.tool(annotations=READ_ONLY)
        async def dns_filter_status() -> FilterStatusResult:
            """AdGuard Home status (running, version, protection, DNS addresses) and query counts for the
            recent window. Read-only."""
            ad = runtime.dns_filter()
            return FilterStatusResult(status=await ad.request("GET", "/status"),
                                      stats=await ad.request("GET", "/stats"))

        @mcp.tool(annotations=READ_ONLY)
        async def dns_filter_queries(
            limit: int = 20,
            offset: int = 0,
            domain: str = "",
            blocked_only: bool = False,
        ) -> QueriesResult:
            """Recent DNS queries, newest first, one page at a time (limit up to 100). domain filters on the queried
            name (substring). blocked_only keeps queries AdGuard Home filtered. has_more is true when the page is full;
            call again with offset increased by limit. Read-only."""
            ad = runtime.dns_filter()
            lim = max(1, min(limit, 100))
            off = max(0, offset)
            data = await ad.request("GET", "/querylog", params={"limit": lim, "offset": off})
            rows = []
            for raw in data.get("data", []):
                name = (raw.get("question") or {}).get("name")
                reason = raw.get("reason")
                blocked = str(reason or "").startswith("Filtered")
                if domain and domain.lower() not in str(name or "").lower():
                    continue
                if blocked_only and not blocked:
                    continue
                rows.append(QueryRow(time=raw.get("time"), client=raw.get("client"), domain=name,
                                     type=(raw.get("question") or {}).get("type"), reason=reason, blocked=blocked))
            raw_count = len(data.get("data", []))
            note = "Filters apply to each page, not the whole log." if (domain or blocked_only) else None
            return QueriesResult(items=rows, offset=off, has_more=raw_count == lim, note=note)

        @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False))
        async def dns_filter_rules(
            ctx: Context,
            action: Literal["list", "add", "remove"] = "list",
            rule: str = "",
            dry_run: bool = False,
        ) -> RulesResult:
            """Custom filtering rules and blocked services. list is read-only. add and remove change the custom rule
            list and need the person's approval (or HOMELAB_DNS_FILTER_ALLOW_WRITES=true). Rules use AdGuard syntax:
            ||ads.example.com^ blocks a host, @@||example.com^ allows it. Each change rewrites the whole custom list."""
            ad = runtime.dns_filter()
            if action == "list":
                flt = await ad.request("GET", "/filtering/status")
                blocked = await ad.request("GET", "/blocked_services/list")
                return RulesResult(action=action, user_rules=list(flt.get("user_rules") or []),
                                   blocked_services=list(blocked or []))
            text = _clean_rule(rule)
            current = list((await ad.request("GET", "/filtering/status")).get("user_rules") or [])
            if action == "add":
                if text in current:
                    raise HomelabError(MODULE, "conflict", "that rule already exists.", "use action=list to see the rules.")
                new_rules = current + [text]
                summary = f"add AdGuard Home custom rule {text}"
            else:
                if text not in current:
                    raise HomelabError(MODULE, "not_found", "that rule is not in the custom list.",
                                       "use action=list to see the exact text of each rule.")
                new_rules = [r for r in current if r != text]
                summary = f"remove AdGuard Home custom rule {text}"

            async def perform():
                await ad.request("POST", "/filtering/set_rules", json={"rules": new_rules})
                return None, None

            change = await run_change(ctx, config, module=MODULE, action=action, summary=summary,
                                      perform=perform, dry_run=dry_run,
                                      preview={"rules_after": new_rules})
            return RulesResult(action=action, user_rules=new_rules, change=change)
