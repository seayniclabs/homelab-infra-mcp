"""Result shapes shared by every tool."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, TypeVar

from pydantic import BaseModel

from homelab_infra_mcp.approval import gate
from homelab_infra_mcp.config import Config

T = TypeVar("T")


class Change(BaseModel):
    """What a state-changing tool did, or would do in a dry run."""

    module: str
    action: str
    dry_run: bool = False
    changed: bool = False
    approved_by: str | None = None  # "person" (elicitation) or "settings" (pre-approved)
    summary: str  # the exact change, in the words the person was shown
    id: str | None = None
    note: str | None = None
    detail: dict[str, Any] | None = None  # the payload a dry run would send


def page(items: list[T], limit: int, offset: int) -> tuple[list[T], int, bool]:
    """Slice a full list. Returns (page, total, has_more)."""
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    return items[offset: offset + limit], len(items), offset + limit < len(items)


async def run_change(
    ctx: Any,
    config: Config,
    *,
    module: str,
    action: str,
    summary: str,
    perform: Callable[[], Awaitable[tuple[str | None, dict[str, Any] | None]]],
    dry_run: bool = False,
    preview: dict[str, Any] | None = None,
    modules: list[str] | None = None,
) -> Change:
    """Run one change: preview on dry_run, otherwise ask the gate, then perform it.

    ``perform`` returns (id, detail). ``modules`` lists every module the change touches, so
    pre-approval has to cover all of them. Default: just ``module``.
    """
    if dry_run:
        return Change(module=module, action=action, dry_run=True, summary=f"Would {summary}", detail=preview)
    decision = await gate(ctx, config, modules or [module], f"Homelab ({module}) will {summary}.",
                          tool=f"{module}.{action}")
    if not decision.approved:
        return Change(module=module, action=action, summary=summary, note=decision.note)
    change_id, detail = await perform()
    return Change(module=module, action=action, changed=True, approved_by=decision.approved_by,
                  summary=summary, id=change_id, detail=detail)
