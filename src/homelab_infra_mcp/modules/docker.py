"""Docker module — 16 tools for container, image, volume, and network management."""

import json

import docker as docker_sdk

from homelab_infra_mcp.config import config
from homelab_infra_mcp.safety import check_mode, is_dry_run, request_confirmation

_client: docker_sdk.DockerClient | None = None


def _docker() -> docker_sdk.DockerClient:
    """Get or create Docker client."""
    global _client
    if _client is None:
        _client = docker_sdk.DockerClient(base_url=config.docker_host)
    return _client


def register(mcp):
    """Register Docker tools with the MCP server."""

    @mcp.tool()
    def docker_list_containers(all: bool = False) -> str:
        """List containers with status, ports, image, and uptime.

        Args:
            all: Include stopped containers (default: running only).
        """
        containers = _docker().containers.list(all=all)
        summary = []
        for c in containers:
            # Resolve image label without triggering an extra API call.
            # c.image.tags / c.image.short_id call the Docker API and 404 if
            # the image has been pruned out from under a still-running container
            # (which happens after `docker image prune -a`). Fall back to the
            # SHA stored on the container itself.
            try:
                tags = c.image.tags
                image_label = tags[0] if tags else c.image.short_id
            except docker_sdk.errors.ImageNotFound:
                image_sha = c.attrs.get("Image", "")
                image_label = image_sha[7:19] if image_sha.startswith("sha256:") else (image_sha[:12] or "unknown")
            except Exception:
                image_label = "unknown"
            summary.append({
                "id": c.short_id,
                "name": c.name,
                "status": c.status,
                "image": image_label,
                "ports": c.ports,
                "created": c.attrs.get("Created", ""),
            })
        return json.dumps({"count": len(summary), "containers": summary})

    @mcp.tool()
    def docker_get_container(name_or_id: str) -> str:
        """Get detailed container inspect data.

        Args:
            name_or_id: Container name or ID.
        """
        try:
            c = _docker().containers.get(name_or_id)
            return json.dumps({
                "id": c.id,
                "name": c.name,
                "status": c.status,
                "image": c.image.tags[0] if c.image.tags else c.image.short_id,
                "ports": c.ports,
                "env": c.attrs.get("Config", {}).get("Env", []),
                "mounts": [{"source": m.get("Source"), "destination": m.get("Destination"), "mode": m.get("Mode")}
                           for m in c.attrs.get("Mounts", [])],
                "network": list(c.attrs.get("NetworkSettings", {}).get("Networks", {}).keys()),
                "created": c.attrs.get("Created"),
                "started_at": c.attrs.get("State", {}).get("StartedAt"),
                "restart_count": c.attrs.get("RestartCount", 0),
            })
        except docker_sdk.errors.NotFound:
            return json.dumps({"error": f"Container not found: {name_or_id}"})

    @mcp.tool()
    def docker_start_container(name_or_id: str) -> str:
        """Start a stopped container.

        Args:
            name_or_id: Container name or ID.
        """
        blocked = check_mode("write")
        if blocked:
            return json.dumps({"error": blocked})
        if is_dry_run():
            return json.dumps({"dry_run": True, "would_start": name_or_id})

        try:
            c = _docker().containers.get(name_or_id)
            c.start()
            return json.dumps({"started": True, "name": c.name})
        except docker_sdk.errors.NotFound:
            return json.dumps({"error": f"Container not found: {name_or_id}"})

    @mcp.tool()
    def docker_stop_container(name_or_id: str, timeout: int = 10) -> str:
        """Stop a running container gracefully.

        Args:
            name_or_id: Container name or ID.
            timeout: Seconds to wait before killing (default 10).
        """
        blocked = check_mode("write")
        if blocked:
            return json.dumps({"error": blocked})
        if is_dry_run():
            return json.dumps({"dry_run": True, "would_stop": name_or_id})

        try:
            c = _docker().containers.get(name_or_id)
            c.stop(timeout=timeout)
            return json.dumps({"stopped": True, "name": c.name})
        except docker_sdk.errors.NotFound:
            return json.dumps({"error": f"Container not found: {name_or_id}"})

    @mcp.tool()
    def docker_restart_container(name_or_id: str, timeout: int = 10) -> str:
        """Restart a container.

        Args:
            name_or_id: Container name or ID.
            timeout: Seconds to wait before killing (default 10).
        """
        blocked = check_mode("write")
        if blocked:
            return json.dumps({"error": blocked})
        if is_dry_run():
            return json.dumps({"dry_run": True, "would_restart": name_or_id})

        try:
            c = _docker().containers.get(name_or_id)
            c.restart(timeout=timeout)
            return json.dumps({"restarted": True, "name": c.name})
        except docker_sdk.errors.NotFound:
            return json.dumps({"error": f"Container not found: {name_or_id}"})

    @mcp.tool()
    def docker_remove_container(name_or_id: str) -> str:
        """Remove a stopped container.

        Args:
            name_or_id: Container name or ID.
        """
        blocked = check_mode("destructive")
        if blocked:
            return json.dumps({"error": blocked})
        if is_dry_run():
            return json.dumps({"dry_run": True, "would_remove": name_or_id})

        return request_confirmation(
            f"remove container {name_or_id}",
            f"This will permanently remove the container. Data in unnamed volumes may be lost."
        )

    @mcp.tool()
    def docker_container_logs(name_or_id: str, tail: int = 100, since: str = "") -> str:
        """Get container logs.

        Args:
            name_or_id: Container name or ID.
            tail: Number of lines from the end (default 100).
            since: Only logs since this timestamp (ISO 8601 or relative like '1h').
        """
        try:
            c = _docker().containers.get(name_or_id)
            kwargs = {"tail": tail, "timestamps": True}
            if since:
                kwargs["since"] = since
            logs = c.logs(**kwargs).decode("utf-8", errors="replace")
            lines = logs.strip().split("\n")
            return json.dumps({"container": c.name, "lines": len(lines), "logs": lines[-tail:]})
        except docker_sdk.errors.NotFound:
            return json.dumps({"error": f"Container not found: {name_or_id}"})

    @mcp.tool()
    def docker_container_stats(name_or_id: str) -> str:
        """Get CPU, memory, and network I/O stats for a container.

        Args:
            name_or_id: Container name or ID.
        """
        try:
            c = _docker().containers.get(name_or_id)
            stats = c.stats(stream=False)
            # Parse CPU
            cpu_delta = stats["cpu_stats"]["cpu_usage"]["total_usage"] - stats["precpu_stats"]["cpu_usage"]["total_usage"]
            system_delta = stats["cpu_stats"]["system_cpu_usage"] - stats["precpu_stats"]["system_cpu_usage"]
            cpu_pct = (cpu_delta / system_delta * 100.0) if system_delta > 0 else 0.0

            # Parse memory
            mem = stats.get("memory_stats", {})
            mem_usage = mem.get("usage", 0)
            mem_limit = mem.get("limit", 1)
            mem_pct = (mem_usage / mem_limit * 100.0) if mem_limit > 0 else 0.0

            return json.dumps({
                "container": c.name,
                "cpu_percent": round(cpu_pct, 2),
                "memory_usage_mb": round(mem_usage / 1024 / 1024, 1),
                "memory_limit_mb": round(mem_limit / 1024 / 1024, 1),
                "memory_percent": round(mem_pct, 2),
            })
        except docker_sdk.errors.NotFound:
            return json.dumps({"error": f"Container not found: {name_or_id}"})
        except (KeyError, ZeroDivisionError):
            return json.dumps({"error": "Could not parse container stats"})

    @mcp.tool()
    def docker_list_images() -> str:
        """List Docker images with size, tags, and creation date."""
        images = _docker().images.list()
        summary = [{
            "id": i.short_id,
            "tags": i.tags,
            "size_mb": round(i.attrs.get("Size", 0) / 1024 / 1024, 1),
            "created": i.attrs.get("Created", ""),
        } for i in images]
        return json.dumps({"count": len(summary), "images": summary})

    @mcp.tool()
    def docker_pull_image(image: str, tag: str = "latest") -> str:
        """Pull an image from a registry.

        Args:
            image: Image name (e.g. 'nginx', 'ghcr.io/org/app').
            tag: Image tag (default: latest).
        """
        blocked = check_mode("write")
        if blocked:
            return json.dumps({"error": blocked})
        if is_dry_run():
            return json.dumps({"dry_run": True, "would_pull": f"{image}:{tag}"})

        _docker().images.pull(image, tag=tag)
        return json.dumps({"pulled": True, "image": f"{image}:{tag}"})

    @mcp.tool()
    def docker_remove_image(image: str, force: bool = False) -> str:
        """Remove an image.

        Args:
            image: Image name or ID.
            force: Force removal even if in use.
        """
        blocked = check_mode("destructive")
        if blocked:
            return json.dumps({"error": blocked})
        if is_dry_run():
            return json.dumps({"dry_run": True, "would_remove": image})

        return request_confirmation(f"remove image {image}", "This will delete the image locally.")

    @mcp.tool()
    def docker_list_volumes() -> str:
        """List Docker volumes with mount points."""
        volumes = _docker().volumes.list()
        summary = [{
            "name": v.name,
            "driver": v.attrs.get("Driver", ""),
            "mountpoint": v.attrs.get("Mountpoint", ""),
            "created": v.attrs.get("CreatedAt", ""),
        } for v in volumes]
        return json.dumps({"count": len(summary), "volumes": summary})

    @mcp.tool()
    def docker_list_networks() -> str:
        """List Docker networks with driver and connected containers."""
        networks = _docker().networks.list()
        summary = [{
            "id": n.short_id,
            "name": n.name,
            "driver": n.attrs.get("Driver", ""),
            "containers": list(n.attrs.get("Containers", {}).keys()),
        } for n in networks]
        return json.dumps({"count": len(summary), "networks": summary})

    @mcp.tool()
    def docker_prune_containers() -> str:
        """Remove all stopped containers."""
        blocked = check_mode("destructive")
        if blocked:
            return json.dumps({"error": blocked})
        if is_dry_run():
            return json.dumps({"dry_run": True, "would_prune": "stopped containers"})

        return request_confirmation(
            "prune all stopped containers",
            "This will remove ALL stopped containers. This cannot be undone."
        )

    @mcp.tool()
    def docker_prune_images() -> str:
        """Remove dangling and unused images."""
        blocked = check_mode("destructive")
        if blocked:
            return json.dumps({"error": blocked})
        if is_dry_run():
            return json.dumps({"dry_run": True, "would_prune": "unused images"})

        return request_confirmation(
            "prune unused images",
            "This will remove all dangling images and reclaim disk space."
        )

    @mcp.tool()
    def docker_health() -> str:
        """Check Docker socket connectivity, engine version, and resource summary."""
        try:
            info = _docker().info()
            return json.dumps({
                "healthy": True,
                "version": info.get("ServerVersion", "unknown"),
                "containers": info.get("Containers", 0),
                "containers_running": info.get("ContainersRunning", 0),
                "images": info.get("Images", 0),
                "os": info.get("OperatingSystem", "unknown"),
                "architecture": info.get("Architecture", "unknown"),
            })
        except Exception as e:
            return json.dumps({"healthy": False, "error": str(e)})
