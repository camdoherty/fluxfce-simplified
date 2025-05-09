# ~/dev/fluxfce-simplified/fluxfce_core/config.py

import configparser
import logging
import pathlib

# typing.Dict and typing.Optional will be flagged by ruff (UP006/UP007/UP035)
# and can be changed to dict and | None (or just Optional if Python < 3.10 for return only)
# For now, keeping them as per original file for direct comparison of state file removal.
from typing import Dict, Optional

# Import custom exceptions from within the same package
from .exceptions import (
    ConfigError,
)  # ValidationError is not used in this file after changes

log = logging.getLogger(__name__)

# --- Constants ---
APP_NAME = "fluxfce"
CONFIG_DIR = pathlib.Path.home() / ".config" / APP_NAME
CONFIG_FILE = CONFIG_DIR / "config.ini"
# STATE_FILE constant removed

# Default configuration values
DEFAULT_CONFIG: Dict[str, Dict[str, str]] = (
    {  # Ruff will suggest: dict[str, dict[str, str]]
        "Location": {
            "LATITUDE": "43.65N",  # Toronto Latitude (Example)
            "LONGITUDE": "79.38W",  # Toronto Longitude (Example)
            "TIMEZONE": "America/Toronto",  # IANA Timezone Name
        },
        "Themes": {
            "LIGHT_THEME": "Arc-Lighter",
            "DARK_THEME": "Materia-dark-compact",
        },
        "BackgroundDay": {
            "BG_HEX1": "ADD8E6",
            "BG_HEX2": "87CEEB",
            "BG_DIR": "v",
        },
        "ScreenDay": {
            "XSCT_TEMP": "6500",  # Typically reset, but provide a default value
            "XSCT_BRIGHT": "1.0",  # Typically reset, but provide a default value
        },
        "BackgroundNight": {
            "BG_HEX1": "1E1E2E",
            "BG_HEX2": "000000",
            "BG_DIR": "v",
        },
        "ScreenNight": {
            "XSCT_TEMP": "4500",
            "XSCT_BRIGHT": "0.85",
        },
    }
)


# --- Configuration Manager ---


class ConfigManager:
    """Handles reading/writing config.ini."""  # Docstring updated: "and state file" removed

    def __init__(self):
        """Ensures the configuration directory exists."""
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            log.debug(f"Configuration directory ensured: {CONFIG_DIR}")
        except OSError as e:
            # This is potentially serious, raise it.
            raise ConfigError(
                f"Failed to create configuration directory {CONFIG_DIR}: {e}"
            ) from e

    def _load_ini(self, file_path: pathlib.Path) -> configparser.ConfigParser:
        """Loads an INI file, returning a ConfigParser object."""
        parser = configparser.ConfigParser()
        if file_path.exists():
            try:
                # Handle potential empty file
                if file_path.stat().st_size > 0:
                    read_files = parser.read(file_path, encoding="utf-8")
                    if not read_files:
                        log.warning(
                            f"Config file {file_path} was reported as read, but might be empty or unparseable by configparser."
                        )
                    else:
                        log.debug(f"Loaded config from {file_path}")
                else:
                    log.warning(f"Config file {file_path} is empty.")
            except configparser.Error as e:
                # Raise specific error for parsing issues
                raise ConfigError(
                    f"Could not parse config file {file_path}: {e}"
                ) from e
            except (
                OSError
            ) as e:  # Changed from IOError to OSError for broader catch, though read_text uses OSError
                raise ConfigError(f"Could not read config file {file_path}: {e}") from e
        else:
            log.debug(f"Config file {file_path} not found. Returning empty parser.")

        return parser

    def _save_ini(
        self, parser: configparser.ConfigParser, file_path: pathlib.Path
    ) -> bool:
        """Saves a ConfigParser object to an INI file."""
        try:
            with file_path.open("w", encoding="utf-8") as f:
                parser.write(f)
            log.debug(f"Saved configuration to {file_path}")
            return True
        except OSError as e:  # Changed from IOError to OSError for broader catch
            raise ConfigError(
                f"Failed to write configuration to {file_path}: {e}"
            ) from e

    def load_config(self) -> configparser.ConfigParser:
        """
        Loads the main config.ini (config.CONFIG_FILE).

        Applies default values (from config.DEFAULT_CONFIG) for any missing
        sections or keys directly to the returned ConfigParser object.
        It does *not* automatically save the file after applying defaults;
        the caller can modify further and then call save_config.

        Returns:
            A ConfigParser object representing the configuration.

        Raises:
            ConfigError: If the file cannot be read or parsed.
        """
        parser = self._load_ini(CONFIG_FILE)
        # Apply defaults in memory without saving immediately
        made_changes = False
        for section, defaults in DEFAULT_CONFIG.items():
            if not parser.has_section(section):
                parser.add_section(section)
                made_changes = True
                log.debug(f"Added missing section [{section}] to config object")
            for key, value in defaults.items():
                if not parser.has_option(section, key):
                    parser.set(section, key, value)
                    made_changes = True
                    log.debug(
                        f"Added missing key '{key}' = '{value}' to section [{section}] in config object"
                    )

        if made_changes:
            log.info("Default values applied in memory to the loaded configuration.")
            # Caller must call save_config explicitly if they want to persist these defaults

        return parser

    def save_config(self, config: configparser.ConfigParser) -> bool:
        """
        Saves the provided ConfigParser object to the main config.ini file.

        Args:
            config: The ConfigParser object to save.

        Returns:
            True if saving was successful.

        Raises:
            ConfigError: If the file cannot be written.
        """
        log.info(f"Saving configuration to {CONFIG_FILE}")
        return self._save_ini(config, CONFIG_FILE)

    # --- Presets Removed ---

    def get_setting(
        self,
        config: configparser.ConfigParser,
        section: str,
        key: str,
        default: Optional[str] = None,  # Ruff will suggest: str | None = None
    ) -> Optional[str]:  # Ruff will suggest: str | None
        """Gets a setting value from a ConfigParser object."""
        # Uses configparser's fallback mechanism
        return config.get(section, key, fallback=default)

    def set_setting(
        self, config: configparser.ConfigParser, section: str, key: str, value: str
    ):
        """
        Sets a setting value in a ConfigParser object.
        Creates the section if it doesn't exist.
        """
        if not config.has_section(section):
            log.debug(
                f"Adding section [{section}] to config object for setting key '{key}'"
            )
            config.add_section(section)
        log.debug(f"Setting [{section}] {key} = '{value}' in config object")
        config.set(section, key, value)
