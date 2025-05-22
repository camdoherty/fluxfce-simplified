# fluxfce_core/desktop_manager.py
"""
High-level desktop-appearance operations for FluxFCE.

This module is **UI-only**: it never touches systemd or the filesystem
outside XFCE/XSCT calls.  All public call-sites previously lived in
`api.py`; moving them here breaks the monolith and enables focused tests.

Author: <you>
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal, Optional

from . import config as cfg
from . import helpers, xfce
from .exceptions import ConfigError, FluxFceError, ValidationError, XfceError

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# private helpers
# --------------------------------------------------------------------------- #

def handle_internal_apply(mode: Literal["day", "night"]) -> bool:
    """
    Called by systemd (fluxfce-apply-transition@.service) to apply mode.
    Uses this module's public apply_mode function.
    """
    log.info(f"DesktopManager: Internal apply called for mode '{mode}' by systemd.")
    try:
        # Calls the public apply_mode from this same module
        return apply_mode(mode) 
    except FluxFceError as e: # Catch specific FluxFceErrors that apply_mode might re-raise
        log.error(f"DesktopManager: Error during internal apply for mode '{mode}': {e}")
        return False
    except Exception as e: # Catch any other unexpected errors
        log.exception(f"DesktopManager: Unexpected error during internal apply for mode '{mode}': {e}")
        return False

def handle_run_login_check() -> bool:
    """
    Called by systemd (fluxfce-login.service, fluxfce-resume.service)
    and by API's enable_scheduling.
    Determines current solar period and applies appropriate theme settings.
    """
    log.info("DesktopManager: Handling 'run-login-check' command (login/resume/enable)...")
    
    # Load configuration using this module's helper
    conf = _load_cfg() 
    
    # Determine current period using this module's helper
    # Pass the already loaded config object to it.
    mode_to_apply = determine_current_period(conf) 
    
    log.info(f"DesktopManager: Login/Resume/Enable check determined mode '{mode_to_apply}'. Applying now.")
    try:
        # Calls the public apply_mode from this same module
        return apply_mode(mode_to_apply)
    except FluxFceError as e: # Catch specific FluxFceErrors
        log.error(f"DesktopManager: Error during 'run-login-check' applying mode '{mode_to_apply}': {e}")
        return False
    except Exception as e: 
        log.exception(f"DesktopManager: Unexpected error during 'run-login-check' applying mode '{mode_to_apply}': {e}")
        return False

def _load_cfg() -> cfg.configparser.ConfigParser:
    """Return the current config (with in-memory defaults)."""
    return cfg.ConfigManager().load_config()


def _settings_from_cfg(
    mode: Literal["day", "night"],
    conf: cfg.configparser.ConfigParser,
) -> dict[str, str | None]:
    """Collect everything the desktop needs for *one* mode."""
    theme_key = "LIGHT_THEME" if mode == "day" else "DARK_THEME"
    bg_section = "BackgroundDay" if mode == "day" else "BackgroundNight"
    screen_section = "ScreenDay" if mode == "day" else "ScreenNight"

    return {
        "theme": conf.get("Themes", theme_key, fallback=None),
        "bg_hex1": conf.get(bg_section, "BG_HEX1", fallback=None),
        "bg_hex2": conf.get(bg_section, "BG_HEX2", fallback=None),
        "bg_dir": conf.get(bg_section, "BG_DIR", fallback=None),
        "xsct_temp": conf.get(screen_section, "XSCT_TEMP", fallback=None),
        "xsct_bright": conf.get(screen_section, "XSCT_BRIGHT", fallback=None),
    }


def _apply_single_mode(mode: Literal["day", "night"]) -> bool:
    """Low-level worker that performs *all* appearance changes."""
    xfce_handler = xfce.XfceHandler()
    conf = _load_cfg()
    s = _settings_from_cfg(mode, conf)

    if not s["theme"]:
        raise ConfigError(f"Theme for mode '{mode}' is not configured.")

    # -- GTK theme -----------------------------------------------------------
    xfce_handler.set_gtk_theme(s["theme"])

    # -- Background ----------------------------------------------------------
    if s["bg_hex1"] and s["bg_dir"]:
        xfce_handler.set_background(s["bg_hex1"], s["bg_hex2"], s["bg_dir"])
    else:
        log.info("Background not configured — skipping.")

    # -- Screen temperature / brightness -------------------------------------
    try:
        temp = int(s["xsct_temp"]) if s["xsct_temp"] else None
        bright = float(s["xsct_bright"]) if s["xsct_bright"] else None
    except ValueError as e:
        log.warning("Invalid xsct values in config: %s", e)
        temp = bright = None

    xfce_handler.set_screen_temp(temp, bright)
    return True


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #


def apply_mode(mode: Literal["day", "night"]) -> bool:
    """
    Apply **Day** or **Night** appearance immediately.

    Re-raises fatal errors so the caller/CLI can exit non-zero.
    """
    if mode not in ("day", "night"):
        raise ValidationError(f"Invalid mode '{mode}'.")
    log.info("Applying %s mode …", mode)
    return _apply_single_mode(mode)


def set_defaults_from_current(mode: Literal["day", "night"]) -> bool:
    """
    Save the *current* XFCE look as the new default for *mode*.

    This does **not** modify the desktop; only the configuration file.
    """
    xfce_handler = xfce.XfceHandler()
    conf_mgr = cfg.ConfigManager()
    conf = _load_cfg()

    # read current desktop ---------------------------------------------------
    theme = xfce_handler.get_gtk_theme()
    bg = xfce_handler.get_background_settings()  # may raise XfceError
    screen = xfce_handler.get_screen_settings()

    theme_key = "LIGHT_THEME" if mode == "day" else "DARK_THEME"
    bg_section = "BackgroundDay" if mode == "day" else "BackgroundNight"
    screen_section = "ScreenDay" if mode == "day" else "ScreenNight"

    changed = False
    if conf.get("Themes", theme_key, fallback="") != theme:
        conf_mgr.set_setting(conf, "Themes", theme_key, theme)
        changed = True

    if bg:
        for src, dst in (("dir", "BG_DIR"), ("hex1", "BG_HEX1"), ("hex2", "BG_HEX2")):
            if conf.get(bg_section, dst, fallback="") != (bg[src] or ""):
                conf_mgr.set_setting(conf, bg_section, dst, bg[src] or "")
                changed = True

    if screen:
        new_temp = "" if screen["temperature"] is None else str(screen["temperature"])
        new_bri = "" if screen["brightness"] is None else f"{screen['brightness']:.2f}"
        if conf.get(screen_section, "XSCT_TEMP", fallback="") != new_temp:
            conf_mgr.set_setting(conf, screen_section, "XSCT_TEMP", new_temp)
            changed = True
        if conf.get(screen_section, "XSCT_BRIGHT", fallback="") != new_bri:
            conf_mgr.set_setting(conf, screen_section, "XSCT_BRIGHT", new_bri)
            changed = True

    if changed:
        log.info("Desktop defaults updated for %s mode — saving config.ini", mode)
        return conf_mgr.save_config(conf)
    log.info("Configuration already matches the current desktop; nothing to do.")
    return True


def determine_current_period(conf: cfg.configparser.ConfigParser) -> Literal["day", "night"]:
    """
    Cheap helper shared by status & login-check code.

    Returns `"day"` if *now* is between sunrise and sunset for the configured
    coordinates, otherwise `"night"`.  Falls back to `"night"` on errors.
    """
    from zoneinfo import ZoneInfo  # local import to avoid module cost at import-time
    from . import sun

    try:
        lat = helpers.latlon_str_to_float(conf.get("Location", "LATITUDE"))
        lon = helpers.latlon_str_to_float(conf.get("Location", "LONGITUDE"))
        tz = conf.get("Location", "TIMEZONE")
        tzinfo = ZoneInfo(tz)
        now = datetime.now(tzinfo)
        today = now.date()
        times = sun.get_sun_times(lat, lon, today, tz)
    except Exception as e:
        log.warning("Cannot compute current period (%s) — assuming night.", e)
        return "night"

    return "day" if times["sunrise"] <= now < times["sunset"] else "night"
