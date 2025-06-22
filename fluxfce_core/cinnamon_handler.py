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
# Note: The profile name from config.ini is prefixed with this string.
# e.g., 'default-day' in config becomes 'cinnamon-default-day.profile'
PROFILE_PREFIX = "cinnamon-"


class CinnamonHandler(DesktopHandler):
    """Handles interactions with Cinnamon using profile files for backgrounds."""

    def __init__(self):
        try:
            # xsct is for screen temp/bright, gsettings for theme/background
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

        # The handler consistently adds a prefix to the base name from config.ini
        profile_path = PROFILE_DIR / f"{profile_name}.profile"
        if "cinnamon" not in profile_path.name:
             profile_path = PROFILE_DIR / f"{PROFILE_PREFIX}{profile_name}.profile"

        if not profile_path.is_file():
            # If the prefixed version doesn't exist, try the raw name as a fallback.
            raw_profile_path = PROFILE_DIR / f"{profile_name}.profile"
            if raw_profile_path.is_file():
                profile_path = raw_profile_path
            else:
                 raise ConfigError(f"Cinnamon background profile not found. Tried '{profile_path.name}' and '{raw_profile_path.name}'")


        log.info(f"Cinnamon: Applying background from profile '{profile_path.name}'")
        profile_config = configparser.ConfigParser()
        profile_config.read(profile_path)

        bg_type = profile_config.get("Background", "type", fallback="solid")

        # Always clear the picture-uri to ensure gradients/solid colors can be applied
        self._run_gsettings(["set", SCHEMA_BG, "picture-uri", "''"])

        if bg_type == "image":
            img_path_str = profile_config.get("Background", "image_path", fallback="")
            if not img_path_str:
                log.error(f"Cinnamon: Background 'image_path' is empty in profile '{profile_path.name}'")
                return False

            img_path = Path(img_path_str).expanduser().resolve()
            if not img_path.is_file():
                log.error(f"Cinnamon: Background image not found at '{img_path}'")
                return False

            self._run_gsettings(["set", SCHEMA_BG, "picture-options", "'zoom'"])
            self._run_gsettings(["set", SCHEMA_BG, "picture-uri", f"'file://{img_path}'"])

        elif bg_type == "gradient":
            primary = profile_config.get("Background", "primary_color")
            secondary = profile_config.get("Background", "secondary_color")
            direction = profile_config.get("Background", "gradient_direction")
            
            # --- START OF FIX ---
            # The correct gsettings key is 'color-shading-type', not 'gradient-type'.
            log.debug(f"Applying gradient: direction='{direction}', primary='{primary}', secondary='{secondary}'")
            self._run_gsettings(["set", SCHEMA_BG, "color-shading-type", f"'{direction}'"])
            self._run_gsettings(["set", SCHEMA_BG, "primary-color", f"'{primary}'"])
            self._run_gsettings(["set", SCHEMA_BG, "secondary-color", f"'{secondary}'"])
            # --- END OF FIX ---

        else:  # solid color
            primary = profile_config.get("Background", "primary_color")

            # --- START OF FIX ---
            # Set shading type to 'solid' to ensure it's not a gradient.
            log.debug(f"Applying solid color: primary='{primary}'")
            self._run_gsettings(["set", SCHEMA_BG, "color-shading-type", "'solid'"])
            self._run_gsettings(["set", SCHEMA_BG, "primary-color", f"'{primary}'"])
            # --- END OF FIX ---

        return True

    def save_current_background(self, mode: Literal["day", "night"], config: configparser.ConfigParser) -> bool:
        profile_key = "DAY_BACKGROUND_PROFILE" if mode == "day" else "NIGHT_BACKGROUND_PROFILE"
        profile_name = config.get("Appearance", profile_key, fallback=None)

        if not profile_name:
            log.warning(f"Cinnamon: Cannot save background, no profile name configured for mode '{mode}'.")
            return False

        profile_path = PROFILE_DIR / f"{profile_name}.profile"
        if "cinnamon" not in profile_path.name:
             profile_path = PROFILE_DIR / f"{PROFILE_PREFIX}{profile_name}.profile"

        log.info(f"Cinnamon: Saving current background to profile '{profile_path.name}'")

        # --- START OF FIX ---
        # The correct gsettings key is 'color-shading-type', not 'gradient-type'.
        current_shading_type = self._get_gsettings_key(SCHEMA_BG, "color-shading-type")
        # --- END OF FIX ---
        image_uri = self._get_gsettings_key(SCHEMA_BG, "picture-uri")

        profile_config = configparser.ConfigParser()
        profile_config.add_section("Background")

        if image_uri:
            log.debug(f"Saving image background: {image_uri}")
            profile_config.set("Background", "type", "image")
            profile_config.set("Background", "image_path", image_uri.replace("file://", ""))
        elif current_shading_type in ["vertical", "horizontal"]:
            log.debug(f"Saving gradient background: {current_shading_type}")
            profile_config.set("Background", "type", "gradient")
            profile_config.set("Background", "gradient_direction", current_shading_type)
            profile_config.set("Background", "primary_color", self._get_gsettings_key(SCHEMA_BG, "primary-color"))
            profile_config.set("Background", "secondary_color", self._get_gsettings_key(SCHEMA_BG, "secondary-color"))
        else:  # 'solid' or unknown defaults to solid
            log.debug("Saving solid color background")
            profile_config.set("Background", "type", "solid")
            profile_config.set("Background", "primary_color", self._get_gsettings_key(SCHEMA_BG, "primary-color"))

        try:
            with profile_path.open("w") as pf:
                profile_config.write(pf)
            log.info(f"Successfully wrote profile to {profile_path}")
        except OSError as e:
            raise FluxFceError(f"Failed to write profile file '{profile_path}': {e}") from e

        return True

    def get_theme(self) -> str:
        """Gets the current base GTK theme name."""
        return self._get_gsettings_key(SCHEMA_INTERFACE, "gtk-theme")

    def set_theme(self, theme_name: str) -> bool:
        """Sets the base GTK theme and toggles the prefer-dark-mode setting."""
        if not theme_name:
            raise ValidationError("Theme name cannot be empty.")

        is_dark_mode_target = any(dark_str in theme_name.lower() for dark_str in ["dark", "black", "nuit"])
        color_scheme_value = "'prefer-dark'" if is_dark_mode_target else "'default'"

        log.info(f"Setting Cinnamon color scheme to: {color_scheme_value}")
        code_cs, _, stderr_cs = self._run_gsettings(["set", "org.cinnamon.desktop.interface", "color-scheme", color_scheme_value])
        if code_cs != 0:
            log.warning(f"Failed to set Cinnamon color-scheme: {stderr_cs}. This might be okay on older Cinnamon versions.")

        log.info(f"Setting Cinnamon base GTK theme to: '{theme_name}'")
        code_gtk, _, stderr_gtk = self._run_gsettings(["set", SCHEMA_INTERFACE, "gtk-theme", f"'{theme_name}'"])
        if code_gtk != 0:
            raise FluxFceError(f"Failed to set Cinnamon GTK theme to '{theme_name}': {stderr_gtk}")

        log.info(f"Setting Cinnamon WM theme to: '{theme_name}'")
        self._run_gsettings(["set", SCHEMA_WM, "theme", f"'{theme_name}'"])

        return True