"""Homelab server: one process, one tool per resource, plus discovery and health.

Build it with ``build_server()``; run it with ``homelab-infra`` (stdio) or
``homelab-infra --transport http`` (streamable HTTP).
"""

from __future__ import annotations

import argparse
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from homelab_infra_mcp import __version__, diagnose, skills as skills_mod, workflows
from homelab_infra_mcp.config import CORE, Config, config_path
from homelab_infra_mcp.errors import HomelabError
from homelab_infra_mcp.modules import Module, all_modules
from homelab_infra_mcp.modules.uptime import parse_monitor_status
from homelab_infra_mcp.runtime import DockerFactory, HttpFactory, Runtime, default_docker, default_http

PUBLISHER = "Seaynic Labs"
HOMEPAGE = "https://github.com/seayniclabs/homelab-infra-mcp"

INSTRUCTIONS = (
    "Homelab runs your homelab's proxy (Nginx Proxy Manager), containers (Docker or Portainer), DNS (Cloudflare) "
    "and the services around them (Uptime Kuma, Cloudflare Tunnel, AdGuard Home, Authentik) from one server. "
    "Call homelab_modules first: it says which modules are on, which settings are missing, and what each tool does. "
    "Skills (MCP prompts) explain how to do the job well; start with the getting-started prompt. Read tools are safe "
    "to call freely. Changes are shown to the person for approval before they run. Errors read "
    "'homelab.<module>.<code>: <message> Fix: <hint>'."
)
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)


class SettingInfo(BaseModel):
    env_var: str
    help: str
    secret: bool
    set: bool
    writes_preapproved: bool | None = None


class ModuleInfo(BaseModel):
    name: str
    summary: str
    enabled: bool
    configured: bool
    missing: list[str]
    writes_preapproved: bool
    tools: dict[str, str]
    settings: list[SettingInfo] | None = None


class SkillInfo(BaseModel):
    name: str
    description: str
    license: str


class ModulesResult(BaseModel):
    version: str
    read_only: bool
    config_file: str
    core_tools: dict[str, str]
    modules: list[ModuleInfo]
    skills: list[SkillInfo] = []
    publisher: str = PUBLISHER
    homepage: str = HOMEPAGE


class ModuleHealth(BaseModel):
    module: str
    enabled: bool
    healthy: bool | None = None  # None when the module is switched off
    detail: dict[str, Any] | None = None
    error: str | None = None


class HealthResult(BaseModel):
    version: str
    modules: list[ModuleHealth]


CORE_TOOLS = {
    "homelab_modules": "Which modules are on, what settings are missing, and what each tool does.",
    "homelab_health": "Connectivity and version for every enabled module.",
    "expose_service": "Container check, optional Cloudflare CNAME, and proxy host, in one approved plan.",
    "teardown_service": "Remove a service's proxy host and optional DNS record, in one approved plan.",
    "service_status": "One view of a service: container, proxy hosts and DNS records.",
    "infrastructure_overview": "Counts across Docker, the proxy and DNS.",
    "diagnose_service": "Read-only check of each hop from a domain to its upstream, naming the first failure and its fix.",
}


async def _probe(module: Module, runtime: Runtime) -> ModuleHealth:
    missing = module.missing(runtime.config)
    if missing:
        return ModuleHealth(module=module.name, enabled=True, healthy=False,
                            error=f"not_configured: missing {', '.join(missing)}")
    try:
        if module.name == "proxy":
            npm = runtime.npm()
            async with runtime.http() as client:
                r = await client.get(f"{npm._base()}/api/")
            return ModuleHealth(module=module.name, enabled=True, healthy=r.status_code == 200,
                                detail={"status_code": r.status_code})
        if module.name == "docker":
            return ModuleHealth(module=module.name, enabled=True, healthy=True,
                                detail=await runtime.docker().health())
        if module.name == "dns":
            res = await runtime.cloudflare().verify()
            return ModuleHealth(module=module.name, enabled=True, healthy=res.get("status") == "active",
                                detail={"token_status": res.get("status", "unknown")})
        if module.name == "home_assistant":
            ha = runtime.home_assistant()
            await ha.request("GET", "/api/")
            return ModuleHealth(module=module.name, enabled=True, healthy=True)
        if module.name == "uptime":
            monitors = parse_monitor_status(await runtime.uptime().metrics_text())
            return ModuleHealth(module=module.name, enabled=True, healthy=True,
                                detail={"monitors": len(monitors)})
        if module.name == "tunnel":
            tunnels = await runtime.tunnel().tunnels()
            return ModuleHealth(module=module.name, enabled=True, healthy=True, detail={"tunnels": len(tunnels)})
        if module.name == "dns_filter":
            status = await runtime.dns_filter().request("GET", "/status")
            return ModuleHealth(module=module.name, enabled=True, healthy=bool(status.get("running", True)),
                                detail={"version": status.get("version", "unknown")})
        if module.name == "sso":
            me = await runtime.sso().request("GET", "/core/users/me/")
            return ModuleHealth(module=module.name, enabled=True, healthy=True,
                                detail={"user": (me.get("user") or {}).get("username", "unknown")})
    except HomelabError as e:
        return ModuleHealth(module=module.name, enabled=True, healthy=False, error=str(e))
    except Exception as e:  # never let one probe take the others down
        return ModuleHealth(module=module.name, enabled=True, healthy=False, error=f"{type(e).__name__}: {e}")
    return ModuleHealth(module=module.name, enabled=True, healthy=None)


