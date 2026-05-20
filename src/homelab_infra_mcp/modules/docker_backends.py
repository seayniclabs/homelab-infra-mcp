"""Docker backends — unix socket (docker-py) or Portainer REST API."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import docker as docker_sdk
import httpx

from homelab_infra_mcp.config import config


class DockerBackend(ABC):
    backend_name: str

    @abstractmethod
    def health(self) -> dict[str, Any]: ...

    @abstractmethod
    def list_containers(self, all: bool = False) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_container(self, name_or_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def start_container(self, name_or_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def stop_container(self, name_or_id: str, timeout: int = 10) -> dict[str, Any]: ...

    @abstractmethod
    def restart_container(self, name_or_id: str, timeout: int = 10) -> dict[str, Any]: ...

    @abstractmethod
    def remove_container(self, name_or_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def container_logs(self, name_or_id: str, tail: int = 50, since: str = "") -> dict[str, Any]: ...

    @abstractmethod
    def container_stats(self, name_or_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def list_images(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def pull_image(self, image: str, tag: str = "latest") -> dict[str, Any]: ...

    @abstractmethod
    def remove_image(self, image: str, force: bool = False) -> dict[str, Any]: ...

    @abstractmethod
    def list_volumes(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def list_networks(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def prune_containers(self) -> dict[str, Any]: ...

    @abstractmethod
    def prune_images(self) -> dict[str, Any]: ...


class SocketBackend(DockerBackend):
    backend_name = "socket"

    def __init__(self) -> None:
        self._client: docker_sdk.DockerClient | None = None

    def _docker(self) -> docker_sdk.DockerClient:
        if self._client is None:
            self._client = docker_sdk.DockerClient(base_url=config.docker_host)
        return self._client

    def health(self) -> dict[str, Any]:
        info = self._docker().info()
        return {
            "healthy": True,
            "backend": self.backend_name,
            "version": info.get("ServerVersion", "unknown"),
            "containers": info.get("Containers", 0),
            "containers_running": info.get("ContainersRunning", 0),
            "images": info.get("Images", 0),
        }

    def list_containers(self, all: bool = False) -> list[dict[str, Any]]:
        summary = []
        for c in self._docker().containers.list(all=all):
            try:
                tags = c.image.tags
                image_label = tags[0] if tags else c.image.short_id
            except docker_sdk.errors.ImageNotFound:
                image_sha = c.attrs.get("Image", "")
                image_label = (
                    image_sha[7:19]
                    if image_sha.startswith("sha256:")
                    else (image_sha[:12] or "unknown")
                )
            except Exception:
                image_label = "unknown"
            summary.append({
                "id": c.short_id,
                "name": c.name,
                "status": c.status,
                "image": image_label,
                "ports": c.ports,
            })
        return summary

    def get_container(self, name_or_id: str) -> dict[str, Any]:
        c = self._docker().containers.get(name_or_id)
        return {
            "id": c.id,
            "name": c.name,
            "status": c.status,
            "image": c.image.tags[0] if c.image.tags else c.image.short_id,
            "ports": c.ports,
        }

    def start_container(self, name_or_id: str) -> dict[str, Any]:
        c = self._docker().containers.get(name_or_id)
        c.start()
        return {"started": True, "name": c.name}

    def stop_container(self, name_or_id: str, timeout: int = 10) -> dict[str, Any]:
        c = self._docker().containers.get(name_or_id)
        c.stop(timeout=timeout)
        return {"stopped": True, "name": c.name}

    def restart_container(self, name_or_id: str, timeout: int = 10) -> dict[str, Any]:
        c = self._docker().containers.get(name_or_id)
        c.restart(timeout=timeout)
        return {"restarted": True, "name": c.name}

    def remove_container(self, name_or_id: str) -> dict[str, Any]:
        c = self._docker().containers.get(name_or_id)
        name = c.name
        c.remove()
        return {"removed": True, "name": name}

    def container_logs(self, name_or_id: str, tail: int = 50, since: str = "") -> dict[str, Any]:
        c = self._docker().containers.get(name_or_id)
        kwargs: dict[str, Any] = {"tail": tail, "timestamps": True}
        if since:
            kwargs["since"] = since
        logs = c.logs(**kwargs).decode("utf-8", errors="replace")
        lines = logs.strip().split("\n")
        return {"container": c.name, "lines": len(lines), "logs": lines[-tail:]}

    def container_stats(self, name_or_id: str) -> dict[str, Any]:
        c = self._docker().containers.get(name_or_id)
        stats = c.stats(stream=False)
        cpu_delta = (
            stats["cpu_stats"]["cpu_usage"]["total_usage"]
            - stats["precpu_stats"]["cpu_usage"]["total_usage"]
        )
        system_delta = (
            stats["cpu_stats"]["system_cpu_usage"]
            - stats["precpu_stats"]["system_cpu_usage"]
        )
        cpu_pct = (cpu_delta / system_delta * 100.0) if system_delta > 0 else 0.0
        mem = stats.get("memory_stats", {})
        mem_usage = mem.get("usage", 0)
        mem_limit = mem.get("limit", 1)
        mem_pct = (mem_usage / mem_limit * 100.0) if mem_limit > 0 else 0.0
        return {
            "container": c.name,
            "cpu_percent": round(cpu_pct, 2),
            "memory_usage_mb": round(mem_usage / 1024 / 1024, 1),
            "memory_limit_mb": round(mem_limit / 1024 / 1024, 1),
            "memory_percent": round(mem_pct, 2),
        }

    def list_images(self) -> list[dict[str, Any]]:
        return [
            {
                "id": i.short_id,
                "tags": i.tags,
                "size_mb": round(i.attrs.get("Size", 0) / 1024 / 1024, 1),
            }
            for i in self._docker().images.list()
        ]

    def pull_image(self, image: str, tag: str = "latest") -> dict[str, Any]:
        self._docker().images.pull(image, tag=tag)
        return {"pulled": True, "image": f"{image}:{tag}"}

    def remove_image(self, image: str, force: bool = False) -> dict[str, Any]:
        self._docker().images.remove(image, force=force)
        return {"removed": True, "image": image}

    def list_volumes(self) -> list[dict[str, Any]]:
        return [
            {"name": v.name, "driver": v.attrs.get("Driver", "")}
            for v in self._docker().volumes.list()
        ]

    def list_networks(self) -> list[dict[str, Any]]:
        return [
            {
                "id": n.short_id,
                "name": n.name,
                "driver": n.attrs.get("Driver", ""),
            }
            for n in self._docker().networks.list()
        ]

    def prune_containers(self) -> dict[str, Any]:
        result = self._docker().containers.prune()
        return {"pruned": True, "containers_deleted": result.get("ContainersDeleted", [])}

    def prune_images(self) -> dict[str, Any]:
        result = self._docker().images.prune()
        return {"pruned": True, "space_reclaimed": result.get("SpaceReclaimed", 0)}


class PortainerBackend(DockerBackend):
    backend_name = "portainer"

    def __init__(self) -> None:
        self._base = config.portainer_url
        self._headers = {"X-API-Key": config.portainer_token}
        self._endpoint = config.portainer_endpoint_id

    def _docker_path(self, suffix: str) -> str:
        return f"{self._base}/api/endpoints/{self._endpoint}/docker{suffix}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> Any:
        with httpx.Client(timeout=30, headers=self._headers) as client:
            resp = client.request(
                method,
                path,
                params=params,
                json=json_body,
            )
            resp.raise_for_status()
            if resp.content:
                return resp.json()
            return {}

    def _resolve_id(self, name_or_id: str) -> str:
        containers = self.list_containers(all=True)
        needle = name_or_id.lstrip("/")
        for c in containers:
            cid = c["id"]
            if (
                cid == needle
                or cid.startswith(needle)
                or c.get("short_id") == needle
                or c["name"] == needle
            ):
                return cid
        raise KeyError(f"Container not found: {name_or_id}")

    def health(self) -> dict[str, Any]:
        status = self._request("GET", f"{self._base}/api/status")
        return {
            "healthy": True,
            "backend": self.backend_name,
            "version": status.get("Version", "unknown"),
        }

    def list_containers(self, all: bool = False) -> list[dict[str, Any]]:
        raw = self._request(
            "GET",
            self._docker_path("/containers/json"),
            params={"all": 1 if all else 0},
        )
        return [
            {
                "id": c["Id"],
                "short_id": c["Id"][:12],
                "name": (c.get("Names") or [""])[0].lstrip("/"),
                "status": c.get("Status", ""),
                "image": c.get("Image", ""),
                "ports": c.get("Ports", []),
            }
            for c in raw
        ]

    def get_container(self, name_or_id: str) -> dict[str, Any]:
        cid = self._resolve_id(name_or_id)
        c = self._request("GET", self._docker_path(f"/containers/{cid}/json"))
        return {
            "id": c["Id"],
            "short_id": c["Id"][:12],
            "name": c["Name"].lstrip("/"),
            "status": c["State"]["Status"],
            "image": c["Config"]["Image"],
            "ports": c.get("NetworkSettings", {}).get("Ports", {}),
        }

    def start_container(self, name_or_id: str) -> dict[str, Any]:
        cid = self._resolve_id(name_or_id)
        self._request("POST", self._docker_path(f"/containers/{cid}/start"))
        return {"started": True, "id": cid}

    def stop_container(self, name_or_id: str, timeout: int = 10) -> dict[str, Any]:
        cid = self._resolve_id(name_or_id)
        self._request(
            "POST",
            self._docker_path(f"/containers/{cid}/stop"),
            params={"t": timeout},
        )
        return {"stopped": True, "id": cid}

    def restart_container(self, name_or_id: str, timeout: int = 10) -> dict[str, Any]:
        cid = self._resolve_id(name_or_id)
        self._request(
            "POST",
            self._docker_path(f"/containers/{cid}/restart"),
            params={"t": timeout},
        )
        return {"restarted": True, "id": cid}

    def remove_container(self, name_or_id: str) -> dict[str, Any]:
        cid = self._resolve_id(name_or_id)
        self._request("DELETE", self._docker_path(f"/containers/{cid}"))
        return {"removed": True, "id": cid}

    def container_logs(self, name_or_id: str, tail: int = 50, since: str = "") -> dict[str, Any]:
        cid = self._resolve_id(name_or_id)
        params: dict[str, Any] = {"tail": tail, "stdout": 1, "stderr": 1, "timestamps": 1}
        if since:
            params["since"] = since
        with httpx.Client(timeout=30, headers=self._headers) as client:
            resp = client.get(
                self._docker_path(f"/containers/{cid}/logs"),
                params=params,
            )
            resp.raise_for_status()
            text = resp.text
        lines = text.strip().split("\n") if text.strip() else []
        return {"container": name_or_id, "lines": len(lines), "logs": lines[-tail:]}

    def container_stats(self, name_or_id: str) -> dict[str, Any]:
        cid = self._resolve_id(name_or_id)
        stats = self._request(
            "GET",
            self._docker_path(f"/containers/{cid}/stats"),
            params={"stream": "false"},
        )
        return {"container": name_or_id, "stats": stats}

    def list_images(self) -> list[dict[str, Any]]:
        raw = self._request("GET", self._docker_path("/images/json"))
        return [
            {
                "id": i["Id"][:12],
                "tags": i.get("RepoTags") or [],
                "size_mb": round(i.get("Size", 0) / 1024 / 1024, 1),
            }
            for i in raw
        ]

    def pull_image(self, image: str, tag: str = "latest") -> dict[str, Any]:
        ref = f"{image}:{tag}" if ":" not in image else image
        self._request(
            "POST",
            self._docker_path("/images/create"),
            params={"fromImage": ref},
        )
        return {"pulled": True, "image": ref}

    def remove_image(self, image: str, force: bool = False) -> dict[str, Any]:
        self._request(
            "DELETE",
            self._docker_path(f"/images/{image}"),
            params={"force": 1 if force else 0},
        )
        return {"removed": True, "image": image}

    def list_volumes(self) -> list[dict[str, Any]]:
        raw = self._request("GET", self._docker_path("/volumes"))
        return [
            {"name": v["Name"], "driver": v.get("Driver", "")}
            for v in raw.get("Volumes", [])
        ]

    def list_networks(self) -> list[dict[str, Any]]:
        raw = self._request("GET", self._docker_path("/networks"))
        return [
            {"id": n["Id"][:12], "name": n["Name"], "driver": n.get("Driver", "")}
            for n in raw
        ]

    def prune_containers(self) -> dict[str, Any]:
        result = self._request("POST", self._docker_path("/containers/prune"))
        return {"pruned": True, **result}

    def prune_images(self) -> dict[str, Any]:
        result = self._request("POST", self._docker_path("/images/prune"))
        return {"pruned": True, **result}

    def list_stacks(self) -> list[dict[str, Any]]:
        raw = self._request("GET", f"{self._base}/api/stacks")
        return [
            {
                "id": s.get("Id"),
                "name": s.get("Name"),
                "status": s.get("Status"),
                "type": s.get("Type"),
            }
            for s in raw
        ]

    def get_stack(self, stack_id: int) -> dict[str, Any]:
        stack = self._request("GET", f"{self._base}/api/stacks/{stack_id}")
        file = self._request("GET", f"{self._base}/api/stacks/{stack_id}/file")
        return {"stack": stack, "compose_file": file}


_backend: DockerBackend | None = None


def get_backend() -> DockerBackend:
    global _backend
    if _backend is None:
        if config.docker_backend == "portainer":
            _backend = PortainerBackend()
        else:
            _backend = SocketBackend()
    return _backend
