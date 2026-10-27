"""Docker backends: the local socket (docker-py) or the Portainer REST API.

Both expose the same async methods and return plain dicts and lists, so the tools never
care which one is in use. The Docker SDK client is built by an injected factory, which is
how the tests run without a Docker engine.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

import docker as docker_sdk
import httpx

from homelab_infra_mcp.config import Config
from homelab_infra_mcp.errors import HomelabError
from homelab_infra_mcp.runtime import HttpFactory

MODULE = "docker"
DEFAULT_HOST = "unix:///var/run/docker.sock"


def stats_from_raw(raw: dict[str, Any]) -> dict[str, Any]:
    cpu = raw.get("cpu_stats", {})
    pre = raw.get("precpu_stats", {})
    cpu_delta = cpu.get("cpu_usage", {}).get("total_usage", 0) - pre.get("cpu_usage", {}).get("total_usage", 0)
    system_delta = cpu.get("system_cpu_usage", 0) - pre.get("system_cpu_usage", 0)
    cpu_pct = (cpu_delta / system_delta * 100.0) if system_delta > 0 else 0.0
    mem = raw.get("memory_stats", {})
    usage = mem.get("usage", 0)
    limit = mem.get("limit", 1) or 1
    return {
        "cpu_percent": round(cpu_pct, 2),
        "memory_usage_mb": round(usage / 1024 / 1024, 1),
        "memory_limit_mb": round(limit / 1024 / 1024, 1),
        "memory_percent": round(usage / limit * 100.0, 2),
    }


class SocketBackend:
    name = "socket"

    def __init__(self, host: str, factory: Callable[[str], Any]):
        self.host = host
        self.factory = factory
        self._dc: Any = None

    def _client(self) -> Any:
        if self._dc is None:
            self._dc = self.factory(self.host)
        return self._dc

    async def _run(self, fn: Callable[[], Any]) -> Any:
        try:
            return await asyncio.to_thread(fn)
        except docker_sdk.errors.NotFound as e:
            raise HomelabError(MODULE, "not_found", str(e.explanation or e),
                               "call docker_containers with action=list to see names and ids.")
        except docker_sdk.errors.APIError as e:
            raise HomelabError(MODULE, "api_error", f"Docker API error: {e.explanation or e}")
        except docker_sdk.errors.DockerException as e:
            raise HomelabError(MODULE, "unreachable", f"Docker is not reachable ({type(e).__name__}).",
                               f"check HOMELAB_DOCKER_HOST ({self.host}) and that the socket is mounted.")
        except OSError as e:
            raise HomelabError(MODULE, "unreachable", f"Docker socket error: {e}",
                               f"check HOMELAB_DOCKER_HOST ({self.host}).")

    @staticmethod
    def _ports(ports: dict | None) -> list[str]:
        out = []
        for private, bindings in (ports or {}).items():
            if bindings:
                out += [f"{b.get('HostPort')}->{private}" for b in bindings]
            else:
                out.append(private)
        return out

    def _summary(self, c: Any) -> dict[str, Any]:
        try:
            tags = c.image.tags
            image = tags[0] if tags else c.image.short_id
        except Exception:
            image = "unknown"
        return {"id": c.short_id, "name": c.name, "status": c.status, "image": image,
                "ports": self._ports(c.ports)}

    async def health(self) -> dict[str, Any]:
        info = await self._run(lambda: self._client().info())
        return {"backend": self.name, "version": info.get("ServerVersion", "unknown"),
                "containers": info.get("Containers", 0), "containers_running": info.get("ContainersRunning", 0),
                "images": info.get("Images", 0)}

    async def list_containers(self, all: bool) -> list[dict[str, Any]]:
        return await self._run(lambda: [self._summary(c) for c in self._client().containers.list(all=all)])

    async def get_container(self, ref: str) -> dict[str, Any]:
        def go():
            c = self._client().containers.get(ref)
            return dict(self._summary(c), id=c.id, attrs=c.attrs)
        return await self._run(go)

    async def action(self, ref: str, verb: str, timeout: int = 10) -> dict[str, Any]:
        def go():
            c = self._client().containers.get(ref)
            if verb == "start":
                c.start()
            elif verb == "stop":
                c.stop(timeout=timeout)
            elif verb == "restart":
                c.restart(timeout=timeout)
            elif verb == "remove":
                c.remove()
            return {"name": c.name, "id": c.short_id}
        return await self._run(go)

    async def logs(self, ref: str, tail: int, since: str) -> dict[str, Any]:
        def go():
            c = self._client().containers.get(ref)
            kwargs: dict[str, Any] = {"tail": tail, "timestamps": True}
            if since:
                kwargs["since"] = since
            text = c.logs(**kwargs).decode("utf-8", errors="replace")
            return {"name": c.name, "lines": text.strip().split("\n") if text.strip() else []}
        return await self._run(go)

    async def stats(self, ref: str) -> dict[str, Any]:
        def go():
            c = self._client().containers.get(ref)
            return {"name": c.name, **stats_from_raw(c.stats(stream=False))}
        return await self._run(go)

    async def list_images(self) -> list[dict[str, Any]]:
        def go():
            return [{"id": i.short_id, "tags": list(i.tags or []),
                     "size_mb": round(i.attrs.get("Size", 0) / 1024 / 1024, 1)}
                    for i in self._client().images.list()]
        return await self._run(go)

    async def pull(self, image: str, tag: str) -> dict[str, Any]:
        await self._run(lambda: self._client().images.pull(image, tag=tag))
        return {"image": f"{image}:{tag}"}

    async def remove_image(self, image: str, force: bool) -> dict[str, Any]:
        await self._run(lambda: self._client().images.remove(image, force=force))
        return {"image": image}

    async def list_volumes(self) -> list[dict[str, Any]]:
        return await self._run(lambda: [{"name": v.name, "driver": v.attrs.get("Driver", "")}
                                        for v in self._client().volumes.list()])

    async def list_networks(self) -> list[dict[str, Any]]:
        return await self._run(lambda: [{"id": n.short_id, "name": n.name, "driver": n.attrs.get("Driver", "")}
                                        for n in self._client().networks.list()])

    async def prune_containers(self) -> dict[str, Any]:
        result = await self._run(lambda: self._client().containers.prune())
        return {"deleted": result.get("ContainersDeleted") or []}

    async def prune_images(self) -> dict[str, Any]:
        result = await self._run(lambda: self._client().images.prune())
        return {"space_reclaimed": result.get("SpaceReclaimed", 0)}

    async def list_stacks(self) -> list[dict[str, Any]]:
        raise HomelabError(MODULE, "unsupported", "stacks need the Portainer backend.",
                           "set HOMELAB_DOCKER_PORTAINER_URL and HOMELAB_DOCKER_PORTAINER_TOKEN.")

    get_stack = list_stacks


class PortainerBackend:
    name = "portainer"

    def __init__(self, config: Config, http: HttpFactory):
        self.base = config.require(MODULE, "portainer_url")["portainer_url"].rstrip("/")
        self.token = config.require(MODULE, "portainer_token")["portainer_token"]
        self.endpoint = config.get(MODULE, "portainer_endpoint_id", "1")
        self.http = http

    def _docker_path(self, suffix: str) -> str:
        return f"{self.base}/api/endpoints/{self.endpoint}/docker{suffix}"

    async def _request(self, method: str, url: str, *, params: dict | None = None,
                       json_body: dict | None = None) -> Any:
        try:
            async with self.http() as client:
                r = await client.request(method, url, params=params, json=json_body,
                                         headers={"X-API-Key": self.token})
        except httpx.HTTPError as e:
            raise HomelabError(MODULE, "unreachable", f"could not reach Portainer ({type(e).__name__}).",
                               "check HOMELAB_DOCKER_PORTAINER_URL.")
        if r.status_code in (401, 403):
            raise HomelabError(MODULE, "auth_failed", f"Portainer returned {r.status_code}.",
                               "check HOMELAB_DOCKER_PORTAINER_TOKEN.")
        if r.status_code == 404:
            raise HomelabError(MODULE, "not_found", f"Portainer returned 404 for {url.rsplit('/api/', 1)[-1]}.",
                               "check the container, image or stack id.")
        if r.status_code >= 400:
            raise HomelabError(MODULE, "api_error", f"Portainer returned {r.status_code}.")
        return r.json() if r.content else {}

    async def _resolve(self, ref: str) -> str:
        needle = ref.lstrip("/")
        for c in await self.list_containers(all=True):
            if c["id"] == needle or c["id"].startswith(needle) or c["name"] == needle:
                return c["id"]
        raise HomelabError(MODULE, "not_found", f"no container matches {ref!r}.",
                           "call docker_containers with action=list to see names and ids.")

    @staticmethod
    def _ports(ports: list | None) -> list[str]:
        out = []
        for p in ports or []:
            if p.get("PublicPort"):
                out.append(f"{p['PublicPort']}->{p.get('PrivatePort')}/{p.get('Type', 'tcp')}")
            else:
                out.append(f"{p.get('PrivatePort')}/{p.get('Type', 'tcp')}")
        return out

    async def health(self) -> dict[str, Any]:
        status = await self._request("GET", f"{self.base}/api/status")
        return {"backend": self.name, "version": status.get("Version", "unknown")}

    async def list_containers(self, all: bool) -> list[dict[str, Any]]:
        raw = await self._request("GET", self._docker_path("/containers/json"), params={"all": 1 if all else 0})
        return [{"id": c["Id"][:12], "name": (c.get("Names") or [""])[0].lstrip("/"),
                 "status": c.get("State") or c.get("Status", ""), "image": c.get("Image", ""),
                 "ports": self._ports(c.get("Ports"))} for c in raw]

    async def get_container(self, ref: str) -> dict[str, Any]:
        cid = await self._resolve(ref)
        c = await self._request("GET", self._docker_path(f"/containers/{cid}/json"))
        return {"id": c["Id"][:12], "name": c["Name"].lstrip("/"), "status": c["State"]["Status"],
                "image": c["Config"]["Image"], "ports": [], "attrs": c}

    async def action(self, ref: str, verb: str, timeout: int = 10) -> dict[str, Any]:
        cid = await self._resolve(ref)
        if verb == "remove":
            await self._request("DELETE", self._docker_path(f"/containers/{cid}"))
        else:
            params = {"t": timeout} if verb in ("stop", "restart") else None
            await self._request("POST", self._docker_path(f"/containers/{cid}/{verb}"), params=params)
        return {"name": ref.lstrip("/"), "id": cid[:12]}

    async def logs(self, ref: str, tail: int, since: str) -> dict[str, Any]:
        cid = await self._resolve(ref)
        params: dict[str, Any] = {"tail": tail, "stdout": 1, "stderr": 1, "timestamps": 1}
        if since:
            params["since"] = since
        try:
            async with self.http() as client:
                r = await client.get(self._docker_path(f"/containers/{cid}/logs"), params=params,
                                     headers={"X-API-Key": self.token})
        except httpx.HTTPError as e:
            raise HomelabError(MODULE, "unreachable", f"could not reach Portainer ({type(e).__name__}).")
        text = r.text.strip()
        return {"name": ref, "lines": text.split("\n") if text else []}

    async def stats(self, ref: str) -> dict[str, Any]:
        cid = await self._resolve(ref)
        raw = await self._request("GET", self._docker_path(f"/containers/{cid}/stats"), params={"stream": "false"})
        return {"name": ref, **stats_from_raw(raw)}

    async def list_images(self) -> list[dict[str, Any]]:
        raw = await self._request("GET", self._docker_path("/images/json"))
        return [{"id": i["Id"][:12], "tags": i.get("RepoTags") or [],
                 "size_mb": round(i.get("Size", 0) / 1024 / 1024, 1)} for i in raw]

    async def pull(self, image: str, tag: str) -> dict[str, Any]:
        ref = f"{image}:{tag}" if ":" not in image else image
        await self._request("POST", self._docker_path("/images/create"), params={"fromImage": ref})
        return {"image": ref}

    async def remove_image(self, image: str, force: bool) -> dict[str, Any]:
        await self._request("DELETE", self._docker_path(f"/images/{image}"), params={"force": 1 if force else 0})
        return {"image": image}

    async def list_volumes(self) -> list[dict[str, Any]]:
        raw = await self._request("GET", self._docker_path("/volumes"))
        return [{"name": v["Name"], "driver": v.get("Driver", "")} for v in raw.get("Volumes") or []]

    async def list_networks(self) -> list[dict[str, Any]]:
        raw = await self._request("GET", self._docker_path("/networks"))
        return [{"id": n["Id"][:12], "name": n["Name"], "driver": n.get("Driver", "")} for n in raw]

    async def prune_containers(self) -> dict[str, Any]:
        result = await self._request("POST", self._docker_path("/containers/prune"))
        return {"deleted": result.get("ContainersDeleted") or []}

    async def prune_images(self) -> dict[str, Any]:
        result = await self._request("POST", self._docker_path("/images/prune"))
        return {"space_reclaimed": result.get("SpaceReclaimed", 0)}

    async def list_stacks(self) -> list[dict[str, Any]]:
        raw = await self._request("GET", f"{self.base}/api/stacks")
        return [{"id": str(s.get("Id")), "name": s.get("Name"), "status": str(s.get("Status")),
                 "type": str(s.get("Type"))} for s in raw]

    async def get_stack(self, stack_id: int) -> dict[str, Any]:
        stack = await self._request("GET", f"{self.base}/api/stacks/{stack_id}")
        file = await self._request("GET", f"{self.base}/api/stacks/{stack_id}/file")
        return {"stack": stack, "compose_file": file.get("StackFileContent")}


def build_backend(config: Config, http: HttpFactory, docker_factory: Callable[[str], Any]):
    if config.get(MODULE, "portainer_url") and config.get(MODULE, "portainer_token"):
        return PortainerBackend(config, http)
    return SocketBackend(config.get(MODULE, "host") or DEFAULT_HOST, docker_factory)
