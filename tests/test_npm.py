"""Tests for NPM module (mocked HTTP)."""

import json

import httpx
import pytest
import respx

from homelab_infra_mcp.config import config


@pytest.mark.asyncio
@respx.mock
async def test_npm_list_proxy_hosts():
    respx.post(f"{config.npm_url}/api/tokens").mock(
        return_value=httpx.Response(200, json={"token": "jwt-test"})
    )
    respx.get(f"{config.npm_url}/api/nginx/proxy-hosts").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 1, "domain_names": ["test.local"], "forward_host": "127.0.0.1", "forward_port": 80, "certificate_id": 0, "enabled": True}],
        )
    )
    from homelab_infra_mcp.modules.npm import _npm_get

    hosts = await _npm_get("nginx/proxy-hosts")
    assert hosts[0]["id"] == 1
