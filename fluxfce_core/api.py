# ~/dev/fluxfce-simplified/fluxfce_core/api.py

import configparser
import logging
import pathlib
import sys
from datetime import datetime
from typing import Optional, Dict, Any, List

# Import core components and exceptions
from . import config as cfg
from . import exceptions as exc
from . import helpers
from . import scheduler as sched
from . import sun
from . import systemd as sysd
from . import xfce

# zoneinfo needed here for status/period calculation
try:
    from zoneinfo import ZoneInfo
except ImportError:
    raise ImportError("Required module 'zoneinfo' not found. FluxFCE requires Python 3.9+.")


log = logging.getLogger(__name__)

# --- Internal Helper ---

# Instantiate managers that are reused across API calls
# This assumes the API functions are called within the same process lifetime.
# If used differently, these might need to be instantiated per call.
_cfg_mgr = cfg.ConfigManager()
_xfce_handler = xfce.XfceHandler() # Checks xfconf-query, xsct on init
# Scheduler and SystemdManager check deps on init, instantiate only when needed
# or handle potential init errors in the functions using them.

def _get_current_config() -> configparser.ConfigParser:
    """Helper to load configuration, raising API-level error."""
    try:
        return _cfg_mgr.load_config()
    except exc.ConfigError as e:
        log.error(f"API: Failed to load configuration: {e}")
        raise exc.ConfigError(f"Failed to load configuration: {e}") from e
    except Exception as e:
        log.exception(f"API: Unexpected error loading configuration: {e}")
        raise exc.FluxFceError(f"Unexpected error loading configuration: {e}") from e

def _apply_settings_for_mode(mode: str) -> bool:
    """Internal helper to apply all settings for 'day' or 'night'."""
    if mode not in ['day', 'night']:
        raise exc.ValidationError(f"Invalid mode specified for apply: {mode}")

    config = _get_current_config()
    theme_key = 'LIGHT_THEME' if mode == 'day' else 'DARK_THEME'
    bg_section = 'BackgroundDay' if mode == 'day' else 'BackgroundNight'
    screen_section = 'ScreenDay' if mode == 'day' else 'ScreenNight'

    theme = config.get('Themes', theme_key, fallback=None)
    bg_hex1 = config.get(bg_section, 'BG_HEX1', fallback=None)
    bg_hex2 = config.get(bg_section, 'BG_HEX2', fallback=None)
    bg_dir = config.get(bg_section, 'BG_DIR', fallback=None)
    temp_str = config.get(screen_section, 'XSCT_TEMP', fallback=None)
    bright_str = config.get(screen_section, 'XSCT_BRIGHT', fallback=None)

    if not theme:
        raise exc.ConfigError(f"Theme '{theme_key}' not configured in [{config.Themes}].")

    xsct_temp: Optional[int] = None
    xsct_bright: Optional[float] = None
    try:
        # Special handling for ScreenDay - empty values mean reset xsct
        if mode == 'day' and (temp_str == '' or bright_str == ''):
             log.info("Day mode specifies resetting screen temperature/brightness.")
        elif temp_str is not None and bright_str is not None and temp_str != '' and bright_str != '':
             xsct_temp = int(temp_str)
             xsct_bright = float(bright_str)
        # Else: Leave as None if not configured or partially configured for night
    except (ValueError, TypeError) as e:
         log.warning(f"Could not parse screen settings from [{screen_section}]: {e}. Screen settings skipped.")
         # Don't raise, just skip applying screen settings

    theme_ok, bg_ok, screen_ok = True, True, True # Assume success unless failed

    # Apply Theme
    try:
        log.info(f"API: Applying theme '{theme}' for mode '{mode}'")
        _xfce_handler.set_gtk_theme(theme)
    except exc.XfceError as e:
        log.error(f"API: Failed to set theme: {e}")
        theme_ok = False
        # Propagate theme failure as it's critical
        raise exc.FluxFceError(f"Critical failure setting theme '{theme}': {e}") from e

    # Apply Background (if configured)
    if bg_hex1 and bg_dir:
        try:
            log.info(f"API: Applying background (Dir={bg_dir}, Hex1={bg_hex1}, Hex2={bg_hex2}) for mode '{mode}'")
            _xfce_handler.set_background(bg_hex1, bg_hex2, bg_dir)
        except (exc.XfceError, exc.ValidationError) as e:
            log.error(f"API: Failed to set background: {e}")
            bg_ok = False # Non-critical failure
    else:
        log.info("API: Background not fully configured in config, skipping background set.")

    # Apply Screen Settings
    try:
        log.info(f"API: Applying screen settings (Temp={xsct_temp}, Bright={xsct_bright}) for mode '{mode}'")
        _xfce_handler.set_screen_temp(xsct_temp, xsct_bright)
    except (exc.XfceError, exc.ValidationError) as e:
        log.error(f"API: Failed to set screen settings: {e}")
        screen_ok = False # Non-critical failure

    # Update state file only if theme applied successfully
    if theme_ok:
        try:
            _cfg_mgr.write_state(mode)
        except exc.ConfigError as e:
             log.error(f"API: Failed to write state file after applying mode '{mode}': {e}")
             # Don't mark overall failure just for state file write

    return theme_ok and bg_ok and screen_ok # Return overall success (True only if all succeed)

