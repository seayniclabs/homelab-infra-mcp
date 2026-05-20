"""Docker module — 16 core tools + 2 Portainer-only stack tools."""

import json

import docker as docker_sdk

from homelab_infra_mcp.config import config
from homelab_infra_mcp.modules.docker_backends import PortainerBackend, get_backend
from homelab_infra_mcp.safety import check_mode, is_dry_run, request_confirmation
from homelab_infra_mcp.utils.validation import (
    ValidationError,
    validate_container_name,
    validation_error_response,
)


def _err_not_found(name_or_id: str) -> str:
    return json.dumps({"error": f"Container not found: {name_or_id}"})


def register(mcp):
    """Register Docker tools with the MCP server."""
    backend = get_backend()

    @mcp.tool()
    def docker_list_containers(all: bool = False) -> str:
        """List containers with status, ports, image, and uptime."""
        try:
            summary = backend.list_containers(all=all)
            return json.dumps({
                "backend": backend.backend_name,
                "count": len(summary),
                "containers": summary,
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def docker_get_container(name_or_id: str) -> str:
        """Get detailed container inspect data."""
        try:
            validate_container_name(name_or_id)
            return json.dumps(backend.get_container(name_or_id))
        except ValidationError as e:
            return validation_error_response(e)
        except (docker_sdk.errors.NotFound, KeyError):
            return _err_not_found(name_or_id)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def docker_start_container(name_or_id: str) -> str:
        """Start a stopped container."""
        blocked = check_mode("write")
        if blocked:
            return json.dumps({"error": blocked})
        if is_dry_run():
            return json.dumps({"dry_run": True, "would_start": name_or_id})
        try:
            validate_container_name(name_or_id)
            return json.dumps(backend.start_container(name_or_id))
        except ValidationError as e:
            return validation_error_response(e)
        except (docker_sdk.errors.NotFound, KeyError):
            return _err_not_found(name_or_id)

    @mcp.tool()
    def docker_stop_container(name_or_id: str, timeout: int = 10) -> str:
        """Stop a running container gracefully."""
        blocked = check_mode("write")
        if blocked:
            return json.dumps({"error": blocked})
        if is_dry_run():
            return json.dumps({"dry_run": True, "would_stop": name_or_id})
        try:
            validate_container_name(name_or_id)
            return json.dumps(backend.stop_container(name_or_id, timeout=timeout))
        except ValidationError as e:
            return validation_error_response(e)
        except (docker_sdk.errors.NotFound, KeyError):
            return _err_not_found(name_or_id)

    @mcp.tool()
    def docker_restart_container(name_or_id: str, timeout: int = 10) -> str:
        """Restart a container."""
        blocked = check_mode("write")
        if blocked:
            return json.dumps({"error": blocked})
        if is_dry_run():
            return json.dumps({"dry_run": True, "would_restart": name_or_id})
        try:
            validate_container_name(name_or_id)
            return json.dumps(backend.restart_container(name_or_id, timeout=timeout))
        except ValidationError as e:
            return validation_error_response(e)
        except (docker_sdk.errors.NotFound, KeyError):
            return _err_not_found(name_or_id)

    @mcp.tool()
    def docker_remove_container(name_or_id: str) -> str:
        """Remove a stopped container."""
        blocked = check_mode("destructive")
        if blocked:
            return json.dumps({"error": blocked})
        if is_dry_run():
            return json.dumps({"dry_run": True, "would_remove": name_or_id})
        try:
            validate_container_name(name_or_id)

            def _execute():
                return backend.remove_container(name_or_id)

            return request_confirmation(
                f"remove container {name_or_id}",
                "This will permanently remove the container.",
                execute=_execute,
            )
        except ValidationError as e:
            return validation_error_response(e)

    @mcp.tool()
    def docker_container_logs(name_or_id: str, tail: int = 50, since: str = "") -> str:
        """Get container logs (default last 50 lines)."""
        try:
            validate_container_name(name_or_id)
            return json.dumps(backend.container_logs(name_or_id, tail=tail, since=since))
        except ValidationError as e:
            return validation_error_response(e)
        except (docker_sdk.errors.NotFound, KeyError):
            return _err_not_found(name_or_id)

    @mcp.tool()
    def docker_container_stats(name_or_id: str) -> str:
        """Get CPU, memory, and network I/O stats for a container."""
        try:
            validate_container_name(name_or_id)
            return json.dumps(backend.container_stats(name_or_id))
        except ValidationError as e:
            return validation_error_response(e)
        except (docker_sdk.errors.NotFound, KeyError):
            return _err_not_found(name_or_id)

    @mcp.tool()
    def docker_list_images() -> str:
        """List Docker images with size, tags, and creation date."""
        return json.dumps({"count": len(backend.list_images()), "images": backend.list_images()})

    @mcp.tool()
    def docker_pull_image(image: str, tag: str = "latest") -> str:
        """Pull an image from a registry."""
        blocked = check_mode("write")
        if blocked:
            return json.dumps({"error": blocked})
        if is_dry_run():
            return json.dumps({"dry_run": True, "would_pull": f"{image}:{tag}"})
        return json.dumps(backend.pull_image(image, tag=tag))

    @mcp.tool()
    def docker_remove_image(image: str, force: bool = False) -> str:
        """Remove an image."""
        blocked = check_mode("destructive")
        if blocked:
            return json.dumps({"error": blocked})
        if is_dry_run():
            return json.dumps({"dry_run": True, "would_remove": image})

        def _execute():
            return backend.remove_image(image, force=force)

        return request_confirmation(
            f"remove image {image}",
            "This will delete the image locally.",
            execute=_execute,
        )

    @mcp.tool()
    def docker_list_volumes() -> str:
        """List Docker volumes with mount points."""
        volumes = backend.list_volumes()
        return json.dumps({"count": len(volumes), "volumes": volumes})

    @mcp.tool()
    def docker_list_networks() -> str:
        """List Docker networks with driver and connected containers."""
        networks = backend.list_networks()
        return json.dumps({"count": len(networks), "networks": networks})

    @mcp.tool()
    def docker_prune_containers() -> str:
        """Remove all stopped containers."""
        blocked = check_mode("destructive")
        if blocked:
            return json.dumps({"error": blocked})
        if is_dry_run():
            return json.dumps({"dry_run": True, "would_prune": "stopped containers"})

        def _execute():
            return backend.prune_containers()

        return request_confirmation(
            "prune all stopped containers",
            "This will remove ALL stopped containers.",
            execute=_execute,
        )

    @mcp.tool()
    def docker_prune_images() -> str:
        """Remove dangling and unused images."""
        blocked = check_mode("destructive")
        if blocked:
            return json.dumps({"error": blocked})
        if is_dry_run():
            return json.dumps({"dry_run": True, "would_prune": "unused images"})

        def _execute():
            return backend.prune_images()

        return request_confirmation(
            "prune unused images",
            "This will remove dangling/unused images.",
            execute=_execute,
        )

    @mcp.tool()
    def docker_health() -> str:
        """Check Docker API connectivity and backend type."""
        try:
            return json.dumps(backend.health())
        except Exception as e:
            return json.dumps({"healthy": False, "backend": backend.backend_name, "error": str(e)})

    if isinstance(backend, PortainerBackend):

        @mcp.tool()
        def docker_list_stacks() -> str:
            """List all Portainer stacks (Portainer backend only)."""
            stacks = backend.list_stacks()
            return json.dumps({"count": len(stacks), "stacks": stacks})

        @mcp.tool()
        def docker_get_stack(stack_id: int) -> str:
            """Get Portainer stack details including compose file."""
            return json.dumps(backend.get_stack(stack_id))
