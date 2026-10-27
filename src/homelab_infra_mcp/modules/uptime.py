"""Uptime Kuma module (opt-in, off by default): monitor list, status and details. Read-only.

Source checked 2026-10-27 against louislam/uptime-kuma (master):
- ``server/server.js``: ``GET /metrics`` is served only when the Prometheus API is enabled in
  Uptime Kuma's settings; otherwise it answers 404.
- ``server/auth.js`` (``apiAuth``): ``/metrics`` uses HTTP Basic auth; with API keys enabled the
  password is the API key and the username is ignored.
- ``server/prometheus.js``: gauge ``monitor_status`` with labels ``monitor_id``, ``monitor_name``,
  ``monitor_type``, ``monitor_url``, ``monitor_hostname``; value 1 = up, 0 = down, 2 = pending,
  3 = maintenance.

Pause and resume are NOT implemented in 2.1. Uptime Kuma 2.x signs the socket in through a
better-auth session (``src/auth-client.ts``, ``src/components/Login.vue``), and there is no
REST endpoint for pausing. A Socket.IO client would add a dependency and could not be checked
against a live server here, so the tools below only read.
"""

from __future__ import annotations

import re
from typing import Any, Literal

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from homelab_infra_mcp.config import Config
from homelab_infra_mcp.errors import HomelabError
from homelab_infra_mcp.modules import ALLOW_WRITES, Module, Setting
from homelab_infra_mcp.models import page
from homelab_infra_mcp.runtime import HttpFactory, Runtime

MODULE = "uptime"
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
STATUS_NAMES = {0: "down", 1: "up", 2: "pending", 3: "maintenance"}
_LABEL_RE = re.compile(r'(\w+)="((?:[^"\\]|\\.)*)"')
_SAMPLE_RE = re.compile(r"^monitor_status\{(.*)\}\s+(\S+)\s*$")


class UptimeClient:
    def __init__(self, config: Config, http: HttpFactory):
        self.config = config
        self.http = http

    def base(self) -> str:
        return self.config.require(MODULE, "url")["url"].rstrip("/")

    async def metrics_text(self) -> str:
        key = self.config.require(MODULE, "api_key")["api_key"]
        try:
            async with self.http() as client:
                r = await client.get(f"{self.base()}/metrics", auth=httpx.BasicAuth("", key))
        except httpx.HTTPError as e:
            raise HomelabError(MODULE, "unreachable", f"could not reach Uptime Kuma ({type(e).__name__}).",
                               "check HOMELAB_UPTIME_URL and that Uptime Kuma is running.")
        if r.status_code in (401, 403):
            raise HomelabError(MODULE, "auth_failed", f"Uptime Kuma returned {r.status_code} for /metrics.",
                               "check HOMELAB_UPTIME_API_KEY (an API key from Settings > API Keys).")
        if r.status_code == 404:
            raise HomelabError(MODULE, "metrics_off", "Uptime Kuma has no /metrics endpoint.",
                               "turn on the Prometheus API in Uptime Kuma's settings (Settings > General).")
        if r.status_code >= 400:
            raise HomelabError(MODULE, "api_error", f"Uptime Kuma returned {r.status_code} for /metrics.")
        return r.text


class Monitor(BaseModel):
    id: str
    name: str
    type: str | None = None
    url: str | None = None
    hostname: str | None = None
    status: str  # up | down | pending | maintenance | unknown


class MonitorsResult(BaseModel):
    items: list[Monitor] = []
    total: int | None = None
    has_more: bool = False
    detail: dict[str, Any] | None = None


def parse_monitor_status(text: str) -> list[Monitor]:
    """Read the ``monitor_status`` samples from Prometheus text format."""
    out: list[Monitor] = []
    for line in text.splitlines():
        m = _SAMPLE_RE.match(line.strip())
        if not m:
            continue
        labels = {k: v.replace('\\"', '"').replace("\\\\", "\\") for k, v in _LABEL_RE.findall(m.group(1))}
        try:
            status = STATUS_NAMES.get(int(float(m.group(2))), "unknown")
        except ValueError:
            status = "unknown"
        out.append(Monitor(id=labels.get("monitor_id", ""), name=labels.get("monitor_name", ""),
                           type=labels.get("monitor_type") or None, url=labels.get("monitor_url") or None,
                           hostname=labels.get("monitor_hostname") or None, status=status))
    return out


class UptimeModule(Module):
    def __init__(self) -> None:
        super().__init__(
            name=MODULE,
            summary="Uptime Kuma: monitor list, status and details, read through /metrics. Off by default.",
            default_enabled=False,
            settings=[
                Setting("url", "Base URL of Uptime Kuma, e.g. http://uptime-kuma:3001."),
                Setting("api_key", "Uptime Kuma API key. Also turn on the Prometheus API in its settings.",
                        secret=True),
                ALLOW_WRITES,
            ],
            tools={
                "uptime_monitors": "List monitors with their status, or get one monitor by id. Read-only.",
            },
        )

    def register(self, mcp: FastMCP, runtime: Runtime) -> None:
        @mcp.tool(annotations=READ_ONLY)
        async def uptime_monitors(
            action: Literal["list", "get"] = "list",
            monitor_id: str = "",
            status: Literal["", "up", "down", "pending", "maintenance", "unknown"] = "",
            limit: int = 20,
            offset: int = 0,
        ) -> MonitorsResult:
            """Uptime Kuma monitors. list returns monitors with status (filter with status=down to see what is
            failing). get returns one monitor by monitor_id, with its full metric labels. Read-only: pausing and
            resuming monitors is not available in 2.1."""
            client = runtime.uptime()
            monitors = parse_monitor_status(await client.metrics_text())
            if action == "get":
                if not monitor_id:
                    raise HomelabError(MODULE, "bad_input", "get needs monitor_id.", "use action=list to find ids.")
                found = next((m for m in monitors if m.id == monitor_id), None)
                if found is None:
                    raise HomelabError(MODULE, "not_found", f"no monitor with id {monitor_id}.",
                                       "use action=list to see the ids.")
                return MonitorsResult(items=[found], total=1, detail=found.model_dump())
            if status:
                monitors = [m for m in monitors if m.status == status]
            items, total, more = page(monitors, limit, offset)
            return MonitorsResult(items=items, total=total, has_more=more)
