# lightfx_core/xfce_handler.py
"""
Concrete DesktopHandler implementation for the XFCE Desktop Environment.
"""
import configparser
import logging
from typing import Literal

from . import helpers
from .background_manager import BackgroundManager
from .desktop_handler import DesktopHandler
from .exceptions import DependencyError, ValidationError, XfceError

log = logging.getLogger(__name__)

# --- XFCE Constants ---
XFCONF_THEME_CHANNEL = "xsettings"
XFCONF_THEME_PROPERTY = "/Net/ThemeName"
XFCONF_WM_THEME_CHANNEL = "xfwm4"
XFCONF_WM_THEME_PROPERTY = "/general/theme"


class XfceHandler(DesktopHandler):
    """Handles interactions with XFCE."""

    def __init__(self):
        try:
            helpers.check_dependencies(["xfconf-query", "xsct", "xfdesktop"])
            self.bg_manager = BackgroundManager()
        except DependencyError as e:
            raise XfceError(f"Cannot initialize XfceHandler: {e}") from e

    def get_theme(self) -> str:
        log.debug(f"Getting GTK theme from {XFCONF_THEME_CHANNEL} {XFCONF_THEME_PROPERTY}")
        cmd = ["xfconf-query", "-c", XFCONF_THEME_CHANNEL, "-p", XFCONF_THEME_PROPERTY]
        code, stdout, stderr = helpers.run_command(cmd, capture=True, check=False)
        if code != 0 or not stdout:
            raise XfceError(f"Failed to query GTK theme: {stderr or 'Empty output'}")
        log.info(f"Current GTK theme: {stdout}")
        return stdout

    def set_theme(self, theme_name: str) -> bool:
        if not theme_name:
            raise ValidationError("Theme name cannot be empty.")

        log.info(f"Setting GTK (application) theme to: {theme_name}")
        cmd_gtk = ["xfconf-query", "-c", XFCONF_THEME_CHANNEL, "-p", XFCONF_THEME_PROPERTY, "-s", theme_name]
        code_gtk, _, stderr_gtk = helpers.run_command(cmd_gtk, capture=True, check=False)
        if code_gtk != 0:
            raise XfceError(f"Failed to set GTK theme to '{theme_name}': {stderr_gtk}")

        log.info(f"Setting Window Manager (XFWM4) theme to: {theme_name}")
        cmd_wm = ["xfconf-query", "-c", XFCONF_WM_THEME_CHANNEL, "-p", XFCONF_WM_THEME_PROPERTY, "-s", theme_name]
        code_wm, _, stderr_wm = helpers.run_command(cmd_wm, capture=True, check=False)
        if code_wm != 0:
            raise XfceError(f"Successfully set GTK theme, but failed to set WM theme to '{theme_name}': {stderr_wm}")
        return True

    def apply_background(self, mode: Literal["day", "night"], config: configparser.ConfigParser) -> bool:
        profile_key = "DAY_BACKGROUND_PROFILE" if mode == "day" else "NIGHT_BACKGROUND_PROFILE"
        bg_profile_to_load = config.get("Appearance", profile_key, fallback=None)

        if bg_profile_to_load:
            log.info(f"XFCE: Applying background profile '{bg_profile_to_load}' for {mode} mode.")
            self.bg_manager.load_profile(bg_profile_to_load)
            return True
        else:
            log.warning(f"XFCE: Background profile for mode '{mode}' is not configured.")
            return False

    def save_current_background(self, mode: Literal["day", "night"], config: configparser.ConfigParser) -> bool:
        profile_key = "DAY_BACKGROUND_PROFILE" if mode == "day" else "NIGHT_BACKGROUND_PROFILE"
        profile_to_save = config.get("Appearance", profile_key, fallback=None)

        if profile_to_save:
            log.info(f"XFCE: Saving current background to profile: '{profile_to_save}'")
            self.bg_manager.save_current_to_profile(profile_to_save)
            return True
        else:
            log.warning(f"XFCE: No background profile name configured for {mode} mode; cannot save background.")
            return False
