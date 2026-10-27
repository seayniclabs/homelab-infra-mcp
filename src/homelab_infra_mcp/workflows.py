"""Cross-module workflows: expose and tear down a service in one call, plus status and overview.

Each workflow reads what it needs, shows the person the exact plan, and changes things only after
the approval gate. Steps that fail are reported, and the others still run (as before 2.0).
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from homelab_infra_mcp import validation
from homelab_infra_mcp.approval import gate
from homelab_infra_mcp.errors import HomelabError
from homelab_infra_mcp.runtime import Runtime

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
CHANGES = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True)
DEFAULT_FORWARD_HOST = "host.docker.internal"


class WorkflowResult(BaseModel):
    dry_run: bool = False
    planned: list[str] = []
    steps_completed: list[str] = []
    errors: list[str] = []
    success: bool = False
    approved_by: str | None = None
    note: str | None = None


class StatusResult(BaseModel):
    container: dict[str, Any] | None = None
    proxy_hosts: list[dict[str, Any]] | None = None
    dns_records: list[dict[str, Any]] | None = None
    errors: list[str] = []


class OverviewResult(BaseModel):
    docker: dict[str, Any] | None = None
    proxy: dict[str, Any] | None = None
    dns: dict[str, Any] | None = None


def register(mcp: FastMCP, runtime: Runtime, enabled: set[str]) -> None:
    config = runtime.config

    def need(module: str) -> None:
        if module not in enabled:
            raise HomelabError("core", "module_disabled", f"the {module} module is switched off.",
                               f"set HOMELAB_{module.upper()}_ENABLED=true, then restart the server.")

    @mcp.tool(annotations=CHANGES)
    async def expose_service(
        ctx: Context,
        container_name: str,
        domain: str,
        forward_port: int,
        forward_host: str = DEFAULT_FORWARD_HOST,
        dns_zone_id: str = "",
        tunnel_hostname: str = "",
        dry_run: bool = False,
    ) -> WorkflowResult:
        """Expose a container: check it runs, add a Cloudflare CNAME to tunnel_hostname (only if given), and add an
        Nginx Proxy Manager host that forwards domain to forward_host:forward_port. The plan is shown to the
        person before anything changes."""
        need("proxy")
        domain = validation.domain(domain, "core")
        validation.port(forward_port, "proxy")
        container = validation.container(container_name, "docker")
        use_dns = bool(tunnel_hostname) and "dns" in enabled
        planned = [f"check container {container} is running",
                   f"create proxy host {domain} -> http://{forward_host}:{forward_port}"]
        if tunnel_hostname:
            planned.insert(1, f"create CNAME {domain} -> {tunnel_hostname} (proxied)")
        if dry_run:
            return WorkflowResult(dry_run=True, planned=planned)
        modules = ["proxy"] + (["dns"] if use_dns else [])
        decision = await gate(ctx, config, modules, "Homelab (expose_service) will:\n- " + "\n- ".join(planned),
                              tool="expose_service")
        if not decision.approved:
            return WorkflowResult(planned=planned, note=decision.note)

        steps: list[str] = []
        errors: list[str] = []
        try:
            c = await runtime.docker().get_container(container)
            if c.get("status") != "running":
                errors.append(f"Container '{container}' is {c.get('status')}, not running")
            else:
                steps.append(f"Verified container '{container}' is running")
        except HomelabError as e:
            errors.append(f"Docker check failed: {e}")

        if use_dns:
            try:
                cf = runtime.cloudflare()
                zone = dns_zone_id or config.get("dns", "zone_id") or ""
                if not zone:
                    raise HomelabError("dns", "bad_input", "no zone id for the CNAME.",
                                       "pass dns_zone_id, or set HOMELAB_DNS_ZONE_ID.")
                await cf.create(zone, {"type": "CNAME", "name": domain, "content": tunnel_hostname,
                                       "proxied": True, "ttl": 1})
                steps.append(f"Created CNAME: {domain} -> {tunnel_hostname}")
            except HomelabError as e:
                errors.append(f"DNS creation failed: {e}")

        try:
            await runtime.npm().request("POST", "nginx/proxy-hosts", json={
                "domain_names": [domain], "forward_scheme": "http", "forward_host": forward_host,
                "forward_port": forward_port, "block_exploits": True, "allow_websocket_upgrade": True,
                "access_list_id": "0", "certificate_id": 0,
                "meta": {"letsencrypt_agree": True, "dns_challenge": False}, "advanced_config": "",
                "locations": [], "http2_support": False, "hsts_enabled": False, "hsts_subdomains": False,
                "ssl_forced": False,
            })
            steps.append(f"Created proxy host: {domain} -> http://{forward_host}:{forward_port}")
        except HomelabError as e:
            errors.append(f"Proxy host creation failed: {e}")
        return WorkflowResult(planned=planned, steps_completed=steps, errors=errors, success=not errors,
                              approved_by=decision.approved_by)

    @mcp.tool(annotations=CHANGES)
    async def teardown_service(
        ctx: Context,
        domain: str,
        dns_zone_id: str = "",
        proxy_host_id: int = 0,
        dns_record_id: str = "",
        dry_run: bool = False,
    ) -> WorkflowResult:
        """Reverse expose_service: delete the proxy host for domain (found by name unless proxy_host_id is given)
        and, if dns_record_id is given, that DNS record. The exact plan is shown to the person first."""
        domain = validation.domain(domain, "core")
        planned: list[str] = []
        errors: list[str] = []
        modules: list[str] = []
        host_id = proxy_host_id
        if "proxy" in enabled:
            npm = runtime.npm()
            host_names = ""
            if proxy_host_id:
                raw = await npm.request("GET", f"nginx/proxy-hosts/{proxy_host_id}")
                names = list(raw.get("domain_names") or [])
                if domain not in names:
                    raise HomelabError(
                        "proxy", "host_mismatch",
                        f"proxy host {proxy_host_id} serves {', '.join(names) or 'no domains'}, not {domain}.",
                        "pass the id of the host for this domain, or leave proxy_host_id at 0 to find it by name.")
                host_names = ", ".join(names)
            else:
                for h in await npm.request("GET", "nginx/proxy-hosts"):
                    if domain in h.get("domain_names", []):
                        host_id = h["id"]
                        host_names = ", ".join(h.get("domain_names") or [])
                        break
            if host_id:
                planned.append(f"DELETE proxy host {host_id} ({host_names})")
                modules.append("proxy")
            else:
                errors.append(f"No proxy host found for {domain}")
        zone = dns_zone_id or (config.get("dns", "zone_id") or "")
        record_desc = None
        if dns_record_id and "dns" in enabled:
            cf = runtime.cloudflare()
            rec = await cf.record(zone, dns_record_id) if zone else {}
            record_desc = f"{rec.get('type', '?')} {rec.get('name', '?')} -> {rec.get('content', '?')}"
            planned.append(f"PERMANENTLY delete DNS record {dns_record_id} ({record_desc})")
            modules.append("dns")
        if not planned:
            return WorkflowResult(errors=errors + ["Nothing to remove."], success=False)
        if dry_run:
            return WorkflowResult(dry_run=True, planned=planned, errors=errors)
        decision = await gate(ctx, config, modules, "Homelab (teardown_service) will:\n- " + "\n- ".join(planned),
                              tool="teardown_service")
        if not decision.approved:
            return WorkflowResult(planned=planned, errors=errors, note=decision.note)
        steps: list[str] = []
        if host_id and "proxy" in enabled:
            try:
                await runtime.npm().request("DELETE", f"nginx/proxy-hosts/{host_id}")
                steps.append(f"Deleted NPM proxy host {host_id} for {domain}")
            except HomelabError as e:
                errors.append(f"NPM teardown failed: {e}")
        if dns_record_id and "dns" in enabled:
            try:
                await runtime.cloudflare().delete(zone, dns_record_id)
                steps.append(f"Deleted DNS record {dns_record_id}")
            except HomelabError as e:
                errors.append(f"DNS teardown failed: {e}")
        return WorkflowResult(planned=planned, steps_completed=steps, errors=errors, success=not errors,
                              approved_by=decision.approved_by)

    @mcp.tool(annotations=READ_ONLY)
    async def service_status(container_name: str, domain: str = "", dns_zone_id: str = "") -> StatusResult:
        """One view of a service: the container, the proxy hosts that name the domain, and its DNS records."""
        result = StatusResult()
        if "docker" in enabled:
            try:
                result.container = await runtime.docker().get_container(validation.container(container_name, "docker"))
            except HomelabError as e:
                result.errors.append(str(e))
        domain = validation.domain(domain, "core") if domain else ""
        if domain and "proxy" in enabled:
            try:
                hosts = await runtime.npm().request("GET", "nginx/proxy-hosts")
                result.proxy_hosts = [h for h in hosts if domain in h.get("domain_names", [])]
            except HomelabError as e:
                result.errors.append(str(e))
        zone = dns_zone_id or (config.get("dns", "zone_id") or "")
        if domain and "dns" in enabled and zone:
            try:
                rows, _ = await runtime.cloudflare().records(zone, "", 1, 100)
                result.dns_records = [r for r in rows if r.get("name") == domain]
            except HomelabError as e:
                result.errors.append(str(e))
        return result

    @mcp.tool(annotations=READ_ONLY)
    async def infrastructure_overview() -> OverviewResult:
        """Counts across Docker, Nginx Proxy Manager and Cloudflare DNS, in one call."""
        out = OverviewResult()
        if "docker" in enabled:
            try:
                backend = runtime.docker()
                rows = await backend.list_containers(all=True)
                out.docker = {"backend": backend.name, "total": len(rows),
                              "running": sum(1 for c in rows if "running" in str(c.get("status", "")).lower()
                                             or "up" in str(c.get("status", "")).lower())}
            except HomelabError as e:
                out.docker = {"error": str(e)}
        if "proxy" in enabled:
            try:
                hosts = await runtime.npm().request("GET", "nginx/proxy-hosts")
                out.proxy = {"proxy_hosts": len(hosts),
                             "domains": [d for h in hosts for d in h.get("domain_names", [])]}
            except HomelabError as e:
                out.proxy = {"error": str(e)}
        if "dns" in enabled:
            try:
                cf = runtime.cloudflare()
                zone = config.get("dns", "zone_id") or ""
                if zone:
                    rows, _ = await cf.records(zone, "", 1, 100)
                    by_type: dict[str, int] = {}
                    for r in rows:
                        by_type[r["type"]] = by_type.get(r["type"], 0) + 1
                    out.dns = {"total_records": len(rows), "by_type": by_type}
                else:
                    zones, _ = await cf.zones(1, 50)
                    out.dns = {"zones": len(zones)}
            except HomelabError as e:
                out.dns = {"error": str(e)}
        return out
