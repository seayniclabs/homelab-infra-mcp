"""Shared runtime: one config, one HTTP client factory, and lazily built module clients."""

from __future__ import annotations

from typing import Any, Callable

import httpx

from homelab_infra_mcp.config import Config

HttpFactory = Callable[[], httpx.AsyncClient]
DockerFactory = Callable[[str], Any]


def default_http() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=15.0)


def default_docker(host: str) -> Any:
    import docker

    return docker.DockerClient(base_url=host)


class Runtime:
    def __init__(self, config: Config, http: HttpFactory = default_http,
                 docker: DockerFactory = default_docker):
        self.config = config
        self.http = http
        self.docker_factory = docker
        self._clients: dict[str, Any] = {}

    def client(self, name: str, build: Callable[[], Any]) -> Any:
        if name not in self._clients:
            self._clients[name] = build()
        return self._clients[name]

    def npm(self):
        from homelab_infra_mcp.modules.proxy import NpmClient

        return self.client("npm", lambda: NpmClient(self.config, self.http))

    def cloudflare(self):
        from homelab_infra_mcp.modules.dns import CloudflareClient

        return self.client("cloudflare", lambda: CloudflareClient(self.config, self.http))

    def docker(self):
        from homelab_infra_mcp.modules.docker_backends import build_backend

        return self.client("docker", lambda: build_backend(self.config, self.http, self.docker_factory))

    def home_assistant(self):
        from homelab_infra_mcp.modules.home_assistant import HomeAssistantClient

        return self.client("home_assistant", lambda: HomeAssistantClient(self.config, self.http))
