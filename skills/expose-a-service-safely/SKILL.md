---
name: expose-a-service-safely
description: Put a homelab container on a public web address in a fixed order: check the container runs, check the name is free, show the dry-run plan, apply it with approval, then diagnose every hop until the name works from outside. Use when the user wants a service reachable from the internet or a new public domain, or wants to tear one down.
license: MIT
source: https://github.com/seayniclabs/homelab-infra-mcp
author: Seaynic Labs
---

# Expose a service safely

This workflow adds a public name for one container. It creates the DNS record and the proxy host in one approved plan, then checks each hop until the name works. Run the steps in order. Do not skip the dry run or the diagnosis.

Collect three values before you start:

- **Container name**, for example `wiki-app`.
- **Public domain**, for example `wiki.example.com`.
- **Port inside the container**, for example `8080`.

## 1. Check the container runs

Call `docker_containers` with `action` set to `get` on the container name.

- The state must be `running`. If it is not, stop. Use the `containers` skill to start it or read its logs first.
- Confirm the port is published or reachable on the Docker network the proxy uses.

## 2. Check the name is free

1. Call `proxy_hosts` with `action` set to `list`. Search the results for the domain. A host that already exists for the domain is a conflict. Stop and ask the user whether to update it.
2. When the `dns` module is on, call `dns_records` with `action` set to `list` for the zone. Search for the domain. Report any existing record and its target.

## 3. Show the dry-run plan

Call `expose_service` with `dry_run` set to `true`, the domain, and `forward_host` set to the container name and port, for example `wiki-app:8080`. Set the DNS record option only when the `dns` module is on and the user wants a record created.

Show the user the full plan:

- The DNS record: name, type and target.
- The proxy host: domain, forward host, forward port, SSL setting.
- Every other change the plan lists.

Ask for a go-ahead in chat. Do not run the real call before the user says yes.

## 4. Apply the plan

Call `expose_service` with the same arguments and no `dry_run`. The person approves the exact change in the MCP client.

- If the call returns `approval_unavailable`, stop. Explain the setting it names, `HOMELAB_<MODULE>_ALLOW_WRITES=true`, and the alternative of applying the change by hand in the proxy. Do not set the setting yourself.
- Record the result: what the tool created, and its ID if it returns one.

## 5. Diagnose every hop

Call `diagnose_service` with `domain` set to the public name. It returns one row per hop with its result. Read the rows in order and stop at the first failing hop.

Fix the first failing hop only. Then run `diagnose_service` again. Common failures:

| Failing hop | Likely cause | Fix |
|---|---|---|
| DNS record | Record missing, or not yet visible | Confirm the record in `dns_records` `get`. Allow a few minutes for the change to spread, then check again. |
| Proxy host | Forward target points at `localhost` or the wrong port | Update the proxy host to the container name and port. Dry run, then approval. |
| Certificate | Not issued yet | Call `proxy_certificates` with `action` set to `request` for the domain. Dry run, then approval. Let's Encrypt needs the DNS record to resolve first. |
| Service response | Container up, but the app returns an error | Read `docker_containers` `logs`. Use the `homelab-troubleshooting` skill. |

Do not change two things in one pass. Change one, run the diagnosis, then decide the next step.

## 6. Check from outside the network

When every hop passes, check the name from outside your network. Use a phone on cellular data, or a host that is not on the LAN:

```bash
curl -sI https://wiki.example.com
```

Report the status code and the first line of the response. Use this result as the final check.

## 7. Add access controls when the service needs them

- **No open ports.** When the `tunnel` module is on, call `tunnel_routes` with `action` set to `list` to see the routes. Use `add` to route the domain through the Cloudflare Tunnel. `add` and `remove` need approval, so dry run first. A tunnel route avoids opening inbound ports on the router.
- **Login in front of the service.** When the `sso` module is on, call `sso_applications` with `action` set to `create` for the host. It creates a proxy provider and an application for that one host, and needs approval. Finish the wiring in the proxy host's settings using the Authentik documentation, because Homelab does not change the proxy's advanced settings.
- **Only some networks.** Call `proxy_access_lists` with `action` set to `list`. Attach a list to the proxy host only when the user asks for it.

## 8. Tell the user where the approval log is

Every approval decision is written to the approval log. The default path is `~/.local/state/homelab/approvals.jsonl`. When `XDG_STATE_HOME` is set, the path is `$XDG_STATE_HOME/homelab/approvals.jsonl`. `HOMELAB_APPROVAL_LOG` overrides it. Tell the user the path so they can review what was approved.

## Tearing a service down

Reverse the steps. Call `teardown_service` with `dry_run` set to `true`, show the plan to the user, then call it again with the approval. The plan removes the proxy host and, when the user asks, the DNS record. Confirm the domain no longer resolves after the change.
