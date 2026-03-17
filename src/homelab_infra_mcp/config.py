"""Configuration from environment variables."""

import os


class Config:
    """Server configuration loaded from environment variables."""

    # NPM
    npm_url: str = os.environ.get("NPM_URL", "http://localhost:81")
    npm_email: str = os.environ.get("NPM_EMAIL", "")
    npm_password: str = os.environ.get("NPM_PASSWORD", "")

    # Docker
    docker_host: str = os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock")

    # DNS
    dns_provider: str = os.environ.get("DNS_PROVIDER", "cloudflare")
    cloudflare_api_token: str = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    cloudflare_zone_id: str = os.environ.get("CLOUDFLARE_ZONE_ID", "")

    # Server
    mode: str = os.environ.get("HOMELAB_MCP_MODE", "normal")  # normal, readonly, dryrun
    modules: list[str] = os.environ.get("HOMELAB_MCP_MODULES", "npm,docker,dns").split(",")
    log_level: str = os.environ.get("HOMELAB_MCP_LOG_LEVEL", "INFO")
    transport: str = os.environ.get("HOMELAB_MCP_TRANSPORT", "stdio")  # stdio or sse
    port: int = int(os.environ.get("HOMELAB_MCP_PORT", "8200"))


config = Config()
