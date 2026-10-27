# Homelab

<!-- mcp-name: io.github.seayniclabs/homelab-infra-mcp -->

Homelab is an MCP server that lets an AI assistant manage Nginx Proxy Manager proxy hosts, Docker containers and Cloudflare DNS records from one place. It covers the path from a container to a public web address. One call, `expose_service`, checks the container, adds the DNS record and the proxy host, and shows the plan before anything changes. Four more optional modules cover Uptime Kuma, Cloudflare Tunnel, AdGuard Home and Authentik.

It is a **bundle**: one server made of modules, plus skills that teach the assistant the workflows. You switch on the modules you use. New modules arrive switched off, so an update never changes what your assistant can do until you choose to.

**Audience:** self-hosters running a homelab.

| Module | What it does | Status |
|---|---|---|
| `proxy` | Nginx Proxy Manager: proxy hosts, redirections, SSL certificates, access lists | On by default |
| `docker` | Containers, images and volumes through the local Docker socket or Portainer | On by default |
| `dns` | Cloudflare DNS zones and records, and BIND export | On by default |
| `home_assistant` | Entities, automations, scripts and system info in Home Assistant | Off by default, turn on with `HOMELAB_HOME_ASSISTANT_ENABLED=true` |
| `uptime` | Uptime Kuma monitors: list and read status (read only) | Off by default, turn on with `HOMELAB_UPTIME_ENABLED=true` |
| `tunnel` | Cloudflare Tunnel routes: list, add and remove | Off by default, turn on with `HOMELAB_TUNNEL_ENABLED=true` |
| `dns_filter` | AdGuard Home: filter status, query log and filter rules | Off by default, turn on with `HOMELAB_DNS_FILTER_ENABLED=true` |
| `sso` | Authentik: list applications, create a proxy provider and application for one host | Off by default, turn on with `HOMELAB_SSO_ENABLED=true` |

The core tools are always on: `homelab_modules`, `homelab_health`, `expose_service`, `teardown_service`, `service_status`, `infrastructure_overview` and `diagnose_service`.

Homelab works with any MCP client: Claude Desktop, Claude Code, Cursor, VS Code, Sonique, Hermes, OpenClaw and others. It runs on your own machine and keeps no data of its own. It talks only to the services you configure.

## Install

