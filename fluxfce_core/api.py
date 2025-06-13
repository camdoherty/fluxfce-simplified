# fluxfce_core/api.py
"""
Public API Facade for the fluxfce_core library.

This module provides the primary interface for external callers (like the CLI)
to interact with the core functionalities of FluxFCE, including configuration,
scheduling, desktop appearance management, and systemd integration.
It orchestrates calls to other internal modules within `fluxfce_core`.
"""

import configparser
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

# Import core components and exceptions
from . import config as cfg
from . import exceptions as exc
from . import helpers, sun, systemd as sysd
from . import desktop_manager, scheduler
from .background_manager import BackgroundManager

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:
    raise ImportError("Required module 'zoneinfo' not found. FluxFCE requires Python 3.9+.")

log = logging.getLogger(__name__)

# --- Module-level Managers ---
_cfg_mgr_api = cfg.ConfigManager()
_sysd_mgr_api = sysd.SystemdManager()

# --- Public API Functions for Config ---

def get_current_config() -> configparser.ConfigParser:
    """Loads the current configuration, applying defaults in memory."""
    log.debug("API: get_current_config called")
    return _cfg_mgr_api.load_config()

def save_configuration(config_obj: configparser.ConfigParser) -> bool:
    """Saves the given ConfigParser object to file."""
    log.debug("API: save_configuration called")
    return _cfg_mgr_api.save_config(config_obj)

# --- Installation and Uninstallation ---

def install_default_background_profiles() -> None:
    """
    API function to trigger the installation of default background profiles.
    This is called by the CLI during the main `install` process.
    """
    log.info("API: Triggering installation of default background profiles.")
    try:
        bg_manager = BackgroundManager()
        bg_manager.install_default_profiles()
    except exc.XfceError as e:
        log.error(f"API: Failed to install default background profiles: {e}")
        # This is not a fatal error; the main installation can continue with a warning.
    except Exception as e:
        log.exception(f"API: Unexpected error installing default background profiles: {e}")

def install_fluxfce(script_path: str, python_executable: Optional[str] = None) -> bool:
    """API Façade: Installs static systemd units."""
    log.info(f"API Facade: Installing static systemd units for {sysd._APP_NAME}.")
    install_mgr = sysd.SystemdManager()
    return install_mgr.install_units(script_path=script_path, python_executable=python_executable)

def uninstall_fluxfce() -> bool:
    """API Façade: Disables scheduling and removes all systemd units."""
    log.info(f"API Facade: Uninstalling {sysd._APP_NAME} (disabling schedule, removing units).")
    scheduler.disable_scheduling()
    uninstall_mgr = sysd.SystemdManager()
    return uninstall_mgr.remove_units()

# --- Scheduling Façade ---

def enable_scheduling(python_exe_path: str, script_exe_path: str) -> bool:
    """API Façade: Enables scheduling and applies the theme for the current solar period."""
    log.info("API Facade: Attempting to enable scheduling...")
    scheduler.enable_scheduling(python_exe_path=python_exe_path, script_exe_path=script_exe_path)
    log.info("API Facade: Scheduling setup. Applying theme for current solar period...")
    return desktop_manager.handle_run_login_check()

def disable_scheduling() -> bool:
    """API Façade: Disables scheduling by calling the scheduler module."""
    log.info("API Facade: Calling scheduler.disable_scheduling...")
    return scheduler.disable_scheduling()

def handle_schedule_dynamic_transitions_command(python_exe_path: str, script_exe_path: str) -> bool:
    """API Façade: For CLI internal command to call the scheduler function."""
    log.debug("API Facade: Relaying 'schedule-dynamic-transitions' to scheduler module.")
    return scheduler.handle_schedule_dynamic_transitions_command(python_exe_path, script_exe_path)

# --- Desktop Appearance Façade ---

