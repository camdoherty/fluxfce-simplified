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

def _convert_cinnamon_color_to_hex(cinnamon_color: str) -> str:
    """Converts Cinnamon's 12-digit hex (#RRRRGGGGBBBB) to standard 6-digit hex (#RRGGBB)."""
    c_strip = cinnamon_color.lstrip('#')
    if len(c_strip) == 12:
        r = c_strip[0:2]
        g = c_strip[4:6]
        b = c_strip[8:10]
        return f"#{r}{g}{b}".upper()
    log.warning(f"Could not parse Cinnamon color '{cinnamon_color}', returning as is.")
    return cinnamon_color # Fallback for unexpected formats

def _convert_hex_to_cinnamon_color(hex_color: str) -> str:
    """Converts standard 6-digit hex (#RRGGBB) to Cinnamon's 12-digit format."""
    h_strip = hex_color.lstrip('#')
    if len(h_strip) == 6:
        r = h_strip[0:2] * 2
        g = h_strip[2:4] * 2
        b = h_strip[4:6] * 2
        return f"#{r}{g}{b}"
    log.warning(f"Could not parse standard hex color '{hex_color}', returning as is.")
    return hex_color # Fallback for unexpected formats


class CinnamonHandler(DesktopHandler):
    """Handles interactions with Cinnamon using profile files for backgrounds."""

    def __init__(self):
        try:
            helpers.check_dependencies([GSET, "xsct"])
            PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        except (DependencyError, OSError) as e:
            raise FluxFceError(f"Cannot initialize CinnamonHandler: {e}") from e

    def _run_gsettings_set(self, schema: str, key: str, value: str) -> tuple[int, str, str]:
        cmd = [GSET, "set", schema, key, value]
        log.debug(f"Running gsettings command: {' '.join(cmd)}")
        return helpers.run_command(cmd, capture=True, check=False)

    def _get_gsettings_key(self, schema: str, key: str) -> str:
        cmd = [GSET, "get", schema, key]
        code, stdout, _ = helpers.run_command(cmd, capture=True, check=False)
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
        bg_section = profile_config["Background"]

        bg_type = bg_section.get("type", "solid")

        if bg_type == "image":
            img_path_str = bg_section.get("image_path", "")
            if not img_path_str:
                log.error(f"Cinnamon: 'image_path' is empty in profile '{profile_path.name}'")
                return False
            img_path = Path(img_path_str).expanduser().resolve()
            if not img_path.is_file():
                log.error(f"Cinnamon: Background image not found at '{img_path}'")
                return False

            aspect = bg_section.get("picture_aspect", "zoom")
            self._run_gsettings_set(SCHEMA_BG, "picture-options", aspect)
            self._run_gsettings_set(SCHEMA_BG, "picture-uri", f"file://{img_path}")
        else:
            self._run_gsettings_set(SCHEMA_BG, "picture-options", "none")
            
            if bg_type == "gradient":
                primary = _convert_hex_to_cinnamon_color(bg_section.get("primary_color", "#000000"))
                secondary = _convert_hex_to_cinnamon_color(bg_section.get("secondary_color", "#000000"))
                direction = bg_section.get("gradient_direction", "vertical")
                
                self._run_gsettings_set(SCHEMA_BG, "color-shading-type", direction)
                self._run_gsettings_set(SCHEMA_BG, "primary-color", primary)
                self._run_gsettings_set(SCHEMA_BG, "secondary-color", secondary)
            else:
                primary = _convert_hex_to_cinnamon_color(bg_section.get("primary_color", "#000000"))
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

        current_pic_options = self._get_gsettings_key(SCHEMA_BG, "picture-options")

        if current_pic_options != 'none':
            profile_config.set("Background", "type", "image")
            image_uri = self._get_gsettings_key(SCHEMA_BG, "picture-uri")
            profile_config.set("Background", "image_path", image_uri.replace("file://", ""))
            profile_config.set("Background", "picture_aspect", current_pic_options)
        else:
            current_shading_type = self._get_gsettings_key(SCHEMA_BG, "color-shading-type")
            if current_shading_type in ["vertical", "horizontal"]:
                profile_config.set("Background", "type", "gradient")
                profile_config.set("Background", "gradient_direction", current_shading_type)
                
                primary_c = self._get_gsettings_key(SCHEMA_BG, "primary-color")
                secondary_c = self._get_gsettings_key(SCHEMA_BG, "secondary-color")
                profile_config.set("Background", "primary_color", _convert_cinnamon_color_to_hex(primary_c))
                profile_config.set("Background", "secondary_color", _convert_cinnamon_color_to_hex(secondary_c))
            else:
                profile_config.set("Background", "type", "solid")
                primary_c = self._get_gsettings_key(SCHEMA_BG, "primary-color")
                profile_config.set("Background", "primary_color", _convert_cinnamon_color_to_hex(primary_c))

        try:
            with profile_path.open("w") as pf:
                profile_config.write(pf)
        except OSError as e:
            raise FluxFceError(f"Failed to write profile file '{profile_path}': {e}") from e

        return True

    def get_theme(self) -> dict[str, str]:
        """Gets the current theme settings as a dictionary for Cinnamon."""
        return {
            "applications": self._get_gsettings_key(SCHEMA_INTERFACE, "gtk-theme"),
            "desktop": self._get_gsettings_key("org.cinnamon.theme", "name"),
            "icons": self._get_gsettings_key(SCHEMA_INTERFACE, "icon-theme"),
            "cursor": self._get_gsettings_key(SCHEMA_INTERFACE, "cursor-theme"),
        }

    def set_theme(self, theme_settings: dict[str, str]) -> bool:
        """Sets all theme components for Cinnamon from a dictionary."""
        if not isinstance(theme_settings, dict):
            raise TypeError("CinnamonHandler.set_theme expects a dictionary.")

        app_theme = theme_settings.get("applications", "")
        is_dark_mode_target = any(dark_str in app_theme.lower() for dark_str in ["dark", "black", "nuit"])
        color_scheme_value = "prefer-dark" if is_dark_mode_target else "default"

        self._run_gsettings_set(SCHEMA_INTERFACE, "color-scheme", color_scheme_value)

        if app_theme:
            self._run_gsettings_set(SCHEMA_INTERFACE, "gtk-theme", app_theme)
        if desktop_theme := theme_settings.get("desktop"):
            self._run_gsettings_set("org.cinnamon.theme", "name", desktop_theme)
        if icon_theme := theme_settings.get("icons"):
            self._run_gsettings_set(SCHEMA_INTERFACE, "icon-theme", icon_theme)
        if cursor_theme := theme_settings.get("cursor"):
            self._run_gsettings_set(SCHEMA_INTERFACE, "cursor-theme", cursor_theme)

        return True