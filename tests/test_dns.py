"""Tests for Cloudflare DNS module (mocked)."""

import httpx
import pytest
import respx

from homelab_infra_mcp.modules.dns.cloudflare import _cf_get


@pytest.mark.asyncio
@respx.mock
async def test_cf_list_zones():
    respx.get("https://api.cloudflare.com/client/v4/zones").mock(
        return_value=httpx.Response(200, json={"success": True, "result": [{"id": "z1", "name": "example.com"}]})
    )
    data = await _cf_get("zones")
    assert data["result"][0]["name"] == "example.com"
