"""DNS module: Cloudflare zones and records. Read-only zone listing and export; record changes need approval."""

from __future__ import annotations

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

MODULE = "dns"
CF_API = "https://api.cloudflare.com/client/v4"
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)


class CloudflareClient:
    def __init__(self, config: Config, http: HttpFactory):
        self.config = config
        self.http = http

    def _token(self) -> str:
        return self.config.require(MODULE, "api_token")["api_token"]

    async def _send(self, method: str, path: str, *, params: dict | None = None,
                    json: Any = None) -> httpx.Response:
        token = self._token()
        try:
            async with self.http() as client:
                return await client.request(method, f"{CF_API}/{path}", params=params, json=json,
                                            headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as e:
            raise HomelabError(MODULE, "unreachable", f"could not reach Cloudflare ({type(e).__name__}).",
                               "check network access to api.cloudflare.com.")

    def _check(self, r: httpx.Response) -> None:
        if r.status_code in (401, 403):
            raise HomelabError(MODULE, "auth_failed", f"Cloudflare returned {r.status_code}.",
                               "check HOMELAB_DNS_API_TOKEN and that the token can edit this zone.")
        if r.status_code == 429:
            raise HomelabError(MODULE, "rate_limited", "Cloudflare rate limit reached.", "wait and retry.")
        if r.status_code >= 400:
            try:
                errors = r.json().get("errors") or []
                message = "; ".join(str(e.get("message", "")) for e in errors) or r.text
            except ValueError:
                message = r.text
            raise HomelabError(MODULE, "api_error", f"Cloudflare returned {r.status_code}: {message[:200]}")

    async def _json(self, method: str, path: str, *, params: dict | None = None, json: Any = None) -> dict:
        r = await self._send(method, path, params=params, json=json)
        self._check(r)
        return r.json()

    async def verify(self) -> dict[str, Any]:
        return (await self._json("GET", "user/tokens/verify")).get("result", {})

    async def zones(self, page: int, per_page: int) -> tuple[list[dict], dict]:
        data = await self._json("GET", "zones", params={"page": page, "per_page": per_page})
        return data.get("result", []), data.get("result_info", {})

    async def records(self, zone: str, record_type: str, page: int, per_page: int) -> tuple[list[dict], dict]:
        zone = validation.cf_id(zone, MODULE, "zone_id")
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if record_type:
            params["type"] = record_type
        data = await self._json("GET", f"zones/{zone}/dns_records", params=params)
        return data.get("result", []), data.get("result_info", {})

    async def record(self, zone: str, record_id: str) -> dict[str, Any]:
        zone, record_id = validation.cf_id(zone, MODULE, "zone_id"), validation.cf_id(record_id, MODULE, "record_id")
        return (await self._json("GET", f"zones/{zone}/dns_records/{record_id}")).get("result", {})

    async def create(self, zone: str, body: dict) -> dict[str, Any]:
        zone = validation.cf_id(zone, MODULE, "zone_id")
        return (await self._json("POST", f"zones/{zone}/dns_records", json=body)).get("result", {})

    async def update(self, zone: str, record_id: str, body: dict) -> dict[str, Any]:
        zone, record_id = validation.cf_id(zone, MODULE, "zone_id"), validation.cf_id(record_id, MODULE, "record_id")
        return (await self._json("PUT", f"zones/{zone}/dns_records/{record_id}", json=body)).get("result", {})

    async def delete(self, zone: str, record_id: str) -> None:
        zone, record_id = validation.cf_id(zone, MODULE, "zone_id"), validation.cf_id(record_id, MODULE, "record_id")
        await self._json("DELETE", f"zones/{zone}/dns_records/{record_id}")

    async def export(self, zone: str) -> str:
        zone = validation.cf_id(zone, MODULE, "zone_id")
        r = await self._send("GET", f"zones/{zone}/dns_records/export")
        self._check(r)
        return r.text


class Zone(BaseModel):
    id: str
    name: str
    status: str | None = None
    name_servers: list[str] = []


class ZonesResult(BaseModel):
    action: str
    zones: list[Zone] = []
    export: str | None = None  # action=export: the zone in BIND format
    zone_id: str | None = None
    page: int = 1
    has_more: bool = False


class DnsRecord(BaseModel):
    id: str
    type: str
    name: str
    content: str
    proxied: bool = False
    ttl: int = 1


class DnsRecordsResult(BaseModel):
    items: list[DnsRecord] = []
    detail: dict[str, Any] | None = None
    page: int = 1
    has_more: bool = False
    change: Change | None = None


def _record(r: dict) -> DnsRecord:
    return DnsRecord(id=r["id"], type=r["type"], name=r["name"], content=r["content"],
                     proxied=bool(r.get("proxied", False)), ttl=r.get("ttl", 1))


class DnsModule(Module):
    def __init__(self) -> None:
        super().__init__(
            name=MODULE,
            summary="Cloudflare DNS: zones, records, and BIND export.",
            settings=[
                Setting("api_token", "Cloudflare API token with DNS edit permission on the zone.", secret=True),
                Setting("zone_id", "Default zone id, so tools can leave zone_id empty.", required=False),
                ALLOW_WRITES,
            ],
            tools={
                "dns_zones": "List zones, or export one zone in BIND format.",
                "dns_records": "List, get, create, update or delete DNS records.",
            },
        )

    def register(self, mcp: FastMCP, runtime: Runtime) -> None:
        config = runtime.config

        def zone_of(zone_id: str) -> str:
            zone = zone_id.strip() or config.get(MODULE, "zone_id") or ""
            if not zone:
                raise HomelabError(MODULE, "bad_input", "no zone id given and no default zone is set.",
                                   "pass zone_id, or set HOMELAB_DNS_ZONE_ID.")
            return zone

        @mcp.tool(annotations=READ_ONLY)
        async def dns_zones(
            action: Literal["list", "export"] = "list",
            zone_id: str = "",
            page: int = 1,
            limit: int = 20,
        ) -> ZonesResult:
            """Zones for the Cloudflare account (action=list), or one zone exported in BIND format (action=export)."""
            cf = runtime.cloudflare()
            if action == "export":
                zone = zone_of(zone_id)
                return ZonesResult(action=action, export=await cf.export(zone), zone_id=zone)
            rows, info = await cf.zones(max(1, page), validation.limit(limit))
            zones = [Zone(id=z["id"], name=z["name"], status=z.get("status"),
                          name_servers=list(z.get("name_servers") or [])) for z in rows]
            more = bool(info.get("total_pages") and page < info["total_pages"])
            return ZonesResult(action=action, zones=zones, page=page, has_more=more)

        @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False))
        async def dns_records(
            ctx: Context,
            action: Literal["list", "get", "create", "update", "delete"] = "list",
            record_id: str = "",
            zone_id: str = "",
            name: str = "",
            record_type: str = "",
            content: str = "",
            proxied: bool | None = None,
            ttl: int = 1,
            page: int = 1,
            limit: int = 20,
            dry_run: bool = False,
        ) -> DnsRecordsResult:
            """DNS records. list and get are read-only. create, update and delete change the zone and need
            the person's approval (or HOMELAB_DNS_ALLOW_WRITES=true). create needs name, record_type and content;
            update needs record_id and any field to change; delete removes the record permanently."""
            cf = runtime.cloudflare()
            zone = zone_of(zone_id)
            if action == "list":
                rtype = validation.record_type(record_type, MODULE) if record_type else ""
                rows, info = await cf.records(zone, rtype, max(1, page), validation.limit(limit))
                more = bool(info.get("total_pages") and page < info["total_pages"])
                return DnsRecordsResult(items=[_record(r) for r in rows], page=page, has_more=more)
            if action == "create":
                if not (name.strip() and content.strip() and record_type):
                    raise HomelabError(MODULE, "bad_input", "create needs name, record_type and content.",
                                       "pass all three, for example name=app.example.com record_type=CNAME.")
                rtype = validation.record_type(record_type, MODULE)
                body = {"type": rtype, "name": name.strip(), "content": content.strip(),
                        "proxied": bool(proxied), "ttl": validation.ttl(ttl, MODULE)}
                summary = (f"create DNS {rtype} record {body['name']} -> {body['content']}"
                           f" (proxied {'yes' if body['proxied'] else 'no'}, TTL {body['ttl']})")

                async def perform():
                    res = await cf.create(zone, body)
                    return res.get("id"), None

                change = await run_change(ctx, config, module=MODULE, action=action, summary=summary,
                                          perform=perform, dry_run=dry_run, preview=body)
                return DnsRecordsResult(change=change)
            if not record_id:
                raise HomelabError(MODULE, "bad_input", f"record_id is required for {action}.",
                                   "get ids from dns_records with action=list.")
            current = await cf.record(zone, record_id)
            if not current:
                raise HomelabError(MODULE, "not_found", f"no DNS record {record_id} in zone {zone}.",
                                   "get ids from dns_records with action=list.")
            if action == "get":
                return DnsRecordsResult(items=[_record(current)], detail=current)
            desc = f"{current.get('type')} {current.get('name')} -> {current.get('content')}"
            if action == "update":
                body = {
                    "type": current["type"],
                    "name": name.strip() or current["name"],
                    "content": content.strip() or current["content"],
                    "proxied": proxied if proxied is not None else current.get("proxied", False),
                    "ttl": current.get("ttl", 1),
                }
                summary = f"update DNS record {record_id} ({desc}) to {body['type']} {body['name']} -> {body['content']}"

                async def perform():
                    await cf.update(zone, record_id, body)
                    return record_id, None

                change = await run_change(ctx, config, module=MODULE, action=action, summary=summary,
                                          perform=perform, dry_run=dry_run, preview=body)
                return DnsRecordsResult(change=change)
            summary = f"PERMANENTLY delete DNS record {record_id} ({desc})"

            async def perform():
                await cf.delete(zone, record_id)
                return record_id, None

            change = await run_change(ctx, config, module=MODULE, action=action, summary=summary,
                                      perform=perform, dry_run=dry_run, preview={"id": record_id, "record": desc})
            return DnsRecordsResult(change=change)
