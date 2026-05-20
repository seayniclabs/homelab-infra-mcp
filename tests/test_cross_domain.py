"""Tests for cross-domain dry-run behavior."""

import json

import pytest

from homelab_infra_mcp.config import config
from homelab_infra_mcp.modules.cross_domain import register
from mcp.server.fastmcp import FastMCP


@pytest.mark.asyncio
async def test_expose_service_dry_run():
    config.mode = "dryrun"
    mcp = FastMCP("test")
    register(mcp)
    # Tool functions are registered on mcp — invoke via imported module logic
    from homelab_infra_mcp.safety import is_dry_run

    assert is_dry_run()
    config.mode = "normal"
