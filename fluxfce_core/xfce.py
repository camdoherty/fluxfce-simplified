# ~/dev/fluxfce-simplified/fluxfce_core/xfce.py
"""
XFCE desktop environment interaction for FluxFCE.

This module provides the `XfceHandler` class, which encapsulates interactions
with XFCE settings for GTK theme and screen temperature/brightness.
Backgrounds are handled by the BackgroundManager.
"""

import logging
import re
from typing import Any, Optional

from . import helpers
from .exceptions import DependencyError, ValidationError, XfceError

log = logging.getLogger(__name__)

# --- XFCE Constants ---
XFCONF_THEME_CHANNEL = "xsettings"
XFCONF_THEME_PROPERTY = "/Net/ThemeName"

class XfceHandler:
    """Handles interactions with XFCE GTK theme and xsct."""

    def __init__(self):
        """Check for essential dependencies."""
        try:
            # Note: xfconf-query is still needed for themes
            helpers.check_dependencies(["xfconf-query", "xsct"])
        except DependencyError as e:
            raise XfceError(f"Cannot initialize XfceHandler: {e}") from e

    def get_gtk_theme(self) -> str:
        log.debug(f"Getting GTK theme from {XFCONF_THEME_CHANNEL} {XFCONF_THEME_PROPERTY}")
        cmd = ["xfconf-query", "-c", XFCONF_THEME_CHANNEL, "-p", XFCONF_THEME_PROPERTY]
        code, stdout, stderr = helpers.run_command(cmd, capture=True)
        if code != 0 or not stdout:
            raise XfceError(f"Failed to query GTK theme: {stderr or 'Empty output'}")
        log.info(f"Current GTK theme: {stdout}")
        return stdout

    def set_gtk_theme(self, theme_name: str) -> bool:
        if not theme_name:
            raise ValidationError("Theme name cannot be empty.")
        log.info(f"Setting GTK theme to: {theme_name}")
        cmd = ["xfconf-query", "-c", XFCONF_THEME_CHANNEL, "-p", XFCONF_THEME_PROPERTY, "-s", theme_name]
        code, _, stderr = helpers.run_command(cmd)
        if code != 0:
            raise XfceError(f"Failed to set GTK theme to '{theme_name}': {stderr}")
        return True

    def get_screen_settings(self) -> dict[str, Any]:
        log.debug("Getting screen settings via xsct")
        cmd = ["xsct"]
        code, stdout, stderr = helpers.run_command(cmd, capture=True)
        if code != 0:
            log.info("xsct appears off or failed to query. Assuming default screen settings.")
            return {"temperature": None, "brightness": None}

        temp, brightness = None, None
        if stdout:
            temp_match = re.search(r"temperature\s*[:~]?\s*(\d+)", stdout, re.I)
            bright_match = re.search(r"brightness\s*[:~]?\s*([\d.]+)", stdout, re.I)
            if temp_match: temp = int(temp_match.group(1))
            if bright_match: brightness = float(bright_match.group(1))

        log.info(f"Retrieved screen settings: Temp={temp}, Brightness={brightness}")
        return {"temperature": temp, "brightness": brightness}

    def set_screen_temp(self, temp: Optional[int], brightness: Optional[float]) -> bool:
        if temp is not None and brightness is not None:
            if not (1000 <= temp <= 10000):
                raise ValidationError(f"Temperature value {temp}K is outside typical range (1000-10000).")
            log.info(f"Setting screen: Temp={temp}, Brightness={brightness:.2f}")
            cmd_args = ["xsct", str(temp), f"{brightness:.2f}"]
        else:
            log.info("Resetting screen temperature/brightness (xsct -x)")
            cmd_args = ["xsct", "-x"]
        
        code, _, stderr = helpers.run_command(cmd_args, capture=True)
        if code != 0:
            raise XfceError(f"Failed to set screen via xsct: {stderr}")
        return True
