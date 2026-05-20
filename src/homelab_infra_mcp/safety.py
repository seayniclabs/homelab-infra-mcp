"""Safety layer — mode enforcement and destructive operation confirmation."""

import asyncio
import json
import secrets
import time
from collections.abc import Awaitable, Callable
from typing import Any

from homelab_infra_mcp.config import config

_pending_confirmations: dict[str, dict] = {}


def check_mode(operation_type: str) -> str | None:
    """Return an error message if the current mode blocks this operation."""
    if config.mode == "readonly" and operation_type in ("write", "destructive"):
        return "Blocked: server is in read-only mode. Use set_mode('normal') to allow writes."
    return None


def is_dry_run() -> bool:
    return config.mode == "dryrun"


def request_confirmation(
    action: str,
    details: str,
    execute: Callable[[], Any] | Callable[[], Awaitable[Any]] | None = None,
) -> str:
    """Create a confirmation token. Optionally register an executor for confirm_destructive."""
    token = secrets.token_urlsafe(16)
    _pending_confirmations[token] = {
        "action": action,
        "details": details,
        "expires": time.time() + 60,
        "execute": execute,
    }
    _cleanup_expired()
    return json.dumps({
        "confirmation_required": True,
        "action": action,
        "details": details,
        "token": token,
        "expires_in_seconds": 60,
        "message": (
            f"This will {action}. Call confirm_destructive with this token to proceed."
        ),
    })


def validate_confirmation(token: str) -> dict | None:
    _cleanup_expired()
    return _pending_confirmations.pop(token, None)


async def run_confirmed_action(entry: dict) -> Any:
    """Run the registered executor for a confirmed destructive action."""
    execute = entry.get("execute")
    if execute is None:
        return {
            "note": "No executor registered for this action.",
            "action": entry["action"],
        }
    if asyncio.iscoroutinefunction(execute):
        return await execute()
    return execute()


def _cleanup_expired() -> None:
    now = time.time()
    expired = [k for k, v in _pending_confirmations.items() if v["expires"] < now]
    for k in expired:
        del _pending_confirmations[k]
