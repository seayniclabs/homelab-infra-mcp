---
name: homelab-health-check
description: Run a read-only sweep of the homelab across Homelab modules, containers, certificates, uptime monitors and DNS filtering, and report the results as one table. Use when the user asks for a health check, a status sweep, a morning check, or whether anything in the homelab needs attention. This skill never changes anything.
license: MIT
source: https://github.com/seayniclabs/homelab-infra-mcp
author: Seaynic Labs
---

# Homelab health check

This sweep reads state and changes nothing. Every call below is a read or a list. Do not pass `dry_run`, and do not call any tool that changes a resource. If a problem needs a change, name the skill that fixes it and stop.

## Steps

Run these in order. Skip any step whose module is off, and record the skip in the table.

1. **Modules.** Call `homelab_modules`. Note which modules are on.
2. **Connectivity.** Call `homelab_health`. Record each enabled module's result.
3. **Overview.** Call `infrastructure_overview`. Record the counts it returns across Docker, the proxy and DNS.
4. **Containers.** Call `docker_containers` with `action` set to `list`. Read every page: repeat the call with `offset` until a page is shorter than `limit`. Flag each container that is restarting, unhealthy, or exited.
5. **Certificates.** Call `proxy_certificates` with `action` set to `list`. Flag each certificate that expires within 14 days of today. Give the domain and the number of days left.
6. **Uptime monitors.** When the `uptime` module is on, call `uptime_monitors` with `action` set to `list`. Flag each monitor that is down or paused. Read every page.
7. **DNS filtering.** When the `dns_filter` module is on, call `dns_filter_status`. Record whether filtering is on and the query and block totals it returns.

## Report

Lead with one table. One row per check.

| Check | Result | Notes |
|---|---|---|
| Modules | 3 on, 5 off | Off: `home_assistant`, `uptime`, `tunnel`, `dns_filter`, `sso` |
| Connectivity | 3 of 3 reachable | `docker` reports the socket is reachable |
| Containers | 22 running, 1 restarting | `wiki-app` restarting |
| Certificates | 4 valid, 1 expires in 9 days | `photos.example.com`, 9 days |
| Uptime | 0 down | Skipped: module off |
| DNS filtering | Skipped | Module off |

Below the table, list the items that need attention, most severe first. For each item give the one next step and the skill that handles it:

- A container that is restarting or unhealthy: `homelab-troubleshooting`, then `containers`.
- A certificate that expires within 14 days: `homelab-troubleshooting`. Renewal is `proxy_certificates` with `action` set to `request`, which needs approval.
- A down uptime monitor: `homelab-troubleshooting` for the service behind it.

If nothing needs attention, say so in one line under the table. Give the counts. Do not add advice the sweep did not find.

## Rules

- Never change a container, proxy host, certificate, DNS record, monitor or filter rule during this sweep.
- Report a module that returns an error by its `homelab.<module>.<code>` message and its `Fix:` line, and continue with the other checks.
- Never print a secret value. Settings appear by name only.
