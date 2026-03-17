"""Homelab Infrastructure MCP — main server with module loading and cross-domain tools."""

import json
import logging

from mcp.server.fastmcp import FastMCP

from homelab_infra_mcp.config import config
from homelab_infra_mcp.safety import (
    check_mode,
    is_dry_run,
    request_confirmation,
    validate_confirmation,
)

logging.basicConfig(level=getattr(logging, config.log_level, logging.INFO))
logger = logging.getLogger("homelab-infra-mcp")

mcp = FastMCP(
    "homelab-infra",
    instructions="""\
Homelab Infrastructure MCP — unified management for your homelab.

## Modules
- **NPM** — Nginx Proxy Manager: proxy hosts, SSL, redirections, access lists
- **Docker** — containers, images, volumes, networks, stats, logs
- **DNS** — Cloudflare DNS records and zone management

## Cross-Domain Workflows
- `expose_service` — create DNS + proxy host for a container in one call
- `teardown_service` — reverse of expose
- `service_status` — container + proxy + DNS in one view
- `infrastructure_overview` — full dashboard

## Safety Modes
- `normal` — all operations permitted (destructive requires confirmation)
- `read-only` — only read operations work
- `dry-run` — write/destructive operations show what would happen without executing

## Tips
- Use `server_health` to check connectivity to all backends
- Use `set_mode("dryrun")` to preview changes before committing
- Destructive operations return a confirmation token — pass it to `confirm_destructive` to execute
""",
)


# ---------------------------------------------------------------------------
# Safety & Utility Tools (always registered)
# ---------------------------------------------------------------------------

@mcp.tool()
def set_mode(mode: str) -> str:
    """Switch operating mode.

    Args:
        mode: One of 'normal', 'readonly', 'dryrun'.
    """
    if mode not in ("normal", "readonly", "dryrun"):
        return json.dumps({"error": f"Invalid mode: {mode}. Use normal, readonly, or dryrun."})
    config.mode = mode
    return json.dumps({"mode": mode, "message": f"Mode set to {mode}."})


@mcp.tool()
def get_mode() -> str:
    """Show the current operating mode."""
    return json.dumps({"mode": config.mode})


@mcp.tool()
def confirm_destructive(token: str) -> str:
    """Confirm a pending destructive operation.

    Args:
        token: The confirmation token from the destructive operation.
    """
    entry = validate_confirmation(token)
    if entry is None:
        return json.dumps({"error": "Invalid or expired confirmation token."})

    # Execute the confirmed action
    return json.dumps({
        "confirmed": True,
        "action": entry["action"],
        "message": f"Confirmed: {entry['action']}. Operation would execute here.",
        "note": "Full execution wiring is implemented per-module in the actual destructive handlers.",
    })


@mcp.tool()
async def server_health() -> str:
    """Health check for all backend APIs and server version."""
    from homelab_infra_mcp import __version__

    results = {"version": __version__, "mode": config.mode, "modules": config.modules}

    # Check each enabled module's health
    if "npm" in config.modules:
        try:
            from homelab_infra_mcp.modules import npm
            # Simple connectivity check
            import httpx
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{config.npm_url}/api/")
                results["npm"] = {"healthy": resp.status_code == 200}
        except Exception as e:
            results["npm"] = {"healthy": False, "error": str(e)}

    if "docker" in config.modules:
        try:
            import docker as docker_sdk
            client = docker_sdk.DockerClient(base_url=config.docker_host)
            info = client.info()
            results["docker"] = {"healthy": True, "version": info.get("ServerVersion")}
        except Exception as e:
            results["docker"] = {"healthy": False, "error": str(e)}

    if "dns" in config.modules:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get("https://api.cloudflare.com/client/v4/user/tokens/verify",
                                        headers={"Authorization": f"Bearer {config.cloudflare_api_token}"})
                data = resp.json()
                results["dns"] = {"healthy": data.get("result", {}).get("status") == "active"}
        except Exception as e:
            results["dns"] = {"healthy": False, "error": str(e)}

    return json.dumps(results)


