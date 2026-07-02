"""
Unit tests for configuration loading and settings resolution (tw_report.config).

Tests verify TOML parsing, XDG path resolution, and settings precedence.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from tw_report.config import (
    ResolvedSettings,
    get_config_path,
    load_user_config,
    resolve_settings,
)
from tw_report.exceptions import ConfigParsingError


class TestGetConfigPath:
    """Test XDG Base Directory path resolution."""

    def test_uses_xdg_config_home_when_set(self):
        """Should use $XDG_CONFIG_HOME when set."""
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": "/custom/config"}):
            path = get_config_path()
            assert path == Path("/custom/config/tw-report/config.toml")

    def test_uses_home_config_when_xdg_not_set(self):
        """Should fall back to ~/.config when $XDG_CONFIG_HOME not set."""
        with patch.dict(os.environ, {}, clear=False):
            if "XDG_CONFIG_HOME" in os.environ:
                del os.environ["XDG_CONFIG_HOME"]
            path = get_config_path()
            assert path == Path.home() / ".config" / "tw-report" / "config.toml"

    def test_xdg_config_home_empty_uses_fallback(self):
        """Empty $XDG_CONFIG_HOME should use ~/.config fallback."""
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": ""}):
            path = get_config_path()
            assert path == Path.home() / ".config" / "tw-report" / "config.toml"


class TestLoadUserConfig:
    """Test TOML config file loading."""

    def test_nonexistent_file_returns_empty_dict(self):
        """Nonexistent config file should return empty dict."""
        path = Path("/nonexistent/path/config.toml")
        config = load_user_config(path)
        assert config == {}

    def test_valid_toml_file(self):
        """Valid TOML file should be parsed correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "config.toml"
            config_file.write_text("""
detail_level = 3
exclude_projects = ["Personal", "Test"]
terminal_width = 100
""")
            config = load_user_config(config_file)
            assert config["detail_level"] == 3
            assert config["exclude_projects"] == ["Personal", "Test"]
            assert config["terminal_width"] == 100

    def test_malformed_toml_raises_error(self):
        """Malformed TOML should raise ConfigParsingError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "config.toml"
            config_file.write_text("invalid toml [[[")
            with pytest.raises(ConfigParsingError):
                load_user_config(config_file)

    def test_empty_toml_file(self):
        """Empty TOML file should return empty dict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "config.toml"
            config_file.write_text("")
            config = load_user_config(config_file)
            assert config == {}


class TestResolveSettings:
    """Test settings precedence and resolution."""

    def test_cli_args_override_config(self):
        """CLI args should override config file settings."""
        cli_args = {"detail_level": 5}
        user_config = {"detail_level": 2}
        settings = resolve_settings(cli_args, user_config)
        assert settings.detail_level == 5

    def test_config_overrides_defaults(self):
        """Config file should override defaults."""
        user_config = {"detail_level": 2}
        settings = resolve_settings(user_config=user_config)
        assert settings.detail_level == 2

    def test_defaults_when_nothing_set(self):
        """Defaults should be used when nothing else is set."""
        settings = resolve_settings()
        assert settings.detail_level == 4

    def test_exclude_projects_list(self):
        """Exclude projects should be passed through correctly."""
        user_config = {"exclude_projects": ["Personal", "Test"]}
        settings = resolve_settings(user_config=user_config)
        assert settings.exclude_projects == ["Personal", "Test"]

    def test_none_cli_args_ignored(self):
        """None values in CLI args should not override config."""
        cli_args = {"detail_level": None, "terminal_width": 120}
        user_config = {"detail_level": 2}
        settings = resolve_settings(cli_args, user_config)
        assert settings.detail_level == 2
        assert settings.terminal_width == 120

    def test_categories_file_config(self):
        """Categories file should be configurable."""
        user_config = {"categories_file": "/etc/tw-report/categories.json"}
        settings = resolve_settings(user_config=user_config)
        assert settings.categories_file == "/etc/tw-report/categories.json"

    def test_resolved_settings_is_frozen(self):
        """ResolvedSettings should be immutable (frozen dataclass)."""
        settings = resolve_settings()
        with pytest.raises(AttributeError):
            settings.detail_level = 5


class TestSettingsPrecedence:
    """Test complete precedence chain with all sources."""

    def test_full_precedence_chain(self):
        """Test full precedence: CLI > config > defaults."""
        defaults = {
            "detail_level": 1,
            "exclude_projects": ["Default"],
            "terminal_width": 80,
        }
        user_config = {
            "detail_level": 2,
            "exclude_projects": ["Config"],
            "terminal_width": 100,
        }
        cli_args = {
            "detail_level": 5,  # Override both config and defaults
            "terminal_width": None,  # Don't override config
        }

        settings = resolve_settings(cli_args, user_config, defaults)

        assert settings.detail_level == 5  # From CLI
        assert settings.exclude_projects == ["Config"]  # From config (not overridden)
        assert settings.terminal_width == 100  # From config (CLI was None)

    def test_partial_config_with_defaults(self):
        """Config can partially override defaults."""
        defaults = {
            "detail_level": 4,
            "exclude_projects": None,
            "terminal_width": 80,
        }
        user_config = {
            "detail_level": 3,  # Override one setting
            # terminal_width not set, uses default
        }

        settings = resolve_settings(user_config=user_config, defaults=defaults)

        assert settings.detail_level == 3
        assert settings.terminal_width == 80
