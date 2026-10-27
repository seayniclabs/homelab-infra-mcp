---
name: containers
description: Check, read, restart and inspect Docker containers on a homelab through the docker tools, with a dry run before every change. Use when the user asks for container status, logs, resource use, a restart, or wants a container started, stopped, removed or its images pulled or pruned.
license: MIT
source: https://github.com/seayniclabs/homelab-infra-mcp
author: Seaynic Labs
---

# Manage containers

This skill uses three tools from the `docker` module: `docker_containers`, `docker_images` and `docker_inventory`. The module is on by default. If a call says the module is off, turn it on with `HOMELAB_DOCKER_ENABLED=true`.

If the user gives no action, list these and ask which one they need: `status`, `health`, `logs`, `restart`, `stats`, `images`.

## status

1. Call `docker_containers` with `action` set to `list`.
2. Present a table: Container | State | Health | Image. Use only the fields the tool returns.
3. Put every container that is stopped, exited, restarting or unhealthy at the top of the table.
4. If a container is down, offer the next step: `logs` first, then `restart`.

Lists return one page. Read the page size from `limit`. If the page is full, call again with `offset` set to the number of rows already read. Do not say "all containers are up" until a page comes back shorter than `limit`.

## health

1. Call `homelab_health` to confirm the Docker module can reach the engine.
2. Call `docker_containers` with `action` set to `list` and read every page.
3. Report two lists: containers not running or restarting, and containers whose health check fails. Name each one with its state.
4. If both lists are empty, report the count of running containers and stop.

## logs

1. Call `docker_containers` with `action` set to `logs` and the container name. Ask for 50 lines when the user gives no count.
2. Quote each line that contains `error`, `warn`, `fatal`, `panic`, `exception`, `refused`, `denied` or `timeout`.
3. Summarize in one sentence: healthy operation, a repeating error, a startup failure, or a crash loop. Use the timestamps to tell a crash loop (the same startup lines repeat) from one error that happened once.
4. For the most frequent error, name the next check: the dependency it cannot reach, the port, the mounted path, or the name of the environment variable that is missing. Name variables only. Never print their values.
5. Redact any token, password or key that appears in a log line before you show it.

## restart

A restart changes a running service, so it goes through the approval flow.

1. Call `docker_containers` with `action` set to `restart`, the container name and `dry_run` set to `true`. Show the plan: container, current state, and what happens.
2. Get a go-ahead from the user in chat.
3. Call the same request without `dry_run`. The person approves the change in the MCP client. If the call returns `approval_unavailable`, stop, report the message, and explain the setting it names. Do not set that setting yourself.
4. Verify: call `docker_containers` with `action` set to `get` for the container. The state must read `running`.
5. Read the last 50 lines of logs. Report startup warnings.
6. Report four facts: container name, state before, state after, warnings.

A restart does not fix a bad image or a bad configuration. If the container restarts into the same error, stop and use the `homelab-troubleshooting` skill.

**Compose stacks.** Homelab has no compose-stack tool. Restart a multi-container stack on the host with `docker compose restart` in the stack's directory, or restart each container with `docker_containers`. With Portainer, `docker_inventory` with `kind` set to `stacks` lists each stack. Pass `stack_id` to get one stack's compose file.

## stats

Call `docker_containers` with `action` set to `stats`. Report CPU and memory per container in one table. Flag any container whose memory use is above 85% of its limit when the container has a limit set.

## stop, start and remove

Each one follows the restart flow: dry run, go-ahead in chat, approved call, verification.

- `stop` ends the process. Say so in the plan and name the dependent services that will fail.
- `start` runs a stopped container. Check its state after the call.
- `remove` deletes the container and its writable layer. Say so in the plan. Named volumes stay on the host.

Homelab lists volumes and networks through `docker_inventory` with `kind` set to `volumes` or `networks`. It does not delete volumes. Tell the user to remove a volume on the host themselves.

## images

- `docker_images` with `action` set to `list` shows local images.
- `pull` fetches a tag. Run it with `dry_run` first, then approval.
- `remove` and `prune` delete images. Run `prune` with `dry_run` first and report how many images it would remove before the approved call.

## Running commands inside a container

Homelab has no tool that runs a command inside a container. Tell the user the exact command to run on the host, for example `docker exec -it <container> sh`, and read the output they paste back. Do not suggest a command that writes to the container.

## Errors

Every error reads `homelab.docker.<code>: <message> Fix: <hint>`. Pass the `Fix:` line to the user as written.
