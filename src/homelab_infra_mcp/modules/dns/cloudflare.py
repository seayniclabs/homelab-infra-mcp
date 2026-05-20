"""Cloudflare DNS provider — 8 tools for zone and record management."""

import json

import httpx

from homelab_infra_mcp.config import config
from homelab_infra_mcp.safety import check_mode, is_dry_run, request_confirmation

CF_API = "https://api.cloudflare.com/client/v4"
VALID_RECORD_TYPES = {"A", "AAAA", "CNAME", "MX", "TXT", "SRV", "NS", "CAA"}


async def _cf_get(path: str, params: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{CF_API}/{path}",
            params=params,
            headers={"Authorization": f"Bearer {config.cloudflare_api_token}"},
        )
        resp.raise_for_status()
        return resp.json()


async def _cf_post(path: str, data: dict) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(f"{CF_API}/{path}", json=data,
                                 headers={"Authorization": f"Bearer {config.cloudflare_api_token}"})
        resp.raise_for_status()
        return resp.json()


async def _cf_put(path: str, data: dict) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.put(f"{CF_API}/{path}", json=data,
                                headers={"Authorization": f"Bearer {config.cloudflare_api_token}"})
        resp.raise_for_status()
        return resp.json()


async def _cf_delete(path: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.delete(f"{CF_API}/{path}",
                                   headers={"Authorization": f"Bearer {config.cloudflare_api_token}"})
        resp.raise_for_status()
        return resp.json()


def register(mcp):
    """Register DNS (Cloudflare) tools with the MCP server."""

    @mcp.tool()
    async def dns_list_zones() -> str:
        """List DNS zones/domains for the configured Cloudflare account."""
        data = await _cf_get("zones")
        zones = [{
            "id": z["id"],
            "name": z["name"],
            "status": z["status"],
            "name_servers": z.get("name_servers", []),
        } for z in data.get("result", [])]
        return json.dumps({"count": len(zones), "zones": zones})

    @mcp.tool()
    async def dns_list_records(zone_id: str = "", record_type: str = "") -> str:
        """List DNS records for a zone.

        Args:
            zone_id: Cloudflare zone ID (uses default if empty).
            record_type: Filter by type (A, AAAA, CNAME, etc.). Empty for all.
        """
        zid = zone_id or config.cloudflare_zone_id
        if not zid:
            return json.dumps({"error": "No zone_id provided and no default CLOUDFLARE_ZONE_ID set"})

        path = f"zones/{zid}/dns_records"
        if record_type:
            path += f"?type={record_type.upper()}"

        data = await _cf_get(path)
        records = [{
            "id": r["id"],
            "type": r["type"],
            "name": r["name"],
            "content": r["content"],
            "proxied": r.get("proxied", False),
            "ttl": r.get("ttl", 1),
        } for r in data.get("result", [])]
        return json.dumps({"count": len(records), "records": records})

    @mcp.tool()
    async def dns_get_record(record_id: str, zone_id: str = "") -> str:
        """Get a specific DNS record by ID.

        Args:
            record_id: The DNS record ID.
            zone_id: Cloudflare zone ID (uses default if empty).
        """
        zid = zone_id or config.cloudflare_zone_id
        if not zid:
            return json.dumps({"error": "No zone_id provided"})

        data = await _cf_get(f"zones/{zid}/dns_records/{record_id}")
        return json.dumps(data.get("result", {}))

    @mcp.tool()
    async def dns_create_record(
        name: str,
        record_type: str,
        content: str,
        zone_id: str = "",
        proxied: bool = False,
        ttl: int = 1,
    ) -> str:
        """Create a DNS record.

        Args:
            name: Record name (e.g. 'app.example.com').
            record_type: Record type (A, AAAA, CNAME, MX, TXT, SRV, NS, CAA).
            content: Record value (IP, hostname, text, etc.).
            zone_id: Cloudflare zone ID (uses default if empty).
            proxied: Enable Cloudflare proxy (default: false).
            ttl: TTL in seconds (1 = auto).
        """
        blocked = check_mode("write")
        if blocked:
            return json.dumps({"error": blocked})

        rt = record_type.upper()
        if rt not in VALID_RECORD_TYPES:
            return json.dumps({"error": f"Invalid record type: {rt}. Valid: {', '.join(sorted(VALID_RECORD_TYPES))}"})

        zid = zone_id or config.cloudflare_zone_id
        if not zid:
            return json.dumps({"error": "No zone_id provided"})

        data = {"type": rt, "name": name, "content": content, "proxied": proxied, "ttl": ttl}

        if is_dry_run():
            return json.dumps({"dry_run": True, "would_create": data})

        result = await _cf_post(f"zones/{zid}/dns_records", data)
        record = result.get("result", {})
        return json.dumps({"created": True, "id": record.get("id"), "name": name, "type": rt})

    @mcp.tool()
    async def dns_update_record(
        record_id: str,
        name: str = "",
        content: str = "",
        zone_id: str = "",
        proxied: bool | None = None,
    ) -> str:
        """Update an existing DNS record.

        Args:
            record_id: The DNS record ID to update.
            name: New record name (empty to keep current).
            content: New record value (empty to keep current).
            zone_id: Cloudflare zone ID (uses default if empty).
            proxied: Enable/disable proxy (None to keep current).
        """
        blocked = check_mode("write")
        if blocked:
            return json.dumps({"error": blocked})

        zid = zone_id or config.cloudflare_zone_id
        if not zid:
            return json.dumps({"error": "No zone_id provided"})

        # Get current record
        current = await _cf_get(f"zones/{zid}/dns_records/{record_id}")
        record = current.get("result", {})

        update = {
            "type": record["type"],
            "name": name or record["name"],
            "content": content or record["content"],
            "proxied": proxied if proxied is not None else record.get("proxied", False),
            "ttl": record.get("ttl", 1),
        }

        if is_dry_run():
            return json.dumps({"dry_run": True, "would_update": update})

        result = await _cf_put(f"zones/{zid}/dns_records/{record_id}", update)
        return json.dumps({"updated": True, "id": record_id})

    @mcp.tool()
    async def dns_delete_record(record_id: str, zone_id: str = "") -> str:
        """Delete a DNS record.

        Args:
            record_id: The DNS record ID to delete.
            zone_id: Cloudflare zone ID (uses default if empty).
        """
        blocked = check_mode("destructive")
        if blocked:
            return json.dumps({"error": blocked})

        zid = zone_id or config.cloudflare_zone_id
        if not zid:
            return json.dumps({"error": "No zone_id provided"})

        # Get record details for confirmation
        current = await _cf_get(f"zones/{zid}/dns_records/{record_id}")
        record = current.get("result", {})
        desc = f"{record.get('type', '?')} {record.get('name', '?')} -> {record.get('content', '?')}"

        if is_dry_run():
            return json.dumps({"dry_run": True, "would_delete": desc})

        async def _execute():
            await _cf_delete(f"zones/{zid}/dns_records/{record_id}")
            return {"deleted": True, "id": record_id, "record": desc}

        return request_confirmation(
            f"delete DNS record ({desc})",
            f"This will permanently remove the DNS record: {desc}",
            execute=_execute,
        )

    @mcp.tool()
    async def dns_export_zone(zone_id: str = "") -> str:
        """Export full zone file in BIND format.

        Args:
            zone_id: Cloudflare zone ID (uses default if empty).
        """
        zid = zone_id or config.cloudflare_zone_id
        if not zid:
            return json.dumps({"error": "No zone_id provided"})

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{CF_API}/zones/{zid}/dns_records/export",
                                    headers={"Authorization": f"Bearer {config.cloudflare_api_token}"})
            resp.raise_for_status()
            return json.dumps({"zone_id": zid, "format": "BIND", "content": resp.text})

    @mcp.tool()
    async def dns_health() -> str:
        """Check Cloudflare API connectivity."""
        try:
            data = await _cf_get("user/tokens/verify")
            result = data.get("result", {})
            return json.dumps({
                "healthy": result.get("status") == "active",
                "status": result.get("status", "unknown"),
            })
        except Exception as e:
            return json.dumps({"healthy": False, "error": str(e)})
