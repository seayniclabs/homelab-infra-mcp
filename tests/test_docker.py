"""Tests for Docker socket backend."""

from unittest.mock import MagicMock, patch

from homelab_infra_mcp.modules.docker_backends import SocketBackend


@patch("homelab_infra_mcp.modules.docker_backends.docker_sdk.DockerClient")
def test_socket_list_containers(mock_client_cls):
    mock_container = MagicMock()
    mock_container.short_id = "abc123"
    mock_container.name = "n8n"
    mock_container.status = "running"
    mock_container.image.tags = ["n8nio/n8n:latest"]
    mock_container.ports = {}
    mock_client_cls.return_value.containers.list.return_value = [mock_container]

    backend = SocketBackend()
    backend._client = mock_client_cls.return_value
    items = backend.list_containers()
    assert items[0]["name"] == "n8n"
