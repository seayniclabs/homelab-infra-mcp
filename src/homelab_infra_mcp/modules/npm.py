"""Nginx Proxy Manager module — 14 tools for proxy host, SSL, and redirection management."""

import json

import httpx

from homelab_infra_mcp.config import config
from homelab_infra_mcp.safety import check_mode, is_dry_run, request_confirmation

_npm_token: str | None = None


async def _npm_auth() -> str:
    """Authenticate with NPM and return a bearer token."""
    global _npm_token
    if _npm_token:
        return _npm_token
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{config.npm_url}/api/tokens", json={
            "identity": config.npm_email,
            "secret": config.npm_password,
        })
        resp.raise_for_status()
        _npm_token = resp.json()["token"]
        return _npm_token


async def _npm_get(path: str) -> dict:
    token = await _npm_auth()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{config.npm_url}/api/{path}",
                                headers={"Authorization": f"Bearer {token}"})
        resp.raise_for_status()
        return resp.json()


async def _npm_post(path: str, data: dict) -> dict:
    token = await _npm_auth()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(f"{config.npm_url}/api/{path}", json=data,
                                 headers={"Authorization": f"Bearer {token}"})
        resp.raise_for_status()
        return resp.json()


async def _npm_put(path: str, data: dict) -> dict:
    token = await _npm_auth()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.put(f"{config.npm_url}/api/{path}", json=data,
                                headers={"Authorization": f"Bearer {token}"})
        resp.raise_for_status()
        return resp.json()


async def _npm_delete(path: str) -> bool:
    token = await _npm_auth()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.delete(f"{config.npm_url}/api/{path}",
                                   headers={"Authorization": f"Bearer {token}"})
        resp.raise_for_status()
        return True


