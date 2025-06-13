# ~/dev/fluxfce-simplified/fluxfce_core/api.py

import configparser  # Ensure this is imported
import logging
from datetime import datetime
from typing import Any, Optional

# Import core components and exceptions
from . import config as cfg
from . import exceptions as exc
from . import helpers, sun, xfce
from . import scheduler as sched
from . import systemd as sysd
from . import desktop_manager # Added for internal transitions
from .scheduler import schedule_dynamic_transitions # Added for dynamic timer scheduling
# sun.get_sun_times is available via 'from . import sun' then sun.get_sun_times
# datetime, ZoneInfo, ZoneInfoNotFoundError are already imported
# configparser is already imported

# zoneinfo needed here for status/period calculation
try:
    from zoneinfo import (
        ZoneInfo,
        ZoneInfoNotFoundError,
    )  # Corrected import location for check
except ImportError:
    raise ImportError(
        "Required module 'zoneinfo' not found. FluxFCE requires Python 3.9+."
    )


log = logging.getLogger(__name__)

# --- Internal Helper ---

# Instantiate managers that are reused across API calls
_cfg_mgr = cfg.ConfigManager()
_xfce_handler = xfce.XfceHandler()  # Checks xfconf-query, xsct on init


# RENAMED Internal Helper
def _load_config_with_defaults() -> configparser.ConfigParser:
    """Internal helper to load configuration, applying defaults in memory."""
    try:
        # Assume _cfg_mgr is already instantiated at module level
        return _cfg_mgr.load_config()
    except exc.ConfigError as e:
        log.error(f"API Helper: Failed to load configuration: {e}")
        raise exc.ConfigError(f"Failed to load configuration: {e}") from e
    except Exception as e:
        log.exception(f"API Helper: Unexpected error loading configuration: {e}")
        raise exc.FluxFceError(f"Unexpected error loading configuration: {e}") from e


def handle_internal_transition(mode: str) -> bool:
    """
    Called by the transition service to perform the gradual transition.
    Delegates to desktop_manager.
    """
    log.info(f"API: Handling internal transition for mode '{mode}'...")
    try:
        return desktop_manager.handle_gradual_transition(mode)
    except Exception as e: # Catch any unexpected error from desktop_manager
        log.exception(f"API: Unexpected error during handle_internal_transition for mode '{mode}': {e}")
        return False


