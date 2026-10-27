"""diagnose_service: one read-only pass over every hop between a domain and its upstream container.

Hops, in order: DNS, tunnel route, Nginx Proxy Manager host, TLS certificate, upstream container,
upstream port, uptime monitor, Authentik login. A hop whose module is switched off is reported as
``skipped``. The first ``fail`` is named in ``first_failure``, with the fix for it. Every hop is
checked, so one row per hop is always returned.

This tool only reads. It resolves the domain, opens a TCP connection to the upstream and to the
public domain on port 443 (for the certificate), and calls the module APIs it already has.
"""

from __future__ import annotations

import asyncio
import re
import socket
import ssl
import time
from datetime import datetime, timezone
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from homelab_infra_mcp import validation
from homelab_infra_mcp.errors import HomelabError
from homelab_infra_mcp.runtime import Runtime

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
CERT_WARN_DAYS = 14

# Names a container uses to reach the machine Docker runs on. They resolve inside containers only.
DOCKER_HOST_ALIASES = {"host.docker.internal", "gateway.docker.internal",
                       "docker.for.mac.host.internal", "docker.for.mac.localhost"}

HOPS = ["dns", "tunnel", "proxy", "certificate", "container", "upstream_port", "uptime", "sso"]


class Hop(BaseModel):
    hop: str
    status: Literal["ok", "fail", "skipped", "unknown"]
    detail: str
    fix: str | None = None


class DiagnoseResult(BaseModel):
    domain: str
    hops: list[Hop] = []
    first_failure: str | None = None
    note: str | None = None


def _ok(hop: str, detail: str) -> Hop:
    return Hop(hop=hop, status="ok", detail=detail)


def _fail(hop: str, detail: str, fix: str) -> Hop:
    return Hop(hop=hop, status="fail", detail=detail, fix=fix)


def _skip(hop: str, module: str) -> Hop:
    return Hop(hop=hop, status="skipped", detail=f"the {module} module is switched off.",
               fix=f"set HOMELAB_{module.upper()}_ENABLED=true to check this hop.")


def _unknown(hop: str, detail: str, fix: str | None = None) -> Hop:
    return Hop(hop=hop, status="unknown", detail=detail, fix=fix)


def cert_days_left(domain: str, timeout: float = 5.0) -> tuple[float, str]:
    """Days until the certificate served for domain expires, read with the system trust store (stdlib only)."""
    ctx = ssl.create_default_context()
    with socket.create_connection((domain, 443), timeout=timeout) as raw:
        with ctx.wrap_socket(raw, server_hostname=domain) as tls:
            cert = tls.getpeercert()
    not_after = ssl.cert_time_to_seconds(cert["notAfter"])
    issuer = dict(x[0] for x in cert.get("issuer", ())).get("organizationName", "unknown issuer")
    return (not_after - time.time()) / 86400, issuer


def _port_matches(ports: list[str], port: int) -> bool:
    for p in ports:
        nums = [int(n) for n in re.findall(r"\d+", p)]
        if port in nums:
            return True
    return False


async def _tcp_open(host: str, port: int, timeout: float = 3.0) -> tuple[bool, str]:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        writer.close()
        await writer.wait_closed()
        return True, "accepted a TCP connection"
    except (OSError, asyncio.TimeoutError) as e:
        return False, f"{type(e).__name__}: {e or 'timed out'}"


def _docker_is_local(runtime: Runtime) -> bool:
    """True when the Docker module talks to a local socket, so this machine is the Docker host."""
    try:
        backend = runtime.docker()
    except HomelabError:
        return False
    return getattr(backend, "name", "") == "socket" and str(getattr(backend, "host", "")).startswith("unix://")


