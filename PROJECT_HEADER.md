# Homelab Infra MCP

**Type:** MCP server (free, MIT; lead magnet)  
**Status:** active  
**Owner:** Charlie  
**Last Updated:** 2026-10-20

## Purpose
One MCP server for homelab operations across Nginx Proxy Manager, Docker (optionally through Portainer) and Cloudflare DNS: 46 tools, including `expose_service`, which starts a container, adds the proxy host and creates the DNS record in one call. Repo: github.com/seayniclabs/homelab-infra-mcp.

## Current State
- **1.0.1 in the repo (2026-10-19):** pins `mcp<2` (2.x removed FastMCP), 16/16 tests pass, internal QA report excluded from the sdist. Not published to PyPI (Charlie's call, 2026-10-19).
- **1.0.0 on PyPI is broken:** it crashes on a fresh install because it doesn't pin `mcp<2`.
- Not in the free MCP catalog on Bridge (Lathe and Bench only, 2026-10-19). Kept active by Charlie 2026-10-20.

## Next Steps
1. Decide what to do about PyPI: publish 1.0.1, or yank 1.0.0 so nobody installs the broken version (needs Charlie's OK either way)
2. Write the blueprint (`blueprint new homelab-infra-mcp`), including whether it joins the free catalog
