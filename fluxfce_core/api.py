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
import re 
from datetime import datetime # For get_status, timedelta was only in scheduler
from typing import Any, Optional

# Import core components and exceptions
from . import config as cfg # For ConfigManager instance if api needs one directly
from . import exceptions as exc
from . import helpers, sun, xfce, systemd as sysd # systemd might be needed for constants

# --- NEW IMPORTS from refactored modules ---
from . import desktop_manager # For appearance and related handlers
from . import scheduler       # For scheduling logic

# zoneinfo needed for get_status and potentially other api-level functions if any evolve
try:
    from zoneinfo import (
        ZoneInfo,
        ZoneInfoNotFoundError,
    )
except ImportError: # Should be caught by Python version checks or at a higher level
    raise ImportError(
        "Required module 'zoneinfo' not found. FluxFCE requires Python 3.9+."
    )

log = logging.getLogger(__name__)

# --- Module-level Managers (Primarily for functions still residing in api.py like get_status) ---
# If all logic moves out, these might not be needed here.
_cfg_mgr_api = cfg.ConfigManager()
_sysd_mgr_api = sysd.SystemdManager() # Used by get_status

# --- Public API Functions for Config ---
# These are fundamental and can stay in api.py or move to a config_manager_facade.py
# For now, keeping them here for simplicity of this refactor step.

def get_current_config() -> configparser.ConfigParser:
    """Loads the current configuration, applying defaults in memory."""
    log.debug("API: get_current_config called")
    try:
        # Assuming _cfg_mgr_api is the intended ConfigManager instance for this
        return _cfg_mgr_api.load_config()
    except exc.ConfigError as e:
        log.error(f"API: Failed to load configuration: {e}")
        raise 
    except Exception as e:
        log.exception(f"API: Unexpected error loading configuration: {e}")
        raise exc.FluxFceError(f"Unexpected error loading configuration: {e}") from e

def save_configuration(config_obj: configparser.ConfigParser) -> bool:
    """Saves the given ConfigParser object to file."""
    log.debug("API: save_configuration called")
    try:
        return _cfg_mgr_api.save_config(config_obj)
    except exc.ConfigError as e:
        log.error(f"API: Failed to save configuration: {e}")
        raise
    except Exception as e:
        log.exception(f"API: Unexpected error saving configuration: {e}")
        raise exc.FluxFceError(f"Unexpected error saving configuration: {e}") from e

# --- Installation and Uninstallation ---
# These orchestrate actions from systemd.py and scheduler.py

def install_fluxfce(script_path: str, python_executable: Optional[str] = None) -> bool:
    """
    API Façade: Installs static systemd units.
    The CLI will call enable_scheduling after this.
    """
    log.info(f"API Facade: Installing static systemd units for {sysd._APP_NAME}.")
    try:
        # Use a local SystemdManager instance for this specific task
        install_mgr = sysd.SystemdManager()
        success = install_mgr.install_units(
            script_path=script_path, python_executable=python_executable
        )
        if success:
            log.info("API Facade: Static systemd units installed successfully.")
            return True
        else:
            # install_units should ideally raise on critical failure.
            raise exc.SystemdError(f"API Facade: SystemdManager install_units failed for {sysd._APP_NAME}.")
    except (exc.SystemdError, FileNotFoundError, exc.DependencyError) as e:
        log.error(f"API Facade: Static systemd unit installation failed: {e}")
        raise
    except Exception as e:
        log.exception(f"API Facade: Unexpected error during {sysd._APP_NAME} installation: {e}")
        raise exc.FluxFceError(f"API Facade: Unexpected error during {sysd._APP_NAME} installation: {e}") from e

