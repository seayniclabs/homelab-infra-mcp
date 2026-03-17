# Homelab Infrastructure MCP

A unified MCP server for homelab ops — manage Nginx Proxy Manager, Docker, and Cloudflare DNS from Claude Code, Cursor, or any MCP-compatible AI assistant.

**One server. Three domains. 46 tools.**

## Why?

Homelabbers manage infrastructure across disconnected tools. Existing MCP servers handle these individually, but real homelab tasks span all three:

> "Expose my new container to the internet" = start container + create proxy host + add DNS record

This server does that in one `expose_service` call.

## Modules

### NPM (14 tools)
Proxy hosts, SSL certificates, redirections, access lists. Full CRUD via the NPM REST API.

### Docker (16 tools)
Containers (list, start, stop, restart, remove, logs, stats), images (list, pull, remove), volumes, networks, prune.

### DNS (8 tools)
Cloudflare zones, records (CRUD), zone export. More providers planned.

### Cross-Domain (4 tools)
- `expose_service` — DNS + proxy + container verification in one call
- `teardown_service` — reverse of expose
- `service_status` — full picture of a service across all three systems
- `infrastructure_overview` — dashboard in a tool call

### Safety (4 tools)
- Three modes: `normal`, `read-only`, `dry-run`
- Destructive operations require confirmation tokens (60s expiry)
- Selective module loading — only enable what you use

## Quick Start

### Claude Code (stdio)

```bash
pip install homelab-infra-mcp
```

```bash
claude mcp add homelab -- python -m homelab_infra_mcp
```

Set environment variables:

```bash
export NPM_URL=http://localhost:81
export NPM_EMAIL=admin@example.com
export NPM_PASSWORD=changeme
export CLOUDFLARE_API_TOKEN=your-token
```

### Docker

```yaml
services:
  homelab-mcp:
    image: ghcr.io/seayniclabs/homelab-infra-mcp:latest
    environment:
      - TZ=America/Chicago
      - NPM_URL=http://host.docker.internal:81
      - NPM_EMAIL=admin@example.com
      - NPM_PASSWORD=changeme
      - DOCKER_HOST=unix:///var/run/docker.sock
      - DNS_PROVIDER=cloudflare
      - CLOUDFLARE_API_TOKEN=your-token
      - HOMELAB_MCP_MODE=normal
      - HOMELAB_MCP_TRANSPORT=sse
      - HOMELAB_MCP_PORT=8200
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    ports:
      - "8200:8200"
```

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NPM_URL` | Yes | `http://localhost:81` | NPM API URL |
| `NPM_EMAIL` | Yes | — | NPM admin email |
| `NPM_PASSWORD` | Yes | — | NPM admin password |
| `DOCKER_HOST` | No | `unix:///var/run/docker.sock` | Docker socket |
| `DNS_PROVIDER` | No | `cloudflare` | DNS provider |
| `CLOUDFLARE_API_TOKEN` | Cond. | — | Required for DNS module |
| `CLOUDFLARE_ZONE_ID` | No | — | Default zone ID |
| `HOMELAB_MCP_MODE` | No | `normal` | `normal` / `readonly` / `dryrun` |
| `HOMELAB_MCP_MODULES` | No | `npm,docker,dns` | Comma-separated enabled modules |
| `HOMELAB_MCP_TRANSPORT` | No | `stdio` | `stdio` or `sse` |
| `HOMELAB_MCP_PORT` | No | `8200` | SSE server port |

### Selective Modules

Don't use NPM? Disable it:

```bash
export HOMELAB_MCP_MODULES=docker,dns
```

Only NPM tools will register. No Docker/DNS connection errors.

## Safety

All destructive operations (delete, prune, remove) follow a two-step confirmation pattern:

1. First call returns details + a one-time token
2. Pass the token to `confirm_destructive` to execute

Tokens expire after 60 seconds. Dry-run mode previews all changes without executing.

## Contributing

Contributions welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

MIT. See [LICENSE](LICENSE).

---

Built by [Seaynic Labs](https://seayniclabs.com).
