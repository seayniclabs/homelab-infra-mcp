# Security Policy

## Docker socket access

Docker socket access is equivalent to **root on the host**. Mount the socket read-only when you only need to look at containers. Starting, stopping, restarting and removing containers needs write access. Portainer is an alternative that avoids mounting the socket.

## Credentials

Proxy passwords, Cloudflare tokens, Portainer keys and Home Assistant tokens are read from environment variables, from files named by `HOMELAB_<MODULE>_<KEY>_FILE`, or from the config file. They are never written to logs or tool responses. `homelab_modules` reports whether a setting is set, never its value.

## Network transport

Keep the HTTP transport on `127.0.0.1` unless you put authentication in front of it. Do not expose it to the public internet without a reverse proxy and authentication.

## Changes need approval

Homelab does not let the model approve its own changes. Each change is shown to the person through MCP elicitation, or runs only if you pre-approve the module in settings. See the Safety section of the README.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting: open the repository's **Security** tab and choose **Report a vulnerability**. Please do not open a public issue for an unfixed security problem.
