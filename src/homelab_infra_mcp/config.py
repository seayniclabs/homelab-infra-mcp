"""Configuration from environment variables."""

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("homelab-infra-mcp")

_SECRETS_DIR = Path("/Volumes/data/secrets")


def _read_secret(name: str) -> str:
    """Load a secret from env or /Volumes/data/secrets/<name> (never logged)."""
    env_key = name.upper()
    if os.environ.get(env_key):
        return os.environ[env_key]
    path = _SECRETS_DIR / name
    if path.is_file():
        return path.read_text().strip()
    return ""


def _read_env_or_file(env_var: str, file_env_var: str, secret_name: str) -> str:
    """Prefer direct env, then explicit file path env, then default secrets file."""
    if os.environ.get(env_var):
        return os.environ[env_var]
    file_path = os.environ.get(file_env_var, "")
    if file_path:
        path = Path(file_path)
        if path.is_file():
            return path.read_text().strip()
    return _read_secret(secret_name)


def _normalize_mode(mode: str) -> str:
    aliases = {
        "read-only": "readonly",
        "dry-run": "dryrun",
        "normal": "normal",
        "readonly": "readonly",
        "dryrun": "dryrun",
    }
    return aliases.get(mode.strip().lower(), mode.strip().lower())


class Config:
    """Server configuration loaded from environment variables."""

    npm_url: str = os.environ.get("NPM_URL", "http://localhost:81")
    npm_email: str = _read_env_or_file("NPM_EMAIL", "NPM_EMAIL_FILE", "npm_admin_email")
    npm_password: str = _read_env_or_file("NPM_PASSWORD", "NPM_PASSWORD_FILE", "npm_password")

    docker_host: str = os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock")
    portainer_url: str = os.environ.get("PORTAINER_URL", "").rstrip("/")
    portainer_token: str = os.environ.get("PORTAINER_TOKEN", "") or _read_secret(
        "code_server_portainer_token"
    )
    portainer_endpoint_id: int = int(os.environ.get("PORTAINER_ENDPOINT_ID", "1"))

    dns_provider: str = os.environ.get("DNS_PROVIDER", "cloudflare")
    cloudflare_api_token: str = os.environ.get("CLOUDFLARE_API_TOKEN", "") or _read_secret(
        "cloudflare_api_token"
    )
    cloudflare_zone_id: str = os.environ.get("CLOUDFLARE_ZONE_ID", "")

    home_assistant_url: str = os.environ.get(
        "HOME_ASSISTANT_URL", "http://homeassistant.local:8123"
    )

    mode: str = _normalize_mode(os.environ.get("HOMELAB_MCP_MODE", "normal"))
    modules: list[str] = [
        m.strip()
        for m in os.environ.get("HOMELAB_MCP_MODULES", "npm,docker,dns").split(",")
        if m.strip()
    ]
    log_level: str = os.environ.get("HOMELAB_MCP_LOG_LEVEL", "INFO")
    transport: str = os.environ.get("HOMELAB_MCP_TRANSPORT", "stdio")
    port: int = int(os.environ.get("HOMELAB_MCP_PORT", "8200"))

    @property
    def docker_backend(self) -> str:
        """portainer | socket"""
        if self.portainer_url and self.portainer_token:
            if self.docker_host and self.docker_host != "unix:///var/run/docker.sock":
                logger.warning(
                    "PORTAINER_URL is set — using Portainer backend; DOCKER_HOST is ignored."
                )
            return "portainer"
        return "socket"

    def validate_modules(self) -> list[str]:
        """Warn on missing credentials for enabled modules; return warnings."""
        warnings: list[str] = []
        if "npm" in self.modules:
            if not self.npm_email or not self.npm_password:
                warnings.append("NPM module enabled but NPM_EMAIL/NPM_PASSWORD are missing.")
        if "docker" in self.modules:
            if self.docker_backend == "portainer":
                if not self.portainer_url or not self.portainer_token:
                    warnings.append(
                        "Docker module enabled for Portainer but PORTAINER_URL/TOKEN missing."
                    )
            elif not Path(self.docker_host.replace("unix://", "")).exists() and self.docker_host.startswith("unix://"):
                warnings.append(
                    f"Docker socket not found at {self.docker_host} — Docker tools may fail."
                )
        if "dns" in self.modules and self.dns_provider == "cloudflare":
            if not self.cloudflare_api_token:
                warnings.append(
                    "DNS module enabled but CLOUDFLARE_API_TOKEN is missing."
                )
        return warnings


config = Config()
