"""Shared pytest fixtures."""

import os

import pytest


@pytest.fixture(autouse=True)
def _test_env(monkeypatch):
    """Isolate tests from host secrets and live services."""
    monkeypatch.setenv("HOMELAB_MCP_MODULES", "npm,docker,dns")
    monkeypatch.setenv("HOMELAB_MCP_MODE", "normal")
    monkeypatch.setenv("NPM_EMAIL", "admin@test.local")
    monkeypatch.setenv("NPM_PASSWORD", "test-password")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf-test-token")
    monkeypatch.setenv("CLOUDFLARE_ZONE_ID", "zone123")
    monkeypatch.delenv("PORTAINER_URL", raising=False)
    monkeypatch.delenv("PORTAINER_TOKEN", raising=False)
