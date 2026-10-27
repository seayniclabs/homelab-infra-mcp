---
name: fix-and-deploy
description: Fix a bug in a running homelab service, check the fix against the original symptom, apply it to the live container, proxy or DNS path, then check the live target again before reporting it fixed. Use when a fix must reach something already running, not only a commit or a local copy.
license: MIT
source: https://github.com/seayniclabs/homelab-infra-mcp
author: Seaynic Labs
---

# Fix and deploy

A fix counts as deployed when the live target shows the fix. A passing local test, a container that restarted, or a 200 from a health endpoint does not prove the reported bug is gone. Verify against the symptom the user reported, on the target where they saw it.

## The sequence

### 1. Reproduce the original symptom

Before you change anything, make the failure happen again:

- Record the exact target: the public URL, the container name, or the DNS name.
- Record the exact symptom: the status code, the error text, or the behavior.
- Run the request that failed. If you cannot reproduce it, you do not yet know what "fixed" means. Ask the user for the steps they took.

Use the `homelab-troubleshooting` skill to find the cause when it is not clear.

### 2. Fix the cause

Change one thing at a time. Write the cause in one sentence before you edit the config or image. Stop when the fix addresses that cause, not the symptom.

### 3. Check the fix before deploying

Check the fix where you made it. A local test or a dry run proves the change is valid. It does not prove the live service works. Call this the pre-deploy check, and report it as a separate step.

### 4. Deploy through Homelab

Every deploy change follows the dry run, go-ahead, approval flow. Pick the call that matches what changed:

| What changed | Call | Dry run first |
|---|---|---|
| Container image or config | `docker_containers` with `restart`, or `pull` then `restart` for a new image tag | Yes |
| Proxy host forward target or SSL | `proxy_hosts` with `update` | Yes |
| DNS record target | `dns_records` with `update` | Yes |
| Certificate after a domain change | `proxy_certificates` with `request` | Yes |

Show each dry-run plan to the user. The person approves each change in the MCP client. If the client returns `approval_unavailable`, stop and explain the setting that the message names. Do not set it yourself.

### 5. Check the live target against the original symptom

Repeat step 1's request exactly. Check these first:

- The container started after the deploy. Compare `docker_containers` with `get`: the state is `running`, and the start time is after the deploy. A container that did not restart still runs the old code.
- `diagnose_service` with the domain. Every hop passes.

### 6. Check the public path from outside

If the target is reachable from the internet, check it from outside your network. Use a phone on cellular data, or a request from a host that is not on the LAN. Run `curl -sI https://<domain>` from that host and repeat the failing request.

A check from inside the network can pass while the public path still fails. This is the step that catches a stale DNS record, a missing certificate or a proxy rule that only applies locally.

### 7. Report

Report four facts:

1. The original symptom, as the user reported it.
2. The cause and the change.
3. The pre-deploy check result.
4. The live result, from outside the network when the service is public.

Say "fixed" only after step 6 passes. If step 6 does not pass, say which hop failed and what you checked.

## The rule

If the target is public, the proof must be public too. A check that reaches the service only from the same machine proves less than the user's check.
