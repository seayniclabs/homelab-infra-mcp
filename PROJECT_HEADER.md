# Homelab

**Type:** MCP bundle (free, MIT)
**Status:** 2.0.0 in progress on branch `bundle-standard`; not yet published
**Last Updated:** 2026-10-27

## Purpose
One MCP server for a homelab's proxy (Nginx Proxy Manager), containers (Docker or Portainer) and DNS (Cloudflare). `expose_service` starts a container check, adds the proxy host and creates the DNS record in one approved plan.

## Current State
- 2.0.0: code-mode refactor. 15 tools by default (18 with the opt-in Home Assistant module), down from 46. Approval through MCP elicitation or per-module pre-approval replaces the old self-confirmation tokens.
- Package name `homelab-infra-mcp` is unchanged from 1.0.1 on PyPI.
- Tests: mocked HTTP for NPM and Cloudflare, a fake Docker client, an elicitation test, and an empty-environment stdio start.

## Next Steps
1. Review the 2.0.0 changes and the CHANGELOG mapping table.
2. Validate `server.json` with the MCP publisher's read-only validate command.
3. Tag and publish when approved.
