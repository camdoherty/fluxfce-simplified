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
XFCONF_WM_THEME_CHANNEL = "xfwm4"
XFCONF_WM_THEME_PROPERTY = "/general/theme"


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
        """
        Gets the current GTK theme name from xfconf.
        This is used as the primary theme name when saving defaults.
        """
        log.debug(
            f"Getting GTK theme from {XFCONF_THEME_CHANNEL} {XFCONF_THEME_PROPERTY}"
        )
        cmd = ["xfconf-query", "-c", XFCONF_THEME_CHANNEL, "-p", XFCONF_THEME_PROPERTY]
        code, stdout, stderr = helpers.run_command(cmd, capture=True)
        if code != 0 or not stdout:
            raise XfceError(f"Failed to query GTK theme: {stderr or 'Empty output'}")
        log.info(f"Current GTK theme: {stdout}")
        return stdout

    def set_gtk_theme(self, theme_name: str) -> bool:
        """
        Sets the desktop theme, updating both the GTK (applications) theme and
        the XFWM4 (window manager/decorations) theme.
        """
        if not theme_name:
            raise ValidationError("Theme name cannot be empty.")

        # --- 1. Set GTK Theme (Applications) ---
        log.info(f"Setting GTK (application) theme to: {theme_name}")
        cmd_gtk = [
            "xfconf-query",
            "-c",
            XFCONF_THEME_CHANNEL,
            "-p",
            XFCONF_THEME_PROPERTY,
            "-s",
            theme_name,
        ]
        code_gtk, _, stderr_gtk = helpers.run_command(cmd_gtk, capture=True)
        if code_gtk != 0:
            raise XfceError(f"Failed to set GTK theme to '{theme_name}': {stderr_gtk}")

        # --- 2. Set Window Manager (XFWM4) Theme ---
        log.info(f"Setting Window Manager (XFWM4) theme to: {theme_name}")
        cmd_wm = [
            "xfconf-query",
            "-c",
            XFCONF_WM_THEME_CHANNEL,
            "-p",
            XFCONF_WM_THEME_PROPERTY,
            "-s",
            theme_name,
        ]
        code_wm, _, stderr_wm = helpers.run_command(cmd_wm, capture=True)
        if code_wm != 0:
            # If the WM theme fails, raise an error. The desktop is in an
            # inconsistent state, so this should be treated as a failure.
            # The error message notes the partial success.
            raise XfceError(
                f"Successfully set GTK theme, but failed to set Window Manager "
                f"theme to '{theme_name}': {stderr_wm}"
            )

        return True

    def get_screen_settings(self) -> dict[str, Any]:
        """Gets screen settings by parsing the output of the `xsct` command."""
        log.debug("Getting screen settings via xsct")
        cmd = ["xsct"]
        code, stdout, stderr = helpers.run_command(cmd, capture=True)
        if code != 0 or not stdout:
            if "unknown" in stderr.lower():
                log.info(
                    "xsct appears off or not set. Assuming default screen settings."
                )
            else:
                log.warning(
                    "xsct command failed or returned empty. Assuming default settings. Stderr: {stderr}"
                )
            return {"temperature": None, "brightness": None}

        temp: Optional[int] = None
        brightness: Optional[float] = None

        # --- START: CORRECTED PARSING LOGIC ---
        # 1. Try a combined regex first, which matches the common single-line output format.
        #    e.g., "Screen 0: temperature ~ 4500 0.85"
        combined_pattern = re.compile(
            r"temperature\s*[~:]?\s*(\d+)\s+([\d.]+)", re.IGNORECASE
        )
        combined_match = combined_pattern.search(stdout)

        if combined_match:
            log.debug("Parsing xsct output with combined regex pattern.")
            try:
                temp = int(combined_match.group(1))
                brightness = float(combined_match.group(2))
                log.info(
                    f"Retrieved screen settings: Temp={temp}, Brightness={brightness:.2f}"
                )
                return {"temperature": temp, "brightness": brightness}
            except (ValueError, IndexError) as e:
                log.warning(
                    f"Could not parse values from combined xsct regex match: {e}. Output: '{stdout}'"
                )

        # 2. If combined pattern fails, fall back to separate patterns for resilience.
        #    This handles older or different xsct versions with multi-line output.
        log.debug(
            "Combined regex failed or was incomplete. Trying separate regex patterns as a fallback."
        )
        temp_pattern = re.compile(r"temperature\s*[~:]?\s*(\d+)", re.IGNORECASE)
        bright_pattern = re.compile(r"brightness\s*[~:]?\s*([\d.]+)", re.IGNORECASE)

        temp_match = temp_pattern.search(stdout)
        bright_match = bright_pattern.search(stdout)

        if temp_match:
            try:
                temp = int(temp_match.group(1))
            except (ValueError, IndexError):
                log.warning(
                    f"Could not parse temperature from separate xsct match: '{stdout}'"
                )

        if bright_match:
            try:
                brightness = float(bright_match.group(1))
            except (ValueError, IndexError):
                log.warning(
                    f"Could not parse brightness from separate xsct match: '{stdout}'"
                )

        if temp is None and brightness is None:
            log.warning(
                f"Could not parse temperature or brightness from xsct output. Output: '{stdout}'"
            )

        # --- END: CORRECTED PARSING LOGIC ---

        log.info(f"Retrieved screen settings: Temp={temp}, Brightness={brightness}")
        return {"temperature": temp, "brightness": brightness}

    def set_screen_temp(
        self, temp: Optional[int], brightness: Optional[float]
    ) -> bool:
        if temp is not None and brightness is not None:
            if not (1000 <= temp <= 10000):
                raise ValidationError(
                    f"Temperature value {temp}K is outside typical range (1000-10000)."
                )
            log.info(f"Setting screen: Temp={temp}, Brightness={brightness:.2f}")
            cmd_args = ["xsct", str(temp), f"{brightness:.2f}"]
        else:
            log.info("Resetting screen temperature/brightness (xsct -x)")
            cmd_args = ["xsct", "-x"]

        code, _, stderr = helpers.run_command(cmd_args, capture=True)
        if code != 0:
            raise XfceError(f"Failed to set screen via xsct: {stderr}")
        return True

    def run_fade_transition(
        self,
        target_temp: int,
        target_bright: float,
        duration_minutes: int,
        steps_per_minute: int,
    ) -> bool:
        """
        Performs a linear fade of screen temperature and brightness over a duration.

        Args:
            target_temp: The final temperature in Kelvin.
            target_bright: The final brightness (0.1 to 1.0).
            duration_minutes: The total duration of the fade in minutes.
            steps_per_minute: How many times to update the screen settings per minute.
        """
        import time

        DEFAULT_START_TEMP = 6500
        DEFAULT_START_BRIGHT = 1.0

        log.info(
            f"Starting fade to Temp={target_temp}K, Brightness={target_bright:.2f} "
            f"over {duration_minutes} mins."
        )

        # 1. Get Start State
        start_settings = self.get_screen_settings()
        start_temp = start_settings.get("temperature")
        start_bright = start_settings.get("brightness")

        if start_temp is None:
            start_temp = DEFAULT_START_TEMP
            log.info(f"Current temp is None, starting fade from default {start_temp}K")
        if start_bright is None:
            start_bright = DEFAULT_START_BRIGHT
            log.info(f"Current bright is None, starting fade from default {start_bright:.2f}")

        # Ensure values are floats for interpolation
        start_temp_f = float(start_temp)
        start_bright_f = float(start_bright)
        target_temp_f = float(target_temp)
        target_bright_f = float(target_bright)

        duration_seconds = duration_minutes * 60.0
        if duration_seconds <= 0:
            log.warning("Fade duration is zero or negative. Applying final settings immediately.")
            return self.set_screen_temp(target_temp, target_bright)

        total_steps = duration_minutes * steps_per_minute
        if total_steps <= 0:
            log.warning("Invalid step configuration. Applying final settings immediately.")
            return self.set_screen_temp(target_temp, target_bright)

        interval_seconds = duration_seconds / total_steps
        log.debug(
            f"Fade parameters: duration={duration_seconds}s, steps={total_steps}, interval={interval_seconds:.2f}s"
        )

        start_time = time.monotonic()
        step_count = 0

        try:
            while step_count < total_steps:
                elapsed_time = time.monotonic() - start_time
                if elapsed_time >= duration_seconds:
                    break  # Duration has passed

                progress = elapsed_time / duration_seconds
                progress = max(0.0, min(1.0, progress)) # Clamp progress

                current_temp = start_temp_f + (target_temp_f - start_temp_f) * progress
                current_bright = start_bright_f + (target_bright_f - start_bright_f) * progress

                log.debug(
                    f"Fade step {step_count + 1}/{total_steps}: Progress={progress*100:.1f}%, "
                    f"Temp={int(current_temp)}K, Bright={current_bright:.3f}"
                )
                self.set_screen_temp(int(current_temp), current_bright)

                step_count += 1
                
                # Calculate sleep time to align with the next interval
                next_step_time = start_time + (step_count * interval_seconds)
                sleep_duration = next_step_time - time.monotonic()

                if sleep_duration > 0:
                    time.sleep(sleep_duration)

        except KeyboardInterrupt:
            log.info("Fade transition interrupted by user.")
            return False
        except XfceError as e:
            log.error(f"Error during fade step, aborting: {e}")
            return False

        log.info("Fade complete. Applying final target settings for precision.")
        return self.set_screen_temp(target_temp, target_bright)