def uninstall_fluxfce() -> bool:
    """
    API Façade: Disables scheduling and removes all systemd units.
    """
    log.info(f"API Facade: Uninstalling {sysd._APP_NAME} (disabling schedule, removing units).")
    try:
        disable_success = True
        try:
            # Call the scheduler module to handle its part of disabling
            scheduler.disable_scheduling() 
            log.info("API Facade: Scheduling disabled by scheduler module.")
        except Exception as e_disable:
            log.warning(f"API Facade: Error during scheduler.disable_scheduling in uninstall (continuing): {e_disable}")
            disable_success = False # Logged, but uninstallation of files should proceed

        # Remove static unit files via SystemdManager
        uninstall_mgr = sysd.SystemdManager()
        removal_ok = uninstall_mgr.remove_units()
        
        if removal_ok:
            log.info(f"API Facade: Systemd units removed by SystemdManager.")
            if not disable_success:
                 log.warning("API Facade: Uninstallation completed, but disabling/cleanup of schedule encountered issues.")
            return True
        else:
            raise exc.SystemdError(f"API Facade: SystemdManager remove_units failed for {sysd._APP_NAME}.")
    except (exc.SystemdError, exc.DependencyError) as e:
        log.error(f"API Facade: Failed to remove {sysd._APP_NAME} systemd units: {e}")
        raise
    except Exception as e:
        log.exception(f"API Facade: Unexpected error during {sysd._APP_NAME} uninstallation: {e}")
        raise exc.FluxFceError(f"API Facade: Unexpected error during {sysd._APP_NAME} uninstallation: {e}") from e


# --- SCHEDULING FAÇADE ---

def enable_scheduling(python_exe_path: str, script_exe_path: str) -> bool:
    """
    API Façade: Enables scheduling and applies the theme for the current solar period.
    """
    log.info("API Facade: Attempting to enable scheduling...")
    
    # Step 1 & 2: Enable scheduling via the scheduler module
    # This sets up timers and starts the main scheduler.timer --now
    try:
        scheduler_enabled_ok = scheduler.enable_scheduling(
            python_exe_path=python_exe_path, script_exe_path=script_exe_path
        )
    except exc.FluxFceError as e_sched: # Catch errors from scheduler.enable_scheduling
        log.error(f"API Facade: Scheduler module failed to enable scheduling: {e_sched}")
        raise # Re-raise to be caught by CLI
    except Exception as e_sched_unexpected:
        log.exception(f"API Facade: Unexpected error from scheduler.enable_scheduling: {e_sched_unexpected}")
        raise exc.FluxFceError(f"API Facade: Unexpected error from scheduler.enable_scheduling: {e_sched_unexpected}") from e_sched_unexpected


    # Step 3: Explicitly apply the theme for the current actual period.
    log.info("API Facade: Scheduling setup by scheduler module. Applying theme for current solar period...")
    try:
        # desktop_manager.handle_run_login_check() determines current period and applies settings.
        apply_current_ok = desktop_manager.handle_run_login_check()
        if apply_current_ok:
            log.info("API Facade: Theme for current solar period applied successfully.")
        else:
            # This means applying the current theme failed. This is a significant issue.
            log.error("API Facade: FAILED to apply theme for the current solar period after enabling schedule.")
            # Consider if this should make the whole operation fail.
            # For now, scheduling might be enabled, but the state isn't right.
            # The CLI should inform the user. FluxFceError could be raised here.
            # Let's return False to indicate a problem.
            return False 
    except exc.FluxFceError as e_apply_current:
        log.error(f"API Facade: Error applying current theme after enabling scheduling: {e_apply_current}")
        raise # Re-raise to be caught by CLI
    except Exception as e_apply_unexpected:
        log.exception(f"API Facade: Unexpected error applying current theme after enabling scheduling: {e_apply_unexpected}")
        raise exc.FluxFceError(f"Unexpected error applying current theme: {e_apply_unexpected}") from e_apply_unexpected
    
    log.info("API Facade: Scheduling enabled and current theme applied.")
    return True # If we reach here, scheduler setup and current theme application were successful

def disable_scheduling() -> bool:
    """API Façade: Disables scheduling by calling the scheduler module."""
    log.info("API Facade: Calling scheduler.disable_scheduling...")
    return scheduler.disable_scheduling()

def handle_schedule_dynamic_transitions_command(python_exe_path: str, script_exe_path: str) -> bool:
    """API Façade: For CLI internal command to call the scheduler function."""
    log.debug("API Facade: Relaying 'schedule-dynamic-transitions' to scheduler module.")
    return scheduler.handle_schedule_dynamic_transitions_command(python_exe_path, script_exe_path)


# --- DESKTOP APPEARANCE FAÇADE (via desktop_manager) ---

