# Homelab

<!-- mcp-name: io.github.seayniclabs/homelab-infra-mcp -->

Homelab is an MCP server for people who run their own homelab. It lets an AI assistant manage the path from a container to a public web address: your Nginx Proxy Manager proxy hosts, your Docker containers (or Portainer), and your Cloudflare DNS records. One call, `expose_service`, starts the check, adds the DNS record and the proxy host, and shows you the plan before anything changes.

It is a **bundle**: one server made of modules. You switch on the modules you use. New modules arrive switched off, so an update never changes what your assistant can do until you choose to.

**Audience:** self-hosters running a homelab.

| Module | What it does | Status |
|---|---|---|
| `proxy` | Nginx Proxy Manager: proxy hosts, redirections, SSL certificates, access lists | 2.0, on by default |
| `docker` | Containers, images and volumes through the local Docker socket or Portainer | 2.0, on by default |
| `dns` | Cloudflare DNS zones and records, and BIND export | 2.0, on by default |
| `home_assistant` | Entities, automations, scripts and system info in Home Assistant | 2.0, **off by default** |

Plus the cross-module workflows `expose_service`, `teardown_service`, `service_status`, `infrastructure_overview`, and `homelab_health`.

Homelab works with any MCP client: Claude Desktop, Claude Code, Cursor, VS Code, Sonique, Hermes, OpenClaw and others. It runs on your own machine and keeps no data of its own; it talks only to the services you configure.

## Install

