"""TOML configuration files: config/base.toml plus the optional config/<APP_ENV>.toml overlay."""

import os
import tomllib
from pathlib import Path
from typing import Any

from src.config.errors import ConfigError

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"  # Folder holding the TOML files
BASE_FILE = "base.toml"  # Complete configuration, with the local-development values
APP_ENVS = ("local", "production")  # Allowed APP_ENV values; each may have an overlay file
DEFAULT_APP_ENV = "local"  # Environment used when APP_ENV is unset or empty

Sections = dict[str, dict[str, Any]]  # Parsed configuration: [section] name -> key -> value


def _read(path: Path) -> Sections:
    """Parse one TOML file whose top level holds only [section] tables.

    Args:
        path: The file to parse.

    Returns:
        The file's sections.
    """
    try:
        with path.open("rb") as file:
            data = tomllib.load(file)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path.name} is not valid TOML: {exc}") from None
    loose = [key for key, value in data.items() if not isinstance(value, dict)]
    if loose:
        raise ConfigError(f"{path.name} has keys outside a [section]: {', '.join(loose)}")
    return data


def load_config(app_env: str | None = None) -> Sections:
    """Read the base file, then override it key by key with the environment's overlay, if any.

    APP_ENV is the only non-secret environment variable: it selects the overlay and carries
    no setting itself. Values are returned unvalidated; `Settings` checks them.

    Args:
        app_env: Environment whose overlay applies; None reads APP_ENV.

    Returns:
        The merged sections.
    """
    app_env = app_env or os.getenv("APP_ENV", "").strip() or DEFAULT_APP_ENV
    if app_env not in APP_ENVS:
        raise ConfigError(f"APP_ENV must be one of {', '.join(APP_ENVS)}, got {app_env!r}")
    base = CONFIG_DIR / BASE_FILE
    if not base.is_file():
        raise ConfigError(f"Missing configuration file {base}")
    sections = _read(base)
    overlay = CONFIG_DIR / f"{app_env}.toml"
    if overlay.is_file():
        for name, values in _read(overlay).items():
            sections[name] = sections.get(name, {}) | values
    return sections