def apply_temporary_mode(mode: str) -> bool:
    """API Façade: Applies an appearance mode temporarily, WITHOUT disabling scheduling."""
    log.info(f"API Facade: Applying temporary mode '{mode}' (scheduling remains active)...")
    return desktop_manager.apply_mode(mode)

def apply_manual_mode(mode: str) -> bool:
    """API Façade: Applies a manual appearance mode and disables scheduling."""
    log.info(f"API Facade: Applying manual mode '{mode}' and then disabling scheduling...")
    desktop_manager.apply_mode(mode)
    return scheduler.disable_scheduling()

def set_default_from_current(mode: str) -> bool:
    """API Façade: Saves current desktop settings as default via desktop_manager."""
    log.info(f"API Facade: Calling desktop_manager.set_defaults_from_current for mode '{mode}'.")
    return desktop_manager.set_defaults_from_current(mode)

# --- Internal Command Handlers Façade ---

def handle_internal_apply(mode: str) -> bool:
    """API Façade: Relays to desktop_manager.handle_internal_apply."""
    log.debug(f"API Facade: Relaying 'internal-apply --mode {mode}' to desktop_manager.")
    return desktop_manager.handle_internal_apply(mode)

def handle_run_login_check() -> bool:
    """API Façade: Relays to desktop_manager.handle_run_login_check."""
    log.debug("API Facade: Relaying 'run-login-check' to desktop_manager.")
    return desktop_manager.handle_run_login_check()

# --- Status Function ---