# --- Public API Functions ---

def install_fluxfce(script_path: str, python_executable: Optional[str] = None) -> bool:
    """
    Handles the installation process: creates config, installs systemd units.
    (Note: Interactive parts like prompting for Lat/Lon/Tz during install
     would typically be handled by the CLI/GUI layer calling specific config API functions).
    This function focuses on the systemd part after config is assumed present/defaulted.

    Args:
        script_path: Absolute path to the fluxfce script for systemd units.
        python_executable: Path to python interpreter. Defaults to sys.executable.

    Returns:
        True if installation (systemd units) succeeded.

    Raises:
        exc.FluxFceError / exc.SystemdError / exc.ConfigError / FileNotFoundError: On failure.
    """
    log.info("API: Starting fluxfce installation (systemd units).")
    # Ensure config directory exists and load config to apply defaults if first time
    _get_current_config()
    log.info("API: Configuration loaded/initialized.")

    try:
        # Instantiate SystemdManager here to check systemctl dependency at install time
        sysd_mgr = sysd.SystemdManager()
        success = sysd_mgr.install_units(script_path=script_path, python_executable=python_executable)
        if success:
             log.info("API: Systemd units installed successfully.")
             # Initial scheduling is handled by 'enable_scheduling' which should be called next
             return True
        else:
             # install_units should raise on failure, but double-check
             raise exc.SystemdError("SystemdManager install_units returned False.")
    except (exc.SystemdError, FileNotFoundError) as e:
         log.error(f"API: Systemd unit installation failed: {e}")
         raise # Re-raise specific error
    except Exception as e:
         log.exception(f"API: Unexpected error during installation: {e}")
         raise exc.FluxFceError(f"Unexpected error during installation: {e}") from e


def uninstall_fluxfce() -> bool:
    """
    Handles the uninstallation process: removes systemd units and clears schedule.
    (Note: Removing config dir is typically handled by CLI/GUI layer after confirmation).

    Returns:
        True if systemd removal and schedule clearing succeeded.

    Raises:
        exc.FluxFceError / exc.SystemdError / exc.SchedulerError: On failure.
    """
    log.info("API: Starting fluxfce uninstallation (systemd units, schedule).")
    schedule_clear_ok = False
    systemd_remove_ok = False

    # 1. Clear schedule
    try:
        # Instantiate scheduler here to check dependencies
        scheduler = sched.AtdScheduler()
        schedule_clear_ok = scheduler.clear_scheduled_transitions()
    except (exc.SchedulerError, exc.DependencyError) as e:
         log.error(f"API: Failed to clear schedule during uninstall: {e}")
         # Continue to systemd removal even if schedule clear fails
    except Exception as e:
         log.exception(f"API: Unexpected error clearing schedule during uninstall: {e}")

    # 2. Remove systemd units
    try:
        # Instantiate manager here to check dependencies
        sysd_mgr = sysd.SystemdManager()
        systemd_remove_ok = sysd_mgr.remove_units()
    except (exc.SystemdError, exc.DependencyError) as e:
         log.error(f"API: Failed to remove systemd units during uninstall: {e}")
    except Exception as e:
         log.exception(f"API: Unexpected error removing systemd units during uninstall: {e}")

    overall_success = schedule_clear_ok and systemd_remove_ok
    log.info(f"API: Uninstallation process completed. Overall success: {overall_success}")
    if not overall_success:
        # Raise a generic error if any part failed
        raise exc.FluxFceError("Uninstallation failed. Check logs for details on schedule clearing or systemd unit removal.")
    return True


