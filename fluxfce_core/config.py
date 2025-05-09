# ~/dev/fluxfce-simplified/fluxfce_core/config.py

import configparser
import logging
import pathlib
from typing import Dict, Optional

# Import custom exceptions from within the same package
from .exceptions import ConfigError, ValidationError

log = logging.getLogger(__name__)

# --- Constants ---
APP_NAME = "fluxfce"
CONFIG_DIR = pathlib.Path.home() / ".config" / APP_NAME
CONFIG_FILE = CONFIG_DIR / "config.ini"

# Default configuration values
DEFAULT_CONFIG: Dict[str, Dict[str, str]] = {
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


# --- Configuration Manager ---


class ConfigManager:
    """Handles reading/writing config.ini and state file."""

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
            except OSError as e:
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
        except OSError as e:
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
        default: Optional[str] = None,
    ) -> Optional[str]:
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

    def read_state(self) -> Optional[str]:
        """
        Reads the last known auto-applied state ('day' or 'night') from the state file.

        Returns:
            'day', 'night', or None if the file doesn't exist, is empty,
            contains invalid data, or cannot be read.
        """
        if STATE_FILE.exists():
            try:
                # Handle empty state file
                if STATE_FILE.stat().st_size == 0:
                    log.warning(f"State file {STATE_FILE} is empty. Returning None.")
                    return None

                state = STATE_FILE.read_text(encoding="utf-8").strip()
                if state in ("day", "night"):
                    log.debug(f"Read state: {state}")
                    return state
                else:
                    log.warning(
                        f"Invalid content '{state}' in state file {STATE_FILE}. Attempting to remove."
                    )
                    # --- Attempt to remove invalid state file ---
                    try:
                        STATE_FILE.unlink()
                        log.debug(f"Removed invalid state file: {STATE_FILE}")
                    except OSError as e:
                        log.warning(
                            f"Could not remove invalid state file {STATE_FILE}: {e}"
                        )
                    # --- End Attempt ---
                    return None  # Return None as state is invalid/unknown
            except OSError as e:
                # Raise specific error for read issues
                raise ConfigError(f"Could not read state file {STATE_FILE}: {e}") from e
        else:
            log.debug("State file not found.")
            return None

    def write_state(self, state: str) -> bool:
        """
        Writes the current auto-applied state ('day' or 'night') to the state file.

        Args:
            state: The state to write ('day' or 'night').

        Returns:
            True on success.

        Raises:
            ValidationError: If the provided state is not 'day' or 'night'.
            ConfigError: If the state file cannot be written.
        """
        if state not in ("day", "night"):
            raise ValidationError(
                f"Attempted to write invalid state: {state}. Must be 'day' or 'night'."
            )
        try:
            STATE_FILE.write_text(state, encoding="utf-8")
            log.info(f"State successfully written to {STATE_FILE}: {state}")
            return True
        except OSError as e:
            raise ConfigError(f"Failed to write state file {STATE_FILE}: {e}") from e
