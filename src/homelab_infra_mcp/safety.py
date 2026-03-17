"""Safety layer — mode enforcement and destructive operation confirmation."""

import json
import secrets
import time

from homelab_infra_mcp.config import config

# Pending confirmations: token -> {action, details, expires}
_pending_confirmations: dict[str, dict] = {}


def check_mode(operation_type: str) -> str | None:
    """Check if the current mode allows this operation type.

    Returns None if allowed, or an error message if blocked.
    """
    if config.mode == "readonly" and operation_type in ("write", "destructive"):
        return f"Blocked: server is in read-only mode. Use set_mode to switch to normal."
    return None


def is_dry_run() -> bool:
    """Check if we're in dry-run mode."""
    return config.mode == "dryrun"


def request_confirmation(action: str, details: str) -> str:
    """Create a confirmation token for a destructive operation.

    Returns a JSON response with the token and details.
    """
    token = secrets.token_urlsafe(16)
    _pending_confirmations[token] = {
        "action": action,
        "details": details,
        "expires": time.time() + 60,  # 60 second expiry
    }
    # Clean up expired tokens
    _cleanup_expired()
    return json.dumps({
        "confirmation_required": True,
        "action": action,
        "details": details,
        "token": token,
        "expires_in_seconds": 60,
        "message": f"This will {action}. Call confirm_destructive with this token to proceed.",
    })


def validate_confirmation(token: str) -> dict | None:
    """Validate a confirmation token. Returns the action details or None."""
    _cleanup_expired()
    if token not in _pending_confirmations:
        return None
    entry = _pending_confirmations.pop(token)
    return entry


def _cleanup_expired():
    """Remove expired confirmation tokens."""
    now = time.time()
    expired = [k for k, v in _pending_confirmations.items() if v["expires"] < now]
    for k in expired:
        del _pending_confirmations[k]
