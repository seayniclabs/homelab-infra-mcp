"""Homelab Infrastructure MCP — main server with module loading."""

import json
import logging
import sys

from mcp.server.fastmcp import FastMCP

from homelab_infra_mcp.config import config
from homelab_infra_mcp.safety import run_confirmed_action, validate_confirmation

logging.basicConfig(level=getattr(logging, config.log_level, logging.INFO))
logger = logging.getLogger("homelab-infra-mcp")

mcp = FastMCP(
    "homelab-infra",
    instructions="""\
Homelab Infrastructure MCP — unified management for NPM, Docker/Portainer, and Cloudflare DNS.

Cross-domain: expose_service, teardown_service, service_status, infrastructure_overview.
Safety: set_mode (normal / read-only / dry-run), confirm_destructive for destructive ops.
Use server_health to verify backend connectivity.
""",
)


@mcp.tool()
def set_mode(mode: str) -> str:
    """Switch operating mode: normal, readonly (read-only), or dryrun (dry-run)."""
    aliases = {
        "read-only": "readonly",
        "dry-run": "dryrun",
        "normal": "normal",
        "readonly": "readonly",
        "dryrun": "dryrun",
    }
    normalized = aliases.get(mode.strip().lower())
    if not normalized:
        return json.dumps({"error": f"Invalid mode: {mode}. Use normal, read-only, or dry-run."})
    config.mode = normalized
    return json.dumps({"mode": normalized, "message": f"Mode set to {normalized}."})


@mcp.tool()
def get_mode() -> str:
    """Show the current operating mode."""
    return json.dumps({"mode": config.mode})


@mcp.tool()
async def confirm_destructive(token: str) -> str:
    """Confirm and execute a pending destructive operation."""
    entry = validate_confirmation(token)
    if entry is None:
        return json.dumps({"error": "Invalid or expired confirmation token."})
    try:
        result = await run_confirmed_action(entry)
        return json.dumps({
            "confirmed": True,
            "action": entry["action"],
            "result": result,
        })
    except Exception as e:
        return json.dumps({"confirmed": False, "error": str(e)})


@mcp.tool()
async def server_health() -> str:
    """Health check for all backend APIs and server version."""
    from homelab_infra_mcp import __version__

    results: dict = {
        "version": __version__,
        "mode": config.mode,
        "modules": config.modules,
        "docker_backend": config.docker_backend if "docker" in config.modules else None,
    }

    if "npm" in config.modules:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{config.npm_url}/api/")
                results["npm"] = {"healthy": resp.status_code == 200}
        except Exception as e:
            results["npm"] = {"healthy": False, "error": str(e)}

    if "docker" in config.modules:
        try:
            from homelab_infra_mcp.modules.docker_backends import get_backend

            results["docker"] = get_backend().health()
        except Exception as e:
            results["docker"] = {"healthy": False, "error": str(e)}

    if "dns" in config.modules:
        try:
            from homelab_infra_mcp.modules.dns.cloudflare import _cf_get

            data = await _cf_get("user/tokens/verify")
            results["dns"] = {
                "healthy": data.get("result", {}).get("status") == "active",
            }
        except Exception as e:
            results["dns"] = {"healthy": False, "error": str(e)}

    return json.dumps(results)


def _register_modules() -> None:
    from homelab_infra_mcp.modules.cross_domain import register as register_cross

    register_cross(mcp)
    logger.info("Cross-domain module loaded (4 tools)")

    if "npm" in config.modules:
        from homelab_infra_mcp.modules.npm import register as register_npm

        register_npm(mcp)
        logger.info("NPM module loaded (14 tools)")

    if "docker" in config.modules:
        from homelab_infra_mcp.modules.docker import register as register_docker

        register_docker(mcp)
        tool_count = 18 if config.docker_backend == "portainer" else 16
        logger.info("Docker module loaded (%s tools, backend=%s)", tool_count, config.docker_backend)

    if "dns" in config.modules:
        from homelab_infra_mcp.modules.dns.cloudflare import register as register_dns

        register_dns(mcp)
        logger.info("DNS/Cloudflare module loaded (8 tools)")

    if "home_assistant" in config.modules:
        from homelab_infra_mcp.modules.home_assistant import register as register_ha

        register_ha(mcp)
        logger.info("Home Assistant module loaded (optional)")


def _startup_log() -> None:
    from homelab_infra_mcp import __version__

    print(f"[homelab-infra-mcp] v{__version__} mode={config.mode} modules={','.join(config.modules)}", file=sys.stderr)
    if config.docker_backend == "portainer":
        print(f"[homelab-infra-mcp] Docker backend: Portainer ({config.portainer_url})", file=sys.stderr)
    else:
        print(f"[homelab-infra-mcp] Docker backend: socket ({config.docker_host})", file=sys.stderr)
    for warning in config.validate_modules():
        print(f"[homelab-infra-mcp] WARNING: {warning}", file=sys.stderr)


def main() -> None:
    _register_modules()
    _startup_log()
    if config.transport == "sse":
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