# Updated internal helper to use the renamed config loader
def _apply_settings_for_mode(mode: str) -> bool:
    """Internal helper to apply all settings for 'day' or 'night'."""
    if mode not in ["day", "night"]:
        raise exc.ValidationError(f"Invalid mode specified for apply: {mode}")

    config = _load_config_with_defaults()  # UPDATED Call to renamed helper
    theme_key = "LIGHT_THEME" if mode == "day" else "DARK_THEME"
    bg_section = "BackgroundDay" if mode == "day" else "BackgroundNight"
    screen_section = "ScreenDay" if mode == "day" else "ScreenNight"

    theme = config.get("Themes", theme_key, fallback=None)
    bg_hex1 = config.get(bg_section, "BG_HEX1", fallback=None)
    bg_hex2 = config.get(bg_section, "BG_HEX2", fallback=None)
    bg_dir = config.get(bg_section, "BG_DIR", fallback=None)
    temp_str = config.get(screen_section, "XSCT_TEMP", fallback=None)
    bright_str = config.get(screen_section, "XSCT_BRIGHT", fallback=None)

    if not theme:
        # Ensure the section name is correct in the error message
        raise exc.ConfigError(f"Theme '{theme_key}' not configured in [Themes].")

    xsct_temp: Optional[int] = None
    xsct_bright: Optional[float] = None
    try:
        # Correct logic for Day mode reset (empty string signifies reset)
        if mode == "day" and (temp_str == "" or bright_str == ""):
            log.info("Day mode specifies resetting screen temperature/brightness.")
            # Ensure xsct_temp and xsct_bright remain None for reset call
        # Check for Night mode or non-empty Day mode values
        elif (
            temp_str is not None
            and bright_str is not None
            and temp_str != ""
            and bright_str != ""
        ):
            xsct_temp = int(temp_str)
            xsct_bright = float(bright_str)
        # Else: Leave as None if not configured or partially configured
    except (ValueError, TypeError) as e:
        log.warning(
            f"Could not parse screen settings from [{screen_section}]: {e}. Screen settings skipped."
        )

    theme_ok, bg_ok, screen_ok = True, True, True  # Assume success unless failed

    # Apply Theme
    try:
        log.info(f"API: Applying theme '{theme}' for mode '{mode}'")
        _xfce_handler.set_gtk_theme(theme)
    except (exc.XfceError, exc.ValidationError) as e:  # Catch validation error too
        log.error(f"API: Failed to set theme: {e}")
        theme_ok = False
        raise exc.FluxFceError(f"Critical failure setting theme '{theme}': {e}") from e

    # Apply Background (if configured)
    if bg_hex1 and bg_dir:
        try:
            log.info(
                f"API: Applying background (Dir={bg_dir}, Hex1={bg_hex1}, Hex2={bg_hex2}) for mode '{mode}'"
            )
            _xfce_handler.set_background(bg_hex1, bg_hex2, bg_dir)
        except (exc.XfceError, exc.ValidationError) as e:
            log.error(f"API: Failed to set background: {e}")
            bg_ok = False
    else:
        log.info(
            "API: Background not fully configured in config, skipping background set."
        )

    # Apply Screen Settings
    try:
        log.info(
            f"API: Applying screen settings (Temp={xsct_temp}, Bright={xsct_bright}) for mode '{mode}'"
        )
        _xfce_handler.set_screen_temp(xsct_temp, xsct_bright)
    except (exc.XfceError, exc.ValidationError) as e:
        log.error(f"API: Failed to set screen settings: {e}")
        screen_ok = False

    # Only return True if critical theme step succeeded. BG/Screen are optional.
    # Return theme_ok # Decide if partial success is okay
    if not theme_ok:  # If theme failed, it's a failure
        return False
    if not bg_ok:
        log.warning(f"Mode '{mode}' applied, but background setting failed.")
    if not screen_ok:
        log.warning(f"Mode '{mode}' applied, but screen setting failed.")
    return True  # Return True if theme succeeded, even if bg/screen failed


# --- NEW Public API Functions for Config ---
def get_current_config() -> configparser.ConfigParser:
    """
    Public API function to load the current configuration using ConfigManager.
    Applies defaults in memory if keys/sections are missing.

    Returns:
        The loaded ConfigParser object.

    Raises:
        exc.ConfigError: If loading or parsing fails.
        exc.FluxFceError: For unexpected errors during loading.
    """
    log.debug("API: get_current_config called")
    # Call the renamed internal helper
    return _load_config_with_defaults()


def save_configuration(config_obj: configparser.ConfigParser) -> bool:
    """
    Public API function to save the given ConfigParser object to file.

    Args:
        config_obj: The ConfigParser object to save.

    Returns:
        True on success.

    Raises:
        exc.ConfigError: If saving fails.
        exc.FluxFceError: For unexpected errors during saving.
    """
    log.debug("API: save_configuration called")
    try:
        # Assume _cfg_mgr is already instantiated at module level
        return _cfg_mgr.save_config(config_obj)
    except exc.ConfigError as e:
        log.error(f"API: Failed to save configuration: {e}")
        raise  # Re-raise the specific error
    except Exception as e:
        log.exception(f"API: Unexpected error saving configuration: {e}")
        raise exc.FluxFceError(f"Unexpected error saving configuration: {e}") from e


# --- Existing Public API Functions ---


