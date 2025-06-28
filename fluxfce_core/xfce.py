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
        """Gets screen settings by parsing the output of the `xsct` command."""
        log.debug("Getting screen settings via xsct")
        cmd = ["xsct"]
        code, stdout, stderr = helpers.run_command(cmd, capture=True)
        if code != 0 or not stdout:
            if "unknown" in stderr.lower():
                log.info("xsct appears off or not set. Assuming default screen settings.")
            else:
                log.warning(f"xsct command failed or returned empty. Assuming default settings. Stderr: {stderr}")
            return {"temperature": None, "brightness": None}

        temp: Optional[int] = None
        brightness: Optional[float] = None

        # --- START: CORRECTED PARSING LOGIC ---
        # 1. Try a combined regex first, which matches the common single-line output format.
        #    e.g., "Screen 0: temperature ~ 4500 0.85"
        combined_pattern = re.compile(r"temperature\s*[~:]?\s*(\d+)\s+([\d.]+)", re.IGNORECASE)
        combined_match = combined_pattern.search(stdout)

        if combined_match:
            log.debug("Parsing xsct output with combined regex pattern.")
            try:
                temp = int(combined_match.group(1))
                brightness = float(combined_match.group(2))
                log.info(f"Retrieved screen settings: Temp={temp}, Brightness={brightness:.2f}")
                return {"temperature": temp, "brightness": brightness}
            except (ValueError, IndexError) as e:
                log.warning(f"Could not parse values from combined xsct regex match: {e}. Output: '{stdout}'")

        # 2. If combined pattern fails, fall back to separate patterns for resilience.
        #    This handles older or different xsct versions with multi-line output.
        log.debug("Combined regex failed or was incomplete. Trying separate regex patterns as a fallback.")
        temp_pattern = re.compile(r"temperature\s*[~:]?\s*(\d+)", re.IGNORECASE)
        bright_pattern = re.compile(r"brightness\s*[~:]?\s*([\d.]+)", re.IGNORECASE)
        
        temp_match = temp_pattern.search(stdout)
        bright_match = bright_pattern.search(stdout)

        if temp_match:
            try:
                temp = int(temp_match.group(1))
            except (ValueError, IndexError):
                log.warning(f"Could not parse temperature from separate xsct match: '{stdout}'")
        
        if bright_match:
            try:
                brightness = float(bright_match.group(1))
            except (ValueError, IndexError):
                log.warning(f"Could not parse brightness from separate xsct match: '{stdout}'")

        if temp is None and brightness is None:
            log.warning(f"Could not parse temperature or brightness from xsct output. Output: '{stdout}'")

        # --- END: CORRECTED PARSING LOGIC ---
        
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