---
name: getting-started
description: Set up and check the Homelab MCP server. Covers which modules are on, the settings each module needs, how to switch a module on or off, the first checks, how approvals work, and how to read an error. Use when the user installs Homelab, asks what it can do, gets a homelab.<module>.<code> error, or wants a module turned on or off.
license: MIT
source: https://github.com/seayniclabs/homelab-infra-mcp
author: Seaynic Labs
---

# Get started with Homelab

Homelab connects an assistant to Nginx Proxy Manager, Docker, and Cloudflare DNS, and to four optional services. The first five minutes take four steps: see what is on, add the missing settings, run the first checks, and learn how approvals work.

## 1. See what is on

Call `homelab_modules` first. It returns each module with whether it is enabled, which settings are missing, and what each tool does. Report the missing settings by name. Never guess a value.

Default state:

| Module | Default | Tools |
|---|---|---|
| `proxy` | on | `proxy_hosts`, `proxy_redirections`, `proxy_certificates`, `proxy_access_lists` |
| `docker` | on | `docker_containers`, `docker_images`, `docker_inventory` |
| `dns` | on | `dns_zones`, `dns_records` |
| `home_assistant` | off | `ha_entities`, `ha_automations`, `ha_system` |
| `uptime` | off | `uptime_monitors` |
| `tunnel` | off | `tunnel_routes` |
| `dns_filter` | off | `dns_filter_status`, `dns_filter_queries`, `dns_filter_rules` |
| `sso` | off | `sso_applications` |

The core tools are always on: `homelab_modules`, `homelab_health`, `expose_service`, `teardown_service`, `service_status`, `infrastructure_overview`, `diagnose_service`.

## 2. Add the settings

Set each value as an environment variable in the MCP client's `env` block, or in `~/.config/homelab/config.toml`. Set `HOMELAB_CONFIG` to use a different file. Environment variables win over the file. Restart the MCP client after you change a setting.

Each module needs only its own settings:

| Module | Variables |
|---|---|
| `proxy` | `HOMELAB_PROXY_URL` (default `http://localhost:81`), `HOMELAB_PROXY_EMAIL`, `HOMELAB_PROXY_PASSWORD` |
| `docker` | `HOMELAB_DOCKER_HOST` (default `unix:///var/run/docker.sock`); for Portainer, `HOMELAB_DOCKER_PORTAINER_URL`, `HOMELAB_DOCKER_PORTAINER_TOKEN`, `HOMELAB_DOCKER_PORTAINER_ENDPOINT_ID` |
| `dns` | `HOMELAB_DNS_API_TOKEN`, `HOMELAB_DNS_ZONE_ID` |
| `home_assistant` | `HOMELAB_HOME_ASSISTANT_URL`, `HOMELAB_HOME_ASSISTANT_TOKEN` |
| `uptime` | `HOMELAB_UPTIME_URL`, `HOMELAB_UPTIME_API_KEY`; `HOMELAB_UPTIME_USERNAME` and `HOMELAB_UPTIME_PASSWORD` only for pause and resume |
| `tunnel` | `HOMELAB_TUNNEL_API_TOKEN`, `HOMELAB_TUNNEL_ACCOUNT_ID`, `HOMELAB_TUNNEL_TUNNEL_ID` |
| `dns_filter` | `HOMELAB_DNS_FILTER_URL`, `HOMELAB_DNS_FILTER_USERNAME`, `HOMELAB_DNS_FILTER_PASSWORD` |
| `sso` | `HOMELAB_SSO_URL`, `HOMELAB_SSO_TOKEN`, `HOMELAB_SSO_FLOW_SLUG` |

Any secret can come from a file instead: set `HOMELAB_<MODULE>_<KEY>_FILE` to the file path, for example `HOMELAB_PROXY_PASSWORD_FILE=/run/secrets/npm_password`. Secrets are `*_PASSWORD`, `*_TOKEN`, `*_API_KEY` and `*_API_TOKEN` values.

Config file example:

```toml
[proxy]
email = "admin@example.com"
password = "change-me"

[dns]
api_token = "your-cloudflare-token"
zone_id = "your-zone-id"
```

Every value above is a placeholder. Use the user's real values only in their own config.

## 3. Switch a module on or off

Set `HOMELAB_<MODULE>_ENABLED` to `true` or `false`. Examples: `HOMELAB_UPTIME_ENABLED=true`, `HOMELAB_DNS_FILTER_ENABLED=true`. Restart the MCP client, then call `homelab_modules` to confirm.

New modules ship off, so an update does not add tools until the user turns them on.

## 4. Run the first checks

Run these in order. All are read only.

1. `homelab_modules`: confirm which modules are on and which settings are missing.
2. `homelab_health`: connectivity and version for each enabled module.
3. `proxy_hosts` with `action` set to `list`: the proxy works and lists its hosts.
4. `docker_containers` with `action` set to `list`: the Docker socket or Portainer answers.
5. `dns_zones` with `action` set to `list`: the Cloudflare token reads its zones.

## 5. How approvals work

Homelab changes nothing on a read or a dry run. Every change asks the person first:

- The person approves each change in the MCP client, which shows the exact change: the domain, the container, the DNS record.
- The assistant cannot approve a change for the person. No argument sets approval.
- Every change tool accepts `dry_run` set to `true`. It shows the plan and changes nothing.
- Every decision goes into the approval log. The default path is `~/.local/state/homelab/approvals.jsonl`, or `$XDG_STATE_HOME/homelab/approvals.jsonl` when `XDG_STATE_HOME` is set. `HOMELAB_APPROVAL_LOG` overrides the path.

If the MCP client cannot show an approval prompt, the change returns `approval_unavailable`. The message names the setting that pre-approves the module, `HOMELAB_<MODULE>_ALLOW_WRITES=true`, or it says to leave changes alone. Explain both options to the user. Do not set `HOMELAB_<MODULE>_ALLOW_WRITES` yourself. Pre-approval applies to every change in that module, so it is the person's decision.

`HOMELAB_READ_ONLY=true` refuses every change, including pre-approved ones.

## 6. Diagnose a setup

Run `homelab-infra --doctor` in a terminal. It checks each enabled module's settings and reachability, the Docker socket access and the certificate tool. It prints a `FIX` line for each problem and exits with status 1 when something needs fixing.

## Errors

Every error reads `homelab.<module>.<code>: <message> Fix: <hint>`. The module tells you where to look. Pass the `Fix:` line to the user as written. If the error names a setting, check that the setting is set in the environment or the config file, then restart the MCP client.
