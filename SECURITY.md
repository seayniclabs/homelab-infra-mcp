# Security Policy

## Docker socket access

Docker socket access is equivalent to **root on the host**. Mount the socket read-only when you only need observability; start/stop/restart/remove require write access.

Do not expose the MCP SSE transport (`HOMELAB_MCP_TRANSPORT=sse`) to the public internet without authentication and a reverse proxy in front.

## Credentials

NPM passwords, Cloudflare tokens, and Portainer API keys are read from environment variables or local secret files. They are **never** written to logs or tool responses.

## Reporting

Report vulnerabilities to support@seayniclabs.com. Do not open public issues for undisclosed security bugs.
