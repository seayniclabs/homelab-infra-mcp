"""The approval gate. Every change to the homelab goes through here.

A change runs only when one of these is true:

1. Every module it touches is pre-approved in settings (``HOMELAB_<MODULE>_ALLOW_WRITES=true``), or
2. The person approves the exact change in an MCP elicitation prompt.

The model cannot approve on its own behalf: there is no confirm flag. If the client cannot
show a prompt and the modules are not pre-approved, the call fails and names the setting.
``HOMELAB_READ_ONLY=true`` refuses every change, whatever the other settings say.

Every path is written to a local JSONL log (``HOMELAB_APPROVAL_LOG``, default
``$XDG_STATE_HOME/homelab/approvals.jsonl``): requested, approved, declined, refused. The log
holds the summary the person was shown, never request bodies, file contents or secrets.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from mcp.server.fastmcp import Context
from pydantic import BaseModel, Field

from homelab_infra_mcp.config import CORE, Config, env_name
from homelab_infra_mcp.errors import HomelabError


class ApprovalChoice(BaseModel):
    approve: bool = Field(description="Approve this change?")


@dataclass(frozen=True)
class Decision:
    approved: bool
    approved_by: str | None = None  # "person" or "settings"
    note: str | None = None


def log_path(env: Mapping[str, str]) -> Path:
    if env.get("HOMELAB_APPROVAL_LOG"):
        return Path(env["HOMELAB_APPROVAL_LOG"]).expanduser()
    base = env.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "homelab" / "approvals.jsonl"


def record(env: Mapping[str, str], tool: str, decision: str, by: str | None, summary: str) -> None:
    """decision: requested | approved | declined | refused. Never raises: logging must not block a change."""
    try:
        path = log_path(env)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "tool": tool,
                "decision": decision, "approved_by": by, "summary": summary[:500]}
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
        os.chmod(path, 0o600)
    except OSError:
        pass


def _can_ask_person(ctx: Context | None) -> bool:
    if ctx is None:
        return False
    try:
        caps = ctx.session.client_params.capabilities  # type: ignore[union-attr]
    except (ValueError, AttributeError):
        return False
    return bool(caps and caps.elicitation)


def allow_writes_env(modules: list[str]) -> str:
    return " and ".join(env_name(m, "allow_writes") + "=true" for m in modules)


async def gate(ctx: Context | None, config: Config, modules: list[str], summary: str, tool: str = "") -> Decision:
    """Return whether the change may run. ``summary`` is shown to the person verbatim."""
    tool = tool or "+".join(modules)
    log_env = config.env
    if config.flag(CORE, "read_only", False):
        record(log_env, tool, "refused", None, summary)
        raise HomelabError(
            "core", "read_only",
            "HOMELAB_READ_ONLY is on, so this change was refused.",
            "unset HOMELAB_READ_ONLY (or set it to false) to allow approved changes. Dry runs still work.",
        )
    not_preapproved = [m for m in modules if not config.flag(m, "allow_writes", False)]
    if not not_preapproved:
        record(log_env, tool, "approved", "settings", summary)
        return Decision(True, "settings")
    if _can_ask_person(ctx):
        record(log_env, tool, "requested", None, summary)
        answer = await ctx.elicit(f"{summary}\n\nApprove this change?", ApprovalChoice)  # type: ignore[union-attr]
        if answer.action == "accept" and answer.data.approve:
            record(log_env, tool, "approved", "person", summary)
            return Decision(True, "person")
        record(log_env, tool, "declined", None, summary)
        return Decision(False, None, "The person declined. Nothing was changed.")
    record(log_env, tool, "refused", None, summary)
    raise HomelabError(
        not_preapproved[0], "approval_unavailable",
        "this MCP client cannot ask you to approve changes, and "
        + ", ".join(not_preapproved) + " not pre-approved.",
        "set " + allow_writes_env(not_preapproved) + " to pre-approve these modules, "
        "or use an MCP client that supports elicitation.",
    )