def enable_scheduling(python_exe_path: str, script_exe_path: str) -> bool:
    """
    Enables automatic theme transitions by scheduling 'at' jobs.

    Args:
        python_exe_path: Absolute path to the Python interpreter.
        script_exe_path: Absolute path to the fluxfce script.

    Returns:
        True if scheduling was successful (at least one job scheduled).

    Raises:
        exc.ConfigError: If location config is missing/invalid.
        exc.ValidationError: If location config format is bad.
        exc.CalculationError: If sun times cannot be calculated.
        exc.SchedulerError: If atd interaction fails.
        FileNotFoundError: If exe paths are invalid.
    """
    log.info("API: Enabling automatic scheduling...")
    config = _get_current_config()
    try:
        lat_str = config.get('Location', 'LATITUDE')
        lon_str = config.get('Location', 'LONGITUDE')
        tz_name = config.get('Location', 'TIMEZONE')

        # Validate and convert lat/lon using helper
        lat = helpers.latlon_str_to_float(lat_str)
        lon = helpers.latlon_str_to_float(lon_str)

        if not tz_name: # Basic check for empty timezone
            raise exc.ValidationError("Timezone is not configured.")

        # Instantiate scheduler here
        scheduler = sched.AtdScheduler()
        success = scheduler.schedule_transitions(lat, lon, tz_name, python_exe_path, script_exe_path)
        log.info(f"API: Scheduling completed. Success: {success}")
        return success

    except (configparser.NoSectionError, configparser.NoOptionError) as e:
         raise exc.ConfigError(f"Location settings missing in configuration: {e}") from e
    # Re-raise specific errors from helpers/scheduler
    except (exc.ValidationError, exc.CalculationError, exc.SchedulerError, FileNotFoundError, exc.DependencyError) as e:
         log.error(f"API: Failed to enable scheduling: {e}")
         raise
    except Exception as e:
         log.exception(f"API: Unexpected error enabling scheduling: {e}")
         raise exc.FluxFceError(f"Unexpected error enabling scheduling: {e}") from e


def disable_scheduling() -> bool:
    """
    Disables automatic theme transitions by clearing 'at' jobs.

    Returns:
        True if clearing jobs was successful.

    Raises:
        exc.SchedulerError: If atd interaction fails.
    """
    log.info("API: Disabling automatic scheduling...")
    try:
        # Instantiate scheduler here
        scheduler = sched.AtdScheduler()
        success = scheduler.clear_scheduled_transitions()
        log.info(f"API: Clearing scheduled jobs completed. Success: {success}")
        return success
    except (exc.SchedulerError, exc.DependencyError) as e:
        log.error(f"API: Failed to disable scheduling: {e}")
        raise
    except Exception as e:
        log.exception(f"API: Unexpected error disabling scheduling: {e}")
        raise exc.FluxFceError(f"Unexpected error disabling scheduling: {e}") from e

