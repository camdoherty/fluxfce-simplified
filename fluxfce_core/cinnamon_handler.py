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

    def _run_gsettings_set(self, schema: str, key: str, value: str) -> tuple[int, str, str]:
        """Wrapper for 'gsettings set' to ensure correct argument format."""
        cmd = [GSET, "set", schema, key, value]
        log.debug(f"Running gsettings command: {' '.join(cmd)}")
        return helpers.run_command(cmd, capture=True, check=False)

    def _get_gsettings_key(self, schema: str, key: str) -> str:
        """Wrapper for 'gsettings get' to retrieve and clean the output value."""
        cmd = [GSET, "get", schema, key]
        code, stdout, _ = helpers.run_command(cmd, capture=True, check=False)
        return stdout.strip().strip("'") if code == 0 else ""

    def apply_background(self, mode: Literal["day", "night"], config: configparser.ConfigParser) -> bool:
        profile_key = "DAY_BACKGROUND_PROFILE" if mode == "day" else "NIGHT_BACKGROUND_PROFILE"
        profile_name = config.get("Appearance", profile_key, fallback=None)

        if not profile_name:
            log.warning(f"Cinnamon: Background profile for mode '{mode}' is not configured.")
            return False

        profile_path = PROFILE_DIR / f"{profile_name}.profile"
        if not profile_path.is_file():
            profile_path_prefixed = PROFILE_DIR / f"{PROFILE_PREFIX}{profile_name}.profile"
            if profile_path_prefixed.is_file():
                profile_path = profile_path_prefixed
            else:
                 raise ConfigError(f"Cinnamon background profile not found. Tried '{profile_path.name}' and '{profile_path_prefixed.name}'")

        log.info(f"Cinnamon: Applying background from profile '{profile_path.name}'")
        profile_config = configparser.ConfigParser()
        profile_config.read(profile_path)

        bg_type = profile_config.get("Background", "type", fallback="solid")

        if bg_type == "image":
            img_path_str = profile_config.get("Background", "image_path", fallback="")
            if not img_path_str:
                log.error(f"Cinnamon: 'image_path' is empty in profile '{profile_path.name}'")
                return False
            img_path = Path(img_path_str).expanduser().resolve()
            if not img_path.is_file():
                log.error(f"Cinnamon: Background image not found at '{img_path}'")
                return False

            self._run_gsettings_set(SCHEMA_BG, "picture-options", "zoom")
            self._run_gsettings_set(SCHEMA_BG, "picture-uri", f"file://{img_path}")
        else:
            # For solid colors or gradients, we MUST set picture-options to 'none'.
            self._run_gsettings_set(SCHEMA_BG, "picture-options", "none")
            
            if bg_type == "gradient":
                primary = profile_config.get("Background", "primary_color", fallback="#000000")
                secondary = profile_config.get("Background", "secondary_color", fallback="#000000")
                direction = profile_config.get("Background", "gradient_direction", fallback="vertical")
                
                self._run_gsettings_set(SCHEMA_BG, "color-shading-type", direction)
                self._run_gsettings_set(SCHEMA_BG, "primary-color", primary)
                self._run_gsettings_set(SCHEMA_BG, "secondary-color", secondary)
            
            else:  # solid color
                primary = profile_config.get("Background", "primary_color", fallback="#000000")
                self._run_gsettings_set(SCHEMA_BG, "color-shading-type", "solid")
                self._run_gsettings_set(SCHEMA_BG, "primary-color", primary)

        return True

    def save_current_background(self, mode: Literal["day", "night"], config: configparser.ConfigParser) -> bool:
        profile_key = "DAY_BACKGROUND_PROFILE" if mode == "day" else "NIGHT_BACKGROUND_PROFILE"
        profile_name = config.get("Appearance", profile_key, fallback=None)

        if not profile_name:
            log.warning(f"Cinnamon: Cannot save background, no profile name configured for mode '{mode}'.")
            return False

        profile_path = PROFILE_DIR / f"{PROFILE_PREFIX}{profile_name}.profile"
        log.info(f"Cinnamon: Saving current background to profile '{profile_path.name}'")

        profile_config = configparser.ConfigParser()
        profile_config.add_section("Background")

        # --- START OF CRITICAL FIX ---
        # The authoritative key is 'picture-options'. Check this FIRST.
        current_pic_options = self._get_gsettings_key(SCHEMA_BG, "picture-options")
        log.debug(f"Detected picture-options: '{current_pic_options}'")

        if current_pic_options == 'none':
            # The background is a color or gradient. Now check which one.
            current_shading_type = self._get_gsettings_key(SCHEMA_BG, "color-shading-type")
            log.debug(f"Detected color-shading-type: '{current_shading_type}'")

            if current_shading_type in ["vertical", "horizontal"]:
                log.debug("Saving as gradient background.")
                profile_config.set("Background", "type", "gradient")
                profile_config.set("Background", "gradient_direction", current_shading_type)
                profile_config.set("Background", "primary_color", self._get_gsettings_key(SCHEMA_BG, "primary-color"))
                profile_config.set("Background", "secondary_color", self._get_gsettings_key(SCHEMA_BG, "secondary-color"))
            else:  # Defaults to solid color if shading type is 'solid' or unknown
                log.debug("Saving as solid color background.")
                profile_config.set("Background", "type", "solid")
                profile_config.set("Background", "primary_color", self._get_gsettings_key(SCHEMA_BG, "primary-color"))
        
        else:
            # The background is an image because picture-options is 'zoom', 'scaled', etc.
            # Now it is safe to get the picture-uri.
            log.debug("Saving as image background.")
            image_uri = self._get_gsettings_key(SCHEMA_BG, "picture-uri")
            profile_config.set("Background", "type", "image")
            profile_config.set("Background", "image_path", image_uri.replace("file://", ""))
        # --- END OF CRITICAL FIX ---

        try:
            with profile_path.open("w") as pf:
                profile_config.write(pf)
            log.info(f"Successfully wrote profile to {profile_path}")
        except OSError as e:
            raise FluxFceError(f"Failed to write profile file '{profile_path}': {e}") from e

        return True

    def get_theme(self) -> dict[str, str]:
        """Gets the current theme settings as a dictionary for Cinnamon."""
        log.debug("Getting all current Cinnamon theme components.")
        return {
            "applications": self._get_gsettings_key(SCHEMA_INTERFACE, "gtk-theme"),
            "desktop": self._get_gsettings_key("org.cinnamon.theme", "name"),
            "icons": self._get_gsettings_key(SCHEMA_INTERFACE, "icon-theme"),
            "cursor": self._get_gsettings_key(SCHEMA_INTERFACE, "cursor-theme"),
        }

    def set_theme(self, theme_settings: dict[str, str]) -> bool:
        """
        Sets all theme components for Cinnamon from a dictionary.

        Args:
            theme_settings: A dictionary with keys 'applications', 'desktop',
                            'icons', and 'cursor'.
        """
        if not isinstance(theme_settings, dict):
            raise TypeError("CinnamonHandler.set_theme expects a dictionary.")

        log.info(f"Applying Cinnamon theme set: {theme_settings}")

        # Determine dark mode preference from the applications (GTK) theme name
        app_theme = theme_settings.get("applications", "")
        is_dark_mode_target = any(dark_str in app_theme.lower() for dark_str in ["dark", "black", "nuit"])
        color_scheme_value = "prefer-dark" if is_dark_mode_target else "default"

        # Set the overall dark mode preference hint
        log.info(f"Setting Cinnamon color-scheme to: {color_scheme_value}")
        self._run_gsettings_set(SCHEMA_INTERFACE, "color-scheme", color_scheme_value)

        # Set individual theme components
        if app_theme:
            log.info(f"Setting Applications theme to: '{app_theme}'")
            self._run_gsettings_set(SCHEMA_INTERFACE, "gtk-theme", app_theme)

        if desktop_theme := theme_settings.get("desktop"):
            log.info(f"Setting Desktop theme to: '{desktop_theme}'")
            self._run_gsettings_set("org.cinnamon.theme", "name", desktop_theme)

        if icon_theme := theme_settings.get("icons"):
            log.info(f"Setting Icons theme to: '{icon_theme}'")
            self._run_gsettings_set(SCHEMA_INTERFACE, "icon-theme", icon_theme)

        if cursor_theme := theme_settings.get("cursor"):
            log.info(f"Setting Cursor theme to: '{cursor_theme}'")
            self._run_gsettings_set(SCHEMA_INTERFACE, "cursor-theme", cursor_theme)

        return True