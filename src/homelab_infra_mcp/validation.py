"""Input checks. Each failure is a HomelabError, so the model gets the same shape everywhere."""

from __future__ import annotations

import re

from homelab_infra_mcp.errors import HomelabError


_DOMAIN_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")
_CONTAINER_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
_HEX32_RE = re.compile(r"^[0-9a-f]{32}$")
_HA_NAME_RE = re.compile(r"^[a-z0-9_]+$")
_HA_ENTITY_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
_TAG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
# Docker reference grammar: optional registry host, lowercase path components, optional tag or digest.
_IMAGE_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?(?::[0-9]{1,5})?/)?"
    r"(?:[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*/)*[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*"
    r"(?::[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})?(?:@sha256:[a-f0-9]{64})?$"
)
_FORBIDDEN = ("..", "?", "#", "%", "/", "\\")
_RECORD_TYPES = {"A", "AAAA", "CNAME", "MX", "TXT", "SRV", "NS", "CAA"}


def domain(value: str, module: str) -> str:
    v = value.strip().lower()
    if not _DOMAIN_RE.match(v):
        raise HomelabError(module, "bad_input", f"{value!r} is not a valid domain name.",
                           "use a hostname like app.example.com.")
    return v


def domains(csv: str, module: str) -> list[str]:
    parts = [p for p in csv.split(",") if p.strip()]
    if not parts:
        raise HomelabError(module, "bad_input", "at least one domain name is required.",
                           "pass comma-separated names like app.example.com,www.example.com.")
    return [domain(p, module) for p in parts]


def port(value: int, module: str) -> int:
    if not 1 <= value <= 65535:
        raise HomelabError(module, "bad_input", f"port {value} is outside 1-65535.", "pass a TCP port number.")
    return value


def container(value: str, module: str = "docker") -> str:
    v = value.strip()
    if not _CONTAINER_RE.match(v) or ".." in v:
        raise HomelabError(module, "bad_input", f"{value!r} is not a valid container name or id.",
                           "use letters, digits and . _ - only.")
    return v


def ttl(value: int, module: str = "dns") -> int:
    if not 1 <= value <= 86400:
        raise HomelabError(module, "bad_input", f"TTL {value} is outside 1-86400.", "use 1 (auto) to 86400 seconds.")
    return value


def record_type(value: str, module: str = "dns") -> str:
    v = value.strip().upper()
    if v not in _RECORD_TYPES:
        raise HomelabError(module, "bad_input", f"record type {value!r} is not supported.",
                           "use one of " + ", ".join(sorted(_RECORD_TYPES)) + ".")
    return v


def limit(value: int) -> int:
    return max(1, min(value, 100))


def image_ref(value: str, module: str = "docker") -> str:
    """A Docker image reference (name, optional tag or digest). Rejects path tricks before any API call."""
    v = value.strip()
    if not v or len(v) > 255 or any(bad in v for bad in ("..", "?", "#", "%")) or not _IMAGE_RE.match(v):
        raise HomelabError(module, "bad_input", f"{value!r} is not a valid image reference.",
                           "use a name like nginx, library/nginx or registry.example.com/team/app:1.2.")
    return v


def tag(value: str, module: str = "docker") -> str:
    if not _TAG_RE.match(value) or ".." in value:
        raise HomelabError(module, "bad_input", f"tag {value!r} is not valid.",
                           "use letters, digits, _ . - (up to 128 characters).")
    return value


def cf_id(value: str, module: str, what: str) -> str:
    """Cloudflare zone and record ids are 32 lowercase hex characters."""
    if not _HEX32_RE.match(value or ""):
        raise HomelabError(module, "bad_input", f"{what} {value!r} is not a valid Cloudflare id.",
                           "use the 32-character id from dns_zones or dns_records.")
    return value


def ha_name(value: str, module: str, what: str) -> str:
    if not _HA_NAME_RE.match(value or ""):
        raise HomelabError(module, "bad_input", f"{what} {value!r} is not valid.",
                           "use lowercase letters, digits and underscores only.")
    return value


def ha_entity(value: str, module: str) -> str:
    if not _HA_ENTITY_RE.match(value or ""):
        raise HomelabError(module, "bad_input", f"entity_id {value!r} is not valid.",
                           "use the form domain.object, e.g. light.kitchen.")
    return value