def install_fluxfce(script_path: str, python_executable: Optional[str] = None) -> bool:
    """
    Handles the installation process: creates config, installs systemd units.
    Assumes config file creation/defaults are handled by the caller using
    get_current_config() and save_configuration() if needed before calling this.

    Args:
        script_path: Absolute path to the fluxfce script for systemd units.
        python_executable: Path to python interpreter. Defaults to sys.executable.

    Returns:
        True if installation (systemd units) succeeded.

    Raises:
        exc.FluxFceError / exc.SystemdError / FileNotFoundError: On failure.
    """
    log.info("API: Starting fluxfce installation (systemd units).")
    # Config loading/saving is now responsibility of the caller (CLI)

    try:
        sysd_mgr = sysd.SystemdManager()
        success = sysd_mgr.install_units(
            script_path=script_path, python_executable=python_executable
        )
        if success:
            log.info("API: Systemd units installed successfully.")
            return True
        else:
            raise exc.SystemdError(
                "SystemdManager install_units returned False or failed."
            )
    except (
        exc.SystemdError,
        FileNotFoundError,
        exc.DependencyError,
    ) as e:  # Add DepError
        log.error(f"API: Systemd unit installation failed: {e}")
        raise
    except Exception as e:
        log.exception(f"API: Unexpected error during installation: {e}")
        raise exc.FluxFceError(f"Unexpected error during installation: {e}") from e


def uninstall_fluxfce() -> bool:
    """
    Handles the uninstallation process: removes systemd units and clears schedule.
    (Note: Removing config dir is handled by CLI/GUI layer after confirmation).

    Returns:
        True if systemd removal and schedule clearing succeeded without critical errors.

    Raises:
        exc.FluxFceError: If a critical part of the uninstall fails.
    """
    log.info("API: Starting fluxfce uninstallation (systemd units, schedule).")
    schedule_clear_ok = True  # Assume success unless error occurs
    systemd_remove_ok = True  # Assume success unless error occurs
    critical_error = None

    # 1. Clear schedule
    try:
        scheduler = sched.AtdScheduler()
        if not scheduler.clear_scheduled_transitions():
            # Log warning, maybe not critical? Depends on definition. Let's log warning.
            log.warning(
                "API: clear_scheduled_transitions reported failure (some jobs might remain)."
            )
            # schedule_clear_ok = False # Don't mark as overall failure for this
    except (exc.SchedulerError, exc.DependencyError) as e:
        log.error(f"API: Failed to clear schedule during uninstall: {e}")
        schedule_clear_ok = False
        critical_error = critical_error or e  # Keep first critical error
    except Exception as e:
        log.exception(f"API: Unexpected error clearing schedule during uninstall: {e}")
        schedule_clear_ok = False
        critical_error = critical_error or e

    # 2. Remove systemd units
    try:
        sysd_mgr = sysd.SystemdManager()
        if not sysd_mgr.remove_units():
            log.error("API: Systemd unit removal reported failure.")
            systemd_remove_ok = False
            # Treat systemd removal failure as critical
            critical_error = critical_error or exc.SystemdError(
                "Systemd unit removal failed."
            )
    except (exc.SystemdError, exc.DependencyError) as e:
        log.error(f"API: Failed to remove systemd units during uninstall: {e}")
        systemd_remove_ok = False
        critical_error = critical_error or e
    except Exception as e:
        log.exception(
            f"API: Unexpected error removing systemd units during uninstall: {e}"
        )
        systemd_remove_ok = False
        critical_error = critical_error or e

    overall_success = schedule_clear_ok and systemd_remove_ok
    log.info(
        f"API: Uninstallation process completed. Overall success: {overall_success}"
    )
    if critical_error:
        # Raise the first critical error encountered
        raise exc.FluxFceError(
            f"Uninstallation failed: {critical_error}"
        ) from critical_error
    return True  # Return true if no critical errors occurred


