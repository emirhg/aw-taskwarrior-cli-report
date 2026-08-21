"""
User configuration loading and settings resolution.

Provides TOML config file support with XDG Base Directory specification.
Follows XDG standard: $XDG_CONFIG_HOME/tw-report/config.toml
Fallback: ~/.config/tw-report/config.toml
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from tw_report.exceptions import ConfigParsingError


@dataclass(frozen=True)
class ResolvedSettings:
    """Merged configuration from CLI args, config file, and defaults."""

    detail_level: int
    day_start_hour: int = 4
    exclude_projects: Optional[list] = None
    exclude_tasks: Optional[list] = None
    exclude_apps: Optional[list] = None
    terminal_width: Optional[int] = None
    categories_file: Optional[str] = None


def get_config_path() -> Path:
    """Resolve config file path following XDG Base Directory specification.

    Returns:
        Path to config file: $XDG_CONFIG_HOME/tw-report/config.toml
        or ~/.config/tw-report/config.toml if XDG_CONFIG_HOME not set

    Raises:
        ValueError: If home directory cannot be determined
    """
    xdg_config_home = Path(os.environ.get("XDG_CONFIG_HOME", ""))

    if xdg_config_home.is_absolute():
        config_dir = xdg_config_home / "tw-report"
    else:
        home = Path.home()
        if not home.exists():
            raise ValueError("Could not determine home directory")
        config_dir = home / ".config" / "tw-report"

    return config_dir / "config.toml"


def load_user_config(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load user configuration from TOML file.

    Args:
        path: Optional path to config file. If not provided, uses get_config_path()

    Returns:
        Dictionary of configuration options (empty dict if file doesn't exist)

    Raises:
        ConfigParsingError: If TOML file is malformed
    """
    if path is None:
        path = get_config_path()

    if not path.exists():
        return {}

    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception as e:
        raise ConfigParsingError(
            f"Failed to parse config file {path}: {e}"
        ) from e


def resolve_settings(
    cli_args: Optional[Dict[str, Any]] = None,
    user_config: Optional[Dict[str, Any]] = None,
    defaults: Optional[Dict[str, Any]] = None,
) -> ResolvedSettings:
    """Resolve final settings from CLI args, config file, and defaults.

    Precedence: CLI args > config file > defaults

    Args:
        cli_args: Command-line arguments (takes highest precedence)
        user_config: User config file settings
        defaults: Built-in defaults

    Returns:
        ResolvedSettings object with merged configuration
    """
    if cli_args is None:
        cli_args = {}
    if user_config is None:
        user_config = {}
    if defaults is None:
        defaults = {
            "detail_level": 4,
            "day_start_hour": 4,
            "exclude_projects": None,
            "exclude_tasks": None,
            "exclude_apps": None,
            "terminal_width": None,
            "categories_file": None,
        }

    # Merge settings with CLI args taking precedence
    settings = {**defaults, **user_config}
    for key, value in cli_args.items():
        if value is not None:
            settings[key] = value

    return ResolvedSettings(
        detail_level=settings.get("detail_level", defaults["detail_level"]),
        day_start_hour=settings.get("day_start_hour", defaults["day_start_hour"]),
        exclude_projects=settings.get("exclude_projects"),
        exclude_tasks=settings.get("exclude_tasks"),
        exclude_apps=settings.get("exclude_apps"),
        terminal_width=settings.get("terminal_width"),
        categories_file=settings.get("categories_file"),
    )
