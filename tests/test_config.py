"""Tests for configuration."""

from homelab_infra_mcp.config import Config, _normalize_mode


def test_normalize_mode_aliases():
    assert _normalize_mode("read-only") == "readonly"
    assert _normalize_mode("dry-run") == "dryrun"


def test_docker_backend_defaults_socket():
    cfg = Config()
    cfg.portainer_url = ""
    cfg.portainer_token = ""
    assert cfg.docker_backend == "socket"
