# Changelog

Homelab follows [semantic versioning](https://semver.org). Modules added after 2.0 ship switched off.

## 2.0.0 — unreleased

**Breaking.** The product is now called Homelab. The PyPI package name (`homelab-infra-mcp`) is unchanged. The tool surface, the environment variable names and the approval model all change. Migrate as described below.

### What changed

- **46 tools became 15** by default (18 with Home Assistant on). Each resource has one tool with an `action` argument, so the model loads a smaller set of definitions. No capability was dropped: every old tool has a new home (table below).
- **Approval replaces the self-confirmation design.** `set_mode`, `confirm_destructive` and the confirmation tokens are gone. A change now runs only after the person approves the exact change through MCP elicitation, or after you pre-approve the module with `HOMELAB_<MODULE>_ALLOW_WRITES=true`. A flag the model sets is never enough.
- **Read-only is the default.** `HOMELAB_READ_ONLY=true` refuses every change. Every change tool takes `dry_run=true` to preview without asking.
- **Typed results.** Every tool returns a pydantic model with a published output schema. Lists are paged with `limit` and `offset`.
- **One error shape:** `homelab.<module>.<code>: <message> Fix: <hint>`.
- **Missing config never crashes.** The server starts with an empty environment. A tool names the exact variable it needs.
- **Settings follow one pattern:** `HOMELAB_<KEY>` for core, `HOMELAB_<MODULE>_<KEY>` for modules, and `HOMELAB_<MODULE>_<KEY>_FILE` to read a secret from a file.
- **Modules can be switched off:** `HOMELAB_<MODULE>_ENABLED=false`. `home_assistant` is off by default.
- `homelab_modules` replaces `get_mode`: it reports the read-only state and whether each module's writes are pre-approved.
- `server.json` describes the package and version 2.0.0. Its schema is `2025-12-11`.
- The package reports its own version in `serverInfo` (it used to report the MCP SDK's version).
- The server runs over stdio (default) or streamable HTTP (`--transport http --port 8200`). The SSE transport is gone.
- `SECURITY.md` now points to GitHub private vulnerability reporting.

### Migrating from 1.x

Environment variables:

| 1.x | 2.0 |
|---|---|
| `NPM_URL` | `HOMELAB_PROXY_URL` |
| `NPM_EMAIL` / `NPM_PASSWORD` (or `*_FILE`) | `HOMELAB_PROXY_EMAIL` / `HOMELAB_PROXY_PASSWORD` |
| `DOCKER_HOST` | `HOMELAB_DOCKER_HOST` |
| `PORTAINER_URL` / `PORTAINER_TOKEN` / `PORTAINER_ENDPOINT_ID` | `HOMELAB_DOCKER_PORTAINER_URL` / `HOMELAB_DOCKER_PORTAINER_TOKEN` / `HOMELAB_DOCKER_PORTAINER_ENDPOINT_ID` |
| `CLOUDFLARE_API_TOKEN` | `HOMELAB_DNS_API_TOKEN` |
| `CLOUDFLARE_ZONE_ID` | `HOMELAB_DNS_ZONE_ID` |
| `DNS_PROVIDER` | removed (Cloudflare is the only DNS provider) |
| `HOME_ASSISTANT_URL` / `HA_TOKEN` | `HOMELAB_HOME_ASSISTANT_URL` / `HOMELAB_HOME_ASSISTANT_TOKEN` |
| `HOMELAB_MCP_MODULES=npm,docker,dns` | `HOMELAB_PROXY_ENABLED` etc. (proxy, docker, dns are on; home_assistant is off) |
| `HOMELAB_MCP_MODE=readonly` | `HOMELAB_READ_ONLY=true` |
| `HOMELAB_MCP_MODE=dryrun` | per call: `dry_run=true` |
| `HOMELAB_MCP_TRANSPORT`, `HOMELAB_MCP_PORT` | `--transport` and `--port` flags |
| `HOMELAB_SECRETS_DIR` (one file per secret) | `HOMELAB_<MODULE>_<KEY>_FILE` for each secret |

Client config: the command is now `uvx homelab-infra-mcp` (or `homelab-infra`). Server name `homelab`.

### Tool mapping: old to new

| 1.x tool | 2.0 home |
|---|---|
| `set_mode` | removed. Use `HOMELAB_READ_ONLY` and `HOMELAB_<MODULE>_ALLOW_WRITES` |
| `get_mode` | `homelab_modules` (`read_only`, `writes_preapproved`) |
| `confirm_destructive` | removed. The person approves the change itself (MCP elicitation) |
| `server_health` | `homelab_health` |
| `npm_list_proxy_hosts` | `proxy_hosts` action=`list` |
| `npm_get_proxy_host` | `proxy_hosts` action=`get` |
| `npm_create_proxy_host` | `proxy_hosts` action=`create` |
| `npm_update_proxy_host` | `proxy_hosts` action=`update` |
| `npm_delete_proxy_host` | `proxy_hosts` action=`delete` |
| `npm_list_ssl_certificates` | `proxy_certificates` action=`list` |
| `npm_request_ssl_certificate` | `proxy_certificates` action=`request` |
| `npm_list_redirections` | `proxy_redirections` action=`list` |
| `npm_create_redirection` | `proxy_redirections` action=`create` |
| `npm_delete_redirection` | `proxy_redirections` action=`delete` |
| `npm_list_access_lists` | `proxy_access_lists` action=`list` |
| `npm_create_access_list` | `proxy_access_lists` action=`create` |
| `npm_delete_access_list` | `proxy_access_lists` action=`delete` |
| `npm_health` | `homelab_health` (module `proxy`) |
| `docker_list_containers` | `docker_containers` action=`list` |
| `docker_get_container` | `docker_containers` action=`get` |
| `docker_start_container` | `docker_containers` action=`start` |
| `docker_stop_container` | `docker_containers` action=`stop` |
| `docker_restart_container` | `docker_containers` action=`restart` |
| `docker_remove_container` | `docker_containers` action=`remove` |
| `docker_container_logs` | `docker_containers` action=`logs` |
| `docker_container_stats` | `docker_containers` action=`stats` |
| `docker_prune_containers` | `docker_containers` action=`prune` |
| `docker_list_images` | `docker_images` action=`list` |
| `docker_pull_image` | `docker_images` action=`pull` |
| `docker_remove_image` | `docker_images` action=`remove` |
| `docker_prune_images` | `docker_images` action=`prune` |
| `docker_list_volumes` | `docker_inventory` kind=`volumes` |
| `docker_list_networks` | `docker_inventory` kind=`networks` |
| `docker_health` | `homelab_health` (module `docker`) |
| `docker_list_stacks` (Portainer) | `docker_inventory` kind=`stacks` |
| `docker_get_stack` (Portainer) | `docker_inventory` kind=`stacks` with `stack_id` |
| `dns_list_zones` | `dns_zones` action=`list` |
| `dns_export_zone` | `dns_zones` action=`export` |
| `dns_list_records` | `dns_records` action=`list` |
| `dns_get_record` | `dns_records` action=`get` |
| `dns_create_record` | `dns_records` action=`create` |
| `dns_update_record` | `dns_records` action=`update` |
| `dns_delete_record` | `dns_records` action=`delete` |
| `dns_health` | `homelab_health` (module `dns`) |
| `expose_service` | `expose_service` (adds `forward_host`, `dry_run`) |
| `teardown_service` | `teardown_service` (adds `dry_run`) |
| `service_status` | `service_status` |
| `infrastructure_overview` | `infrastructure_overview` |
| `hass_get_states` | `ha_entities` action=`list` |
| `hass_get_state` | `ha_entities` action=`get` |
| `hass_search_entities` | `ha_entities` action=`search` |
| `hass_call_service` | `ha_entities` action=`call_service` |
| `hass_turn_on` / `hass_turn_off` / `hass_toggle` | `ha_entities` action=`turn_on` / `turn_off` / `toggle` |
| `hass_list_automations` | `ha_automations` action=`list` kind=`automation` |
| `hass_trigger_automation` | `ha_automations` action=`trigger` kind=`automation` |
| `hass_create_automation` | `ha_automations` action=`create`. Returns the YAML; it no longer reports a failure |
| `hass_list_scripts` | `ha_automations` action=`list` kind=`script` |
| `hass_run_script` | `ha_automations` action=`trigger` kind=`script` |
| `hass_reload_automation` / `hass_reload_script` | `ha_automations` action=`reload` kind=`automation` / `script` |
| `hass_get_config` / `hass_list_services` / `hass_check_config` | `ha_system` action=`config` / `services` / `check_config` |

### Measurements

| | 1.0.1 | 2.0.0 |
|---|---|---|
| Tools, default modules | 46 | 15 |
| Tools, every module on | 63 | 18 |
| Tool definitions, default (JSON of `list_tools()`, output schemas included) | 27,021 bytes | 34,472 bytes (input schemas alone: 7,425) |
| Tool definitions, every module on | 37,817 bytes | 42,063 bytes (input schemas alone: 9,747) |

The byte total rises because every 2.0 tool publishes an output schema; 1.x tools returned plain text and had none. The count falls by two thirds.

## 1.0.1 — 2026-10-23

- Published to PyPI. Pins `mcp<2`. Declares `pyyaml` for the Home Assistant module.
- 46 tools by default, 63 with every module on.
