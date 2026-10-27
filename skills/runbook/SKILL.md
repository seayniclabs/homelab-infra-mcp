---
name: runbook
description: Write an operational runbook for one homelab service as a Markdown file, with the container, proxy host and DNS facts pulled from the live tools. Use when the user asks for a runbook, an SOP, or a document that explains how to operate, restart, roll back or troubleshoot one service.
license: MIT
source: https://github.com/seayniclabs/homelab-infra-mcp
author: Seaynic Labs
---

# Write a runbook for one service

This skill writes `Runbooks/runbook-<slug>.md` in the current working directory. It reads live facts from Homelab first, so the commands and names in the runbook match the running system.

## 1. Collect the inputs

Ask only for what the user did not give:

- **Service name** (required). Use the name the user uses, for example "Nginx Proxy Manager". Keep it unslugified in the frontmatter.
- **One-line summary** (required). One sentence that says what the service does.
- **Owner** (optional). Use `TBD` when the user skips it.

## 2. Pull the facts (read only)

These calls change nothing.

1. `docker_containers` with `action` set to `get` on the container. Record the image, the state and the published ports.
2. `docker_containers` with `action` set to `logs` and 50 lines. Use the output for the troubleshooting section.
3. `proxy_hosts` with `action` set to `list`. Find the host whose domain names the service. Record the domain, the forward host, the forward port and whether SSL is on.
4. `dns_records` with `action` set to `list` for the zone that holds the domain. Record the record name, type and target. Skip this step when the `dns` module is off, and write "DNS: not managed by Homelab" in the runbook.
5. `proxy_certificates` with `action` set to `list`. Record the expiry date for the domain.

If a call returns no match, write the gap into the runbook as a line to fill in. Do not invent a value.

## 3. Write the file

1. Create `Runbooks/` in the current directory if it does not exist.
2. Slugify the service name: lowercase, spaces and symbols become hyphens, no leading or trailing hyphens. "Nginx Proxy Manager" becomes `runbook-nginx-proxy-manager.md`.
3. If the file exists, show the user the path and ask before overwriting.
4. Write the file with the template below. Replace each placeholder with a fact from step 2 or the user's answer.
5. Report the path as a Markdown link. Do not open the file.

## Template

```markdown
---
tags: [runbook]
created: <YYYY-MM-DD>
updated: <YYYY-MM-DD>
status: draft
service: <service name>
owner: <owner>
last_verified: <YYYY-MM-DD>
review_cadence: quarterly
---

# Runbook: <service name>

## Overview

<one-line summary>

**Use this runbook when:**
- <situation that starts this procedure>

## Facts

| Item | Value |
|---|---|
| Container | <name>, image <image>, state <state> |
| Public name | <domain>, SSL <on or off>, certificate expires <date> |
| Forward target | <forward host>:<forward port> |
| DNS record | <record name> <type> <target>, or "not managed by Homelab" |

## Prerequisites

| Requirement | Details |
|---|---|
| Homelab tools | `docker` module on; `proxy` module on; `dns` module on if the DNS row is used |
| Secrets | Name each secret and its setting, such as `HOMELAB_PROXY_PASSWORD` or `HOMELAB_PROXY_PASSWORD_FILE`. Never the value. |

## Procedure

### Step 1: <title>

**Action:** `docker_containers` with `action` set to `<action>`, container `<name>`.

**Expected result:** <what the tool returns when the step works>

**Verify:** <the check that confirms the step>

Repeat for each step. Every change step starts with `dry_run` set to `true` and ends with the approved call.

## Rollback

Undo the steps in reverse order.

1. <undo step for step 2>
2. <undo step for step 1>

## Troubleshooting

### <symptom 1>

- **Symptom:** <what the user sees>
- **Cause:** <why it happens>
- **Fix:** <the exact tool call or host command>

## Escalation

| Order | Who | How | When |
|---|---|---|---|
| 1 | <owner> | <channel> | <threshold> |

Include the runbook path, the exact error text, and the time the failure started.

## Change log

| Date | Author | Change |
|---|---|---|
| <YYYY-MM-DD> | <author> | Initial draft |
```

## Rules for the content

- Write every procedure step as the Homelab tool call it uses, with its arguments.
- Put the expected result beside each step. A step without an expected result is not finished.
- Name the setting for each secret. Never write a secret value into the file.
- Keep the file to the sections above. Remove a section that has no content, and say so in the report.
