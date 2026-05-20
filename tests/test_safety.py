"""Tests for safety modes and confirmation tokens."""

import asyncio
import json
import time

import pytest

from homelab_infra_mcp.config import config
from homelab_infra_mcp.safety import (
    check_mode,
    is_dry_run,
    request_confirmation,
    run_confirmed_action,
    validate_confirmation,
)


def test_readonly_blocks_write():
    config.mode = "readonly"
    assert check_mode("write") is not None
    config.mode = "normal"


def test_dry_run_flag():
    config.mode = "dryrun"
    assert is_dry_run()
    config.mode = "normal"


def test_confirmation_execute_sync():
    config.mode = "normal"
    result = json.loads(
        request_confirmation("test action", "details", execute=lambda: {"ok": True})
    )
    token = result["token"]
    entry = validate_confirmation(token)
    assert entry is not None
    out = asyncio.run(run_confirmed_action(entry))
    assert out == {"ok": True}


def test_confirmation_expired_token():
    config.mode = "normal"
    result = json.loads(request_confirmation("x", "y"))
    token = result["token"]
    assert validate_confirmation(token) is not None
    assert validate_confirmation(token) is None


@pytest.mark.asyncio
async def test_confirmation_execute_async():
    async def _run():
        return {"async": True}

    result = json.loads(request_confirmation("async", "d", execute=_run))
    entry = validate_confirmation(result["token"])
    out = await run_confirmed_action(entry)
    assert out == {"async": True}
