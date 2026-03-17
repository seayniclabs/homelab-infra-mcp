# Contributing

Thanks for your interest in contributing to Homelab Infrastructure MCP.

## Development Setup

```bash
git clone https://github.com/seayniclabs/homelab-infra-mcp.git
cd homelab-infra-mcp
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest tests/
```

## Code Style

- Python 3.11+ type hints
- Functions return JSON strings (not dicts) for MCP compatibility
- All tools must respect the safety layer (check_mode, is_dry_run)
- Destructive operations must use request_confirmation

## Adding a DNS Provider

1. Create `src/homelab_infra_mcp/modules/dns/your_provider.py`
2. Implement the same 8 tool functions as `cloudflare.py`
3. Add provider detection logic in `server.py`
4. Add tests in `tests/test_dns_your_provider.py`
5. Update README with the new provider's env vars

## Pull Request Process

1. Fork the repo and create a feature branch
2. Add tests for new functionality
3. Ensure all tests pass
4. Update README if adding new tools or config
5. Submit a PR with a clear description

## Reporting Issues

Use the GitHub issue templates:
- **Bug Report** — something broken
- **Feature Request** — something new
- **New Provider** — request a DNS provider