def apply_manual_mode(mode: str) -> bool:
    """
    Manually applies Day or Night mode settings and disables scheduling.

    Args:
        mode: 'day' or 'night'.

    Returns:
        True if settings applied successfully and schedule cleared.

    Raises:
        exc.ValidationError: If mode is invalid.
        exc.FluxFceError / exc.SchedulerError / exc.ConfigError: On failure.
    """
    log.info(f"API: Manually applying mode '{mode}' and disabling schedule...")
    # 1. Apply settings for the mode
    apply_ok = _apply_settings_for_mode(mode) # Raises on critical (theme) failure

    # 2. Disable scheduling (clear jobs)
    disable_ok = False
    if apply_ok: # Only disable if apply seemed okay (or at least theme didn't fail)
        try:
            disable_ok = disable_scheduling()
            if not disable_ok:
                 log.warning("API: Applied settings, but failed to disable schedule (clear jobs).")
                 # Don't raise, just warn. The main action (apply) succeeded.
        except exc.SchedulerError as e:
             log.warning(f"API: Applied settings, but failed to disable schedule: {e}")
             # Don't raise
        except Exception as e:
             log.exception(f"API: Applied settings, but unexpected error disabling schedule: {e}")
             # Don't raise
    else:
         # Should not happen if _apply_settings_for_mode raises on critical failure
         log.error("API: Apply settings failed critically, cannot proceed to disable schedule.")
         raise exc.FluxFceError(f"Failed to apply settings for mode '{mode}' critically.")

    return apply_ok # Return success of the apply step

def set_default_from_current(mode: str) -> bool:
    """
    Saves the current desktop settings (theme, background, screen) as the
    new default configuration for the specified mode ('day' or 'night').

    Args:
        mode: 'day' or 'night'.

    Returns:
        True if settings were read and saved successfully.

    Raises:
        exc.ValidationError: If mode is invalid.
        exc.XfceError: If current settings cannot be read.
        exc.ConfigError: If configuration cannot be saved.
    """
    if mode not in ['day', 'night']:
        raise exc.ValidationError(f"Invalid mode for set-default: {mode}")

    log.info(f"API: Saving current desktop settings as default for mode '{mode}'...")

    try:
        # 1. Get Current Settings
        current_theme = _xfce_handler.get_gtk_theme() # Raises XfceError
        # get_background_settings raises XfceError if not in color mode or critical failure
        current_bg = _xfce_handler.get_background_settings()
        # get_screen_settings returns dict with None values if off/error, doesn't raise easily
        current_screen = _xfce_handler.get_screen_settings()

        # Theme is essential
        if not current_theme:
             raise exc.XfceError("Could not retrieve current GTK theme.")

        # 2. Load Config
        config = _get_current_config()
        config_changed = False

        # 3. Update Theme Setting
        theme_key = 'LIGHT_THEME' if mode == 'day' else 'DARK_THEME'
        if config.get('Themes', theme_key, fallback=None) != current_theme:
             _cfg_mgr.set_setting(config, 'Themes', theme_key, current_theme)
             log.debug(f"API: Updating [{mode} Theme] to '{current_theme}'")
             config_changed = True

        # 4. Update Background Settings
        bg_section = 'BackgroundDay' if mode == 'day' else 'BackgroundNight'
        if current_bg: # If background settings were successfully retrieved
             for key, config_key in [('dir', 'BG_DIR'), ('hex1', 'BG_HEX1'), ('hex2', 'BG_HEX2')]:
                 new_value = current_bg.get(key) # Can be None for hex2
                 current_value = config.get(bg_section, config_key, fallback=None)
                 # Treat None and empty string as same for comparison
                 new_value_str = str(new_value) if new_value is not None else ''
                 current_value_str = str(current_value) if current_value is not None else ''
                 if new_value_str != current_value_str:
                      _cfg_mgr.set_setting(config, bg_section, config_key, new_value_str)
                      log.debug(f"API: Updating [{bg_section} {config_key}] to '{new_value_str}'")
                      config_changed = True
        else:
             log.warning("API: Could not read current background settings; not updating defaults.")

        # 5. Update Screen Settings
        screen_section = 'ScreenDay' if mode == 'day' else 'ScreenNight'
        temp_to_save: Optional[str] = None
        bright_to_save: Optional[str] = None

        if current_screen: # If screen settings were read (even if None)
            cur_temp = current_screen.get('temperature')
            cur_bright = current_screen.get('brightness')
            if cur_temp is None and cur_bright is None:
                # Save as empty strings to signify reset in config
                temp_to_save = ''
                bright_to_save = ''
                log.debug("API: Current screen state is off/default; saving reset values ('')")
            elif cur_temp is not None and cur_bright is not None:
                temp_to_save = str(cur_temp)
                bright_to_save = f"{cur_bright:.2f}"
                log.debug(f"API: Current screen state: Temp={temp_to_save}, Bright={bright_to_save}")
            else:
                 log.warning("API: Inconsistent screen settings read; not updating defaults.")

        if temp_to_save is not None and bright_to_save is not None:
            if config.get(screen_section, 'XSCT_TEMP', fallback=None) != temp_to_save:
                _cfg_mgr.set_setting(config, screen_section, 'XSCT_TEMP', temp_to_save)
                log.debug(f"API: Updating [{screen_section} XSCT_TEMP] to '{temp_to_save}'")
                config_changed = True
            if config.get(screen_section, 'XSCT_BRIGHT', fallback=None) != bright_to_save:
                _cfg_mgr.set_setting(config, screen_section, 'XSCT_BRIGHT', bright_to_save)
                log.debug(f"API: Updating [{screen_section} XSCT_BRIGHT] to '{bright_to_save}'")
                config_changed = True

        # 6. Save Config if Changed
        if config_changed:
            _cfg_mgr.save_config(config) # Raises ConfigError on failure
            log.info(f"API: Successfully saved updated defaults for mode '{mode}'.")
            return True
        else:
            log.info(f"API: Current settings already match defaults for mode '{mode}'. No changes made.")
            return True # Indicate success even if no changes needed

    # Re-raise specific errors
    except (exc.ValidationError, exc.XfceError, exc.ConfigError) as e:
        log.error(f"API: Failed to set default from current: {e}")
        raise
    except Exception as e:
        log.exception(f"API: Unexpected error setting default from current: {e}")
        raise exc.FluxFceError(f"Unexpected error setting default from current: {e}") from e