def build_server(
    config: Config | None = None,
    http: HttpFactory = default_http,
    docker: DockerFactory = default_docker,
    modules: list[Module] | None = None,
    **settings: Any,
) -> FastMCP:
    config = config or Config()
    modules = modules if modules is not None else all_modules()
    runtime = Runtime(config, http=http, docker=docker)
    mcp = FastMCP("homelab", instructions=INSTRUCTIONS, **settings)
    # FastMCP 1.x reports the SDK's version unless the low-level server is told otherwise.
    mcp._mcp_server.version = __version__

    enabled = {m.name for m in modules if config.enabled(m.name, m.default_enabled)}
    for m in modules:
        if m.name in enabled:
            m.register(mcp, runtime)
    workflows.register(mcp, runtime, enabled)
    diagnose.register(mcp, runtime, enabled)
    loaded_skills = skills_mod.register(mcp, "homelab")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    def homelab_modules(module: str | None = None) -> ModulesResult:
        """Which modules are on, which settings are missing, whether writes are pre-approved, and what each tool
        does. Pass a module name for its full settings list (values are never shown, only whether they are set)."""
        infos = []
        for m in modules:
            if module and m.name != module:
                continue
            missing = m.missing(config)
            info = ModuleInfo(
                name=m.name, summary=m.summary, enabled=m.name in enabled,
                configured=not missing, missing=missing, tools=m.tools,
                writes_preapproved=config.flag(m.name, "allow_writes", False),
            )
            if module:
                info.settings = [
                    SettingInfo(env_var=s.env_var(m.name), help=s.help, secret=s.secret,
                                set=bool(config.get(m.name, s.key)))
                    for s in m.settings if s.key != "allow_writes"
                ]
            infos.append(info)
        return ModulesResult(version=__version__, read_only=config.flag(CORE, "read_only", False),
                             config_file=str(config_path(config.env)), core_tools=CORE_TOOLS, modules=infos,
                             skills=[SkillInfo(name=s["name"], description=s["description"], license=s["license"])
                                     for s in loaded_skills])

    @mcp.tool(annotations=READ_ONLY)
    async def homelab_health() -> HealthResult:
        """Connectivity and version for every enabled module. A module with missing settings reports the
        variable it needs."""
        results = []
        for m in modules:
            if m.name not in enabled:
                results.append(ModuleHealth(module=m.name, enabled=False))
                continue
            results.append(await _probe(m, runtime))
        return HealthResult(version=__version__, modules=results)

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="homelab-infra", description=INSTRUCTIONS)
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP only. Keep 127.0.0.1 unless you add auth in front.")
    parser.add_argument("--port", type=int, default=8200, help="HTTP only.")
    parser.add_argument("--version", action="version", version=f"homelab-infra {__version__}")
    parser.add_argument("--doctor", action="store_true",
                        help="Check settings and connections, print a fix for each problem, and exit (1 if any).")
    args = parser.parse_args(argv)

    if args.doctor:
        from homelab_infra_mcp.doctor import run

        raise SystemExit(run())

    if args.transport == "http":
        build_server(host=args.host, port=args.port).run(transport="streamable-http")
    else:
        build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
