"""Tests for server utility tools."""

import json

from homelab_infra_mcp.config import config
from homelab_infra_mcp.server import get_mode, set_mode


def test_set_mode_aliases():
    result = json.loads(set_mode("read-only"))
    assert result["mode"] == "readonly"
    config.mode = "normal"


def test_get_mode():
    config.mode = "dryrun"
    assert json.loads(get_mode())["mode"] == "dryrun"
    config.mode = "normal"