def enable_scheduling(python_exe_path: str, script_exe_path: str) -> bool:
    """
    Enables automatic theme transitions by scheduling 'at' jobs.

    Args:
        python_exe_path: Absolute path to the Python interpreter.
        script_exe_path: Absolute path to the fluxfce script.

    Returns:
        True if scheduling was successful (at least one job scheduled).

    Raises:
        exc.ConfigError, exc.ValidationError, exc.CalculationError,
        exc.SchedulerError, FileNotFoundError, exc.DependencyError, exc.FluxFceError
    """
    log.info("API: Enabling automatic scheduling...")
    config = _load_config_with_defaults()  # Use internal helper
    try:
        lat_str = config.get("Location", "LATITUDE")
        lon_str = config.get("Location", "LONGITUDE")
        tz_name = config.get("Location", "TIMEZONE")

        lat = helpers.latlon_str_to_float(lat_str)  # Raises ValidationError
        lon = helpers.latlon_str_to_float(lon_str)  # Raises ValidationError

        if not tz_name:
            raise exc.ValidationError("Timezone is not configured.")
        # Validate timezone using zoneinfo before passing to scheduler
        try:
            ZoneInfo(tz_name)
        except Exception as tz_err:
            raise exc.ValidationError(
                f"Invalid timezone '{tz_name}': {tz_err}"
            ) from tz_err

        scheduler = sched.AtdScheduler()  # Raises SchedulerError/DepError on init fail
        success = scheduler.schedule_transitions(
            lat, lon, tz_name, python_exe_path, script_exe_path
        )
        log.info(f"API: Scheduling completed. Success: {success}")
        return success

    except (configparser.NoSectionError, configparser.NoOptionError) as e:
        raise exc.ConfigError(f"Location settings missing in configuration: {e}") from e
    except (
        exc.ValidationError,
        exc.CalculationError,
        exc.SchedulerError,
        FileNotFoundError,
        exc.DependencyError,
    ) as e:
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
        exc.SchedulerError, exc.DependencyError, exc.FluxFceError
    """
    log.info("API: Disabling automatic scheduling...")
    try:
        scheduler = sched.AtdScheduler()  # Raises SchedulerError/DepError on init fail
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
        True if theme setting succeeded (background/screen failures are warnings).

    Raises:
        exc.ValidationError: If mode is invalid.
        exc.FluxFceError: If theme setting fails critically.
        exc.SchedulerError: If disabling the schedule fails critically (less likely).
    """
    log.info(f"API: Manually applying mode '{mode}' and disabling schedule...")
    apply_ok = False
    try:
        # 1. Apply settings for the mode
        apply_ok = _apply_settings_for_mode(
            mode
        )  # Raises FluxFceError on critical theme fail
    except exc.FluxFceError as e:
        log.error(f"API: Failed critical apply step for mode '{mode}': {e}")
        raise  # Re-raise critical failure

    # 2. Disable scheduling (clear jobs) - attempt even if non-critical apply failed
    try:
        disable_ok = disable_scheduling()
        if not disable_ok:
            log.warning(
                "API: Applied settings, but failed to disable schedule (clear jobs)."
            )
            # Don't raise, just warn. The main action (apply) might have succeeded.
    except exc.SchedulerError as e:
        log.warning(f"API: Applied settings, but failed to disable schedule: {e}")
    except Exception as e:
        log.exception(
            f"API: Applied settings, but unexpected error disabling schedule: {e}"
        )

    return apply_ok  # Return success of the apply step (primarily theme success)


