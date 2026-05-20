"""Input validation for homelab MCP tools."""

import re

_DOMAIN_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$"
)
_CONTAINER_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")


class ValidationError(ValueError):
    """Raised when tool input fails validation."""


def validate_domain(domain: str) -> str:
    domain = domain.strip().lower()
    if not domain or not _DOMAIN_RE.match(domain):
        raise ValidationError(
            f"Invalid domain name: {domain!r}. Use a valid hostname like app.example.com."
        )
    return domain


def validate_domains_csv(domains: str) -> list[str]:
    parts = [validate_domain(d) for d in domains.split(",") if d.strip()]
    if not parts:
        raise ValidationError("At least one domain name is required.")
    return parts


def validate_port(port: int) -> int:
    if port < 1 or port > 65535:
        raise ValidationError(f"Invalid port: {port}. Must be between 1 and 65535.")
    return port


def validate_container_name(name: str) -> str:
    name = name.strip()
    if not name or not _CONTAINER_RE.match(name):
        raise ValidationError(
            f"Invalid container name: {name!r}. Use alphanumeric names with . _ -"
        )
    return name


def validate_ttl(ttl: int) -> int:
    if ttl < 1 or ttl > 86400:
        raise ValidationError(f"Invalid TTL: {ttl}. Cloudflare TTL must be 1–86400.")
    return ttl


def validation_error_response(exc: ValidationError) -> str:
    import json

    return json.dumps({"error": str(exc)})
