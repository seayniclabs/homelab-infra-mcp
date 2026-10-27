"""Module contract and registry.

A module is one integration (proxy, docker, dns, home_assistant). It declares its settings and
registers its tools on the shared server. Adding a module means adding a file here and listing it
in ``all_modules()``. New modules must set ``default_enabled = False`` so an update never turns on
something the user did not choose.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mcp.server.fastmcp import FastMCP

from homelab_infra_mcp.config import Config, env_name
from homelab_infra_mcp.errors import not_configured
from homelab_infra_mcp.runtime import Runtime


@dataclass(frozen=True)
class Setting:
    key: str
    help: str
    secret: bool = False
    required: bool = True

    def env_var(self, module: str) -> str:
        return env_name(module, self.key)


@dataclass
class Module:
    name: str
    summary: str
    settings: list[Setting]
    default_enabled: bool = True
    tools: dict[str, str] = field(default_factory=dict)  # tool name -> one-line purpose

    def missing(self, config: Config) -> list[str]:
        return [s.env_var(self.name) for s in self.settings
                if s.required and not config.get(self.name, s.key)]

    def require(self, config: Config, *keys: str) -> dict[str, str]:
        values = {k: config.get(self.name, k) for k in keys}
        absent = [s.env_var(self.name) for s in self.settings if s.key in keys and not values[s.key]]
        if absent:
            raise not_configured(self.name, absent)
        return values  # type: ignore[return-value]

    def register(self, mcp: FastMCP, runtime: Runtime) -> None:
        raise NotImplementedError


def all_modules() -> list[Module]:
    from homelab_infra_mcp.modules.dns import DnsModule
    from homelab_infra_mcp.modules.docker import DockerModule
    from homelab_infra_mcp.modules.home_assistant import HomeAssistantModule
    from homelab_infra_mcp.modules.proxy import ProxyModule

    return [ProxyModule(), DockerModule(), DnsModule(), HomeAssistantModule()]


ALLOW_WRITES = Setting(
    "allow_writes",
    "true: changes run without asking the person. false (default): each change needs the person's "
    "approval through the MCP client. Read-only tools never need approval.",
    required=False,
)
