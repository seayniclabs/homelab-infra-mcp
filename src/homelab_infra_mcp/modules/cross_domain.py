"""Cross-domain tools — expose, teardown, service status, infrastructure overview."""

import json

from homelab_infra_mcp.config import config
from homelab_infra_mcp.modules.docker_backends import get_backend
from homelab_infra_mcp.safety import check_mode, is_dry_run
from homelab_infra_mcp.utils.validation import ValidationError, validate_domain, validate_port


def register(mcp):
    """Register cross-domain MCP tools."""

    @mcp.tool()
    async def expose_service(
        container_name: str,
        domain: str,
        forward_port: int,
        dns_zone_id: str = "",
        tunnel_hostname: str = "",
    ) -> str:
        """Expose a container: create Cloudflare CNAME + NPM proxy host."""
        blocked = check_mode("write")
        if blocked:
            return json.dumps({"error": blocked})
        try:
            validate_domain(domain)
            validate_port(forward_port)
        except ValidationError as e:
            return json.dumps({"error": str(e)})

        if is_dry_run():
            return json.dumps({
                "dry_run": True,
                "would_do": [
                    f"Verify container '{container_name}' is running",
                    f"Create CNAME: {domain} -> {tunnel_hostname or 'tunnel'}",
                    f"Create NPM proxy: {domain} -> host.docker.internal:{forward_port}",
                ],
            })

        steps: list[str] = []
        errors: list[str] = []

        if "docker" in config.modules:
            try:
                c = get_backend().get_container(container_name)
                if c.get("status") != "running":
                    errors.append(
                        f"Container '{container_name}' is {c.get('status')}, not running"
                    )
                else:
                    steps.append(f"Verified container '{container_name}' is running")
            except Exception as e:
                errors.append(f"Docker check failed: {e}")

        if "dns" in config.modules and tunnel_hostname:
            try:
                from homelab_infra_mcp.modules.dns.cloudflare import _cf_post

                zid = dns_zone_id or config.cloudflare_zone_id
                if zid:
                    await _cf_post(
                        f"zones/{zid}/dns_records",
                        {
                            "type": "CNAME",
                            "name": domain,
                            "content": tunnel_hostname,
                            "proxied": True,
                            "ttl": 1,
                        },
                    )
                    steps.append(f"Created CNAME: {domain} -> {tunnel_hostname}")
                else:
                    errors.append("No zone_id for DNS record creation")
            except Exception as e:
                errors.append(f"DNS creation failed: {e}")

        if "npm" in config.modules:
            try:
                from homelab_infra_mcp.modules.npm import _npm_post

                await _npm_post(
                    "nginx/proxy-hosts",
                    {
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
                    },
                )
                steps.append(
                    f"Created NPM proxy: {domain} -> host.docker.internal:{forward_port}"
                )
            except Exception as e:
                errors.append(f"NPM proxy creation failed: {e}")

        return json.dumps({"steps_completed": steps, "errors": errors, "success": len(errors) == 0})

    @mcp.tool()
    async def teardown_service(
        domain: str,
        dns_zone_id: str = "",
        proxy_host_id: int = 0,
        dns_record_id: str = "",
    ) -> str:
        """Reverse expose_service — remove NPM proxy host and DNS record."""
        blocked = check_mode("destructive")
        if blocked:
            return json.dumps({"error": blocked})
        try:
            validate_domain(domain)
        except ValidationError as e:
            return json.dumps({"error": str(e)})

        if is_dry_run():
            return json.dumps({
                "dry_run": True,
                "would_remove": {"domain": domain, "proxy_host_id": proxy_host_id, "dns_record_id": dns_record_id},
            })

        steps: list[str] = []
        errors: list[str] = []

        if "npm" in config.modules:
            try:
                from homelab_infra_mcp.modules.npm import _npm_delete, _npm_get

                host_id = proxy_host_id
                if not host_id:
                    hosts = await _npm_get("nginx/proxy-hosts")
                    for h in hosts:
                        if domain in h.get("domain_names", []):
                            host_id = h["id"]
                            break
                if host_id:
                    await _npm_delete(f"nginx/proxy-hosts/{host_id}")
                    steps.append(f"Deleted NPM proxy host {host_id} for {domain}")
                else:
                    errors.append(f"No NPM proxy host found for {domain}")
            except Exception as e:
                errors.append(f"NPM teardown failed: {e}")

        if "dns" in config.modules and dns_record_id:
            try:
                from homelab_infra_mcp.modules.dns.cloudflare import _cf_delete

                zid = dns_zone_id or config.cloudflare_zone_id
                await _cf_delete(f"zones/{zid}/dns_records/{dns_record_id}")
                steps.append(f"Deleted DNS record {dns_record_id}")
            except Exception as e:
                errors.append(f"DNS teardown failed: {e}")

        return json.dumps({"steps_completed": steps, "errors": errors, "success": len(errors) == 0})

    @mcp.tool()
    async def service_status(
        container_name: str,
        domain: str = "",
        dns_zone_id: str = "",
    ) -> str:
        """Unified view: container health, NPM proxy, and DNS record."""
        result: dict = {"container": None, "npm": None, "dns": None}

        if "docker" in config.modules:
            try:
                result["container"] = get_backend().get_container(container_name)
            except Exception as e:
                result["container"] = {"error": str(e)}

        if "npm" in config.modules and domain:
            try:
                from homelab_infra_mcp.modules.npm import _npm_get

                hosts = await _npm_get("nginx/proxy-hosts")
                matches = [h for h in hosts if domain in h.get("domain_names", [])]
                result["npm"] = {"proxy_hosts": matches}
            except Exception as e:
                result["npm"] = {"error": str(e)}

        if "dns" in config.modules and domain:
            try:
                from homelab_infra_mcp.modules.dns.cloudflare import _cf_get

                zid = dns_zone_id or config.cloudflare_zone_id
                data = await _cf_get(f"zones/{zid}/dns_records", params={"name": domain})
                result["dns"] = {"records": data.get("result", [])}
            except Exception as e:
                result["dns"] = {"error": str(e)}

        return json.dumps(result)

    @mcp.tool()
    async def infrastructure_overview() -> str:
        """Summary counts across Docker, NPM, and DNS."""
        overview: dict = {}

        if "docker" in config.modules:
            try:
                containers = get_backend().list_containers(all=True)
                overview["docker"] = {
                    "backend": get_backend().backend_name,
                    "total": len(containers),
                    "running": sum(1 for c in containers if "up" in c.get("status", "").lower()),
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

                if config.cloudflare_zone_id:
                    data = await _cf_get(f"zones/{config.cloudflare_zone_id}/dns_records")
                    records = data.get("result", [])
                    by_type: dict[str, int] = {}
                    for r in records:
                        by_type[r["type"]] = by_type.get(r["type"], 0) + 1
                    overview["dns"] = {"total_records": len(records), "by_type": by_type}
                else:
                    zones = await _cf_get("zones")
                    overview["dns"] = {"zones": len(zones.get("result", []))}
            except Exception as e:
                overview["dns"] = {"error": str(e)}

        return json.dumps(overview)
