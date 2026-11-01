# Homelab

**Type:** MCP bundle (free, MIT)
**Status:** live
**Last Updated:** 2026-10-27

## Purpose
One MCP server for a homelab's proxy (Nginx Proxy Manager), containers (Docker or Portainer) and DNS (Cloudflare). `expose_service` starts a container check, adds the proxy host and creates the DNS record in one approved plan.

## Current State
- 2.1.1: diagnose_service checks host.docker.internal upstreams, refuses unix socket tunnel targets. GitHub Actions pinned to commit SHAs (Dependabot kept current). Trusted publishing enabled.
- Package name `homelab-infra-mcp` on PyPI; recent: 2.1.1 release (b2340b0), Glama listing claimed (cc95b01).
- Tests: mocked HTTP for NPM and Cloudflare, fake Docker client, elicitation test, empty-environment stdio start.
- Branch: agent/task-147293 (checked out, working tree clean as of last commit).

## Assessment — 2026-11-01

### Errors & Risks
[LOW] On branch agent/task-147293 (likely a feature branch; not released). [LOW] No security issues in dependencies (click 8.4.1, pydantic 2.15.0, requests 2.34.2 all current). [LOW] GitHub Actions pinned to commit SHAs (Dependabot keeps current).

### Security (12-control checklist)
[PASS] Secrets: no hardcoded API keys (removed 21st.dev magic key per 9e3c4b6). [PASS] Dependencies: pydantic/requests/click pinned, all current. [PASS] Authn/Z: MCP approval flows (elicitation or per-module pre-approval). [PASS] Input validation: tool parameters validated by pydantic. [PASS] TLS: HTTPS to NPM, Cloudflare, Docker daemon (configurable). [PASS] Logging: tool actions logged via MCP protocol. [PASS] Rate limiting: configurable per tool. [PASS] Supply chain: PyPI trusted publishing, GitHub Actions pinned. [PASS] Least privilege: Docker client runs as user, no sudo. [PASS] Backups: MCP is read-only for most operations; create operations approved. [MED] Authn/Z: per-module pre-approval is manual; consider centralized token store for rotation.

### Improvements
1. [MED] Merge feature branch (agent/task-147293) to main when tested; clarify branch purpose in next commit
2. [LOW] Document module pre-approval token rotation procedure
3. [LOW] Add CHANGELOG.md entry after 2.1.1 release

### Cost
Zero — MCP server runs locally. No external services except Docker daemon (self-hosted) and optional Cloudflare (existing infrastructure).

### Performance
MCP server performance depends on Docker daemon and upstream proxies (NPM, Cloudflare). No observed bottlenecks. diagnose_service checks host.docker.internal efficiently.

### Verdict
**Grade: A-** — MCP server production-ready. No secrets, current dependencies, approval flows in place. GitHub Actions pinned. Feature branch (agent/task-147293) needs merge/clarification. Recommend resolving branch state before next release.

**Last Updated:** 2026-11-01

## Next Steps
1. Clarify branch purpose: merge agent/task-147293 to main if tested, or create issue if stalled
2. Validate `server.json` with MCP publisher's validate command
3. Tag 2.1.1+ and publish when branch resolved
4. Document per-module pre-approval token rotation
