# Security Policy

## Docker socket access

Docker socket access is equivalent to **root on the host**. Mount the socket read-only when you only need to look at containers. Starting, stopping, restarting and removing containers needs write access. Portainer is an alternative that avoids mounting the socket.

## Credentials

Secrets are read from environment variables, from files named by `HOMELAB_<MODULE>_<KEY>_FILE`, or from the config file. They are never written to logs or tool responses. `homelab_modules` reports whether a setting is set, never its value.

The secrets Homelab reads:

- Nginx Proxy Manager password (`HOMELAB_PROXY_PASSWORD`)
- Cloudflare DNS API token (`HOMELAB_DNS_API_TOKEN`) and Cloudflare Tunnel API token (`HOMELAB_TUNNEL_API_TOKEN`). Treat a tunnel token as a credential that can change public routes.
- Portainer API key (`HOMELAB_DOCKER_PORTAINER_TOKEN`)
- Home Assistant long-lived token (`HOMELAB_HOME_ASSISTANT_TOKEN`)
- Uptime Kuma API key (`HOMELAB_UPTIME_API_KEY`), used only to read `/metrics`
- AdGuard Home password (`HOMELAB_DNS_FILTER_PASSWORD`)
- Authentik API token (`HOMELAB_SSO_TOKEN`)

Give each token the narrowest scope the module needs. A read-only token suits a module you only inspect. Rotate a token when you stop using a module or when a config file leaves your machine.

## Network transport

Keep the HTTP transport on `127.0.0.1` unless you put authentication in front of it. Do not expose it to the public internet without a reverse proxy and authentication.

Homelab calls only the services you configure. It has no telemetry and sends nothing to any other host.

## Changes need approval

Homelab does not let the model approve its own changes. Each change is shown to the person through MCP elicitation, or runs only if you pre-approve the module in settings. See the Safety section of the README.

## Approval log

Every approve, decline and refusal is written to a local file. The default path is `~/.local/state/homelab/approvals.jsonl`, or `$XDG_STATE_HOME/homelab/approvals.jsonl` when `XDG_STATE_HOME` is set. `HOMELAB_APPROVAL_LOG` chooses another path. The log stays on your machine and Homelab never sends it anywhere.

## Diagnosis is read only

`diagnose_service` makes read-only calls only. It reads proxy hosts, DNS records, certificates and container state, and it changes nothing. Its fix lines are suggestions for the person to approve, not actions the tool takes.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting: open the repository's **Security** tab and choose **Report a vulnerability**. Please do not open a public issue for an unfixed security problem.