def set_default_from_current(mode: str) -> bool:
    """
    Saves the current desktop settings (theme, background, screen) as the
    new default configuration for the specified mode ('day' or 'night').

    Args:
        mode: 'day' or 'night'.

    Returns:
        True if settings were read and config was saved (or no changes needed).

    Raises:
        exc.ValidationError, exc.XfceError, exc.ConfigError, exc.FluxFceError
    """
    if mode not in ["day", "night"]:
        raise exc.ValidationError(f"Invalid mode for set-default: {mode}")

    log.info(f"API: Saving current desktop settings as default for mode '{mode}'...")

    try:
        # 1. Get Current Settings
        current_theme = _xfce_handler.get_gtk_theme()  # Raises XfceError if fail
        current_bg = None
        try:
            # Handle background get failure gracefully - don't fail whole operation
            current_bg = _xfce_handler.get_background_settings()
        except exc.XfceError as bg_e:
            log.warning(
                f"API: Could not get current background settings: {bg_e}. Skipping background save."
            )

        current_screen = _xfce_handler.get_screen_settings()  # Doesn't usually raise

        # 2. Load Config
        config = _load_config_with_defaults()  # Use internal helper
        config_changed = False

        # 3. Update Theme Setting
        theme_key = "LIGHT_THEME" if mode == "day" else "DARK_THEME"
        if config.get("Themes", theme_key, fallback=None) != current_theme:
            _cfg_mgr.set_setting(config, "Themes", theme_key, current_theme)
            log.debug(f"API: Updating [{mode} Theme] to '{current_theme}'")
            config_changed = True

        # 4. Update Background Settings
        bg_section = "BackgroundDay" if mode == "day" else "BackgroundNight"
        if current_bg:  # Only update if successfully retrieved
            for key, config_key in [
                ("dir", "BG_DIR"),
                ("hex1", "BG_HEX1"),
                ("hex2", "BG_HEX2"),
            ]:
                new_value = current_bg.get(key)
                current_value = config.get(bg_section, config_key, fallback=None)
                new_value_str = str(new_value) if new_value is not None else ""
                current_value_str = (
                    str(current_value) if current_value is not None else ""
                )
                if new_value_str != current_value_str:
                    _cfg_mgr.set_setting(config, bg_section, config_key, new_value_str)
                    log.debug(
                        f"API: Updating [{bg_section} {config_key}] to '{new_value_str}'"
                    )
                    config_changed = True
        # No else needed, warning logged above if current_bg is None

        # 5. Update Screen Settings
        screen_section = "ScreenDay" if mode == "day" else "ScreenNight"
        temp_to_save: Optional[str] = None
        bright_to_save: Optional[str] = None

        if current_screen:
            cur_temp = current_screen.get("temperature")
            cur_bright = current_screen.get("brightness")
            if cur_temp is None and cur_bright is None:
                temp_to_save = ""
                bright_to_save = ""
                log.debug(
                    "API: Current screen state is off/default; saving reset values ('')"
                )
            elif cur_temp is not None and cur_bright is not None:
                temp_to_save = str(cur_temp)
                bright_to_save = f"{cur_bright:.2f}"
                log.debug(
                    f"API: Current screen state: Temp={temp_to_save}, Bright={bright_to_save}"
                )
            else:
                log.warning(
                    "API: Inconsistent screen settings read; not updating defaults."
                )

        if temp_to_save is not None and bright_to_save is not None:
            if config.get(screen_section, "XSCT_TEMP", fallback=None) != temp_to_save:
                _cfg_mgr.set_setting(config, screen_section, "XSCT_TEMP", temp_to_save)
                log.debug(
                    f"API: Updating [{screen_section} XSCT_TEMP] to '{temp_to_save}'"
                )
                config_changed = True
            if (
                config.get(screen_section, "XSCT_BRIGHT", fallback=None)
                != bright_to_save
            ):
                _cfg_mgr.set_setting(
                    config, screen_section, "XSCT_BRIGHT", bright_to_save
                )
                log.debug(
                    f"API: Updating [{screen_section} XSCT_BRIGHT] to '{bright_to_save}'"
                )
                config_changed = True

        # 6. Save Config if Changed
        if config_changed:
            if save_configuration(config):  # Use the public API save function
                log.info(f"API: Successfully saved updated defaults for mode '{mode}'.")
                return True
            else:
                # save_configuration should raise on failure, this is fallback
                return False
        else:
            log.info(
                f"API: Current settings already match defaults for mode '{mode}'. No changes made."
            )
            return True  # Success even if no changes

    except (exc.ValidationError, exc.XfceError, exc.ConfigError) as e:
        log.error(f"API: Failed to set default from current: {e}")
        raise
    except Exception as e:
        log.exception(f"API: Unexpected error setting default from current: {e}")
        raise exc.FluxFceError(
            f"Unexpected error setting default from current: {e}"
        ) from e


