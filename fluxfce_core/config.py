# ~/dev/fluxfce-simplified/fluxfce_core/config.py
"""
Configuration management for FluxFCE.

This module handles the loading, saving, and default value application
for FluxFCE's configuration file (`config.ini`).
"""

import configparser
import logging
import pathlib
from typing import Optional

from .exceptions import ConfigError

log = logging.getLogger(__name__)

# --- Constants ---
APP_NAME = "fluxfce"
CONFIG_DIR = pathlib.Path.home() / ".config" / APP_NAME
CONFIG_FILE = CONFIG_DIR / "config.ini"

# Default configuration values
# Background settings are now handled by profiles.
DEFAULT_CONFIG: dict[str, dict[str, str]] = {
    "Location": {
        "LATITUDE": "43.65N",
        "LONGITUDE": "79.38W",
        "TIMEZONE": "America/Toronto",
    },
    "GUI": {
        "opacity": "0.88",
        "widget_opacity": "0.92"
    },
    "Appearance": {
        "LIGHT_THEME": "Adwaita",
        "DARK_THEME": "Adwaita-dark",
        "DAY_BACKGROUND_PROFILE": "default-day",
        "NIGHT_BACKGROUND_PROFILE": "default-night",
    },
    "ScreenDay": {
        "XSCT_TEMP": "6500",
        "XSCT_BRIGHT": "1.0",
    },
    "ScreenNight": {
        "XSCT_TEMP": "5000",
        "XSCT_BRIGHT": "1.0",
    },
}

class ConfigManager:
    """Handles reading/writing config.ini."""
    
    def __init__(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            log.debug(f"Configuration directory ensured: {CONFIG_DIR}")
        except OSError as e:
            raise ConfigError(f"Failed to create configuration directory {CONFIG_DIR}: {e}") from e

    def _load_ini(self, file_path: pathlib.Path) -> configparser.ConfigParser:
        parser = configparser.ConfigParser()
        if file_path.exists():
            try:
                if file_path.stat().st_size > 0:
                    parser.read(file_path, encoding="utf-8")
                else:
                    log.warning(f"Config file {file_path} is empty.")
            except configparser.Error as e:
                raise ConfigError(f"Could not parse config file {file_path}: {e}") from e
            except OSError as e:
                raise ConfigError(f"Could not read config file {file_path}: {e}") from e
        return parser

    def _save_ini(self, parser: configparser.ConfigParser, file_path: pathlib.Path) -> bool:
        try:
            with file_path.open("w", encoding="utf-8") as f:
                parser.write(f)
            log.debug(f"Saved configuration to {file_path}")
            return True
        except OSError as e:
            raise ConfigError(f"Failed to write configuration to {file_path}: {e}") from e

    def load_config(self) -> configparser.ConfigParser:
        parser = self._load_ini(CONFIG_FILE)
        made_changes = False
        for section, defaults in DEFAULT_CONFIG.items():
            if not parser.has_section(section):
                parser.add_section(section)
                made_changes = True
            for key, value in defaults.items():
                if not parser.has_option(section, key):
                    parser.set(section, key, value)
                    made_changes = True
        if made_changes:
            log.info("Default values applied in memory to the loaded configuration.")
        return parser

    def save_config(self, config: configparser.ConfigParser) -> bool:
        log.info(f"Saving configuration to {CONFIG_FILE}")
        return self._save_ini(config, CONFIG_FILE)

    def get_setting(self, config: configparser.ConfigParser, section: str, key: str, default: Optional[str] = None) -> Optional[str]:
        return config.get(section, key, fallback=default)

    def set_setting(self, config: configparser.ConfigParser, section: str, key: str, value: str):
        if not config.has_section(section):
            config.add_section(section)
        config.set(section, key, value)