def get_status() -> Dict[str, Any]:
    """
    Retrieves the current status of fluxfce.

    Returns:
        A dictionary containing status information. (Structure documented previously)

    Raises:
        FluxFceError for unexpected issues, but tries to return partial status
        even if some components fail. Errors within components are noted in the dict.
    """
    log.debug("API: Getting status...")
    status: Dict[str, Any] = {
        'config': {},
        'state': {'last_auto_applied': None},
        'sun_times': {'sunrise': None, 'sunset': None, 'error': None},
        'current_period': 'unknown',
        'schedule': {'enabled': False, 'jobs': [], 'error': None},
        # systemd statuses will be added dynamically below
        'systemd': {'error': None}
    }

    # 1. Get Config (Keep as before)
    try:
        config = _get_current_config()
        status['config']['latitude'] = config.get('Location', 'LATITUDE', fallback='Not Set')
        status['config']['longitude'] = config.get('Location', 'LONGITUDE', fallback='Not Set')
        status['config']['timezone'] = config.get('Location', 'TIMEZONE', fallback='Not Set')
        status['config']['light_theme'] = config.get('Themes', 'LIGHT_THEME', fallback='Not Set')
        status['config']['dark_theme'] = config.get('Themes', 'DARK_THEME', fallback='Not Set')
    except exc.FluxFceError as e:
         status['config']['error'] = str(e)

    # 2. Get State (Keep as before)
    try:
        status['state']['last_auto_applied'] = _cfg_mgr.read_state()
    except exc.ConfigError as e:
         status['state']['error'] = str(e)

    # 3. Calculate Sun Times & Current Period (Keep as before)
    lat_str = status['config'].get('latitude')
    lon_str = status['config'].get('longitude')
    tz_name = status['config'].get('timezone')
    lat, lon = None, None
    if lat_str and lon_str and tz_name and tz_name != 'Not Set':
        try:
            lat = helpers.latlon_str_to_float(lat_str)
            lon = helpers.latlon_str_to_float(lon_str)
            try:
                 tz_info = ZoneInfo(tz_name)
            except Exception as tz_err:
                 raise exc.ValidationError(f"Invalid timezone '{tz_name}': {tz_err}") from tz_err

            today = datetime.now(tz_info).date()
            sun_times_today = sun.get_sun_times(lat, lon, today, tz_name)
            status['sun_times']['sunrise'] = sun_times_today['sunrise']
            status['sun_times']['sunset'] = sun_times_today['sunset']

            now_local = datetime.now(tz_info)
            if sun_times_today['sunrise'] <= now_local < sun_times_today['sunset']:
                 status['current_period'] = 'day'
            else:
                 status['current_period'] = 'night'

        except (exc.ValidationError, exc.CalculationError) as e:
             status['sun_times']['error'] = str(e)
             status['current_period'] = 'error'
        except Exception as e:
             log.exception("API: Unexpected error calculating sun times for status.")
             status['sun_times']['error'] = f"Unexpected: {e}"
             status['current_period'] = 'error'
    else:
        status['sun_times']['error'] = "Location/Timezone not configured or invalid."
        status['current_period'] = 'unknown'


    # 4. Get Schedule Status (Keep as before)
    try:
        # Instantiate only if needed and handle potential init errors
        scheduler = sched.AtdScheduler()
        status['schedule']['jobs'] = scheduler.list_scheduled_transitions()
        status['schedule']['enabled'] = bool(status['schedule']['jobs'])
    except (exc.SchedulerError, exc.DependencyError) as e:
         status['schedule']['error'] = str(e)
    except Exception as e:
         log.exception("API: Unexpected error getting schedule status.")
         status['schedule']['error'] = f"Unexpected: {e}"


    # 5. Get Systemd Status (RE-CORRECTED KEY GENERATION and Status Logic)
    try:
        sysd_mgr = sysd.SystemdManager() # Instantiate here
        for unit_name in sysd.MANAGED_UNITS:
            # --- RE-CORRECTED KEY GENERATION ---
            # Generate a unique key based on the significant part of the unit name
            if sysd.SCHEDULER_TIMER_NAME == unit_name:
                unit_key = 'scheduler_timer'
            elif sysd.SCHEDULER_SERVICE_NAME == unit_name:
                unit_key = 'scheduler_service' # Use a distinct key
            elif sysd.LOGIN_SERVICE_NAME == unit_name:
                unit_key = 'login_service'    # Use a distinct key
            else:
                log.warning(f"API: Unrecognized managed unit name '{unit_name}' during status check.")
                continue # Skip unrecognized units
            # --- END RE-CORRECTION ---

            status['systemd'][unit_key] = "Error checking" # Default status

            enabled_status_str = "Unknown" # Default
            active_status_str = "Unknown"  # Default

            try:
                # Check Enabled Status
                # is-enabled: 0=enabled, 1=disabled/static, >1=error
                code_enabled, _, err_enabled = sysd_mgr._run_systemctl(['is-enabled', unit_name], check_errors=False)
                if code_enabled == 0:
                     enabled_status_str = "Enabled"
                elif code_enabled == 1:
                     enabled_status_str = "Disabled" # Covers 'disabled' and 'static'
                else:
                     enabled_status_str = f"Error ({code_enabled})"
                     log.warning(f"API: systemctl is-enabled failed for {unit_name}: {err_enabled}")

                # Check Active Status
                # is-active: 0=active, 3=inactive/dead, other non-zero=failed/error
                code_active, _, err_active = sysd_mgr._run_systemctl(['is-active', unit_name], check_errors=False)
                if code_active == 0:
                    active_status_str = "Active"
                    if unit_name.endswith(".timer"):
                        active_status_str += " (waiting)"
                elif code_active == 3:
                    active_status_str = "Inactive"
                else:
                    active_status_str = f"Failed/Error ({code_active})"
                    log.warning(f"API: systemctl is-active failed for {unit_name}: {err_active}")

                # Combine statuses, prioritizing error messages if present
                if "Error" in enabled_status_str or "Error" in active_status_str:
                     status['systemd'][unit_key] = f"{enabled_status_str}, {active_status_str}"
                elif "Unknown" in enabled_status_str or "Unknown" in active_status_str:
                     status['systemd'][unit_key] = "Unknown State" # If checks returned unexpected codes
                else:
                     status['systemd'][unit_key] = f"{enabled_status_str}, {active_status_str}"

                log.debug(f"API: Status for systemd unit {unit_name} (key: {unit_key}): {status['systemd'][unit_key]}")

            except exc.SystemdError as unit_e:
                 log.error(f"API: Could not get full status for systemd unit {unit_name}: {unit_e}")
                 status['systemd'][unit_key] = "Error processing" # Overwrite specific key on error
            except Exception as unit_e:
                 log.exception(f"API: Unexpected error getting status for unit {unit_name}: {unit_e}")
                 status['systemd'][unit_key] = "Unexpected error"

    except (exc.SystemdError, exc.DependencyError) as e:
         status['systemd']['error'] = f"Systemd check failed: {e}"
    except Exception as e:
         log.exception("API: Unexpected error getting systemd status.")
         status['systemd']['error'] = f"Unexpected error: {e}"

    return status

