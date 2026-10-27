"""Settings come from environment variables, then an optional TOML file.

Names follow one pattern. Core settings are ``HOMELAB_<KEY>``; a module setting is
``HOMELAB_<MODULE>_<KEY>``. Any setting can instead be read from a file named by
``HOMELAB_<MODULE>_<KEY>_FILE`` (for Docker secrets and similar). The TOML file is
``$HOMELAB_CONFIG`` if set, otherwise ``$XDG_CONFIG_HOME/homelab/config.toml``
(``~/.config/homelab/config.toml``). Each module reads its own ``[<module>]`` table;
environment variables win over the file. Nothing here assumes a particular MCP client.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Mapping

PREFIX = "HOMELAB"
CORE = "core"
TRUE = {"1", "true", "yes", "on"}
FALSE = {"0", "false", "no", "off"}


def env_name(module: str, key: str) -> str:
    """HOMELAB_<KEY> for core settings, HOMELAB_<MODULE>_<KEY> for module settings."""
    if module == CORE:
        return f"{PREFIX}_{key.upper()}"
    return f"{PREFIX}_{module.upper()}_{key.upper()}"


def config_path(env: Mapping[str, str]) -> Path:
    if env.get("HOMELAB_CONFIG"):
        return Path(env["HOMELAB_CONFIG"]).expanduser()
    base = env.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "homelab" / "config.toml"


class Config:
    def __init__(self, env: Mapping[str, str] | None = None, file_data: dict | None = None):
        self.env = dict(os.environ if env is None else env)
        if file_data is None:
            path = config_path(self.env)
            file_data = tomllib.loads(path.read_text()) if path.is_file() else {}
        self.file = file_data

    def get(self, module: str, key: str, default: str | None = None) -> str | None:
        name = env_name(module, key)
        value = self.env.get(name)
        if value not in (None, ""):
            return value
        file_var = self.env.get(f"{name}_FILE")
        if file_var:
            path = Path(file_var).expanduser()
            if path.is_file():
                text = path.read_text().strip()
                if text:
                    return text
        value = self.file.get(module, {}).get(key)
        if value not in (None, ""):
            return str(value)
        return default

    def flag(self, module: str, key: str, default: bool) -> bool:
        value = self.get(module, key)
        if value is None:
            return default
        value = value.strip().lower()
        if value in TRUE:
            return True
        if value in FALSE:
            return False
        return default

    def enabled(self, module: str, default: bool) -> bool:
        return self.flag(module, "enabled", default)

    def require(self, module: str, *keys: str) -> dict[str, str]:
        """Return the named settings, or raise a not_configured error naming the env vars."""
        from homelab_infra_mcp.errors import not_configured

        missing = [env_name(module, k) for k in keys if not self.get(module, k)]
        if missing:
            raise not_configured(module, missing)
        return {k: self.get(module, k) or "" for k in keys}
