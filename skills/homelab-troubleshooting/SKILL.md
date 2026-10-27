---
name: homelab-troubleshooting
description: Find the root cause of a failing homelab service in a fixed order: state the symptom, run the per-hop checks, gather evidence, test one hypothesis at a time, then verify against the live service. Use when a service is down, returns errors, reports healthy but does not work, has a broken name or certificate, or a container keeps restarting.
license: MIT
source: https://github.com/seayniclabs/homelab-infra-mcp
author: Seaynic Labs
---

# Troubleshoot a homelab service

A green signal often hides the fault. A container in state `running`, a health endpoint that returns 200, or an empty error list can all be true while the service fails for the user. Find the cause before you change anything, and prove it with evidence from the failing service.

## 1. State the symptom

Write two lines before any call:

- **Observed:** what you or the user saw, in their words. Example: "https://wiki.example.com returns 502 from a phone on cellular."
- **Expected:** what should happen. Example: "the wiki page loads."

Keep "the health check passes" out of the observed line. It is a signal, not the user's outcome.

## 2. Run the first checks

Run these three in order. Each is read only.

1. `homelab_health`: which modules can reach their services. A failed module stops the investigation there. Report the module's error and its `Fix:` line.
2. `diagnose_service` with `domain` set to the failing name. It checks each hop of the path and returns one row per hop, with the first failing hop and its fix. Read the rows in order. The first failing hop is the first suspect.
3. `service_status` for the service name. It gives one view of the container, proxy hosts and DNS records.

If `diagnose_service` names a fix for the first failing hop, verify that fix's claim before you apply it. The hop check is a probe, and a probe can be wrong.

## 3. Gather evidence for one suspect

Pick the single most likely cause from the first checks. Collect evidence for it only.

| Suspect | Evidence to collect | Tool |
|---|---|---|
| Container stopped or restarting | State, restart count, last 100 log lines | `docker_containers` with `get` and `logs` |
| Container running, service dead | Logs for errors; resource use | `docker_containers` with `logs` and `stats` |
| Proxy points at the wrong place | Forward host and port of the proxy host | `proxy_hosts` with `get` |
| Name does not resolve or points elsewhere | Record name, type and target | `dns_records` with `list` or `get` |
| Certificate missing or expired | Expiry date and domain list | `proxy_certificates` with `list` |
| Access blocked by a list | Access lists on the proxy | `proxy_access_lists` with `list` |
| Redirect loop or wrong redirect | Redirections | `proxy_redirections` with `list` |

Read the evidence. Write one sentence that names the cause and the proof. If the proof does not fit the symptom, drop that hypothesis and pick the next suspect. Test one hypothesis at a time.

## 4. Check the usual suspects

Most failures in a homelab match one of these patterns. Check the matching row before you invent a new cause.

| Pattern | Tell | Check |
|---|---|---|
| Liveness passes, function fails | Container `running`, HTTP 200 on a status page, but the app shows errors | Make a real request to the function and read the body |
| Forward target is `localhost` | The proxy returns 502 or 504 | From inside the proxy's network, the target must be the container name or the host address, not `localhost` |
| Stale DNS or wrong target | The name resolves to an old address, or to nothing | Compare the record's target with the current public address; check the record was saved |
| Certificate expired or not issued | Browser warning, or SSL error at the edge | `proxy_certificates` `list`: check the expiry date and the domain list |
| Old image still running | Fix is deployed but the symptom continues | Compare the container's start time and image with the last deploy; restart the container |
| Paged list read as complete | Container or record missing from results | Repeat the list with `offset`; a page full to `limit` has more rows |
| Crash loop | Restart count climbs; the same startup lines repeat | `docker_containers` `logs`; the first line of the loop shows the cause |
| Missing secret or setting | A tool returns `homelab.<module>.<code>` | Pass the `Fix:` line on as written |
| Scheduled job runs and does nothing | Exit code 0, no output | Read the job's own logs and the environment it runs in |
| Misleading name | A proxy host or record name suggests a role it does not have | Read the forward target before you act on the name |

## 5. Fix the cause

1. Write the cause as one sentence: "The proxy forwards to `localhost:8080`, which is the proxy's own port, so every request returns 502."
2. Plan the fix as the change tool call and its `dry_run` result.
3. Apply it after the user agrees in chat. The person approves the change in the MCP client.
4. A retry, a restart or a longer timeout without a stated cause is a patch. Use it only as a test, and say so.

## 6. Verify against the original symptom

1. Run `diagnose_service` for the domain again. Every hop must pass.
2. Repeat the request that failed. Use the same name, the same path and, where the user saw it, the same client.
3. If the service is reachable from outside your network, check it from outside. A check from inside the LAN can pass while the public path still fails.

Report the symptom as observed, the cause, the change, and the result of the repeated request.

## 7. Check the blast radius

Ask what else uses the same proxy host, DNS record, certificate, network or image. List those services with `proxy_hosts` `list` and `docker_containers` `list`. Fix them or name them in the report.

## 8. Record the cause

Write the symptom, cause, fix and the evidence line into the service's runbook. Use the `runbook` skill to create one when none exists. Record only confirmed causes. A guess in the record misleads the next person.