def get_status() -> dict[str, Any]:
    """Retrieves the current status of fluxfce."""
    log.debug("API: Getting status...")
    status: dict[str, Any] = {
        "config": {},
        "sun_times": {"sunrise": None, "sunset": None, "error": None},
        "current_period": "unknown",
        "systemd_services": {"error": None},
        "summary": {},
    }

    # --- Part 1: Gather Raw Data ---

    # 1. Get Config
    try:
        config_obj = get_current_config()
        status["config"]["latitude"] = config_obj.get("Location", "LATITUDE", fallback="Not Set")
        status["config"]["longitude"] = config_obj.get("Location", "LONGITUDE", fallback="Not Set")
        status["config"]["timezone"] = config_obj.get("Location", "TIMEZONE", fallback="Not Set")
        # Updated to new [Appearance] section
        status["config"]["light_theme"] = config_obj.get("Appearance", "LIGHT_THEME", fallback="Not Set")
        status["config"]["dark_theme"] = config_obj.get("Appearance", "DARK_THEME", fallback="Not Set")
        status["config"]["day_bg_profile"] = config_obj.get("Appearance", "DAY_BACKGROUND_PROFILE", fallback="Not Set")
        status["config"]["night_bg_profile"] = config_obj.get("Appearance", "NIGHT_BACKGROUND_PROFILE", fallback="Not Set")
    except exc.FluxFceError as e:
        status["config"]["error"] = str(e)
        log.error(f"API Status: Error loading config for status: {e}")

    # 2. Calculate Sun Times & Current Period
    tz_info, lat, lon, tz_name = None, None, None, None
    if "error" not in status["config"]:
        lat_str = status["config"]["latitude"]
        lon_str = status["config"]["longitude"]
        tz_name = status["config"]["timezone"]
        
        if all([lat_str, lon_str, tz_name, lat_str != "Not Set", lon_str != "Not Set", tz_name != "Not Set"]):
            try:
                lat = helpers.latlon_str_to_float(lat_str)
                lon = helpers.latlon_str_to_float(lon_str)
                tz_info = ZoneInfo(tz_name)
                now_local = datetime.now(tz_info)
                today = now_local.date()
                sun_times_today = sun.get_sun_times(lat, lon, today, tz_name)
                status["sun_times"]["sunrise"] = sun_times_today["sunrise"]
                status["sun_times"]["sunset"] = sun_times_today["sunset"]
                status["current_period"] = "day" if sun_times_today["sunrise"] <= now_local < sun_times_today["sunset"] else "night"
            except (exc.ValidationError, exc.CalculationError, ZoneInfoNotFoundError) as e_sun:
                status["sun_times"]["error"] = str(e_sun)
        else:
            status["sun_times"]["error"] = "Location/Timezone not fully configured."
    else:
        status["sun_times"]["error"] = "Cannot calculate sun times (config error)."
    
    # 3. Get Systemd Service Status (for verbose view)
    services_to_check = {
        "scheduler_service": sysd.SCHEDULER_SERVICE_NAME,
        "login_service": sysd.LOGIN_SERVICE_NAME,
        "resume_service": sysd.RESUME_SERVICE_NAME,
    }
    for key, unit_name in services_to_check.items():
        try:
            enabled_code, _, _ = _sysd_mgr_api._run_systemctl(["is-enabled", unit_name], check_errors=False, capture_output=True)
            active_code, _, _ = _sysd_mgr_api._run_systemctl(["is-active", unit_name], check_errors=False, capture_output=True)
            status["systemd_services"][key] = f"{'Enabled' if enabled_code == 0 else 'Disabled'}, {'Active' if active_code == 0 else 'Inactive'}"
        except Exception:
            status["systemd_services"][key] = "Error checking status"
            status["systemd_services"]["error"] = "One or more services could not be checked reliably."

    # --- Part 2: Analyze Raw Data and Generate Summary ---
    summary = {
        "overall_status": "[UNKNOWN]",
        "status_message": "Could not determine scheduler status.",
        "recommendation": "Try running with -v for more details.",
    }

    if status["config"].get("error"):
        summary["overall_status"] = "[ERROR]"
        summary["status_message"] = f"Configuration error: {status['config']['error']}"
        summary["recommendation"] = "Please check your config or run 'fluxfce install'."
    elif status["sun_times"].get("error"):
        summary["overall_status"] = "[ERROR]"
        summary["status_message"] = f"Sun calculation error: {status['sun_times']['error']}"
        summary["recommendation"] = "Please check location/timezone in your configuration."
    else:
        try:
            code, _, _ = _sysd_mgr_api._run_systemctl(["is-enabled", "--quiet", sysd.SCHEDULER_TIMER_NAME], check_errors=False)
            is_enabled = (code == 0)
            
            if not is_enabled:
                summary["overall_status"] = "[DISABLED]"
                summary["status_message"] = "Automatic scheduling is disabled."
                summary["recommendation"] = "Run 'fluxfce enable' to activate."
            else:
                summary["overall_status"] = "[OK]"
                summary["status_message"] = "Enabled and scheduling is active."
                summary["recommendation"] = None

                now = datetime.now(tz_info)
                sunrise_dt = status["sun_times"]["sunrise"]
                sunset_dt = status["sun_times"]["sunset"]

                next_sunrise = sunrise_dt if sunrise_dt > now else None
                next_sunset = sunset_dt if sunset_dt > now else None

                if not next_sunrise or not next_sunset:
                    tmrw_sun = sun.get_sun_times(lat, lon, now.date() + timedelta(days=1), tz_name)
                    if not next_sunrise: next_sunrise = tmrw_sun["sunrise"]
                    if not next_sunset: next_sunset = tmrw_sun["sunset"]

                if next_sunrise and (not next_sunset or next_sunrise < next_sunset):
                    summary["next_transition_time"] = next_sunrise
                    summary["next_transition_mode"] = "Day"
                elif next_sunset:
                    summary["next_transition_time"] = next_sunset
                    summary["next_transition_mode"] = "Night"
                
                summary["reschedule_time"] = (now + timedelta(days=1)).replace(hour=0, minute=15, second=0, microsecond=0)
        except exc.SystemdError as e:
            summary["overall_status"] = "[ERROR]"
            summary["status_message"] = f"Systemd error: {e}"
            summary["recommendation"] = "Check systemd with 'systemctl --user status'."
            
    status["summary"] = summary
    return status