def get_status() -> dict[str, Any]:
    """
    Retrieves the current status of fluxfce.

    Returns:
        A dictionary containing status information. (Structure documented previously)

    Raises:
        FluxFceError for unexpected issues, but tries to return partial status
        even if some components fail. Errors within components are noted in the dict.
    """
    log.debug("API: Getting status...")
    status: dict[str, Any] = {
        "config": {},
        "state": {
            "last_auto_applied": None
        },  # Keep placeholder if state removal not done
        "sun_times": {"sunrise": None, "sunset": None, "error": None},
        "current_period": "unknown",
        "schedule": {"enabled": False, "jobs": [], "error": None},
        # systemd statuses will be added dynamically below
        "systemd": {"error": None},
    }

    # 1. Get Config (Keep as before)
    try:
        config = get_current_config()  # Use public API call now
        status["config"]["latitude"] = config.get(
            "Location", "LATITUDE", fallback="Not Set"
        )
        status["config"]["longitude"] = config.get(
            "Location", "LONGITUDE", fallback="Not Set"
        )
        status["config"]["timezone"] = config.get(
            "Location", "TIMEZONE", fallback="Not Set"
        )
        status["config"]["light_theme"] = config.get(
            "Themes", "LIGHT_THEME", fallback="Not Set"
        )
        status["config"]["dark_theme"] = config.get(
            "Themes", "DARK_THEME", fallback="Not Set"
        )
    except exc.FluxFceError as e:
        status["config"]["error"] = str(e)

    # 2. Calculate Sun Times & Current Period (Keep as before)
    lat_str = status["config"].get("latitude")
    lon_str = status["config"].get("longitude")
    tz_name = status["config"].get("timezone")
    lat, lon = None, None
    if (
        "error" not in status["config"]
        and lat_str
        and lon_str
        and tz_name
        and tz_name != "Not Set"
    ):
        try:
            lat = helpers.latlon_str_to_float(lat_str)
            lon = helpers.latlon_str_to_float(lon_str)
            try:
                tz_info = ZoneInfo(tz_name)
            except Exception as tz_err:
                raise exc.ValidationError(
                    f"Invalid timezone '{tz_name}': {tz_err}"
                ) from tz_err
            today = datetime.now(tz_info).date()
            sun_times_today = sun.get_sun_times(lat, lon, today, tz_name)
            status["sun_times"]["sunrise"] = sun_times_today["sunrise"]
            status["sun_times"]["sunset"] = sun_times_today["sunset"]
            now_local = datetime.now(tz_info)
            if sun_times_today["sunrise"] <= now_local < sun_times_today["sunset"]:
                status["current_period"] = "day"
            else:
                status["current_period"] = "night"
        except (exc.ValidationError, exc.CalculationError) as e:
            status["sun_times"]["error"] = str(e)
            status["current_period"] = "error"
        except Exception as e:
            log.exception("API: Unexpected error calculating sun times for status.")
            status["sun_times"]["error"] = f"Unexpected: {e}"
            status["current_period"] = "error"
    elif "error" not in status["config"]:
        status["sun_times"]["error"] = "Location/Timezone not configured or invalid."
        status["current_period"] = "unknown"

    # 3. Get Schedule Status (Keep as before)
    try:
        scheduler = sched.AtdScheduler()
        status["schedule"]["jobs"] = scheduler.list_scheduled_transitions()
        status["schedule"]["enabled"] = bool(status["schedule"]["jobs"])
    except (exc.SchedulerError, exc.DependencyError) as e:
        status["schedule"]["error"] = str(e)
        status["schedule"]["enabled"] = False
    except Exception as e:
        log.exception("API: Unexpected error getting schedule status.")
        status["schedule"]["error"] = f"Unexpected: {e}"
        status["schedule"]["enabled"] = False

    # 4. Get Systemd Status (FINAL CORRECTED KEY GENERATION)
    try:
        sysd_mgr = sysd.SystemdManager()
        for unit_name in sysd.MANAGED_UNITS:
            # --- FINAL CORRECTED KEY GENERATION ---
            unit_key = None  # Reset key for each iteration
            if unit_name == sysd.SCHEDULER_TIMER_NAME:
                unit_key = "scheduler_timer"
            elif unit_name == sysd.SCHEDULER_SERVICE_NAME:
                unit_key = "scheduler_service"
            elif unit_name == sysd.LOGIN_SERVICE_NAME:
                unit_key = "login_service"
            elif unit_name == sysd.RESUME_SERVICE_NAME:  # <-- ADDED THIS CASE
                unit_key = "resume_service"
            # --- END CORRECTION ---

            if unit_key is None:  # Safety check / handle unrecognized units
                log.warning(
                    f"API: Unrecognized or skipped managed unit name '{unit_name}' during status check."
                )
                continue

            status["systemd"][unit_key] = "Error checking"  # Default
            enabled_status_str = "Unknown"
            active_status_str = "Unknown"

            try:
                code_enabled, _, err_enabled = sysd_mgr._run_systemctl(
                    ["is-enabled", unit_name], check_errors=False
                )
                if code_enabled == 0:
                    enabled_status_str = "Enabled"
                elif code_enabled == 1:
                    enabled_status_str = "Disabled"
                else:
                    enabled_status_str = f"Error ({code_enabled})"

                code_active, _, err_active = sysd_mgr._run_systemctl(
                    ["is-active", unit_name], check_errors=False
                )
                if code_active == 0:
                    active_status_str = "Active"
                    if unit_name.endswith(".timer"):
                        active_status_str += " (waiting)"
                elif code_active == 3:
                    active_status_str = "Inactive"
                else:
                    active_status_str = f"Failed/Error ({code_active})"

                if "Error" in enabled_status_str or "Failed/Error" in active_status_str:
                    status["systemd"][
                        unit_key
                    ] = f"{enabled_status_str}, {active_status_str}"
                elif "Unknown" in enabled_status_str or "Unknown" in active_status_str:
                    status["systemd"][unit_key] = "Unknown State"
                else:
                    status["systemd"][
                        unit_key
                    ] = f"{enabled_status_str}, {active_status_str}"

                log.debug(
                    f"API: Status for systemd unit {unit_name} (key: {unit_key}): {status['systemd'][unit_key]}"
                )

            except exc.SystemdError as unit_e:
                log.error(
                    f"API: Could not get full status for systemd unit {unit_name}: {unit_e}"
                )
                status["systemd"][unit_key] = "Error processing"
            except Exception as unit_e:
                log.exception(
                    f"API: Unexpected error getting status for unit {unit_name}: {unit_e}"
                )
                status["systemd"][unit_key] = "Unexpected error"

    except (exc.SystemdError, exc.DependencyError) as e:
        status["systemd"]["error"] = f"Systemd check failed: {e}"
    except Exception as e:
        log.exception("API: Unexpected error getting systemd status.")
        status["systemd"]["error"] = f"Unexpected error: {e}"

    return status


