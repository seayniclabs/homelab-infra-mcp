# Contributing

1. Fork the repository and branch from `main`.
2. `uv venv -p 3.11 .venv && uv pip install -e '.[dev]'`
3. `.venv/bin/pytest -q`. Tests must not touch the network or a real Docker engine: use `httpx.MockTransport` and a fake Docker client.
4. Open a pull request with a clear description and tests for any behavior change.

## Adding a module

A module is one file in `src/homelab_infra_mcp/modules/`. Subclass `Module`, declare its `Setting`s, and register its tools. Add it to `all_modules()` in `modules/__init__.py`, and set `default_enabled = False` for anything new, so existing installs do not gain tools on update.

Every change tool must go through `run_change` (see `models.py`), so it gets the approval gate and a dry run for free. Every error must be a `HomelabError`.