Homelab needs Python 3.11 or newer. With [uv](https://docs.astral.sh/uv/) there is nothing to install ahead of time:

```bash
uvx homelab-infra-mcp --version
```

Or with pip:

```bash
pip install homelab-infra-mcp
```

Upgrading from 1.x? Version 2.0 changes the tool names and the environment variable names. Read the migration table in [CHANGELOG.md](CHANGELOG.md) first.

## Settings

Set these as environment variables in your MCP client's config, or put them in a config file (see below). You only need the settings for the modules you use. Homelab starts without any of them and tells you what is missing when you call a tool.

| Variable | Module | What it is |
|---|---|---|
| `HOMELAB_PROXY_URL` | proxy | Nginx Proxy Manager address. Default `http://localhost:81`. |
| `HOMELAB_PROXY_EMAIL` / `HOMELAB_PROXY_PASSWORD` | proxy | The NPM admin login used for the API |
| `HOMELAB_DOCKER_HOST` | docker | Docker engine address. Default `unix:///var/run/docker.sock`. |
| `HOMELAB_DOCKER_PORTAINER_URL` / `HOMELAB_DOCKER_PORTAINER_TOKEN` | docker | Use Portainer instead of the socket. Both are needed. |
| `HOMELAB_DOCKER_PORTAINER_ENDPOINT_ID` | docker | Portainer endpoint id. Default `1`. |
| `HOMELAB_DNS_API_TOKEN` | dns | Cloudflare API token with DNS edit permission on the zone |
| `HOMELAB_DNS_ZONE_ID` | dns | Default zone id, so tools can leave `zone_id` empty |
| `HOMELAB_HOME_ASSISTANT_URL` | home_assistant | Home Assistant address. Default `http://homeassistant.local:8123`. |
| `HOMELAB_HOME_ASSISTANT_TOKEN` | home_assistant | Long-lived access token |
| `HOMELAB_<MODULE>_ENABLED` | any | `true` or `false`. Turns a module on or off, e.g. `HOMELAB_HOME_ASSISTANT_ENABLED=true`. |
| `HOMELAB_<MODULE>_ALLOW_WRITES` | any | `false` by default: each change asks you first. `true` lets the assistant make changes in that module without asking. See [Safety](#safety). |
| `HOMELAB_READ_ONLY` | all | `true` refuses every change, whatever else is set. Reads and dry runs still work. |
| `HOMELAB_<MODULE>_<KEY>_FILE` | any | Read a setting from a file instead, e.g. `HOMELAB_DNS_API_TOKEN_FILE=/run/secrets/cf_token` |

**Config file (optional).** Homelab also reads `~/.config/homelab/config.toml`, or the file named by `HOMELAB_CONFIG`. Each module has its own table. Environment variables win over the file.

```toml
[proxy]
email = "admin@example.com"
password = "change-me"

[dns]
api_token = "your-cloudflare-token"
zone_id = "your-zone-id"

[home_assistant]
enabled = true
url = "http://homeassistant.local:8123"
token = "your-long-lived-token"
```

## Add it to your MCP client

Most clients use the same JSON shape. Put it where your client keeps MCP servers:

```json
{
  "mcpServers": {
    "homelab": {
      "command": "uvx",
      "args": ["homelab-infra-mcp"],
      "env": {
        "HOMELAB_PROXY_EMAIL": "admin@example.com",
        "HOMELAB_PROXY_PASSWORD": "change-me",
        "HOMELAB_DNS_API_TOKEN": "your-cloudflare-token",
        "HOMELAB_DNS_ZONE_ID": "your-zone-id"
      }
    }
  }
}
```

| Client | Where the config goes |
|---|---|
| Claude Desktop | `claude_desktop_config.json` (Settings → Developer → Edit Config) |
| Claude Code | `claude mcp add homelab -- uvx homelab-infra-mcp`, then add the `env` values, or a project `.mcp.json` |
| Cursor | `~/.cursor/mcp.json`, or `.cursor/mcp.json` in a project |
| VS Code | `.vscode/mcp.json`, using `"servers"` instead of `"mcpServers"` |
| Sonique, Hermes, OpenClaw, others | Any client that launches a stdio MCP server: command `uvx`, args `["homelab-infra-mcp"]`, plus the env values |

**Over HTTP.** For clients that connect to a URL instead of launching a process:

```bash
homelab-infra --transport http --port 8200
```

It serves streamable HTTP at `http://127.0.0.1:8200/mcp`. It listens only on your own machine by default. Put authentication in front of it before exposing it anywhere else.

## Tools

The default install has 15 tools. Turning on `home_assistant` adds 3.

| Tool | What it does |
|---|---|
| `homelab_modules` | Which modules are on, which settings are missing, and what each tool does. Call this first. |
| `homelab_health` | Connectivity and version for every enabled module |
| `expose_service` | Check a container, add a CNAME (optional), add a proxy host. One approved plan. |
| `teardown_service` | Remove a service's proxy host and optional DNS record. One approved plan. |
| `service_status` | One view of a service: container, proxy hosts, DNS records |
| `infrastructure_overview` | Counts across Docker, the proxy and DNS |
| `proxy_hosts` | `list`, `get`, `create`, `update`, `delete` proxy hosts |
| `proxy_redirections` | `list`, `create`, `delete` HTTP redirections |
| `proxy_certificates` | `list`, `request` a Let's Encrypt certificate |
| `proxy_access_lists` | `list`, `create`, `delete` IP access lists |
| `docker_containers` | `list`, `get`, `start`, `stop`, `restart`, `remove`, `logs`, `stats`, `prune` |
| `docker_images` | `list`, `pull`, `remove`, `prune` |
| `docker_inventory` | `volumes`, `networks`, or Portainer `stacks` (with a stack's compose file) |
| `dns_zones` | `list` zones, or `export` one in BIND format |
| `dns_records` | `list`, `get`, `create`, `update`, `delete` records |
| `ha_entities` | `list`, `get`, `search`; `call_service`, `turn_on`, `turn_off`, `toggle` (Home Assistant) |
| `ha_automations` | `list`, `trigger`, `reload` automations or scripts; `create` previews automation YAML (Home Assistant) |
| `ha_system` | Config, available services, `check_config` (Home Assistant) |

Every tool returns structured data with a published schema, so an assistant can write code against the results. Lists take `limit` and `offset`. Every change tool takes `dry_run=true`, which shows exactly what would change and changes nothing. Errors always look like `homelab.<module>.<code>: <message> Fix: <hint>`.

## Safety

- **Read-only tools never change anything.** The assistant can list, inspect, search and read logs freely.
- **Every change needs your approval.** When the assistant asks to change something, Homelab asks you directly through your MCP client (MCP elicitation) and shows the exact change: the domain, the target, the container, the DNS record. The assistant cannot answer for you. There is no "confirm" flag it can set.
- **Pre-approve only what you trust.** `HOMELAB_<MODULE>_ALLOW_WRITES=true` lets the assistant make changes in that module without asking. Use it for modules you are happy to automate, and leave it off for the rest.
- **Some clients can't ask you questions.** In those, a change fails with a message that names the setting to pre-approve, or the setting to leave alone.
- **Read-only mode.** `HOMELAB_READ_ONLY=true` refuses all changes, even pre-approved ones.
- **Docker socket access is root on the host.** Mount the socket read-only when you only need to look, and use Portainer if you would rather not mount it at all.
- Homelab only calls the services you configure. It sends nothing anywhere else and keeps no data.

## Develop

```bash
uv venv -p 3.11 .venv && uv pip install -e '.[dev]'
.venv/bin/pytest -q
python3 scripts/scan_identifiers.py --patterns <file> .
```

The tests never touch a real network or Docker engine. HTTP goes through `httpx.MockTransport`, and the Docker client is a fake.

## License

MIT. Published by Seaynic Labs.