# --- Internal Command Handlers (Called by Executable Script) ---


def handle_internal_apply(mode: str) -> bool:
    """
    Called internally by the scheduled 'at' job or login service.
    Applies settings for the given mode. Returns True on success.
    """
    log.info(f"API: Internal apply called for mode '{mode}'")
    try:
        # Use the helper which now returns bool indicating if theme succeeded
        return _apply_settings_for_mode(mode)
    except exc.FluxFceError as e:
        log.error(f"API: Error during internal apply for mode '{mode}': {e}")
        return False
    except Exception as e:
        log.exception(
            f"API: Unexpected error during internal apply for mode '{mode}': {e}"
        )
        return False


def handle_schedule_jobs_command(python_exe_path: str, script_exe_path: str) -> bool:
    """
    Called internally by the systemd scheduler service timer.
    Calculates and schedules the next 'at' jobs. Returns True on success.
    """
    log.info("API: Handling schedule-jobs command...")
    at_jobs_scheduled_ok = False
    try:
        at_jobs_scheduled_ok = enable_scheduling(python_exe_path, script_exe_path)
    except exc.FluxFceError as e:
        log.error(f"API: Error during at-job scheduling part of schedule-jobs command: {e}")
        at_jobs_scheduled_ok = False # Explicitly set to false
    except Exception as e: # Catch any other unexpected error
        log.exception(f"API: Unexpected error during at-job scheduling: {e}")
        at_jobs_scheduled_ok = False

    log.info("API: Proceeding to schedule dynamic systemd transition timers...")
    dynamic_transitions_ok = False
    try:
        config = get_current_config() # Load config
        systemd_mgr_for_dynamic = sysd.SystemdManager()

        lat_str = config.get("Location", "LATITUDE")
        lon_str = config.get("Location", "LONGITUDE")
        tz_name = config.get("Location", "TIMEZONE")

        if not all([lat_str, lon_str, tz_name]):
            raise exc.ConfigError("Location latitude, longitude, or timezone not configured for dynamic timers.")

        lat = helpers.latlon_str_to_float(lat_str)
        lon = helpers.latlon_str_to_float(lon_str)

        try:
            tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            raise exc.ValidationError(f"Invalid timezone in configuration for dynamic timers: {tz_name}")

        today_date = datetime.now(tz).date()
        # Use sun.get_sun_times as get_sun_times is not directly imported with that name
        calculated_sun_times = sun.get_sun_times(lat, lon, today_date, tz_name)

        dynamic_transitions_ok = schedule_dynamic_transitions(config, systemd_mgr_for_dynamic, calculated_sun_times)
        if dynamic_transitions_ok:
            log.info("API: Dynamic systemd transition timers scheduled successfully.")
        else:
            log.warning("API: Scheduling dynamic systemd transition timers reported issues or no timers scheduled.")

    except (exc.ConfigError, exc.ValidationError, exc.CalculationError, exc.SystemdError) as e:
        log.error(f"API: Error during the process of scheduling dynamic transition timers: {e}")
        dynamic_transitions_ok = False
    except Exception as e:
        log.exception(f"API: Unexpected error scheduling dynamic transition timers: {e}")
        dynamic_transitions_ok = False

    return at_jobs_scheduled_ok and dynamic_transitions_ok


