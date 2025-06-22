# fluxfce_core/cinnamon_handler.py
"""
Concrete DesktopHandler implementation for the Cinnamon Desktop Environment.
"""
import configparser
import logging
from pathlib import Path
from typing import Literal

from . import helpers
from .desktop_handler import DesktopHandler
from .exceptions import DependencyError, FluxFceError, ValidationError

log = logging.getLogger(__name__)

GSET = "gsettings"
SCHEMA_INTERFACE = "org.cinnamon.desktop.interface"
SCHEMA_WM = "org.cinnamon.desktop.wm.preferences"
SCHEMA_BG = "org.cinnamon.desktop.background"

class CinnamonHandler(DesktopHandler):
    """Handles interactions with Cinnamon."""

    def __init__(self):
        try:
            helpers.check_dependencies([GSET, "xsct"])
        except DependencyError as e:
            raise FluxFceError(f"Cannot initialize CinnamonHandler: {e}") from e

    def _run_gsettings(self, args: list[str]) -> tuple[int, str, str]:
        cmd = [GSET] + args
        return helpers.run_command(cmd, capture=True, check=False)

    def get_theme(self) -> str:
        log.debug("Getting Cinnamon GTK theme")
        code, stdout, stderr = self._run_gsettings(["get", SCHEMA_INTERFACE, "gtk-theme"])
        if code != 0:
            raise FluxFceError(f"Failed to get Cinnamon GTK theme: {stderr}")
        return stdout.strip().strip("'")

    def set_theme(self, theme_name: str) -> bool:
        if not theme_name:
            raise ValidationError("Theme name cannot be empty.")

        log.info(f"Setting Cinnamon GTK theme to: {theme_name}")
        code, _, stderr = self._run_gsettings(["set", SCHEMA_INTERFACE, "gtk-theme", theme_name])
        if code != 0:
            raise FluxFceError(f"Failed to set Cinnamon GTK theme: {stderr}")

        log.info(f"Setting Cinnamon WM theme to: {theme_name}")
        code, _, stderr = self._run_gsettings(["set", SCHEMA_WM, "theme", theme_name])
        if code != 0:
            # Don't raise, just warn, as some themes may not have a matching WM theme.
            log.warning(f"Failed to set Cinnamon WM theme: {stderr}")

        return True

    def apply_background(self, mode: Literal["day", "night"], config: configparser.ConfigParser) -> bool:
        log.info(f"Cinnamon: Applying background for {mode} mode.")
        m = mode.upper()
        bg_type = config.get("Appearance", f"CINNAMON_{m}_BG_TYPE", fallback="solid")

        # Always clear the image first to ensure color/gradient changes apply
        self._run_gsettings(["set", SCHEMA_BG, "picture-uri", "''"])

        if bg_type == "image":
            img_path_str = config.get("Appearance", f"CINNAMON_{m}_BG_IMAGE_PATH", fallback="")
            if not img_path_str:
                log.warning(f"Cinnamon: Background type for '{mode}' is 'image' but path is empty.")
                return False
            img_path = Path(img_path_str)
            if not img_path.is_file():
                log.error(f"Cinnamon: Background image not found at '{img_path}'")
                return False
            self._run_gsettings(["set", SCHEMA_BG, "picture-options", "'zoom'"])
            self._run_gsettings(["set", SCHEMA_BG, "picture-uri", f"'file://{img_path.resolve()}'"])
            log.info(f"Cinnamon: Set background image to {img_path}")

        elif bg_type == "gradient":
            primary = config.get("Appearance", f"CINNAMON_{m}_BG_PRIMARY_COLOR")
            secondary = config.get("Appearance", f"CINNAMON_{m}_BG_SECONDARY_COLOR")
            direction = config.get("Appearance", f"CINNAMON_{m}_BG_GRADIENT_DIR")
            self._run_gsettings(["set", SCHEMA_BG, "gradient-type", f"'{direction}'"])
            self._run_gsettings(["set", SCHEMA_BG, "primary-color", f"'{primary}'"])
            self._run_gsettings(["set", SCHEMA_BG, "secondary-color", f"'{secondary}'"])
            log.info(f"Cinnamon: Set background gradient {primary} -> {secondary} ({direction})")

        else: # solid color
            primary = config.get("Appearance", f"CINNAMON_{m}_BG_PRIMARY_COLOR")
            self._run_gsettings(["set", SCHEMA_BG, "gradient-type", "'solid'"])
            self._run_gsettings(["set", SCHEMA_BG, "primary-color", f"'{primary}'"])
            log.info(f"Cinnamon: Set background color to {primary}")

        return True

    def save_current_background(self, mode: Literal["day", "night"], config: configparser.ConfigParser) -> bool:
        log.info(f"Cinnamon: Saving current background to config for {mode} mode.")
        m = mode.upper()

        # Get all current settings from gsettings
        _, type, _ = self._run_gsettings(["get", SCHEMA_BG, "gradient-type"])
        _, image, _ = self._run_gsettings(["get", SCHEMA_BG, "picture-uri"])
        _, primary, _ = self._run_gsettings(["get", SCHEMA_BG, "primary-color"])
        _, secondary, _ = self._run_gsettings(["get", SCHEMA_BG, "secondary-color"])

        type = type.strip("'")
        image = image.strip("'").replace("file://", "")

        bg_type = "solid"
        if image:
            bg_type = "image"
        elif type in ["vertical", "horizontal"]:
            bg_type = "gradient"

        config.set("Appearance", f"CINNAMON_{m}_BG_TYPE", bg_type)
        config.set("Appearance", f"CINNAMON_{m}_BG_IMAGE_PATH", image)
        config.set("Appearance", f"CINNAMON_{m}_BG_PRIMARY_COLOR", primary.strip("'"))
        config.set("Appearance", f"CINNAMON_{m}_BG_SECONDARY_COLOR", secondary.strip("'"))
        config.set("Appearance", f"CINNAMON_{m}_BG_GRADIENT_DIR", type)

        log.info(f"Cinnamon: Saved background settings for {mode} mode. (Type: {bg_type})")
        return True