def register(mcp):
    """Register NPM tools with the MCP server."""

    @mcp.tool()
    async def npm_list_proxy_hosts() -> str:
        """List all proxy hosts with domain, target, SSL status."""
        hosts = await _npm_get("nginx/proxy-hosts")
        summary = [{
            "id": h["id"],
            "domain": ", ".join(h.get("domain_names", [])),
            "forward_host": h.get("forward_host"),
            "forward_port": h.get("forward_port"),
            "ssl": bool(h.get("certificate_id")),
            "enabled": h.get("enabled", True),
        } for h in hosts]
        return json.dumps({"count": len(summary), "proxy_hosts": summary})

    @mcp.tool()
    async def npm_get_proxy_host(host_id: int) -> str:
        """Get detailed configuration for a specific proxy host.

        Args:
            host_id: The proxy host ID.
        """
        host = await _npm_get(f"nginx/proxy-hosts/{host_id}")
        return json.dumps(host)

    @mcp.tool()
    async def npm_create_proxy_host(
        domain_names: str,
        forward_host: str,
        forward_port: int,
        ssl: bool = True,
        force_ssl: bool = False,
        block_exploits: bool = True,
    ) -> str:
        """Create a new proxy host.

        Args:
            domain_names: Comma-separated domain names.
            forward_host: Backend host/IP to forward to.
            forward_port: Backend port.
            ssl: Enable SSL with Let's Encrypt.
            force_ssl: Force HTTPS redirect.
            block_exploits: Block common exploits.
        """
        blocked = check_mode("write")
        if blocked:
            return json.dumps({"error": blocked})

        data = {
            "domain_names": [d.strip() for d in domain_names.split(",")],
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

        if is_dry_run():
            return json.dumps({"dry_run": True, "would_create": data})

        result = await _npm_post("nginx/proxy-hosts", data)
        return json.dumps({"created": True, "id": result.get("id"), "domains": data["domain_names"]})

    @mcp.tool()
    async def npm_update_proxy_host(host_id: int, forward_host: str = "", forward_port: int = 0) -> str:
        """Update an existing proxy host configuration.

        Args:
            host_id: The proxy host ID to update.
            forward_host: New backend host (empty to keep current).
            forward_port: New backend port (0 to keep current).
        """
        blocked = check_mode("write")
        if blocked:
            return json.dumps({"error": blocked})

        current = await _npm_get(f"nginx/proxy-hosts/{host_id}")
        if forward_host:
            current["forward_host"] = forward_host
        if forward_port:
            current["forward_port"] = forward_port

        if is_dry_run():
            return json.dumps({"dry_run": True, "would_update": {"id": host_id, "forward_host": current["forward_host"], "forward_port": current["forward_port"]}})

        result = await _npm_put(f"nginx/proxy-hosts/{host_id}", current)
        return json.dumps({"updated": True, "id": host_id})

    @mcp.tool()
    async def npm_delete_proxy_host(host_id: int) -> str:
        """Delete a proxy host.

        Args:
            host_id: The proxy host ID to delete.
        """
        blocked = check_mode("destructive")
        if blocked:
            return json.dumps({"error": blocked})

        host = await _npm_get(f"nginx/proxy-hosts/{host_id}")
        domains = ", ".join(host.get("domain_names", []))

        if is_dry_run():
            return json.dumps({"dry_run": True, "would_delete": {"id": host_id, "domains": domains}})

        return request_confirmation(
            f"delete proxy host {host_id} ({domains})",
            f"This will permanently remove the proxy host for {domains}."
        )

    @mcp.tool()
    async def npm_list_ssl_certificates() -> str:
        """List all SSL certificates with expiry dates."""
        certs = await _npm_get("nginx/certificates")
        summary = [{
            "id": c["id"],
            "domain": ", ".join(c.get("domain_names", [])),
            "provider": c.get("provider", "unknown"),
            "expires_on": c.get("expires_on"),
        } for c in certs]
        return json.dumps({"count": len(summary), "certificates": summary})

    @mcp.tool()
    async def npm_request_ssl_certificate(domain_names: str) -> str:
        """Request a new Let's Encrypt SSL certificate.

        Args:
            domain_names: Comma-separated domain names for the certificate.
        """
        blocked = check_mode("write")
        if blocked:
            return json.dumps({"error": blocked})

        data = {
            "domain_names": [d.strip() for d in domain_names.split(",")],
            "meta": {"letsencrypt_agree": True, "dns_challenge": False},
            "provider": "letsencrypt",
        }

        if is_dry_run():
            return json.dumps({"dry_run": True, "would_request": data})

        result = await _npm_post("nginx/certificates", data)
        return json.dumps({"created": True, "id": result.get("id")})

    @mcp.tool()
    async def npm_list_redirections() -> str:
        """List all redirection hosts."""
        hosts = await _npm_get("nginx/redirection-hosts")
        summary = [{
            "id": h["id"],
            "domain": ", ".join(h.get("domain_names", [])),
            "forward_domain": h.get("forward_domain_name"),
            "forward_scheme": h.get("forward_scheme"),
            "preserve_path": h.get("preserve_path", False),
        } for h in hosts]
        return json.dumps({"count": len(summary), "redirections": summary})

    @mcp.tool()
    async def npm_create_redirection(domain_names: str, forward_domain: str, forward_scheme: str = "https", preserve_path: bool = True) -> str:
        """Create a new HTTP redirection.

        Args:
            domain_names: Comma-separated source domains.
            forward_domain: Target domain to redirect to.
            forward_scheme: http or https.
            preserve_path: Whether to preserve the URL path.
        """
        blocked = check_mode("write")
        if blocked:
            return json.dumps({"error": blocked})

        data = {
            "domain_names": [d.strip() for d in domain_names.split(",")],
            "forward_domain_name": forward_domain,
            "forward_scheme": forward_scheme,
            "preserve_path": preserve_path,
            "certificate_id": 0,
            "ssl_forced": False,
            "block_exploits": True,
            "http2_support": False,
            "hsts_enabled": False,
            "hsts_subdomains": False,
            "advanced_config": "",
        }

        if is_dry_run():
            return json.dumps({"dry_run": True, "would_create": data})

        result = await _npm_post("nginx/redirection-hosts", data)
        return json.dumps({"created": True, "id": result.get("id")})

    @mcp.tool()
    async def npm_delete_redirection(host_id: int) -> str:
        """Delete a redirection host.

        Args:
            host_id: The redirection host ID to delete.
        """
        blocked = check_mode("destructive")
        if blocked:
            return json.dumps({"error": blocked})

        if is_dry_run():
            return json.dumps({"dry_run": True, "would_delete": {"id": host_id}})

        return request_confirmation(
            f"delete redirection host {host_id}",
            "This will permanently remove the redirection."
        )

    @mcp.tool()
    async def npm_list_access_lists() -> str:
        """List access lists (IP allow/deny rules)."""
        lists = await _npm_get("nginx/access-lists")
        summary = [{"id": a["id"], "name": a.get("name", "unnamed")} for a in lists]
        return json.dumps({"count": len(summary), "access_lists": summary})

    @mcp.tool()
    async def npm_create_access_list(name: str, allow: str = "", deny: str = "") -> str:
        """Create an access list with IP rules.

        Args:
            name: Name for the access list.
            allow: Comma-separated IPs/CIDRs to allow.
            deny: Comma-separated IPs/CIDRs to deny.
        """
        blocked = check_mode("write")
        if blocked:
            return json.dumps({"error": blocked})

        items = []
        for ip in (i.strip() for i in allow.split(",") if i.strip()):
            items.append({"address": ip, "directive": "allow"})
        for ip in (i.strip() for i in deny.split(",") if i.strip()):
            items.append({"address": ip, "directive": "deny"})

        data = {"name": name, "items": items, "clients": [], "satisfy_any": False, "pass_auth": False}

        if is_dry_run():
            return json.dumps({"dry_run": True, "would_create": data})

        result = await _npm_post("nginx/access-lists", data)
        return json.dumps({"created": True, "id": result.get("id"), "name": name})

    @mcp.tool()
    async def npm_delete_access_list(list_id: int) -> str:
        """Delete an access list.

        Args:
            list_id: The access list ID to delete.
        """
        blocked = check_mode("destructive")
        if blocked:
            return json.dumps({"error": blocked})

        if is_dry_run():
            return json.dumps({"dry_run": True, "would_delete": {"id": list_id}})

        return request_confirmation(
            f"delete access list {list_id}",
            "This will permanently remove the access list and affect any proxy hosts using it."
        )

    @mcp.tool()
    async def npm_health() -> str:
        """Check NPM API connectivity and version."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{config.npm_url}/api/")
                return json.dumps({"healthy": resp.status_code == 200, "status_code": resp.status_code})
        except Exception as e:
            return json.dumps({"healthy": False, "error": str(e)})
