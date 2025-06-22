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

# --- START: CORRECTED CODE ---
# Define paths to default assets to be used in the config
_ASSETS_DIR = pathlib.Path(__file__).resolve().parent / "assets"
_DEFAULT_DAY_IMG_PATH = str(_ASSETS_DIR / "default-day.png")
_DEFAULT_NIGHT_IMG_PATH = str(_ASSETS_DIR / "default-night.png")

DEFAULT_CONFIG: dict[str, dict[str, str]] = {
    "Location": {
        "LATITUDE": "43.65N",
        "LONGITUDE": "79.38W",
        "TIMEZONE": "America/Toronto",
    },
    "GUI": {
        "opacity": "0.7",
        "widget_opacity": "0.92",
    },
    "Appearance": {
        # Universal settings for theme and profile names
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
        "XSCT_TEMP": "4500",
        "XSCT_BRIGHT": "0.85",
    },
}
# --- END: CORRECTED CODE ---

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
        """
        Loads the config from file and ensures all default keys from
        DEFAULT_CONFIG exist, adding them if they are missing. This
        gracefully handles upgrades to the config structure.
        """
        parser = self._load_ini(CONFIG_FILE)
        made_changes = False

        # --- START OF FIX ---
        # Iterate through default sections and keys to ensure all are present.
        for section, defaults in DEFAULT_CONFIG.items():
            if not parser.has_section(section):
                log.info(f"Adding missing section [{section}] to config in memory.")
                parser.add_section(section)
                made_changes = True
            
            for key, value in defaults.items():
                # The crucial check: does the specific option exist?
                if not parser.has_option(section, key):
                    log.info(f"Adding missing option '{key}' to section [{section}] in memory.")
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