def register(mcp: FastMCP, runtime: Runtime, enabled: set[str]) -> None:
    config = runtime.config

    @mcp.tool(annotations=READ_ONLY)
    async def diagnose_service(domain: str) -> DiagnoseResult:
        """Check each hop between a public domain and its upstream container, and name the first one that fails
        with the fix for it. Hops: DNS record, tunnel route (if the tunnel module is on), Nginx Proxy Manager host,
        TLS certificate (expiry and trust), upstream container running (Docker), upstream port answering, uptime
        monitor (if on), Authentik login in front (if on). Read-only: it changes nothing."""
        d = validation.domain(domain, "core")
        hops: list[Hop] = []
        host: dict[str, Any] | None = None
        note = None

        # 1. DNS
        try:
            infos = await asyncio.to_thread(socket.getaddrinfo, d, 443, type=socket.SOCK_STREAM)
            addrs = sorted({i[4][0] for i in infos})
            hops.append(_ok("dns", f"{d} resolves to {', '.join(addrs)}"))
        except OSError as e:
            hops.append(_fail("dns", f"{d} does not resolve ({e}).",
                              "create a DNS record with dns_records (proxied CNAME or A record) or expose_service."))

        # 2. Tunnel
        if "tunnel" in enabled:
            try:
                cf = runtime.tunnel()
                ingress = (await cf.config_of(cf._tunnel())).get("ingress", [])
                if any(r.get("hostname") == d for r in ingress):
                    hops.append(_ok("tunnel", f"tunnel route for {d} exists."))
                else:
                    hops.append(Hop(hop="tunnel", status="skipped",
                                    detail=f"no tunnel route for {d}. Fine if the service is reached directly, not through the tunnel.",
                                    fix="add a route with tunnel_routes (action=add) if this service should go through the tunnel."))
            except HomelabError as e:
                hops.append(_unknown("tunnel", str(e), "check the tunnel module settings; run --doctor."))
        else:
            hops.append(_skip("tunnel", "tunnel"))

        # 3. Nginx Proxy Manager
        if "proxy" in enabled:
            try:
                hosts = await runtime.npm().request("GET", "nginx/proxy-hosts")
                host = next((h for h in hosts if d in (h.get("domain_names") or [])), None)
                if host is None:
                    hops.append(_fail("proxy", f"no Nginx Proxy Manager proxy host serves {d}.",
                                      "run expose_service (dry_run first) to create the proxy host."))
                elif not host.get("enabled", True):
                    hops.append(_fail("proxy", f"the proxy host for {d} is disabled in Nginx Proxy Manager.",
                                      "enable the host in Nginx Proxy Manager, or re-create it with expose_service."))
                else:
                    hops.append(_ok("proxy", f"proxy host {host['id']} forwards {d} to "
                                             f"{host.get('forward_host')}:{host.get('forward_port')}."))
            except HomelabError as e:
                hops.append(_unknown("proxy", str(e), "run --doctor and check the proxy settings."))
        else:
            hops.append(_skip("proxy", "proxy"))

        # 4. Certificate
        if host is None:
            hops.append(_unknown("certificate", "no proxy host, so no certificate to check."))
        elif not host.get("certificate_id"):
            hops.append(Hop(hop="certificate", status="skipped",
                            detail="the proxy host has no SSL certificate.",
                            fix="request one with proxy_certificates (action=request, domain_names=<domain>) and enable SSL on the host."))
        else:
            try:
                days, issuer = await asyncio.to_thread(cert_days_left, d)
                if days < 0:
                    hops.append(_fail("certificate", f"certificate expired {-days:.0f} days ago.",
                                      "request a new one with proxy_certificates (action=request, domain_names=<domain>), then re-check."))
                elif days < CERT_WARN_DAYS:
                    hops.append(_fail("certificate", f"certificate expires in {days:.0f} days (issuer {issuer}).",
                                      "request a new one with proxy_certificates (action=request, domain_names=<domain>) before it expires."))
                else:
                    hops.append(_ok("certificate", f"valid for {days:.0f} more days (issuer {issuer})."))
            except ssl.SSLError as e:
                hops.append(_fail("certificate", f"TLS verification failed: {e.reason or e}.",
                                  "check the certificate on the proxy host and the name it was issued for."))
            except OSError as e:
                hops.append(_unknown("certificate", f"could not open TLS to {d}:443 ({e}).",
                                     "check the DNS and proxy hops above, then re-run."))

        # 5. Upstream container
        upstream_host = (host or {}).get("forward_host") or ""
        upstream_port = int((host or {}).get("forward_port") or 0)
        on_docker_host = upstream_host.lower() in DOCKER_HOST_ALIASES
        if "docker" not in enabled:
            hops.append(_skip("container", "docker"))
        elif not upstream_host:
            hops.append(_unknown("container", "no upstream to look for: no proxy host."))
        else:
            try:
                rows = await runtime.docker().list_containers(all=True)
                match = next((c for c in rows if c.get("name") == upstream_host
                              or (upstream_port and _port_matches(c.get("ports", []), upstream_port))), None)
                if match is None and on_docker_host:
                    hops.append(Hop(hop="container", status="skipped",
                                    detail=f"the upstream is {upstream_host}, a process on the Docker host itself, "
                                           f"and no container publishes port {upstream_port}. The upstream_port hop checks it.",
                                    fix="if the service should run in a container, start it and publish the port."))
                elif match is None:
                    hops.append(_unknown("container", f"no container named {upstream_host} or publishing port "
                                                      f"{upstream_port} on this Docker host.",
                                         "if the upstream runs outside this Docker host, check it there."))
                elif match.get("status") != "running":
                    hops.append(_fail("container", f"container {match['name']} is {match.get('status')}.",
                                      f"start it with docker_containers (action=start, container={match['name']})."))
                else:
                    hops.append(_ok("container", f"container {match['name']} is running."))
            except HomelabError as e:
                hops.append(_unknown("container", str(e), "run --doctor and check the Docker socket."))

        # 6. Upstream port
        if not upstream_host or not upstream_port:
            hops.append(_unknown("upstream_port", "no upstream host and port to test."))
        elif on_docker_host and "docker" in enabled and _docker_is_local(runtime):
            # Homelab runs on the Docker host, so the address a container calls host.docker.internal is this machine.
            good, msg = await _tcp_open("127.0.0.1", upstream_port)
            where = f"{upstream_host}:{upstream_port} (checked as 127.0.0.1:{upstream_port}, this machine is the Docker host)"
            if good:
                hops.append(_ok("upstream_port", f"{where} {msg}."))
            else:
                hops.append(_fail("upstream_port", f"{where} {msg}.",
                                  f"nothing listens on port {upstream_port} on the Docker host. Start the service, "
                                  "or point the proxy host at the right port or container."))
        else:
            try:
                await asyncio.to_thread(socket.getaddrinfo, upstream_host, upstream_port)
            except OSError:
                hops.append(_unknown("upstream_port",
                                     f"{upstream_host} does not resolve from the machine running Homelab.",
                                     "run Homelab where it can reach the upstream, or check the name."))
            else:
                good, msg = await _tcp_open(upstream_host, upstream_port)
                if good:
                    hops.append(_ok("upstream_port", f"{upstream_host}:{upstream_port} {msg}."))
                else:
                    hops.append(_fail("upstream_port", f"{upstream_host}:{upstream_port} {msg}.",
                                      "check the container's port and that it listens on that port inside the container."))

        # 7. Uptime Kuma
        if "uptime" in enabled:
            try:
                from homelab_infra_mcp.modules.uptime import parse_monitor_status
                monitors = parse_monitor_status(await runtime.uptime().metrics_text())
                rel = [m for m in monitors if d in (m.url or "") or d == (m.hostname or "")]
                if not rel:
                    hops.append(_unknown("uptime", f"no Uptime Kuma monitor for {d}.",
                                         "add a monitor for it in Uptime Kuma."))
                elif any(m.status == "down" for m in rel):
                    names = ", ".join(m.name for m in rel if m.status == "down")
                    hops.append(_fail("uptime", f"Uptime Kuma reports {names} down.",
                                      "open the monitor in Uptime Kuma for the error message, then fix the upstream."))
                else:
                    hops.append(_ok("uptime", f"{len(rel)} monitor(s) for {d} are {rel[0].status}."))
            except HomelabError as e:
                hops.append(_unknown("uptime", str(e), "run --doctor and check the uptime settings."))
        else:
            hops.append(_skip("uptime", "uptime"))

        # 8. Authentik
        if "sso" in enabled:
            try:
                provs = await runtime.sso().request("GET", "/providers/proxy/", params={"page_size": 100})
                ext = [p for p in provs.get("results", []) if d in str(p.get("external_host") or "")]
                if ext:
                    hops.append(_ok("sso", f"Authentik proxy provider {ext[0].get('name')} covers {d}."))
                else:
                    hops.append(Hop(hop="sso", status="skipped",
                                    detail=f"no Authentik proxy provider for {d}. Fine if this service has no login.",
                                    fix="create one with sso_applications (action=create, host=...) to add a login."))
            except HomelabError as e:
                hops.append(_unknown("sso", str(e), "run --doctor and check the Authentik settings."))
        else:
            hops.append(_skip("sso", "sso"))

        first = next((h for h in hops if h.status == "fail"), None)
        unchecked = [h.hop for h in hops if h.status == "unknown"]
        if first is None and unchecked:
            note = (f"No hop failed, but {len(unchecked)} could not be checked ({', '.join(unchecked)}), "
                    "so this is not an all-clear. See each hop's fix.")
        elif first is None:
            note = "No failing hop found. If the service still misbehaves, check the application itself and its logs."
        return DiagnoseResult(domain=d, hops=hops, first_failure=first.hop if first else None, note=note)