# --- Internal Command Handlers (Called by Executable Script) ---

def handle_internal_apply(mode: str) -> bool:
    """
    Called internally by the scheduled 'at' job or login service.
    Applies settings for the given mode.

    Args:
        mode: 'day' or 'night'.

    Returns:
        True on success, False on failure (used for exit code).
    """
    log.info(f"API: Internal apply called for mode '{mode}'")
    try:
        return _apply_settings_for_mode(mode)
    except exc.FluxFceError as e:
        # Log errors that occur during the apply process
        log.error(f"API: Error during internal apply for mode '{mode}': {e}")
        return False
    except Exception as e:
        log.exception(f"API: Unexpected error during internal apply for mode '{mode}': {e}")
        return False

def handle_schedule_jobs_command(python_exe_path: str, script_exe_path: str) -> bool:
    """
    Called internally by the systemd scheduler service timer.
    Calculates and schedules the next 'at' jobs.

    Args:
        python_exe_path: Absolute path to the Python interpreter.
        script_exe_path: Absolute path to the fluxfce script.

    Returns:
        True on success, False on failure (used for exit code).
    """
    log.info("API: Handling schedule-jobs command...")
    try:
        return enable_scheduling(python_exe_path, script_exe_path)
    except exc.FluxFceError as e:
        log.error(f"API: Error during schedule-jobs command: {e}")
        return False
    except Exception as e:
        log.exception(f"API: Unexpected error during schedule-jobs command: {e}")
        return False

