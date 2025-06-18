# fluxfce_core/desktop_manager.py
"""
High-level desktop-appearance operations for FluxFCE.

This module orchestrates changes to the desktop by calling the XfceHandler
for themes/screen and the BackgroundManager for desktop backgrounds.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Literal

from . import config as cfg
from . import helpers, xfce
from .background_manager import BackgroundManager
from .exceptions import FluxFceError, ValidationError

log = logging.getLogger(__name__)

_cfg_mgr_desktop = cfg.ConfigManager()

def _load_cfg() -> cfg.configparser.ConfigParser:
    """Return the current config (with in-memory defaults)."""
    return _cfg_mgr_desktop.load_config()

def _apply_single_mode(mode: Literal["day", "night"]) -> bool:
    """Low-level worker that performs all appearance changes."""
    conf = _load_cfg()
    
    theme_key = "LIGHT_THEME" if mode == "day" else "DARK_THEME"
    bg_profile_key = "DAY_BACKGROUND_PROFILE" if mode == "day" else "NIGHT_BACKGROUND_PROFILE"
    screen_section = "ScreenDay" if mode == "day" else "ScreenNight"

    theme_to_set = conf.get("Appearance", theme_key)
    bg_profile_to_load = conf.get("Appearance", bg_profile_key)
    
    # --- Apply settings ---
    xfce_handler = xfce.XfceHandler()
    bg_manager = BackgroundManager()

    # 1. GTK Theme
    if theme_to_set:
        xfce_handler.set_gtk_theme(theme_to_set)
    else:
        log.warning(f"Theme for mode '{mode}' is not configured.")

    # 2. Background via Profile
    if bg_profile_to_load:
        bg_manager.load_profile(bg_profile_to_load)
    else:
        log.warning(f"Background profile for mode '{mode}' is not configured.")

    # 3. Screen Temperature / Brightness
    try:
        # --- START: CORRECTED CODE BLOCK ---
        # First, get the string values, defaulting to None if the option doesn't exist.
        temp_str = conf.get(screen_section, "XSCT_TEMP", fallback=None)
        bright_str = conf.get(screen_section, "XSCT_BRIGHT", fallback=None)

        # Convert to numbers ONLY if the string value is not None and not empty.
        # This correctly handles cases where the config key exists but its value is blank.
        temp = int(temp_str) if temp_str and temp_str.strip() else None
        bright = float(bright_str) if bright_str and bright_str.strip() else None
        
        # This call now reliably happens. If temp/bright are None, xsct will be reset.
        xfce_handler.set_screen_temp(temp, bright)
        # --- END: CORRECTED CODE BLOCK ---
    except (ValueError, TypeError) as e:
        # This will now only catch genuine errors, e.g., if a value is "abc".
        log.warning(f"Invalid numeric value for screen settings in config for {mode} mode: {e}")

    return True

# --- Public API ---

def apply_mode(mode: Literal["day", "night"]) -> bool:
    """Apply Day or Night appearance immediately."""
    if mode not in ("day", "night"):
        raise ValidationError(f"Invalid mode '{mode}'.")
    log.info("Applying %s mode appearance...", mode)
    return _apply_single_mode(mode)

def set_defaults_from_current(mode: Literal["day", "night"]) -> bool:
    """Save the current XFCE look as the new default for the given mode."""
    conf = _load_cfg()
    xfce_handler = xfce.XfceHandler()
    bg_manager = BackgroundManager()
    changed = False

    # 1. Save Background to Profile
    profile_key = "DAY_BACKGROUND_PROFILE" if mode == "day" else "NIGHT_BACKGROUND_PROFILE"
    profile_to_save = conf.get("Appearance", profile_key)
    if profile_to_save:
        log.info(f"Saving current background to profile: '{profile_to_save}'")
        bg_manager.save_current_to_profile(profile_to_save)
    else:
        log.warning(f"No background profile name configured for {mode} mode; cannot save background.")

    # 2. Save Theme and Screen settings to config.ini
    theme_key = "LIGHT_THEME" if mode == "day" else "DARK_THEME"
    screen_section = "ScreenDay" if mode == "day" else "ScreenNight"

    current_theme = xfce_handler.get_gtk_theme()
    if conf.get("Appearance", theme_key) != current_theme:
        _cfg_mgr_desktop.set_setting(conf, "Appearance", theme_key, current_theme)
        changed = True

    current_screen = xfce_handler.get_screen_settings()
    new_temp = "" if current_screen["temperature"] is None else str(current_screen["temperature"])
    new_bright = "" if current_screen["brightness"] is None else f"{current_screen['brightness']:.2f}"
    
    if conf.get(screen_section, "XSCT_TEMP", fallback="") != new_temp:
        _cfg_mgr_desktop.set_setting(conf, screen_section, "XSCT_TEMP", new_temp)
        changed = True
    if conf.get(screen_section, "XSCT_BRIGHT", fallback="") != new_bright:
        _cfg_mgr_desktop.set_setting(conf, screen_section, "XSCT_BRIGHT", new_bright)
        changed = True

    if changed:
        log.info(f"Theme/Screen defaults updated for {mode} mode — saving config.ini")
        return _cfg_mgr_desktop.save_config(conf)

    log.info("Theme/Screen configuration already matches the current desktop; nothing to save to config.ini.")
    return True

def determine_current_period(conf: cfg.configparser.ConfigParser) -> Literal["day", "night"]:
    """Determines if it is currently day or night based on sun times."""
    from zoneinfo import ZoneInfo
    from . import sun
    try:
        lat = helpers.latlon_str_to_float(conf.get("Location", "LATITUDE"))
        lon = helpers.latlon_str_to_float(conf.get("Location", "LONGITUDE"))
        tz_name = conf.get("Location", "TIMEZONE")
        tzinfo = ZoneInfo(tz_name)
        now = datetime.now(tzinfo)
        times = sun.get_sun_times(lat, lon, now.date(), tz_name)
        return "day" if times["sunrise"] <= now < times["sunset"] else "night"
    except Exception as e:
        log.warning("Cannot compute current period (%s) — assuming night.", e)
        return "night"

def handle_internal_apply(mode: Literal["day", "night"]) -> bool:
    """Called by systemd to apply a mode."""
    log.info(f"DesktopManager: Internal apply called for mode '{mode}'.")
    try:
        return apply_mode(mode)
    except FluxFceError as e:
        log.error(f"DesktopManager: Error during internal apply for '{mode}': {e}")
        return False

def _wait_for_xfconfd(timeout: int = 45) -> bool:
    """Waits for xfconfd to be available by pinging it via D-Bus."""
    log.info("Waiting for xfconfd to become available...")
    start_time = time.monotonic()
    while True:
        current_time = time.monotonic()
        if current_time - start_time >= timeout:
            log.error(
                f"Timeout: xfconfd did not become available within {timeout} seconds."
            )
            return False

        exit_code, _, _ = helpers.run_command(
            "gdbus call --session --dest org.xfce.Xfconf "
            "--object-path / --method org.freedesktop.DBus.Peer.Ping"
        )

        if exit_code == 0:
            log.info("xfconfd is available.")
            # Recommended: Short delay after xfconfd is confirmed available
            time.sleep(1)
            return True

        time.sleep(2)  # Poll every 2 seconds


def handle_run_resume_check() -> bool:
    """Called on resume to apply the correct theme after ensuring xfconfd is ready."""
    log.info("DesktopManager: Handling 'run-resume-check'...")
    if _wait_for_xfconfd():
        log.info(
            "xfconfd is available. Proceeding with 'run-login-check' logic..."
        )
        return handle_run_login_check()
    else:
        log.warning(
            "xfconfd did not become available. Skipping theme application on resume."
        )
        return False


def handle_run_login_check() -> bool:
    """Called on login/resume to apply the correct theme for the current time."""
    log.info("DesktopManager: Handling 'run-login-check'...")
    conf = _load_cfg()
    mode_to_apply = determine_current_period(conf)
    log.info(f"Login/resume check determined mode '{mode_to_apply}'. Applying now.")
    return apply_mode(mode_to_apply)