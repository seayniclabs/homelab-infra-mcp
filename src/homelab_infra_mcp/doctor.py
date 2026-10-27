"""``homelab-infra --doctor``: check settings and reachability, print a fix for each problem.

For each enabled module it checks that the required settings are set, then makes one read-only
request to the service (Nginx Proxy Manager's API root, Cloudflare's token verify, the Docker
engine info, Uptime Kuma's /metrics, AdGuard Home's /control/status, Authentik's /users/me, Home
Assistant's /api/). It also checks the Docker socket, the TLS check (Python's ssl module, always
present) and where the approval log is written. It changes nothing. Prints ``ok`` or ``FIX`` per
line; exit status 0 = ready, 1 = something to fix.
"""

from __future__ import annotations

import asyncio
import os
import ssl
import sys
from pathlib import Path

import httpx

from . import __version__
from .approval import log_path
from .config import Config, config_path
from .modules import all_modules

CF_API = "https://api.cloudflare.com/client/v4"
DEFAULT_DOCKER = "unix:///var/run/docker.sock"


async def _get(client: httpx.AsyncClient, url: str, **kw) -> httpx.Response:
    return await client.get(url, **kw)


async def _probe(name: str, config: Config, client: httpx.AsyncClient) -> tuple[bool, str]:
    g = config.get
    try:
        if name == "proxy":
            url = (g("proxy", "url") or "http://localhost:81").rstrip("/")
            r = await _get(client, f"{url}/api/")
            return (r.status_code == 200, f"{url} answered {r.status_code}"
                    + ("" if r.status_code == 200 else ". Check HOMELAB_PROXY_URL."))
        if name == "docker":
            host = g("docker", "host") or DEFAULT_DOCKER
            if g("docker", "portainer_url"):
                url = g("docker", "portainer_url").rstrip("/")
                r = await _get(client, f"{url}/api/system/status",
                               headers={"X-API-Key": g("docker", "portainer_token") or ""})
                return (r.status_code == 200, f"Portainer answered {r.status_code}"
                        + ("" if r.status_code == 200 else ". Check HOMELAB_DOCKER_PORTAINER_TOKEN."))
            if host.startswith("unix://"):
                path = Path(host[len("unix://"):])
                if not path.exists():
                    return False, (f"Docker socket {path} not found. Mount it into the container, or set "
                                   "HOMELAB_DOCKER_HOST, or use Portainer.")
                if not os.access(path, os.R_OK | os.W_OK):
                    return False, (f"no read/write access to {path}. Add your user to the docker group, or "
                                   "mount the socket read-only if you only read containers.")
            return True, f"Docker socket {host} found"
        if name == "dns":
            r = await _get(client, f"{CF_API}/user/tokens/verify",
                           headers={"Authorization": f"Bearer {g('dns', 'api_token')}"})
            status = (r.json().get("result") or {}).get("status") if r.status_code == 200 else None
            if status == "active":
                return True, "Cloudflare token is active"
            return False, "Cloudflare did not accept HOMELAB_DNS_API_TOKEN. Create a token with DNS edit rights."
        if name == "home_assistant":
            url = (g("home_assistant", "url") or "http://homeassistant.local:8123").rstrip("/")
            r = await _get(client, f"{url}/api/", headers={"Authorization": f"Bearer {g('home_assistant', 'token')}"})
            return (r.status_code == 200, f"{url} answered {r.status_code}"
                    + ("" if r.status_code == 200 else ". Check the URL and HOMELAB_HOME_ASSISTANT_TOKEN."))
        if name == "uptime":
            url = g("uptime", "url").rstrip("/")
            r = await _get(client, f"{url}/metrics", auth=httpx.BasicAuth("", g("uptime", "api_key")))
            if r.status_code == 404:
                return False, "Uptime Kuma has no /metrics. Turn on the Prometheus API in its settings."
            if r.status_code in (401, 403):
                return False, "Uptime Kuma rejected HOMELAB_UPTIME_API_KEY."
            return (r.status_code == 200, f"{url}/metrics answered {r.status_code}")
        if name == "tunnel":
            r = await _get(client, f"{CF_API}/user/tokens/verify",
                           headers={"Authorization": f"Bearer {g('tunnel', 'api_token')}"})
            status = (r.json().get("result") or {}).get("status") if r.status_code == 200 else None
            if status != "active":
                return False, "Cloudflare did not accept HOMELAB_TUNNEL_API_TOKEN. Give it Cloudflare Tunnel: Edit."
            acct = g("tunnel", "account_id")
            r = await _get(client, f"{CF_API}/accounts/{acct}/cfd_tunnel",
                           headers={"Authorization": f"Bearer {g('tunnel', 'api_token')}"})
            return (r.status_code == 200, f"tunnel API answered {r.status_code} for account {acct}"
                    + ("" if r.status_code == 200 else ". Check HOMELAB_TUNNEL_ACCOUNT_ID."))
        if name == "dns_filter":
            url = g("dns_filter", "url").rstrip("/")
            r = await _get(client, f"{url}/control/status",
                           auth=httpx.BasicAuth(g("dns_filter", "username"), g("dns_filter", "password")))
            return (r.status_code == 200, f"{url} answered {r.status_code}"
                    + ("" if r.status_code == 200 else ". Check the URL and the AdGuard Home user and password."))
        if name == "sso":
            url = g("sso", "url").rstrip("/")
            r = await _get(client, f"{url}/api/v3/core/users/me/",
                           headers={"Authorization": f"Bearer {g('sso', 'token')}"})
            return (r.status_code == 200, f"Authentik answered {r.status_code}"
                    + ("" if r.status_code == 200 else ". Check HOMELAB_SSO_URL and HOMELAB_SSO_TOKEN."))
    except httpx.HTTPError as e:
        return False, f"could not connect ({type(e).__name__}). Check the address and your network."
    return True, "reachable"


async def _checks(config: Config) -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []
    path = config_path(config.env)
    out.append(("config file", True, f"{path} ({'found' if path.is_file() else 'not used'})"))
    async with httpx.AsyncClient(timeout=8.0) as client:
        for m in all_modules():
            if not config.enabled(m.name, m.default_enabled):
                out.append((m.name, True, "switched off"))
                continue
            missing = m.missing(config)
            if missing:
                out.append((m.name, False, f"missing {', '.join(missing)}. Add them to your MCP app's env or to {path}."))
                continue
            ok, msg = await _probe(m.name, config, client)
            out.append((m.name, ok, msg))
    out.append(("tls check", True, f"Python ssl {ssl.OPENSSL_VERSION} (used by diagnose_service)"))
    out.append(("approval log", True, str(log_path(config.env))))
    return out


def run(config: Config | None = None) -> int:
    config = config or Config()
    results = asyncio.run(_checks(config))
    print(f"homelab-infra {__version__} doctor")
    for name, ok, msg in results:
        print(f"  {'ok ' if ok else 'FIX'}  {name:<13} {msg}")
    bad = sum(1 for _, ok, _ in results if not ok)
    print("ready" if not bad else f"{bad} thing(s) to fix")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(run())