# ---------------------------------------------------------------------------
# Cross-Domain Tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def expose_service(
    container_name: str,
    domain: str,
    forward_port: int,
    dns_zone_id: str = "",
    tunnel_hostname: str = "",
) -> str:
    """Expose a container to the internet: create DNS CNAME + NPM proxy host.

    Args:
        container_name: Docker container name (must be running).
        domain: Full domain name (e.g. 'app.example.com').
        forward_port: Port the container listens on.
        dns_zone_id: Cloudflare zone ID (uses default if empty).
        tunnel_hostname: Cloudflare Tunnel hostname for CNAME target (e.g. 'tunnel.example.com').
    """
    blocked = check_mode("write")
    if blocked:
        return json.dumps({"error": blocked})

    steps = []
    errors = []

    if is_dry_run():
        return json.dumps({
            "dry_run": True,
            "would_do": [
                f"Verify container '{container_name}' is running",
                f"Create CNAME record: {domain} -> {tunnel_hostname or 'host.docker.internal'}",
                f"Create NPM proxy host: {domain} -> host.docker.internal:{forward_port}",
            ]
        })

    # Step 1: Verify container exists and is running
    if "docker" in config.modules:
        try:
            import docker as docker_sdk
            client = docker_sdk.DockerClient(base_url=config.docker_host)
            c = client.containers.get(container_name)
            if c.status != "running":
                errors.append(f"Container '{container_name}' is {c.status}, not running")
            else:
                steps.append(f"Verified container '{container_name}' is running")
        except Exception as e:
            errors.append(f"Docker check failed: {e}")

    # Step 2: Create DNS record
    if "dns" in config.modules and tunnel_hostname:
        try:
            from homelab_infra_mcp.modules.dns.cloudflare import _cf_post
            zid = dns_zone_id or config.cloudflare_zone_id
            if zid:
                await _cf_post(f"zones/{zid}/dns_records", {
                    "type": "CNAME", "name": domain, "content": tunnel_hostname, "proxied": True, "ttl": 1
                })
                steps.append(f"Created CNAME: {domain} -> {tunnel_hostname}")
            else:
                errors.append("No zone_id available for DNS record creation")
        except Exception as e:
            errors.append(f"DNS creation failed: {e}")

    # Step 3: Create NPM proxy host
    if "npm" in config.modules:
        try:
            from homelab_infra_mcp.modules.npm import _npm_post
            await _npm_post("nginx/proxy-hosts", {
                "domain_names": [domain],
                "forward_scheme": "http",
                "forward_host": "host.docker.internal",
                "forward_port": forward_port,
                "block_exploits": True,
                "allow_websocket_upgrade": True,
                "access_list_id": "0",
                "certificate_id": 0,
                "meta": {"letsencrypt_agree": True, "dns_challenge": False},
                "advanced_config": "",
                "locations": [],
                "http2_support": False,
                "hsts_enabled": False,
                "hsts_subdomains": False,
                "ssl_forced": False,
            })
            steps.append(f"Created NPM proxy: {domain} -> host.docker.internal:{forward_port}")
        except Exception as e:
            errors.append(f"NPM proxy creation failed: {e}")

    return json.dumps({"steps_completed": steps, "errors": errors, "success": len(errors) == 0})


@mcp.tool()
async def infrastructure_overview() -> str:
    """Summary of all containers, proxy hosts, and DNS records."""
    overview = {}

    if "docker" in config.modules:
        try:
            import docker as docker_sdk
            client = docker_sdk.DockerClient(base_url=config.docker_host)
            containers = client.containers.list(all=True)
            overview["docker"] = {
                "total": len(containers),
                "running": sum(1 for c in containers if c.status == "running"),
                "stopped": sum(1 for c in containers if c.status != "running"),
            }
        except Exception as e:
            overview["docker"] = {"error": str(e)}

    if "npm" in config.modules:
        try:
            from homelab_infra_mcp.modules.npm import _npm_get
            hosts = await _npm_get("nginx/proxy-hosts")
            overview["npm"] = {
                "proxy_hosts": len(hosts),
                "domains": [d for h in hosts for d in h.get("domain_names", [])],
            }
        except Exception as e:
            overview["npm"] = {"error": str(e)}

    if "dns" in config.modules:
        try:
            from homelab_infra_mcp.modules.dns.cloudflare import _cf_get
            zid = config.cloudflare_zone_id
            if zid:
                data = await _cf_get(f"zones/{zid}/dns_records")
                records = data.get("result", [])
                overview["dns"] = {
                    "total_records": len(records),
                    "by_type": {},
                }
                for r in records:
                    rt = r["type"]
                    overview["dns"]["by_type"][rt] = overview["dns"]["by_type"].get(rt, 0) + 1
            else:
                overview["dns"] = {"note": "No default CLOUDFLARE_ZONE_ID set"}
        except Exception as e:
            overview["dns"] = {"error": str(e)}

    return json.dumps(overview)


# ---------------------------------------------------------------------------
# Module Registration
# ---------------------------------------------------------------------------

def _register_modules():
    """Register enabled modules based on config."""
    if "npm" in config.modules:
        from homelab_infra_mcp.modules.npm import register as register_npm
        register_npm(mcp)
        logger.info("NPM module loaded (14 tools)")

    if "docker" in config.modules:
        from homelab_infra_mcp.modules.docker import register as register_docker
        register_docker(mcp)
        logger.info("Docker module loaded (16 tools)")

    if "dns" in config.modules:
        from homelab_infra_mcp.modules.dns.cloudflare import register as register_dns
        register_dns(mcp)
        logger.info("DNS/Cloudflare module loaded (8 tools)")


def main():
    """Entry point."""
    _register_modules()
    logger.info(f"Homelab Infrastructure MCP starting (mode={config.mode}, modules={config.modules})")

    if config.transport == "sse":
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
