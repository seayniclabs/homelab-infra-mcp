"""Input checks. Each failure is a HomelabError, so the model gets the same shape everywhere."""

from __future__ import annotations

import re

from homelab_infra_mcp.errors import HomelabError

_DOMAIN_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")
_CONTAINER_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
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
    if not _CONTAINER_RE.match(v):
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
