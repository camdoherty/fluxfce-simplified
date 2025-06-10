# ~/dev/fluxfce-simplified/fluxfce_core/config.py
"""
Configuration management for FluxFCE, including default file installation.
"""
import configparser
import logging
import pathlib

from .exceptions import ConfigError

log = logging.getLogger(__name__)

# --- Constants ---
APP_NAME = "fluxfce"
CONFIG_DIR = pathlib.Path.home() / ".config" / APP_NAME
CONFIG_FILE = CONFIG_DIR / "config.ini"
PROFILE_DIR = CONFIG_DIR / "backgrounds"

# Updated default configuration values
DEFAULT_CONFIG_STRUCTURE = {
    "Location": {
        "latitude": "40.71N",
        "longitude": "74.01W",
        "timezone": "America/New_York",
    },
    "Theme": {
        "light_theme": "Adwaita",
        "dark_theme": "Adwaita-dark",
    },
    "Background": {
        "day_background_profile": "default-day",
        "night_background_profile": "default-night",
    },
    "ScreenDay": {
        "xsct_temp": "6500",
        "xsct_bright": "1.0",
    },
    "ScreenNight": {
        "xsct_temp": "4500",
        "xsct_bright": "0.85",
    },
}

class Installer:
    """Handles the creation of default configuration files for a new installation."""

    def __init__(self):
        """Ensures base directories exist."""
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ConfigError(f"Failed to create config directories: {e}") from e

    def create_default_config_ini(self, latitude: str, longitude: str, timezone: str) -> None:
        """Writes a default config.ini file with specified location details."""
        log.info("Writing default configuration file...")
        parser = configparser.ConfigParser()
        parser.read_dict(DEFAULT_CONFIG_STRUCTURE)
        
        # Overwrite default location with detected/provided values
        parser.set("Location", "latitude", latitude)
        parser.set("Location", "longitude", longitude)
        parser.set("Location", "timezone", timezone)

        try:
            with CONFIG_FILE.open("w", encoding="utf-8") as f:
                parser.write(f)
            log.debug(f"Successfully wrote config file to {CONFIG_FILE}")
        except OSError as e:
            raise ConfigError(f"Failed to write config file: {e}") from e

    def create_default_background_profiles(self) -> None:
        """Writes the default-day and default-night background profiles."""
        log.info("Writing default background profiles...")
        
        # NOTE: Using a placeholder that should exist. A real implementation
        # might ship these images or use a solid color as a safer default.
        # For this exercise, we assume the user has the repo cloned.
        base_image_path = pathlib.Path(__file__).resolve().parent
        white_image = (base_image_path / "white-100x100.png").expanduser().resolve()
        black_image = (base_image_path / "black-100x100.png").expanduser().resolve()

        day_content = f"""
monitor=--span--
type=image
image_path={white_image}
image_style=span
"""
        night_content = f"""
monitor=--span--
type=image
image_path={black_image}
image_style=span
"""
        try:
            (PROFILE_DIR / "default-day.profile").write_text(day_content.strip())
            (PROFILE_DIR / "default-night.profile").write_text(night_content.strip())
            log.debug("Successfully wrote default background profiles.")
        except OSError as e:
            raise ConfigError(f"Failed to write background profiles: {e}") from e


class ConfigManager:
    """Handles reading/writing the main config.ini after installation."""
    # ... The rest of ConfigManager remains unchanged, but I'll provide it for completeness ...
    def __init__(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ConfigError(f"Failed to create configuration directory {CONFIG_DIR}: {e}") from e
    
    def load_config(self) -> configparser.ConfigParser:
        """Loads main config, applying defaults for any missing values in memory."""
        parser = configparser.ConfigParser()
        if CONFIG_FILE.exists():
            parser.read(CONFIG_FILE)

        # Apply defaults for any missing sections or keys
        for section, defaults in DEFAULT_CONFIG_STRUCTURE.items():
            if not parser.has_section(section):
                parser.add_section(section)
            for key, value in defaults.items():
                if not parser.has_option(section, key):
                    parser.set(section, key, value)
        return parser

    def save_config(self, config: configparser.ConfigParser) -> bool:
        """Saves the provided ConfigParser object to the main config.ini file."""
        log.info(f"Saving configuration to {CONFIG_FILE}")
        try:
            with CONFIG_FILE.open("w", encoding="utf-8") as f:
                config.write(f)
            return True
        except OSError as e:
            raise ConfigError(f"Failed to write configuration to {CONFIG_FILE}: {e}") from e