def apply_temporary_mode(mode: str) -> bool:
    """
    API Façade: Applies an appearance mode temporarily, WITHOUT disabling scheduling.
    """
    log.info(f"API Facade: Applying temporary mode '{mode}' (scheduling remains active)...")
    try:
        # Step 1: Apply the visual mode using the desktop manager
        return desktop_manager.apply_mode(mode)
    except exc.FluxFceError as e_apply: # Catch errors from desktop_manager.apply_mode
        log.error(f"API Facade: desktop_manager.apply_mode('{mode}') failed: {e_apply}")
        raise # Re-raise the original apply error
    except Exception as e_apply_unexpected:
        log.exception(f"API Facade: Unexpected error from desktop_manager.apply_mode('{mode}'): {e_apply_unexpected}")
        raise exc.FluxFceError(f"Unexpected error applying temporary mode '{mode}'") from e_apply_unexpected

def apply_manual_mode(mode: str) -> bool:
    """
    API Façade: Applies a manual appearance mode and disables scheduling.
    """
    log.info(f"API Facade: Applying manual mode '{mode}' and then disabling scheduling...")
    
    try:
        # Step 1: Apply the visual mode using the desktop manager
        apply_appearance_ok = desktop_manager.apply_mode(mode) 
    except exc.FluxFceError as e_apply: # Catch errors from desktop_manager.apply_manual_mode
        log.error(f"API Facade: desktop_manager.apply_manual_mode('{mode}') failed: {e_apply}")
        # Even if applying appearance fails, still attempt to disable scheduling.
        # But the overall operation has failed.
        try:
            scheduler.disable_scheduling()
        except Exception as e_disable:
            log.warning(f"API Facade: Failed to disable scheduling after failed manual mode apply: {e_disable}")
        raise # Re-raise the original apply error
    except Exception as e_apply_unexpected:
        log.exception(f"API Facade: Unexpected error from desktop_manager.apply_manual_mode('{mode}'): {e_apply_unexpected}")
        try:
            scheduler.disable_scheduling()
        except Exception as e_disable:
            log.warning(f"API Facade: Failed to disable scheduling after unexpected manual mode apply error: {e_disable}")
        raise exc.FluxFceError(f"Unexpected error applying manual mode '{mode}'") from e_apply_unexpected


    # Step 2: Disable scheduling using the scheduler module
    try:
        disable_sched_ok = scheduler.disable_scheduling()
        if not disable_sched_ok:
            log.warning("API Facade: Appearance for manual mode applied, but scheduler.disable_scheduling reported an issue.")
            # If applying appearance was OK, but disabling schedule failed, this is a mixed success.
            # For now, if apply_appearance_ok was true, we return true.
    except exc.FluxFceError as e_disable:
        log.warning(f"API Facade: Appearance for manual mode applied, but scheduler.disable_scheduling failed: {e_disable}")
        # Similar to above, the primary action (applying mode) might have succeeded.
    except Exception as e_disable_unexpected:
        log.exception(f"API Facade: Unexpected error from scheduler.disable_scheduling during manual mode: {e_disable_unexpected}")

    # apply_appearance_ok is True if desktop_manager.apply_manual_mode didn't raise an error
    return apply_appearance_ok

def set_default_from_current(mode: str) -> bool:
    """API Façade: Saves current desktop settings as default via desktop_manager."""
    log.info(f"API Facade: Calling desktop_manager.set_defaults_from_current for mode '{mode}'.")
    return desktop_manager.set_defaults_from_current(mode)


# --- INTERNAL COMMAND HANDLERS FAÇADE (via desktop_manager) ---
# These are called by the CLI for systemd service execution.

def handle_internal_apply(mode: str) -> bool:
    """API Façade: Relays to desktop_manager.handle_internal_apply."""
    log.debug(f"API Facade: Relaying 'internal-apply --mode {mode}' to desktop_manager.")
    return desktop_manager.handle_internal_apply(mode)

def handle_run_login_check() -> bool:
    """API Façade: Relays to desktop_manager.handle_run_login_check."""
    log.debug("API Facade: Relaying 'run-login-check' to desktop_manager.")
    return desktop_manager.handle_run_login_check()
        

