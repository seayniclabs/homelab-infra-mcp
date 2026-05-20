# Contributing

1. Fork and branch from `main`.
2. `python3.12 -m venv .venv && source .venv/bin/activate`
3. `pip install -e ".[test]"`
4. `pytest --cov=src/homelab_infra_mcp`
5. Open a PR with a clear description and test coverage for behavior changes.

## Adding a DNS provider

Implement `homelab_infra_mcp.modules.dns.base.DNSProvider` and register tools from a new module. See `docs/adding-dns-provider.md`.
