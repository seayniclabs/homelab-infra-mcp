# Security Policy

## Reporting Vulnerabilities

If you discover a security vulnerability, please email security@seayniclabs.com.
Do not open a public issue.

## Security Model

- **No shell execution** — all operations use structured API calls (HTTP, Docker socket)
- **Docker socket access** — mount read-only (`:ro`) when possible
- **Destructive confirmation** — two-step pattern with expiring tokens
- **Credential handling** — all secrets via environment variables, never hardcoded
- **Input validation** — container names, domains, ports, record types all validated
- **Mode enforcement** — read-only mode blocks all write/destructive operations
