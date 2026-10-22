# Homelab Infra MCP

**Type:** MCP server (free, MIT; lead magnet)  
**Status:** active  
**Owner:** Charlie  
**Last Updated:** 2026-10-22

## Purpose
One MCP server for homelab operations across Nginx Proxy Manager, Docker (optionally through Portainer) and Cloudflare DNS: 46 tools, including `expose_service`, which starts a container, adds the proxy host and creates the DNS record in one call. Repo: github.com/seayniclabs/homelab-infra-mcp.

## Current State
- **1.0.1 ready, not yet on PyPI (2026-10-22):** pins `mcp<2`; declares `pyyaml` (the Home Assistant module imports it, so 1.0.0 also crashed with that module on); secrets fallback directory is `HOMELAB_SECRETS_DIR` (default `~/.config/homelab-infra-mcp/secrets`) instead of an internal path. Clean clone: wheel builds, 16/16 tests pass, the server starts and lists 63 tools with all modules on.
- **1.0.0 on PyPI is broken:** it crashes on a fresh install because it doesn't pin `mcp<2`.
- It is the free **Homelab Control Kit** (House Cleaning D8, 2026-10-22): public repo, Bridge free-catalog card is this row; the old `homelab-control-kit` row is archived.
- The live proxy entry (`homelab` in mcp-proxy) runs this checkout and needs `HOMELAB_SECRETS_DIR=/Volumes/data/secrets` in its env before the proxy next restarts.

## Next Steps
1. Publish 1.0.1 to PyPI (approved, D8) and verify `pip install homelab-infra-mcp==1.0.1` in a fresh venv
2. Set `HOMELAB_SECRETS_DIR` on the `homelab` mcp-proxy entry, then restart the proxy
3. Write the blueprint (`blueprint new homelab-infra-mcp`)