def handle_run_login_check() -> bool:
    """
    Called internally by the systemd login service.
    Determines the current period (day/night) and applies the appropriate theme.

    Returns:
        True on success, False on failure (used for exit code).
    """
    log.info("API: Handling run-login-check command...")
    try:
        config = _get_current_config()
        lat_str = config.get('Location', 'LATITUDE')
        lon_str = config.get('Location', 'LONGITUDE')
        tz_name = config.get('Location', 'TIMEZONE')

        mode_to_apply = 'night' # Default assumption

        if lat_str and lon_str and tz_name:
            try:
                lat = helpers.latlon_str_to_float(lat_str)
                lon = helpers.latlon_str_to_float(lon_str)
                tz_info = ZoneInfo(tz_name) # Raises on invalid tz
                now_local = datetime.now(tz_info)
                today = now_local.date()
                sun_times = sun.get_sun_times(lat, lon, today, tz_name) # Raises CalculationError
                if sun_times['sunrise'] <= now_local < sun_times['sunset']:
                    mode_to_apply = 'day'
                log.info(f"API: Login check determined current mode: '{mode_to_apply}'")
            except (exc.ValidationError, exc.CalculationError, ZoneInfoNotFoundError) as e:
                log.warning(f"API: Could not determine correct mode for login check ({e}). Defaulting to '{mode_to_apply}'.")
            except Exception as e:
                log.exception(f"API: Unexpected error determining mode for login check. Defaulting to '{mode_to_apply}'.")
        else:
            log.warning("API: Location/Timezone not configured for login check. Defaulting to 'night'.")

        log.info(f"API: Applying mode '{mode_to_apply}' for login check.")
        return _apply_settings_for_mode(mode_to_apply)

    except exc.FluxFceError as e:
        log.error(f"API: Error during run-login-check: {e}")
        return False
    except Exception as e:
        log.exception(f"API: Unexpected error during run-login-check: {e}")
        return False

# --- Optional: Add setup_library_logging to __init__.py or call here ---
# helpers.setup_library_logging() # Configure core logging on import?