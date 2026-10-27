"""Docker module: containers, images and read-only inventory (volumes, networks, Portainer stacks)."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from homelab_infra_mcp import validation
from homelab_infra_mcp.config import Config
from homelab_infra_mcp.errors import HomelabError
from homelab_infra_mcp.models import Change, page, run_change
from homelab_infra_mcp.modules import ALLOW_WRITES, Module, Setting
from homelab_infra_mcp.modules.docker_backends import DEFAULT_HOST
from homelab_infra_mcp.runtime import Runtime

MODULE = "docker"
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)


class ContainerItem(BaseModel):
    id: str
    name: str
    status: str | None = None
    image: str | None = None
    ports: list[str] = []


class ContainerStats(BaseModel):
    name: str
    cpu_percent: float
    memory_usage_mb: float
    memory_limit_mb: float
    memory_percent: float


class ContainersResult(BaseModel):
    items: list[ContainerItem] = []
    detail: dict[str, Any] | None = None  # get: the full inspect record
    logs: list[str] | None = None
    stats: ContainerStats | None = None
    total: int | None = None
    has_more: bool = False
    change: Change | None = None


class ImageItem(BaseModel):
    id: str
    tags: list[str] = []
    size_mb: float | None = None


class ImagesResult(BaseModel):
    items: list[ImageItem] = []
    total: int | None = None
    has_more: bool = False
    change: Change | None = None


class InventoryItem(BaseModel):
    id: str | None = None
    name: str
    driver: str | None = None
    status: str | None = None
    type: str | None = None


class InventoryResult(BaseModel):
    kind: str
    backend: str
    items: list[InventoryItem] = []
    compose_file: str | None = None  # stacks with stack_id: the compose file
    total: int | None = None
    has_more: bool = False


class DockerModule(Module):
    def __init__(self) -> None:
        super().__init__(
            name=MODULE,
            summary="Docker containers and images through the local socket, or through Portainer.",
            settings=[
                Setting("host", f"Docker engine address. Default {DEFAULT_HOST}. Mount the socket into a container "
                        "that runs this server.", required=False),
                Setting("portainer_url", "Use Portainer instead of the socket: its base URL. Needs the token too.",
                        required=False),
                Setting("portainer_token", "Portainer API key (access token).", secret=True, required=False),
                Setting("portainer_endpoint_id", "Portainer endpoint id. Default 1.", required=False),
                ALLOW_WRITES,
            ],
            tools={
                "docker_containers": "List, inspect, start, stop, restart, remove, read logs or stats; prune stopped containers.",
                "docker_images": "List, pull, remove or prune images.",
                "docker_inventory": "List volumes, networks or Portainer stacks; a stack's compose file.",
            },
        )

    def missing(self, config: Config) -> list[str]:
        if config.get(MODULE, "portainer_url") and not config.get(MODULE, "portainer_token"):
            return ["HOMELAB_DOCKER_PORTAINER_TOKEN"]
        return []

    def register(self, mcp: FastMCP, runtime: Runtime) -> None:
        config = runtime.config

        @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False))
        async def docker_containers(
            ctx: Context,
            action: Literal["list", "get", "start", "stop", "restart", "remove", "logs", "stats", "prune"] = "list",
            container: str = "",
            all: bool = False,
            timeout: int = 10,
            tail: int = 50,
            since: str = "",
            limit: int = 20,
            offset: int = 0,
            dry_run: bool = False,
        ) -> ContainersResult:
            """Containers. list, get, logs and stats are read-only. start, stop, restart, remove and prune
            change state and need the person's approval (or HOMELAB_DOCKER_ALLOW_WRITES=true).
            remove deletes a container permanently. prune removes ALL stopped containers.
            container is a name or id (not needed for list or prune)."""
            backend = runtime.docker()
            if action in ("list",):
                rows = await backend.list_containers(all=all)
                items, total, more = page([ContainerItem(**r) for r in rows], limit, offset)
                return ContainersResult(items=items, total=total, has_more=more)
            if action == "prune":
                summary = "PERMANENTLY remove ALL stopped containers."

                async def perform():
                    res = await backend.prune_containers()
                    return None, res

                change = await run_change(ctx, config, module=MODULE, action=action, summary=summary,
                                          perform=perform, dry_run=dry_run, preview={"would_prune": "stopped containers"})
                return ContainersResult(change=change)
            if not container:
                raise HomelabError(MODULE, "bad_input", f"container is required for {action}.",
                                   "pass a container name or id.")
            ref = validation.container(container, MODULE)
            if action == "get":
                raw = await backend.get_container(ref)
                item = ContainerItem(**{k: raw[k] for k in ("id", "name", "status", "image", "ports")})
                return ContainersResult(items=[item], detail=raw.get("attrs") or raw)
            if action == "logs":
                res = await backend.logs(ref, tail=max(1, min(tail, 1000)), since=since)
                return ContainersResult(logs=res["lines"][-tail:])
            if action == "stats":
                return ContainersResult(stats=ContainerStats(**await backend.stats(ref)))
            verbs = {"start": f"start container {ref}",
                     "stop": f"stop container {ref} (timeout {timeout}s)",
                     "restart": f"restart container {ref} (timeout {timeout}s)",
                     "remove": f"PERMANENTLY remove container {ref}"}
            summary = verbs[action]

            async def perform():
                res = await backend.action(ref, action, timeout=timeout)
                return res.get("id"), res

            change = await run_change(ctx, config, module=MODULE, action=action, summary=summary,
                                      perform=perform, dry_run=dry_run, preview={"container": ref})
            return ContainersResult(change=change)

        @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False))
        async def docker_images(
            ctx: Context,
            action: Literal["list", "pull", "remove", "prune"] = "list",
            image: str = "",
            tag: str = "latest",
            force: bool = False,
            limit: int = 20,
            offset: int = 0,
            dry_run: bool = False,
        ) -> ImagesResult:
            """Images. list is read-only. pull, remove and prune change the host and need approval
            (or HOMELAB_DOCKER_ALLOW_WRITES=true). remove deletes an image; prune removes dangling and unused images."""
            backend = runtime.docker()
            if action == "list":
                rows = await backend.list_images()
                items, total, more = page([ImageItem(**r) for r in rows], limit, offset)
                return ImagesResult(items=items, total=total, has_more=more)
            if action == "prune":
                summary = "remove dangling and unused images."

                async def perform():
                    return None, await backend.prune_images()

                change = await run_change(ctx, config, module=MODULE, action=action, summary=summary,
                                          perform=perform, dry_run=dry_run, preview={"would_prune": "unused images"})
                return ImagesResult(change=change)
            if not image.strip():
                raise HomelabError(MODULE, "bad_input", f"image is required for {action}.", "pass an image name.")
            name = image.strip()
            if action == "pull":
                summary = f"pull image {name}:{tag}"

                async def perform():
                    return None, await backend.pull(name, tag)
            else:
                summary = f"PERMANENTLY remove image {name}" + (" (forced)" if force else "")

                async def perform():
                    return None, await backend.remove_image(name, force)

            change = await run_change(ctx, config, module=MODULE, action=action, summary=summary,
                                      perform=perform, dry_run=dry_run, preview={"image": f"{name}:{tag}"})
            return ImagesResult(change=change)

        @mcp.tool(annotations=READ_ONLY)
        async def docker_inventory(
            kind: Literal["volumes", "networks", "stacks"] = "volumes",
            stack_id: int = 0,
            limit: int = 20,
            offset: int = 0,
        ) -> InventoryResult:
            """Read-only lists: volumes, networks, or Portainer stacks (stacks need the Portainer backend).
            Pass stack_id with kind=stacks to get that stack's compose file."""
            backend = runtime.docker()
            base = {"kind": kind, "backend": backend.name}
            if kind == "volumes":
                rows = await backend.list_volumes()
                items, total, more = page([InventoryItem(**r) for r in rows], limit, offset)
                return InventoryResult(**base, items=items, total=total, has_more=more)
            if kind == "networks":
                rows = await backend.list_networks()
                items, total, more = page([InventoryItem(**r) for r in rows], limit, offset)
                return InventoryResult(**base, items=items, total=total, has_more=more)
            if stack_id:
                res = await backend.get_stack(stack_id)
                return InventoryResult(**base, compose_file=res.get("compose_file"), total=1,
                                       items=[InventoryItem(id=str(stack_id), name=str((res.get("stack") or {}).get("Name", "")))])
            rows = await backend.list_stacks()
            items, total, more = page([InventoryItem(**r) for r in rows], limit, offset)
            return InventoryResult(**base, items=items, total=total, has_more=more)
