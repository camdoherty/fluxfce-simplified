# lightfx_core/desktop_handler.py
"""
Abstract Base Class for Desktop Environment Handlers.
"""
import configparser
import logging
from typing import Any, Literal

from . import helpers
from .exceptions import FluxFceError, ValidationError

log = logging.getLogger(__name__)


class DesktopHandler:
    """
    Defines the interface for desktop-specific operations like setting
    themes, backgrounds, and screen properties.
    """

    def set_theme(self, theme_name: str) -> bool:
        """Sets the GTK and Window Manager theme."""
        raise NotImplementedError

    def get_theme(self) -> str:
        """Gets the current GTK theme name."""
        raise NotImplementedError

    def apply_background(self, mode: Literal["day", "night"], config: configparser.ConfigParser) -> bool:
        """Applies the background settings for the given mode."""
        raise NotImplementedError

    def save_current_background(self, mode: Literal["day", "night"], config: configparser.ConfigParser) -> bool:
        """Saves the current background settings to the config for the given mode."""
        raise NotImplementedError

    def get_screen_settings(self) -> dict[str, Any]:
        """
        Gets current screen temperature and brightness using xsct.
        This method can be shared by handlers for X11-based desktops.
        """
        log.debug("Getting screen settings via xsct (shared method)")
        cmd = ["xsct"]
        code, stdout, stderr = helpers.run_command(cmd, capture=True, check=False)
        if code != 0 or not stdout:
            if "unknown" in stderr.lower():
                log.info("xsct appears off or not set. Assuming default screen settings.")
            else:
                log.warning(f"xsct command failed or returned empty. Assuming default settings. Stderr: {stderr}")
            return {"temperature": None, "brightness": None}

        # Use robust parsing logic
        temp, brightness = None, None
        combined_match = helpers.re.search(r"temperature\s*[~:]?\s*(\d+)\s+([\d.]+)", stdout, helpers.re.IGNORECASE)
        if combined_match:
            try:
                temp = int(combined_match.group(1))
                brightness = float(combined_match.group(2))
            except (ValueError, IndexError):
                pass  # Fallback to separate patterns

        if temp is None or brightness is None:
            temp_match = helpers.re.search(r"temperature\s*[~:]?\s*(\d+)", stdout, helpers.re.IGNORECASE)
            bright_match = helpers.re.search(r"brightness\s*[~:]?\s*([\d.]+)", stdout, helpers.re.IGNORECASE)
            if temp_match and temp is None: temp = int(temp_match.group(1))
            if bright_match and brightness is None: brightness = float(bright_match.group(1))

        log.info(f"Retrieved screen settings: Temp={temp}, Brightness={brightness}")
        return {"temperature": temp, "brightness": brightness}

    def set_screen_temp(self, temp: int | None, brightness: float | None) -> bool:
        """
        Sets screen temperature and brightness using xsct.
        This method can be shared by handlers for X11-based desktops.
        """
        if temp is not None and brightness is not None:
            if not (1000 <= temp <= 10000):
                raise ValidationError(f"Temperature value {temp}K is outside typical range (1000-10000).")
            log.info(f"Setting screen: Temp={temp}, Brightness={brightness:.2f}")
            cmd_args = ["xsct", str(temp), f"{brightness:.2f}"]
        else:
            log.info("Resetting screen temperature/brightness (xsct -x)")
            cmd_args = ["xsct", "-x"]

        code, _, stderr = helpers.run_command(cmd_args, capture=True, check=False)
        if code != 0:
            raise FluxFceError(f"Failed to set screen via xsct: {stderr}")
        return True
