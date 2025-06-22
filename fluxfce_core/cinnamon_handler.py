# fluxfce_core/cinnamon_handler.py
"""
Concrete DesktopHandler implementation for the Cinnamon Desktop Environment.
Uses profile files for background settings for consistency.
"""
import configparser
import logging
from pathlib import Path
from typing import Literal

from . import helpers
from .desktop_handler import DesktopHandler
from .exceptions import ConfigError, DependencyError, FluxFceError, ValidationError

log = logging.getLogger(__name__)

# --- gsettings Constants ---
GSET = "gsettings"
SCHEMA_INTERFACE = "org.cinnamon.desktop.interface"
SCHEMA_WM = "org.cinnamon.desktop.wm.preferences"
SCHEMA_BG = "org.cinnamon.desktop.background"

# --- Profile Constants ---
PROFILE_DIR = helpers.pathlib.Path.home() / ".config" / "fluxfce" / "backgrounds"
PROFILE_PREFIX = "cinnamon-"


class CinnamonHandler(DesktopHandler):
    """Handles interactions with Cinnamon using profile files for backgrounds."""

    def __init__(self):
        try:
            helpers.check_dependencies([GSET, "xsct"])
            PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        except (DependencyError, OSError) as e:
            raise FluxFceError(f"Cannot initialize CinnamonHandler: {e}") from e

    def _run_gsettings(self, args: list[str]) -> tuple[int, str, str]:
        cmd = [GSET] + args
        return helpers.run_command(cmd, capture=True, check=False)

    def _get_gsettings_key(self, schema: str, key: str) -> str:
        code, stdout, _ = self._run_gsettings(["get", schema, key])
        return stdout.strip().strip("'") if code == 0 else ""

    def apply_background(self, mode: Literal["day", "night"], config: configparser.ConfigParser) -> bool:
        profile_key = "DAY_BACKGROUND_PROFILE" if mode == "day" else "NIGHT_BACKGROUND_PROFILE"
        profile_name = config.get("Appearance", profile_key, fallback=None)

        if not profile_name:
            log.warning(f"Cinnamon: Background profile for mode '{mode}' is not configured.")
            return False

        profile_path = PROFILE_DIR / f"{PROFILE_PREFIX}{profile_name}.profile"
        if not profile_path.is_file():
            raise ConfigError(f"Cinnamon background profile not found: {profile_path}")

        log.info(f"Cinnamon: Applying background from profile '{profile_path.name}'")
        profile_config = configparser.ConfigParser()
        profile_config.read(profile_path)

        bg_type = profile_config.get("Background", "type", fallback="solid")

        self._run_gsettings(["set", SCHEMA_BG, "picture-uri", "''"])

        if bg_type == "image":
            img_path = profile_config.get("Background", "image_path", fallback="")
            if not img_path or not Path(img_path).is_file():
                log.error(f"Cinnamon: Background image not found at '{img_path}'")
                return False
            self._run_gsettings(["set", SCHEMA_BG, "picture-options", "'zoom'"])
            self._run_gsettings(["set", SCHEMA_BG, "picture-uri", f"'file://{Path(img_path).resolve()}'"])
        elif bg_type == "gradient":
            primary = profile_config.get("Background", "primary_color")
            secondary = profile_config.get("Background", "secondary_color")
            direction = profile_config.get("Background", "gradient_direction")
            self._run_gsettings(["set", SCHEMA_BG, "gradient-type", f"'{direction}'"])
            self._run_gsettings(["set", SCHEMA_BG, "primary-color", f"'{primary}'"])
            self._run_gsettings(["set", SCHEMA_BG, "secondary-color", f"'{secondary}'"])
        else: # solid
            primary = profile_config.get("Background", "primary_color")
            self._run_gsettings(["set", SCHEMA_BG, "gradient-type", "'none'"])
            self._run_gsettings(["set", SCHEMA_BG, "primary-color", f"'{primary}'"])

        return True

    def save_current_background(self, mode: Literal["day", "night"], config: configparser.ConfigParser) -> bool:
        profile_key = "DAY_BACKGROUND_PROFILE" if mode == "day" else "NIGHT_BACKGROUND_PROFILE"
        profile_name = config.get("Appearance", profile_key, fallback=None)

        if not profile_name:
            log.warning(f"Cinnamon: Cannot save background, no profile name configured for mode '{mode}'.")
            return False

        profile_path = PROFILE_DIR / f"{PROFILE_PREFIX}{profile_name}.profile"
        log.info(f"Cinnamon: Saving current background to profile '{profile_path.name}'")

        current_gradient_type = self._get_gsettings_key(SCHEMA_BG, "gradient-type")
        image_uri = self._get_gsettings_key(SCHEMA_BG, "picture-uri")

        profile_config = configparser.ConfigParser()
        profile_config.add_section("Background")

        if image_uri:
            profile_config.set("Background", "type", "image")
            profile_config.set("Background", "image_path", image_uri.replace("file://", ""))
        elif current_gradient_type in ["vertical", "horizontal"]:
            profile_config.set("Background", "type", "gradient")
            profile_config.set("Background", "gradient_direction", current_gradient_type)
            profile_config.set("Background", "primary_color", self._get_gsettings_key(SCHEMA_BG, "primary-color"))
            profile_config.set("Background", "secondary_color", self._get_gsettings_key(SCHEMA_BG, "secondary-color"))
        else:
            profile_config.set("Background", "type", "solid")
            profile_config.set("Background", "primary_color", self._get_gsettings_key(SCHEMA_BG, "primary-color"))

        with profile_path.open("w") as pf:
            profile_config.write(pf)

        return True

    def get_theme(self) -> str:
        """Gets the current base GTK theme name."""
        return self._get_gsettings_key(SCHEMA_INTERFACE, "gtk-theme")

    def set_theme(self, theme_name: str) -> bool:
        """Sets the base GTK theme and toggles the prefer-dark-mode setting."""
        if not theme_name:
            raise ValidationError("Theme name cannot be empty.")

        # Determine if the target theme name implies a dark mode
        # This logic can be adjusted based on common dark theme naming conventions
        is_dark_mode_target = "dark" in theme_name.lower() or \
                              "black" in theme_name.lower() or \
                              "nuit" in theme_name.lower() or \
                              "밤" in theme_name.lower() # Example for Korean

        color_scheme_value = "'prefer-dark'" if is_dark_mode_target else "'default'"

        log.info(f"Setting Cinnamon color scheme to: {color_scheme_value}")
        code_cs, _, stderr_cs = self._run_gsettings(["set", SCHEMA_INTERFACE, "color-scheme", color_scheme_value])
        if code_cs != 0:
             # Warn but don't fail, as some older Cinnamon versions might not have this key
            log.warning(f"Failed to set Cinnamon color-scheme: {stderr_cs}. This might be okay on older Cinnamon.")


        # It's generally good practice to set the base theme name as well,
        # even if color-scheme is the primary driver for dark mode.
        # Some themes might have specific assets that are only picked up if the base name matches.
        # The user provides the "day" or "night" theme name from config.
        # We use this name directly for the gtk-theme and wm-theme.

        log.info(f"Setting Cinnamon base GTK theme to: '{theme_name}'")
        code_gtk, _, stderr_gtk = self._run_gsettings(["set", SCHEMA_INTERFACE, "gtk-theme", f"'{theme_name}'"])
        if code_gtk != 0:
            raise FluxFceError(f"Failed to set Cinnamon GTK theme to '{theme_name}': {stderr_gtk}")

        log.info(f"Setting Cinnamon WM theme to: '{theme_name}'")
        # WM theme might not always match GTK theme name, so don't raise error if it fails
        self._run_gsettings(["set", SCHEMA_WM, "theme", f"'{theme_name}'"])

        return True
