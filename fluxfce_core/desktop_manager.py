# fluxfce_core/desktop_manager.py
"""
High-level desktop-appearance operations for FluxFCE.

This module orchestrates changes to the desktop by calling the appropriate
DesktopHandler (XFCE, Cinnamon, etc.) based on the current environment.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from . import config as cfg
from . import helpers
from .exceptions import FluxFceError, ValidationError

if TYPE_CHECKING:
    from .desktop_handler import DesktopHandler
    import configparser

log = logging.getLogger(__name__)

# --- Module-level Manager Instances ---
_cfg_mgr_desktop = cfg.ConfigManager()
_desktop_handler_instance: DesktopHandler | None = None

def get_desktop_handler() -> DesktopHandler:
    """Factory function to get the correct desktop handler singleton."""
    global _desktop_handler_instance
    if _desktop_handler_instance:
        return _desktop_handler_instance

    de = helpers.get_desktop_environment()
    log.info(f"Detected desktop environment: {de}")

    if de == "XFCE":
        from .xfce_handler import XfceHandler
        _desktop_handler_instance = XfceHandler()
    elif de == "CINNAMON":
        from .cinnamon_handler import CinnamonHandler
        _desktop_handler_instance = CinnamonHandler()
    else:
        raise FluxFceError(f"Unsupported desktop environment: '{de}'. Cannot proceed.")

    return _desktop_handler_instance

def _load_cfg() -> configparser.ConfigParser:
    return _cfg_mgr_desktop.load_config()

def _apply_single_mode(mode: Literal["day", "night"]) -> bool:
    """Low-level worker that performs all appearance changes via the handler."""
    conf = _load_cfg()
    handler = get_desktop_handler()
    
    theme_key = "LIGHT_THEME" if mode == "day" else "DARK_THEME"
    screen_section = "ScreenDay" if mode == "day" else "ScreenNight"

    # 1. GTK Theme
    theme_to_set = conf.get("Appearance", theme_key)
    if theme_to_set:
        handler.set_theme(theme_to_set)
    else:
        log.warning(f"Theme for mode '{mode}' is not configured.")

    # 2. Background
    handler.apply_background(mode, conf)

    # 3. Screen Temperature / Brightness
    try:
        temp_str = conf.get(screen_section, "XSCT_TEMP", fallback=None)
        bright_str = conf.get(screen_section, "XSCT_BRIGHT", fallback=None)
        temp = int(temp_str) if temp_str and temp_str.strip() else None
        bright = float(bright_str) if bright_str and bright_str.strip() else None
        handler.set_screen_temp(temp, bright)
    except (ValueError, TypeError) as e:
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
    """Save the current desktop look as the new default for the given mode."""
    conf = _load_cfg()
    handler = get_desktop_handler()
    changed = False

    # 1. Save Background
    handler.save_current_background(mode, conf)
    changed = True # Assume background changed and needs saving.

    # 2. Save Theme and Screen settings to config.ini
    theme_key = "LIGHT_THEME" if mode == "day" else "DARK_THEME"
    screen_section = "ScreenDay" if mode == "day" else "ScreenNight"

    current_theme = handler.get_theme()
    if conf.get("Appearance", theme_key) != current_theme:
        _cfg_mgr_desktop.set_setting(conf, "Appearance", theme_key, current_theme)
        changed = True

    current_screen = handler.get_screen_settings()
    new_temp = "" if current_screen.get("temperature") is None else str(current_screen["temperature"])
    new_bright = "" if current_screen.get("brightness") is None else f"{current_screen['brightness']:.2f}"
    
    if conf.get(screen_section, "XSCT_TEMP", fallback="") != new_temp:
        _cfg_mgr_desktop.set_setting(conf, screen_section, "XSCT_TEMP", new_temp)
        changed = True
    if conf.get(screen_section, "XSCT_BRIGHT", fallback="") != new_bright:
        _cfg_mgr_desktop.set_setting(conf, screen_section, "XSCT_BRIGHT", new_bright)
        changed = True

    if changed:
        log.info(f"Theme/Screen/Background defaults updated for {mode} mode — saving config.ini")
        return _cfg_mgr_desktop.save_config(conf)

    log.info("Configuration already matches the current desktop; nothing to save to config.ini.")
    return True

def determine_current_period(conf: configparser.ConfigParser) -> Literal["day", "night"]:
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
    log.info(f"DesktopManager: Internal apply called for mode '{mode}'.")
    try:
        return apply_mode(mode)
    except FluxFceError as e:
        log.error(f"DesktopManager: Error during internal apply for '{mode}': {e}")
        return False

def _is_session_ready() -> bool:
    de = helpers.get_desktop_environment()
    if de == "XFCE":
        cmd = ["xfconf-query", "-c", "xfce4-session", "-p", "/general/SessionName"]
    elif de == "CINNAMON":
        # A reliable check for cinnamon is to see if its screen saver service is on the bus
        cmd = ["gdbus", "call", "--session", "--dest", "org.cinnamon.ScreenSaver", "--object-path", "/org/cinnamon/ScreenSaver", "--method", "org.freedesktop.DBus.Peer.Ping"]
    else:
        return True # Assume ready for unknown DEs

    log.debug(f"Probing for {de} session readiness...")
    try:
        code, _, _ = helpers.run_command(cmd, check=False, capture=True)
        if code == 0:
            log.debug(f"{de} session is ready.")
            return True
        log.debug(f"{de} session not yet ready (probe exit code: {code}).")
        return False
    except FileNotFoundError:
        log.error(f"Command '{cmd[0]}' not found. Cannot verify session readiness.")
        return False
    except Exception as e:
        log.warning(f"An unexpected error occurred while checking session readiness: {e}")
        return False

def handle_run_login_check() -> bool:
    """
    Called on login/resume. Waits for the session to be ready
    before applying the correct theme for the current time.
    """
    log.info("DesktopManager: Handling 'run-login-check'...")
    max_retries = 15
    retry_delay_seconds = 2
    for i in range(max_retries):
        if _is_session_ready():
            break
        log.info(f"Waiting for desktop session... (attempt {i + 1}/{max_retries})")
        helpers.time.sleep(retry_delay_seconds)
    else:
        log.error("Desktop session did not become ready after waiting. Aborting theme application.")
        return False

    conf = _load_cfg()
    mode_to_apply = determine_current_period(conf)
    log.info(f"Session is ready. Determined mode '{mode_to_apply}'. Applying now.")
    return apply_mode(mode_to_apply)