Homelab needs Python 3.11 or newer. With [uv](https://docs.astral.sh/uv/) there is nothing to install ahead of time. Pin the version so updates arrive only when you choose them:

```bash
uvx homelab-infra-mcp==2.1.0 --version
```

Or with pip:

```bash
pip install homelab-infra-mcp==2.1.0
```

Upgrading from 2.0? Version 2.1 has no breaking changes. The four new modules are off by default. Read the 2.1.0 section of [CHANGELOG.md](CHANGELOG.md).

Upgrading from 1.x? Version 2.0 changed the tool names and the environment variable names. Read the migration table in [CHANGELOG.md](CHANGELOG.md) first.

### Quick install

Add the server to your MCP client (see [Add it to your MCP client](#add-it-to-your-mcp-client)), set the variables for the modules you use, and restart the client. Then ask the assistant to call `homelab_modules`. The response lists each module, whether it is on, and which settings are missing.

### Doctor

Run `homelab-infra --doctor` in a terminal before you start, and after any settings change:

```bash
homelab-infra --doctor
```

The doctor checks each enabled module's settings and reachability, the Docker socket access, and the TLS check. It prints a `FIX` line for each problem and exits with status 1 when something needs fixing.

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
| `HOMELAB_UPTIME_URL` | uptime | Uptime Kuma address |
| `HOMELAB_UPTIME_API_KEY` | uptime | Uptime Kuma API key. Read from `/metrics`, used for `list` and `get`. |
| `HOMELAB_TUNNEL_API_TOKEN` | tunnel | Cloudflare API token with tunnel edit permission |
| `HOMELAB_TUNNEL_ACCOUNT_ID` | tunnel | Cloudflare account id that owns the tunnel |
| `HOMELAB_TUNNEL_TUNNEL_ID` | tunnel | Cloudflare Tunnel id |
| `HOMELAB_DNS_FILTER_URL` | dns_filter | AdGuard Home address |
| `HOMELAB_DNS_FILTER_USERNAME` / `HOMELAB_DNS_FILTER_PASSWORD` | dns_filter | AdGuard Home login |
| `HOMELAB_SSO_URL` | sso | Authentik address |
| `HOMELAB_SSO_TOKEN` | sso | Authentik API token |
| `HOMELAB_SSO_FLOW_SLUG` | sso | Authorization flow slug that new proxy providers use |
| `HOMELAB_<MODULE>_ENABLED` | any | `true` or `false`. Turns a module on or off, e.g. `HOMELAB_UPTIME_ENABLED=true`. |
| `HOMELAB_<MODULE>_ALLOW_WRITES` | any | `false` by default: each change asks you first. `true` lets the assistant make changes in that module without asking. See [Safety](#safety). |
| `HOMELAB_READ_ONLY` | all | `true` refuses every change, whatever else is set. Reads and dry runs still work. |
| `HOMELAB_<MODULE>_<KEY>_FILE` | any | Read a secret from a file instead, e.g. `HOMELAB_DNS_API_TOKEN_FILE=/run/secrets/cf_token` |
| `HOMELAB_CONFIG` | core | Path to the config file. Default `~/.config/homelab/config.toml`. |
| `HOMELAB_APPROVAL_LOG` | core | Path to the approval log. Default `~/.local/state/homelab/approvals.jsonl`, or `$XDG_STATE_HOME/homelab/approvals.jsonl` when `XDG_STATE_HOME` is set. |

**Config file (optional).** Homelab also reads `~/.config/homelab/config.toml`, or the file named by `HOMELAB_CONFIG`. Each module has its own table. Environment variables win over the file.

```toml
[proxy]
email = "admin@example.com"
password = "change-me"

[dns]
api_token = "your-cloudflare-token"
zone_id = "your-zone-id"
```

Turn a module on in the same file with its `enabled` key, or with `HOMELAB_<MODULE>_ENABLED=true` in the environment.

## Add it to your MCP client

Most clients use the same JSON shape. Pin the version so the server runs the release you tested. Put the block where your client keeps MCP servers:

```json
{
  "mcpServers": {
    "homelab": {
      "command": "uvx",
      "args": ["homelab-infra-mcp==2.1.0"],
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
| Claude Code | `claude mcp add homelab -- uvx homelab-infra-mcp==2.1.0`, then add the `env` values, or a project `.mcp.json` |
| Cursor | `~/.cursor/mcp.json`, or `.cursor/mcp.json` in a project |
| VS Code | `.vscode/mcp.json`, using `"servers"` instead of `"mcpServers"` |
| Sonique, Hermes, OpenClaw, others | Any client that launches a stdio MCP server: command `uvx`, args `["homelab-infra-mcp==2.1.0"]`, plus the env values |

**As a Claude Code plugin.** The plugin installs the server and the skills together. Its `.mcp.json` pins `homelab-infra-mcp==2.1.0`. Set the variables in your environment or in the config file.

**Over HTTP.** For clients that connect to a URL instead of launching a process:

```bash
homelab-infra --transport http --port 8200
```

It serves streamable HTTP at `http://127.0.0.1:8200/mcp`. It listens only on your own machine by default. Put authentication in front of it before exposing it anywhere else.

## Tools

The default install has 16 tools. Each module adds its own tools when you turn it on.

| Tool | What it does |
|---|---|
| `homelab_modules` | Which modules are on, which settings are missing, and what each tool does. Call this first. |
| `homelab_health` | Connectivity and version for every enabled module |
| `expose_service` | Check a container, add a DNS record (optional), add a proxy host. One approved plan. |
| `teardown_service` | Remove a service's proxy host and optional DNS record. One approved plan. |
| `service_status` | One view of a service: container, proxy hosts, DNS records |
| `infrastructure_overview` | Counts across Docker, the proxy and DNS |
| `diagnose_service` | Read only. Checks each hop from a domain to its service, one row per hop. Returns the first failing hop and its fix. |
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
| `uptime_monitors` | `list`, `get`: read only (Uptime Kuma). Pause and resume are not in 2.1. |
| `tunnel_routes` | `list`; `add`, `remove` need approval (Cloudflare Tunnel) |
| `dns_filter_status` | Filter status and query and block totals (AdGuard Home, read only) |
| `dns_filter_queries` | Paged query log (AdGuard Home, read only) |
| `dns_filter_rules` | `list` blocked services and custom rules; `add`, `remove` need approval (AdGuard Home) |
| `sso_applications` | `list`; `create` makes a proxy provider and an application for one host, and needs approval (Authentik) |

Every tool returns structured data with a published schema, so an assistant can write code against the results. Lists take `limit` and `offset`. Every change tool takes `dry_run=true`, which shows exactly what would change and changes nothing. Errors always look like `homelab.<module>.<code>: <message> Fix: <hint>`.

## Skills

Skills are short guides the assistant reads before a job. Homelab ships them in a `skills/` folder for apps that read Agent Skills, and serves each one as an MCP prompt for every other client.

**Written for Homelab**

| Skill | What it covers |
|---|---|
| `getting-started` | Which modules are on, the settings each needs, the first checks, how approvals work |
| `expose-a-service-safely` | Put one container on a public name: dry run, approval, per-hop diagnosis, outside check |
| `homelab-health-check` | A read-only sweep of modules, containers, certificates, monitors and DNS filtering |
| `homelab-troubleshooting` | Root-cause investigation for a failing service, one hypothesis at a time |
| `fix-and-deploy` | Verify a fix against the original symptom, deploy it, check the live target |
| `containers` | Status, logs, restarts, stats and images for Docker containers |
| `runbook` | An operational runbook for one service, with facts pulled from the live tools |
| `diagram` | An editable draw.io file from a description |
| `network-diagram` | A draw.io map of services, Docker networks, the proxy and the DNS path |

**Third-party, under their own licenses**

| Skill | Author | License |
|---|---|---|
| `systematic-debugging` | Jesse Vincent, [obra/superpowers](https://github.com/obra/superpowers) | MIT |
| `cloudflare`, `cloudflare-one` | Cloudflare, [cloudflare/skills](https://github.com/cloudflare/skills) | Apache-2.0 |
| `dashmotion` | csthink, [csthink/dashmotion](https://github.com/csthink/dashmotion) | MIT |
| `architecture-diagram` | Cocoon-AI, [architecture-diagram-generator](https://github.com/Cocoon-AI/architecture-diagram-generator) | MIT |

Each third-party skill keeps its license file. See [CREDITS.md](CREDITS.md) for the pinned upstream commits.

## Try these

1. `Call homelab_modules and tell me which modules are on and which settings are missing.`
2. `Show every container that is restarting or unhealthy, with its last ten log lines.`
3. `Dry-run expose_service for wiki-app on wiki.example.com, port 8080, and show me the plan.`
4. `Diagnose wiki.example.com and fix the first failing hop.`
5. `Run the homelab health check and give me one table.`

## Safety

- **Read-only tools never change anything.** The assistant can list, inspect, search and read logs freely. `diagnose_service` makes read-only calls only.
- **Every change needs your approval.** When the assistant asks to change something, Homelab asks you directly through your MCP client (MCP elicitation) and shows the exact change: the domain, the target, the container, the DNS record. The assistant cannot answer for you. No argument it sets counts as approval.
- **Every decision is logged.** Each approve, decline and refusal goes into a local approval log. The default path is `~/.local/state/homelab/approvals.jsonl`. Set `HOMELAB_APPROVAL_LOG` to choose another path.
- **Dry runs show the plan.** Every change tool accepts `dry_run=true`. It shows what would change and changes nothing.
- **Pre-approve only what you trust.** `HOMELAB_<MODULE>_ALLOW_WRITES=true` lets the assistant make changes in that module without asking. Use it for modules you are happy to automate, and leave it off for the rest.
- **Some clients can't ask you questions.** In those, a change returns `approval_unavailable`, and the message names the setting to pre-approve or the setting to leave alone.
- **Read-only mode.** `HOMELAB_READ_ONLY=true` refuses all changes, even pre-approved ones.
- **Secrets stay out of responses.** Tokens, passwords and keys come from the environment, a file, or the config file. `homelab_modules` reports whether a setting is set, never its value.
- **Docker socket access is root on the host.** Mount the socket read-only when you only need to look, and use Portainer if you would rather not mount it at all.
- **Tunnel and SSO changes reach the public internet.** Review each `tunnel_routes` and `sso_applications` plan before you approve it.
- Homelab only calls the services you configure. It sends nothing anywhere else and keeps no data.

See [SECURITY.md](SECURITY.md) for the secrets list, the approval log and the reporting process.

<!-- security-card:start (generated by scripts/security_card.py) -->
| Security card | |
|---|---|
| Network | Only the services you configure: your Nginx Proxy Manager, your Docker engine or Portainer, api.cloudflare.com (DNS and Tunnel), and the Uptime Kuma, AdGuard Home, Authentik and Home Assistant addresses you set. diagnose_service also opens TCP and TLS connections to your upstreams and public domains. No telemetry. |
| Files | Reads its config file (~/.config/homelab/config.toml). Writes one local approval log (~/.local/state/homelab/approvals.jsonl), which never leaves the machine. |
| Secrets | API keys, tokens and passwords come from your environment or config file. They are never tool arguments and never returned to the model. |
| Read-only tools | 7: `docker_inventory`, `dns_zones`, `service_status`, `infrastructure_overview`, `diagnose_service`, `homelab_modules`, `homelab_health` |
| Needs your approval | `proxy_hosts`, `proxy_redirections`, `proxy_certificates`, `proxy_access_lists`, `docker_containers`, `docker_images`, `dns_records`, `expose_service`, `teardown_service`: you approve each change in your app, or pre-approve a module in settings. The AI cannot approve for you. |
| Startup cost | about 10,200 tokens (16 tools, 14 skill prompts) |
| Changes | Tool descriptions are locked by hash (`tool-manifest.lock.json`); CI fails if they change silently. |
<!-- security-card:end -->

## Develop

```bash
uv venv -p 3.11 .venv && uv pip install -e '.[dev]'
.venv/bin/pytest -q
python3 scripts/scan_identifiers.py --patterns <file> .
```

The tests never touch a real network or Docker engine. HTTP goes through `httpx.MockTransport`, and the Docker client is a fake.

## License

MIT. See [LICENSE](LICENSE). Third-party skills keep their own licenses; see [CREDITS.md](CREDITS.md).

---

## Made by Seaynic Labs

| | |
|---|---|
| **Publisher** | [Seaynic Labs](https://seayniclabs.com) |
| **Source** | [github.com/seayniclabs/homelab-infra-mcp](https://github.com/seayniclabs/homelab-infra-mcp) |
| **Report a vulnerability** | GitHub private vulnerability reporting (see [SECURITY.md](SECURITY.md)) |
| **Credits** | [CREDITS.md](CREDITS.md) |