# --- STATUS FUNCTION (Remains in api.py as it aggregates from multiple sources) ---
def get_status() -> dict[str, Any]:
    """Retrieves the current status of fluxfce."""
    log.debug("API: Getting status...")
    status: dict[str, Any] = {
        "config": {},
        "sun_times": {"sunrise": None, "sunset": None, "error": None},
        "current_period": "unknown",
        "schedule": {"error": None, "timers": {}},
        "systemd_services": {"error": None},
    }

    # 1. Get Config
    try:
        config_obj = get_current_config()
        status["config"]["latitude"] = config_obj.get("Location", "LATITUDE", fallback="Not Set")
        status["config"]["longitude"] = config_obj.get("Location", "LONGITUDE", fallback="Not Set")
        status["config"]["timezone"] = config_obj.get("Location", "TIMEZONE", fallback="Not Set")
        status["config"]["light_theme"] = config_obj.get("Themes", "LIGHT_THEME", fallback="Not Set")
        status["config"]["dark_theme"] = config_obj.get("Themes", "DARK_THEME", fallback="Not Set")
    except exc.FluxFceError as e: # Catch errors from get_current_config()
        status["config"]["error"] = str(e)
        log.error(f"API Status: Error loading config for status: {e}")


    # 2. Calculate Sun Times & Current Period
    # This part relies on config being loaded.
    if "error" not in status["config"]: # Only proceed if config was loaded
        lat_str = status["config"]["latitude"]
        lon_str = status["config"]["longitude"]
        tz_name = status["config"]["timezone"]
        
        if all([lat_str, lon_str, tz_name, 
                lat_str != "Not Set", lon_str != "Not Set", tz_name != "Not Set"]):
            try:
                # Option 1: Re-use logic from desktop_manager if determine_current_period is there
                # current_period = desktop_manager.determine_current_period(config_obj)
                # status["current_period"] = current_period
                # # Need to get sun_times separately if determine_current_period doesn't return them
                # lat = helpers.latlon_str_to_float(lat_str)
                # lon = helpers.latlon_str_to_float(lon_str)
                # tz_info = ZoneInfo(tz_name)
                # today = datetime.now(tz_info).date()
                # sun_times_today = sun.get_sun_times(lat, lon, today, tz_name)
                # status["sun_times"]["sunrise"] = sun_times_today["sunrise"]
                # status["sun_times"]["sunset"] = sun_times_today["sunset"]

                # Option 2: Keep logic here for now (as in codebase.txt)
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
                status["current_period"] = "error (sun calculation/config)"
                log.warning(f"API Status: Error calculating sun times/period: {e_sun}")
            except Exception as e_sun_unexpected: 
                log.exception("API Status: Unexpected error calculating sun times/period.")
                status["sun_times"]["error"] = f"Unexpected error in sun times: {e_sun_unexpected}"
                status["current_period"] = "error (unexpected)"
        else:
            status["sun_times"]["error"] = "Location/Timezone not fully configured."
            status["current_period"] = "unknown (config incomplete)"
    else: # Config loading error
        status["sun_times"]["error"] = "Cannot calculate sun times (config error)."
        status["current_period"] = "unknown (config error)"
    
    # 3. Get Systemd Timer Schedule Status
    timer_names_to_query = [
        sysd.SCHEDULER_TIMER_NAME,
        sysd.SUNRISE_EVENT_TIMER_NAME,
        sysd.SUNSET_EVENT_TIMER_NAME,
    ]
    try:
        code, stdout_timers, stderr_timers = _sysd_mgr_api._run_systemctl(
            ["list-timers", "--all", *timer_names_to_query],
            check_errors=False, capture_output=True
        )
        
        if code != 0 and not ("0 timers listed." in stdout_timers or "No timers found." in stdout_timers):
            err_msg = f"Failed to list systemd timers (code {code}): {stderr_timers.strip() or stdout_timers.strip()}"
            status["schedule"]["error"] = err_msg
            log.warning(f"API Status: {err_msg}")
        
        if stdout_timers:
            parsed_timers = {}
            lines = stdout_timers.strip().split('\n')
            # Check if there's a header and at least one data line
            if len(lines) > 1 and "NEXT" in lines[0].upper():
                header_line = lines[0].upper()
                col_indices = {
                    "NEXT": header_line.find("NEXT"), "LEFT": header_line.find("LEFT"),
                    "LAST": header_line.find("LAST"), "PASSED": header_line.find("PASSED"),
                    "UNIT": header_line.find("UNIT"), "ACTIVATES": header_line.find("ACTIVATES"),
                }
                # Filter out columns not found and sort them by their start index
                sorted_cols = sorted([(name, idx) for name, idx in col_indices.items() if idx != -1], key=lambda item: item[1])

                for line_content in lines[1:]: # Skip header line
                    if not line_content.strip() or not any(tn in line_content for tn in timer_names_to_query):
                        continue # Skip empty lines or lines not containing our timer names
                    
                    timer_data_raw = {}
                    current_unit_name = "" # Initialize
                    
                    # Parse line based on detected column positions
                    for i, (col_name, start_idx) in enumerate(sorted_cols):
                        end_idx = sorted_cols[i+1][1] if i + 1 < len(sorted_cols) else len(line_content)
                        field_value = line_content[start_idx:end_idx].strip()
                        timer_data_raw[col_name.lower()] = field_value
                        if col_name == "UNIT": 
                            current_unit_name = field_value
                    
                    if current_unit_name and current_unit_name in timer_names_to_query:
                        is_enabled_code, _, _ = _sysd_mgr_api._run_systemctl(["is-enabled", current_unit_name], check_errors=False, capture_output=True)
                        is_active_code, _, _ = _sysd_mgr_api._run_systemctl(["is-active", current_unit_name], check_errors=False, capture_output=True)
                        
                        parsed_timers[current_unit_name] = {
                            "enabled": "Enabled" if is_enabled_code == 0 else "Disabled",
                            "active": "Active" if is_active_code == 0 else "Inactive",
                            "next_run": timer_data_raw.get("next", "N/A"),
                            "time_left": timer_data_raw.get("left", "N/A"),
                            "last_run": timer_data_raw.get("last", "N/A"),
                            "activates": timer_data_raw.get("activates", "N/A")
                        }
            
            status["schedule"]["timers"] = parsed_timers
            if not parsed_timers and not status["schedule"].get("error"):
                msg_no_timers = "No relevant fluxfce timers found or listed by systemctl."
                if "0 timers listed." in stdout_timers or "No timers found." in stdout_timers:
                    status["schedule"]["info"] = msg_no_timers
                # else if stdout_timers is not empty but parsing yielded nothing, it's also "not found" effectively
                elif stdout_timers.strip() and not lines[0].upper().startswith("NEXT"): # Handle cases where output is not the expected table
                    status["schedule"]["info"] = f"Unexpected timer listing format. Output: {stdout_timers[:100]}..."
                else: # Default "not found" if truly empty or parsing fails
                    status["schedule"]["info"] = msg_no_timers


    except Exception as e_timers:
        log.exception("API Status: Unexpected error getting systemd timer schedule status.")
        status["schedule"]["error"] = f"Unexpected error querying timers: {e_timers}"

    # 4. Get Systemd Service Status
    services_to_check = {
        "scheduler_service": sysd.SCHEDULER_SERVICE_NAME,
        "login_service": sysd.LOGIN_SERVICE_NAME,
        "resume_service": sysd.RESUME_SERVICE_NAME,
    }
    any_service_error_occurred = False
    for key, unit_name in services_to_check.items():
        try:
            enabled_code, _, _ = _sysd_mgr_api._run_systemctl(["is-enabled", unit_name], check_errors=False, capture_output=True)
            active_code, _, _ = _sysd_mgr_api._run_systemctl(["is-active", unit_name], check_errors=False, capture_output=True)
            status["systemd_services"][key] = f"{'Enabled' if enabled_code == 0 else 'Disabled'}, {'Active' if active_code == 0 else 'Inactive'}"
        except exc.SystemdError as e_svc: # This should ideally not be hit if _run_systemctl handles its errors
            status["systemd_services"][key] = f"Error checking ({unit_name}): {e_svc}"
            any_service_error_occurred = True
            log.warning(f"API Status: SystemdError checking service {unit_name}: {e_svc}")
        except Exception as e_svc_unexpected:
            log.exception(f"API Status: Unexpected error getting status for service {unit_name}")
            status["systemd_services"][key] = f"Unexpected error checking {unit_name}"
            any_service_error_occurred = True
            
    if any_service_error_occurred and not status["systemd_services"].get("error"): # Add a general error if specific one wasn't set
        status["systemd_services"]["error"] = "One or more services could not be checked reliably."
            
    return status