def handle_run_login_check() -> bool:
    """
    Called internally by the systemd login service.
    Determines the current period (day/night) and applies the appropriate theme.
    Returns True on success.
    """
    log.info("API: Handling run-login-check command...")
    try:
        config = _load_config_with_defaults()  # Use internal helper
        lat_str = config.get("Location", "LATITUDE")
        lon_str = config.get("Location", "LONGITUDE")
        tz_name = config.get("Location", "TIMEZONE")

        mode_to_apply = "night"  # Default assumption

        if lat_str and lon_str and tz_name:
            try:
                lat = helpers.latlon_str_to_float(lat_str)
                lon = helpers.latlon_str_to_float(lon_str)
                tz_info = ZoneInfo(tz_name)
                now_local = datetime.now(tz_info)
                today = now_local.date()
                sun_times = sun.get_sun_times(lat, lon, today, tz_name)
                if sun_times["sunrise"] <= now_local < sun_times["sunset"]:
                    mode_to_apply = "day"
                log.info(f"API: Login check determined current mode: '{mode_to_apply}'")
            except (
                exc.ValidationError,
                exc.CalculationError,
                ZoneInfoNotFoundError,
            ) as e:
                log.warning(
                    f"API: Could not determine correct mode for login check ({e}). Defaulting to '{mode_to_apply}'."
                )
            except Exception:
                log.exception(
                    f"API: Unexpected error determining mode for login check. Defaulting to '{mode_to_apply}'."
                )
        else:
            log.warning(
                "API: Location/Timezone not configured for login check. Defaulting to 'night'."
            )

        log.info(f"API: Applying mode '{mode_to_apply}' for login check.")
        # Use the helper which now returns bool indicating if theme succeeded
        return _apply_settings_for_mode(mode_to_apply)

    except exc.FluxFceError as e:
        # Includes ConfigError from loading
        log.error(f"API: Error during run-login-check: {e}")
        return False
    except Exception as e:
        log.exception(f"API: Unexpected error during run-login-check: {e}")
        return False
