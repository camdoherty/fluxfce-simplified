# ~/dev/fluxfce-simplified/fluxfce_core/api.py

import configparser
import logging
import re # For get_status timer parsing
from datetime import datetime, timedelta
from typing import Any, Optional

# Import core components and exceptions
from . import config as cfg
from . import exceptions as exc
from . import helpers, sun, xfce
# No longer importing scheduler: from . import scheduler as sched
from . import systemd as sysd # Use alias for clarity

# zoneinfo needed here for status/period calculation and sun time calculations
try:
    from zoneinfo import (
        ZoneInfo,
        ZoneInfoNotFoundError,
    )
except ImportError:
    # This should be caught by Python version checks or at a higher level.
    # If fluxfce_core is imported, this implies Python 3.9+
    raise ImportError(
        "Required module 'zoneinfo' not found. FluxFCE requires Python 3.9+."
    )


log = logging.getLogger(__name__)

# --- Internal Helper ---

# Instantiate managers that are reused across API calls
_cfg_mgr = cfg.ConfigManager()
_xfce_handler = xfce.XfceHandler()
_sysd_mgr = sysd.SystemdManager() # Module-level instance for SystemdManager

def _load_config_with_defaults() -> configparser.ConfigParser:
    """Internal helper to load configuration, applying defaults in memory."""
    try:
        return _cfg_mgr.load_config()
    except exc.ConfigError as e:
        log.error(f"API Helper: Failed to load configuration: {e}")
        raise # Re-raise the specific ConfigError
    except Exception as e:
        log.exception(f"API Helper: Unexpected error loading configuration: {e}")
        raise exc.FluxFceError(f"Unexpected error loading configuration: {e}") from e

def _apply_settings_for_mode(mode: str) -> bool:
    """Internal helper to apply all settings for 'day' or 'night'."""
    if mode not in ["day", "night"]:
        raise exc.ValidationError(f"Invalid mode specified for apply: {mode}")

    config_obj = _load_config_with_defaults()
    theme_key = "LIGHT_THEME" if mode == "day" else "DARK_THEME"
    bg_section = "BackgroundDay" if mode == "day" else "BackgroundNight"
    screen_section = "ScreenDay" if mode == "day" else "ScreenNight"

    theme = config_obj.get("Themes", theme_key, fallback=None)
    bg_hex1 = config_obj.get(bg_section, "BG_HEX1", fallback=None)
    bg_hex2 = config_obj.get(bg_section, "BG_HEX2", fallback=None)
    bg_dir = config_obj.get(bg_section, "BG_DIR", fallback=None)
    temp_str = config_obj.get(screen_section, "XSCT_TEMP", fallback=None)
    bright_str = config_obj.get(screen_section, "XSCT_BRIGHT", fallback=None)

    if not theme:
        # This is a critical configuration item.
        raise exc.ConfigError(f"Theme '{theme_key}' not configured in [Themes]. Cannot apply mode '{mode}'.")

    xsct_temp: Optional[int] = None
    xsct_bright: Optional[float] = None
    try:
        if mode == "day" and (temp_str == "" or bright_str == ""): # Explicit reset for day mode
            log.info("Day mode: Screen temperature/brightness will be reset by xsct.")
        elif (
            temp_str is not None and temp_str.strip() != "" and
            bright_str is not None and bright_str.strip() != ""
        ):
            xsct_temp = int(temp_str)
            xsct_bright = float(bright_str)
        # If only one is set, or they are set but empty for night mode, xsct might not be called with values.
        # The XfceHandler.set_screen_temp handles None values by resetting.
    except (ValueError, TypeError) as e:
        log.warning(
            f"Could not parse screen settings (Temp: '{temp_str}', Bright: '{bright_str}') "
            f"from [{screen_section}]: {e}. Screen settings will be skipped or reset."
        )

    all_ok = True # Track overall success

    try:
        log.info(f"API: Applying theme '{theme}' for mode '{mode}'")
        _xfce_handler.set_gtk_theme(theme)
    except (exc.XfceError, exc.ValidationError) as e:
        # For _apply_settings_for_mode, a theme failure is critical because it's a primary component.
        log.error(f"API: CRITICAL - Failed to set theme '{theme}': {e}")
        raise exc.FluxFceError(f"Critical failure setting theme '{theme}' for mode '{mode}': {e}") from e

    if bg_hex1 and bg_dir: # Background is optional if not configured
        try:
            log.info(
                f"API: Applying background (Dir={bg_dir}, Hex1={bg_hex1}, Hex2={bg_hex2 or 'N/A'}) for mode '{mode}'"
            )
            _xfce_handler.set_background(bg_hex1, bg_hex2, bg_dir)
        except (exc.XfceError, exc.ValidationError) as e:
            log.error(f"API: Failed to set background for mode '{mode}': {e}")
            all_ok = False # Non-critical, log and continue
    else:
        log.info(f"API: Background not fully configured in [{bg_section}], skipping background set for mode '{mode}'.")

    try:
        log.info(
            f"API: Applying screen settings (Temp={xsct_temp or 'reset'}, Bright={xsct_bright or 'reset'}) for mode '{mode}'"
        )
        _xfce_handler.set_screen_temp(xsct_temp, xsct_bright) # Handles None by resetting
    except (exc.XfceError, exc.ValidationError) as e:
        log.error(f"API: Failed to set screen settings for mode '{mode}': {e}")
        all_ok = False # Non-critical, log and continue
    
    if not all_ok:
        log.warning(f"API: Mode '{mode}' applied, but one or more non-critical appearance settings (background/screen) failed.")
    
    return all_ok # Returns true if theme set, even if bg/screen had warnings


# --- Public API Functions for Config ---
def get_current_config() -> configparser.ConfigParser:
    """Loads the current configuration, applying defaults in memory."""
    log.debug("API: get_current_config called")
    return _load_config_with_defaults()

def save_configuration(config_obj: configparser.ConfigParser) -> bool:
    """Saves the given ConfigParser object to file."""
    log.debug("API: save_configuration called")
    try:
        return _cfg_mgr.save_config(config_obj)
    except exc.ConfigError as e:
        log.error(f"API: Failed to save configuration: {e}")
        raise
    except Exception as e:
        log.exception(f"API: Unexpected error saving configuration: {e}")
        raise exc.FluxFceError(f"Unexpected error saving configuration: {e}") from e

# --- Installation and Uninstallation ---
def install_fluxfce(script_path: str, python_executable: Optional[str] = None) -> bool:
    """
    Handles the installation process: installs static systemd units.
    Configuration is handled separately by the CLI.
    The main scheduler timer is enabled by `enable_scheduling`.
    """
    log.info(f"API: Starting {sysd._APP_NAME} installation (static systemd units).")
    try:
        success = _sysd_mgr.install_units(
            script_path=script_path, python_executable=python_executable
        )
        if success:
            log.info("API: Static systemd units installed successfully.")
            return True
        else:
            raise exc.SystemdError(f"{sysd._APP_NAME} SystemdManager install_units returned False or failed critically.")
    except (exc.SystemdError, FileNotFoundError, exc.DependencyError) as e:
        log.error(f"API: Static systemd unit installation failed: {e}")
        raise
    except Exception as e:
        log.exception(f"API: Unexpected error during {sysd._APP_NAME} installation: {e}")
        raise exc.FluxFceError(f"Unexpected error during {sysd._APP_NAME} installation: {e}") from e

def uninstall_fluxfce() -> bool:
    """
    Handles the uninstallation: removes all systemd units (static and dynamic).
    Config dir removal is handled by CLI.
    """
    log.info(f"API: Starting {sysd._APP_NAME} uninstallation (all systemd units).")
    try:
        disable_scheduling_ok = True
        try:
            # This will stop main scheduler, stop dynamic event timers, and remove their files.
            disable_scheduling() 
        except Exception as e_disable:
            log.warning(f"API: Error during disable_scheduling in uninstall process (continuing): {e_disable}")
            disable_scheduling_ok = False

        # remove_units removes static unit files.
        removal_ok = _sysd_mgr.remove_units() 
        
        if removal_ok:
            log.info(f"API: {sysd._APP_NAME} systemd units removed successfully.")
            if not disable_scheduling_ok:
                 log.warning("API: Uninstallation completed, but disabling/cleanup of dynamic timers encountered issues.")
            return True
        else:
            raise exc.SystemdError(f"{sysd._APP_NAME} SystemdManager remove_units returned False or failed critically.")
    except (exc.SystemdError, exc.DependencyError) as e: # remove_units can raise DependencyError if systemctl is missing
        log.error(f"API: Failed to remove {sysd._APP_NAME} systemd units during uninstall: {e}")
        raise
    except Exception as e:
        log.exception(f"API: Unexpected error during {sysd._APP_NAME} uninstallation: {e}")
        raise exc.FluxFceError(f"Unexpected error during {sysd._APP_NAME} uninstallation: {e}") from e


# --- Scheduling API Functions ---

def handle_schedule_dynamic_transitions_command(python_exe_path: str, script_exe_path: str) -> bool:
    """
    Calculates next sun events, writes dynamic systemd timer files, reloads the
    systemd daemon, and starts the dynamic timers.
    Called by the fluxfce-scheduler.service.
    """
    log.info("API: Handling 'schedule-dynamic-transitions' command...")
    try:
        current_config = get_current_config()
        lat_str = current_config.get("Location", "LATITUDE")
        lon_str = current_config.get("Location", "LONGITUDE")
        tz_name = current_config.get("Location", "TIMEZONE")

        if not all([lat_str, lon_str, tz_name, 
                    lat_str != "Not Set", lon_str != "Not Set", tz_name != "Not Set"]):
            raise exc.ConfigError("Location (latitude, longitude, timezone) not fully configured for scheduling.")

        lat = helpers.latlon_str_to_float(lat_str)
        lon = helpers.latlon_str_to_float(lon_str)
        
        try:
            local_tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            raise exc.ConfigError(f"Invalid timezone in configuration: {tz_name}")

        now_local = datetime.now(local_tz)
        today_local = now_local.date()
        next_event_times: dict[str, Optional[datetime]] = {"day": None, "night": None}

        for day_offset in range(2): # Check today and tomorrow
            target_date = today_local + timedelta(days=day_offset)
            try:
                sun_times = sun.get_sun_times(lat, lon, target_date, tz_name)
                if not next_event_times["day"] and sun_times["sunrise"] > now_local:
                    next_event_times["day"] = sun_times["sunrise"]
                if not next_event_times["night"] and sun_times["sunset"] > now_local:
                    next_event_times["night"] = sun_times["sunset"]
            except exc.CalculationError as e:
                log.warning(f"Could not calculate sun times for {target_date}: {e}")
            if next_event_times["day"] and next_event_times["night"]:
                break
        
        _sysd_mgr._run_systemctl(
            ["stop", sysd.SUNRISE_EVENT_TIMER_NAME, sysd.SUNSET_EVENT_TIMER_NAME],
            check_errors=False, capture_output=True
        )

        scheduled_any_timer = False
        utc_tz = ZoneInfo("UTC")

        if next_event_times["day"]:
            utc_event_time = next_event_times["day"].astimezone(utc_tz)
            _sysd_mgr.write_dynamic_event_timer_unit_file("day", utc_event_time)
            scheduled_any_timer = True
            log.info(f"Dynamic timer for SUNRISE prepared for: {utc_event_time.isoformat()}")
        else:
            log.warning("No upcoming sunrise event found. Removing existing timer if any.")
            (sysd.SYSTEMD_USER_DIR / sysd.SUNRISE_EVENT_TIMER_NAME).unlink(missing_ok=True)

        if next_event_times["night"]:
            utc_event_time = next_event_times["night"].astimezone(utc_tz)
            _sysd_mgr.write_dynamic_event_timer_unit_file("night", utc_event_time)
            scheduled_any_timer = True
            log.info(f"Dynamic timer for SUNSET prepared for: {utc_event_time.isoformat()}")
        else:
            log.warning("No upcoming sunset event found. Removing existing timer if any.")
            (sysd.SYSTEMD_USER_DIR / sysd.SUNSET_EVENT_TIMER_NAME).unlink(missing_ok=True)

        _sysd_mgr._run_systemctl(["daemon-reload"], capture_output=True)

        if next_event_times["day"]:
            _sysd_mgr._run_systemctl(["start", sysd.SUNRISE_EVENT_TIMER_NAME], check_errors=False, capture_output=True)
        if next_event_times["night"]:
            _sysd_mgr._run_systemctl(["start", sysd.SUNSET_EVENT_TIMER_NAME], check_errors=False, capture_output=True)
        
        if not scheduled_any_timer:
            log.warning("No sun event timers could be scheduled (e.g. polar day/night).")
        else:
            log.info("Dynamic event timers (re)written, daemon reloaded, and timers (re)started.")
        return True # Command itself succeeded even if no timers were scheduled

    except (exc.ConfigError, exc.ValidationError, exc.SystemdError, exc.FluxFceError) as e:
        log.error(f"API: Failed to schedule dynamic transitions: {e}")
        return False
    except Exception as e:
        log.exception(f"API: Unexpected error during 'schedule-dynamic-transitions': {e}")
        return False

def enable_scheduling(python_exe_path: str, script_exe_path: str) -> bool:
    """
    Enables automatic theme transitions:
    1. Defines dynamic event timers for the next sunrise/sunset.
    2. Enables and starts the main daily scheduler timer (`fluxfce-scheduler.timer`).
    3. Applies the theme appropriate for the current actual solar period.
    """
    log.info("API: Enabling scheduling...")
    try:
        # Step 1: Define dynamic event timers for future events.
        # This writes timer files, reloads daemon, and starts the dynamic timers.
        # If a dynamic timer's scheduled time (e.g. sunrise) has passed for today but was "missed",
        # systemd's Persistent=true might trigger it now. This is now handled by ensuring the
        # apply-transition service is stable.
        define_schedule_ok = handle_schedule_dynamic_transitions_command(
            python_exe_path=python_exe_path, script_exe_path=script_exe_path
        )
        if not define_schedule_ok:
            # Log as warning because the main scheduler will still be enabled to try again.
            log.warning("API: Initial definition of dynamic event timers failed or scheduled nothing, "
                        "but proceeding to enable the main daily scheduler.")

        # Step 2: Enable and start (--now) the main daily scheduler timer.
        # Its service (`fluxfce-scheduler.service`) will run `handle_schedule_dynamic_transitions_command`
        # again immediately, re-evaluating and ensuring the dynamic timers are correctly set.
        code, _, stderr = _sysd_mgr._run_systemctl(
            ["enable", "--now", sysd.SCHEDULER_TIMER_NAME], capture_output=True
        )
        if code != 0:
            raise exc.SystemdError(
                f"Failed to enable and start main scheduler timer ({sysd.SCHEDULER_TIMER_NAME}): {stderr.strip()}"
            )
        log.info(f"API: Main scheduler ({sysd.SCHEDULER_TIMER_NAME}) enabled; its service runs once now to set schedule.")

        # Step 3: Explicitly apply the theme for the current actual period.
        # This ensures that after enabling, the desktop reflects the correct current state.
        # `handle_run_login_check` determines current period and applies all settings.
        log.info("API: Applying theme for the current actual solar period...")
        apply_current_ok = handle_run_login_check()
        if apply_current_ok:
            log.info("API: Theme for current solar period applied successfully after enabling schedule.")
        else:
            log.warning("API: Failed to apply theme for the current solar period after enabling schedule. "
                        "Scheduled timers should still correct it later if the issue is transient.")
        
        log.info("API: Scheduling enabled successfully.")
        return True
        
    except (exc.SystemdError, exc.FluxFceError) as e: # Catch known, specific errors
        log.error(f"API: Failed to enable scheduling: {e}")
        raise 
    except Exception as e: # Catch unexpected errors
        log.exception(f"API: Unexpected error enabling scheduling: {e}")
        raise exc.FluxFceError(f"An unexpected error occurred while enabling scheduling: {e}") from e

def disable_scheduling() -> bool:
    """
    Disables automatic theme transitions:
    1. Stops and disables the main scheduler timer.
    2. Stops and removes the dynamic event timer files.
    3. Reloads the systemd daemon and resets failed states.
    """
    log.info("API: Disabling scheduling and removing dynamic systemd timers...")
    try:
        _sysd_mgr._run_systemctl(["stop", sysd.SCHEDULER_TIMER_NAME], check_errors=False, capture_output=True)
        _sysd_mgr._run_systemctl(["disable", sysd.SCHEDULER_TIMER_NAME], check_errors=False, capture_output=True)
        log.debug(f"API: Main scheduler timer ({sysd.SCHEDULER_TIMER_NAME}) stopped and disabled.")

        _sysd_mgr._run_systemctl(["stop", sysd.SUNRISE_EVENT_TIMER_NAME], check_errors=False, capture_output=True)
        _sysd_mgr._run_systemctl(["stop", sysd.SUNSET_EVENT_TIMER_NAME], check_errors=False, capture_output=True)
        log.debug("API: Dynamic event timers stopped.")

        for timer_name in [sysd.SUNRISE_EVENT_TIMER_NAME, sysd.SUNSET_EVENT_TIMER_NAME]:
            timer_path = sysd.SYSTEMD_USER_DIR / timer_name
            try:
                timer_path.unlink(missing_ok=True)
                log.debug(f"API: Removed {timer_name} (if existed).")
            except OSError as e:
                log.warning(f"API: Could not remove {timer_name}: {e}")

        _sysd_mgr._run_systemctl(["daemon-reload"], capture_output=True)
        log.debug("API: Systemd daemon reloaded.")
        
        units_to_reset = [
            sysd.SCHEDULER_TIMER_NAME, 
            sysd.SUNRISE_EVENT_TIMER_NAME, 
            sysd.SUNSET_EVENT_TIMER_NAME,
            sysd.SCHEDULER_SERVICE_NAME # Also reset the service it activates
        ]
        _sysd_mgr._run_systemctl(["reset-failed", *units_to_reset], check_errors=False, capture_output=True)

        log.info("API: Scheduling disabled successfully.")
        return True

    except (exc.SystemdError, exc.FluxFceError) as e:
        log.error(f"API: Failed to disable scheduling: {e}")
        raise
    except Exception as e:
        log.exception(f"API: Unexpected error disabling scheduling: {e}")
        raise exc.FluxFceError(f"An unexpected error occurred while disabling scheduling: {e}") from e

# --- Manual Mode and Defaults ---
def apply_manual_mode(mode: str) -> bool:
    """Manually applies Day or Night mode settings and disables scheduling."""
    log.info(f"API: Manually applying mode '{mode}' and disabling schedule...")
    apply_ok = False
    try:
        apply_ok = _apply_settings_for_mode(mode) # This applies all components
    except exc.FluxFceError as e:
        # _apply_settings_for_mode now raises on critical theme failure,
        # or returns True if theme OK but other parts failed (with warnings logged).
        # Here, if it raised, it's a critical failure to apply the mode.
        log.error(f"API: Failed critical apply step for mode '{mode}': {e}")
        # We might still want to attempt to disable scheduling.
        # Or re-raise immediately if apply_ok is the primary concern.
        # For now, let's ensure scheduling is disabled even if apply failed.
        # The CLI will report the error from the raise.
        pass # Allow disable_scheduling to run
    except Exception as e_apply: # Catch any other unexpected error from apply
        log.exception(f"API: Unexpected error applying manual mode '{mode}': {e_apply}")
        # Also allow disable_scheduling to run
        pass


    disable_success = False
    try:
        disable_success = disable_scheduling()
        if not disable_success:
            log.warning("API: Manual mode applied (or attempted), but failed to properly disable/cleanup schedule.")
    except exc.FluxFceError as e_disable: 
        log.warning(f"API: Manual mode applied (or attempted), but an error occurred disabling schedule: {e_disable}")
    
    if not apply_ok: # If _apply_settings_for_mode itself returned False or raised an error caught above
        log.error(f"API: Manual mode '{mode}' did not apply successfully (theme or other critical part failed).")
        return False # Indicate overall failure
        
    return True # True if _apply_settings_for_mode was successful

def set_default_from_current(mode: str) -> bool:
    """Saves current desktop settings as the new default for Day or Night mode."""
    if mode not in ["day", "night"]:
        raise exc.ValidationError(f"Invalid mode for set-default: {mode}")
    log.info(f"API: Saving current desktop settings as default for mode '{mode}'...")
    try:
        current_theme = _xfce_handler.get_gtk_theme()
        current_bg = None
        try:
            # get_background_settings now raises XfceError if it can't reliably get gradient
            current_bg = _xfce_handler.get_background_settings()
        except exc.XfceError as bg_e:
            log.warning(f"API: Could not get current background settings: {bg_e}. Skipping background save for set-default.")
            # If we can't get background, we can still save theme and screen.
            # Consider if this should be a partial success or require all parts. For now, continue.

        current_screen = _xfce_handler.get_screen_settings() # Returns {'temp': None, 'bright': None} if off

        config_obj = _load_config_with_defaults()
        config_changed = False

        theme_key = "LIGHT_THEME" if mode == "day" else "DARK_THEME"
        if config_obj.get("Themes", theme_key, fallback=None) != current_theme:
            _cfg_mgr.set_setting(config_obj, "Themes", theme_key, current_theme)
            config_changed = True
            log.info(f"API: Updated default theme for '{mode}' to '{current_theme}'.")

        bg_section = "BackgroundDay" if mode == "day" else "BackgroundNight"
        if current_bg: # Only try to save background if we successfully got current settings
            for key_in_current_bg, config_key_name in [("dir", "BG_DIR"), ("hex1", "BG_HEX1"), ("hex2", "BG_HEX2")]:
                new_value_from_desktop = current_bg.get(key_in_current_bg)
                current_value_in_config = config_obj.get(bg_section, config_key_name, fallback=None)
                
                value_to_save_str = str(new_value_from_desktop) if new_value_from_desktop is not None else ""
                current_value_in_config_str = str(current_value_in_config) if current_value_in_config is not None else ""

                if value_to_save_str != current_value_in_config_str:
                    _cfg_mgr.set_setting(config_obj, bg_section, config_key_name, value_to_save_str)
                    config_changed = True
                    log.info(f"API: Updated default background '{config_key_name}' for '{mode}' to '{value_to_save_str}'.")
        
        screen_section = "ScreenDay" if mode == "day" else "ScreenNight"
        temp_to_save_str: Optional[str] = None
        bright_to_save_str: Optional[str] = None

        if current_screen: # Will always be a dict, possibly with None values
            cur_temp, cur_bright = current_screen.get("temperature"), current_screen.get("brightness")
            if cur_temp is None and cur_bright is None: # xsct is off or reset (temp and bright are None)
                temp_to_save_str, bright_to_save_str = "", "" # Save as empty strings to signify reset
            elif cur_temp is not None and cur_bright is not None:
                temp_to_save_str, bright_to_save_str = str(cur_temp), f"{cur_bright:.2f}"
            else: # Should not happen if get_screen_settings is consistent (both None or both set)
                log.warning(f"API: Inconsistent screen settings read (Temp: {cur_temp}, Bright: {cur_bright}); not updating screen defaults for '{mode}'.")
                temp_to_save_str, bright_to_save_str = None, None # Don't save if inconsistent

        if temp_to_save_str is not None: # Check if we decided to save temp (not None means yes, or empty string)
            if config_obj.get(screen_section, "XSCT_TEMP", fallback=None) != temp_to_save_str:
                _cfg_mgr.set_setting(config_obj, screen_section, "XSCT_TEMP", temp_to_save_str)
                config_changed = True
                log.info(f"API: Updated default screen temp for '{mode}' to '{temp_to_save_str or 'reset'}'.")
        
        if bright_to_save_str is not None: # Check if we decided to save bright
            if config_obj.get(screen_section, "XSCT_BRIGHT", fallback=None) != bright_to_save_str:
                _cfg_mgr.set_setting(config_obj, screen_section, "XSCT_BRIGHT", bright_to_save_str)
                config_changed = True
                log.info(f"API: Updated default screen bright for '{mode}' to '{bright_to_save_str or 'reset'}'.")

        if config_changed:
            save_ok = save_configuration(config_obj)
            if save_ok:
                log.info(f"API: Successfully saved updated defaults for mode '{mode}'.")
            # save_configuration raises on failure, so no explicit else needed for failure
            return save_ok
        else:
            log.info(f"API: Current settings already match defaults for '{mode}'. No changes made to config file.")
            return True # No changes needed, so "successful" in that sense
            
    except (exc.ValidationError, exc.XfceError, exc.ConfigError) as e:
        log.error(f"API: Failed to set default from current for mode '{mode}': {e}")
        raise # Re-raise to be caught by CLI
    except Exception as e:
        log.exception(f"API: Unexpected error setting default from current for '{mode}': {e}")
        raise exc.FluxFceError(f"Unexpected error setting default from current for '{mode}': {e}") from e

# --- Status Function ---
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
    except exc.FluxFceError as e:
        status["config"]["error"] = str(e)

    # 2. Calculate Sun Times & Current Period
    if "error" not in status["config"]:
        lat_str = status["config"]["latitude"]
        lon_str = status["config"]["longitude"]
        tz_name = status["config"]["timezone"]
        if all([lat_str, lon_str, tz_name, 
                lat_str != "Not Set", lon_str != "Not Set", tz_name != "Not Set"]):
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
            except (exc.ValidationError, exc.CalculationError, ZoneInfoNotFoundError) as e:
                status["sun_times"]["error"] = str(e)
                status["current_period"] = "error (calculation/config)"
            except Exception as e: 
                log.exception("API: Unexpected error calculating sun times for status.")
                status["sun_times"]["error"] = f"Unexpected in sun times: {e}"
                status["current_period"] = "error (unexpected)"
        else:
            status["sun_times"]["error"] = "Location/Timezone not fully configured."
            status["current_period"] = "unknown (config incomplete)"
    
    # 3. Get Systemd Timer Schedule Status
    timer_names_to_query = [
        sysd.SCHEDULER_TIMER_NAME,
        sysd.SUNRISE_EVENT_TIMER_NAME,
        sysd.SUNSET_EVENT_TIMER_NAME,
    ]
    try:
        code, stdout_timers, stderr_timers = _sysd_mgr._run_systemctl(
            ["list-timers", "--all", *timer_names_to_query],
            check_errors=False, capture_output=True
        )
        # "No timers found." is also a valid empty output from systemctl
        if code != 0 and not ("0 timers listed." in stdout_timers or "No timers found." in stdout_timers):
            status["schedule"]["error"] = f"Failed to list systemd timers (code {code}): {stderr_timers.strip() or stdout_timers.strip()}"
        
        if stdout_timers:
            parsed_timers = {}
            lines = stdout_timers.strip().split('\n')
            if "NEXT" in lines[0].upper() and len(lines) > 1: # Basic check for header
                header_line = lines[0].upper()
                col_indices = {
                    "NEXT": header_line.find("NEXT"), "LEFT": header_line.find("LEFT"),
                    "LAST": header_line.find("LAST"), "PASSED": header_line.find("PASSED"),
                    "UNIT": header_line.find("UNIT"), "ACTIVATES": header_line.find("ACTIVATES"),
                }
                sorted_cols = sorted([(name, idx) for name, idx in col_indices.items() if idx != -1], key=lambda item: item[1])

                for line_content in lines[1:]:
                    if not line_content.strip() or "timer" not in line_content: continue # Skip empty lines or non-timer lines
                    
                    timer_data_raw = {}
                    current_unit_name = "Unknown"
                    
                    for i, (col_name, start_idx) in enumerate(sorted_cols):
                        end_idx = sorted_cols[i+1][1] if i + 1 < len(sorted_cols) else len(line_content)
                        field_value = line_content[start_idx:end_idx].strip()
                        timer_data_raw[col_name.lower()] = field_value
                        if col_name == "UNIT": current_unit_name = field_value
                    
                    if current_unit_name in timer_names_to_query:
                        is_enabled_code, _, _ = _sysd_mgr._run_systemctl(["is-enabled", current_unit_name], check_errors=False, capture_output=True)
                        is_active_code, _, _ = _sysd_mgr._run_systemctl(["is-active", current_unit_name], check_errors=False, capture_output=True)
                        
                        parsed_timers[current_unit_name] = {
                            "enabled": "Enabled" if is_enabled_code == 0 else "Disabled",
                            "active": "Active" if is_active_code == 0 else "Inactive",
                            "next_run": timer_data_raw.get("next", "N/A"),
                            "time_left": timer_data_raw.get("left", "N/A"),
                            "last_run": timer_data_raw.get("last", "N/A"),
                            "activates": timer_data_raw.get("activates", "N/A")
                        }
            
            status["schedule"]["timers"] = parsed_timers
            if not parsed_timers and not status["schedule"].get("error"): # Use .get to avoid KeyError if error was already set
                status["schedule"]["info"] = "No relevant fluxfce timers found or listed by systemctl."
            elif "0 timers listed." in stdout_timers or "No timers found." in stdout_timers:
                 status["schedule"]["info"] = "No relevant fluxfce timers found or listed by systemctl."


    except Exception as e:
        log.exception("API: Unexpected error getting systemd timer schedule status.")
        status["schedule"]["error"] = f"Unexpected error querying timers: {e}"

    # 4. Get Systemd Service Status
    services_to_check = {
        "scheduler_service": sysd.SCHEDULER_SERVICE_NAME,
        "login_service": sysd.LOGIN_SERVICE_NAME,
        "resume_service": sysd.RESUME_SERVICE_NAME,
    }
    any_service_error = False
    for key, unit_name in services_to_check.items():
        try:
            enabled_code, _, _ = _sysd_mgr._run_systemctl(["is-enabled", unit_name], check_errors=False, capture_output=True)
            active_code, _, _ = _sysd_mgr._run_systemctl(["is-active", unit_name], check_errors=False, capture_output=True)
            status["systemd_services"][key] = f"{'Enabled' if enabled_code == 0 else 'Disabled'}, {'Active' if active_code == 0 else 'Inactive'}"
        except exc.SystemdError as e:
            status["systemd_services"][key] = f"Error checking: {e}"
            any_service_error = True
        except Exception as e:
            log.exception(f"API: Unexpected error getting status for service {unit_name}")
            status["systemd_services"][key] = "Unexpected error checking"
            any_service_error = True
    if any_service_error and not status["systemd_services"].get("error"):
        status["systemd_services"]["error"] = "One or more services could not be checked."
            
    return status

# --- Internal Command Handlers (Called by Executable Script / Systemd) ---
def handle_internal_apply(mode: str) -> bool:
    """Called by systemd (`fluxfce-apply-transition@.service`) to apply mode."""
    log.info(f"API: Internal apply called for mode '{mode}' by systemd.")
    try:
        return _apply_settings_for_mode(mode)
    except exc.FluxFceError as e: # Includes critical theme errors from _apply_settings_for_mode
        log.error(f"API: Error during internal apply for mode '{mode}': {e}")
        return False # Service should fail if critical part fails
    except Exception as e: # Catch any other unexpected errors
        log.exception(f"API: Unexpected error during internal apply for mode '{mode}': {e}")
        return False

def handle_run_login_check() -> bool:
    """
    Called by systemd (`fluxfce-login.service`, `fluxfce-resume.service`).
    Determines current solar period and applies appropriate theme settings.
    """
    log.info("API: Handling 'run-login-check' command (login/resume)...")
    try:
        config_obj = _load_config_with_defaults() # Ensures defaults are considered
        lat_str = config_obj.get("Location", "LATITUDE")
        lon_str = config_obj.get("Location", "LONGITUDE")
        tz_name = config_obj.get("Location", "TIMEZONE")
        mode_to_apply = "night" # Default assumption if sun times can't be calculated

        if all([lat_str, lon_str, tz_name, 
                lat_str != "Not Set", lon_str != "Not Set", tz_name != "Not Set"]):
            try:
                lat = helpers.latlon_str_to_float(lat_str)
                lon = helpers.latlon_str_to_float(lon_str)
                tz_info = ZoneInfo(tz_name)
                now_local = datetime.now(tz_info)
                today = now_local.date()
                sun_times = sun.get_sun_times(lat, lon, today, tz_name)
                if sun_times["sunrise"] <= now_local < sun_times["sunset"]:
                    mode_to_apply = "day"
                log.info(f"API: Login/Resume check determined current mode: '{mode_to_apply}' based on sun times.")
            except (exc.ValidationError, exc.CalculationError, ZoneInfoNotFoundError) as e:
                log.warning(f"API: Could not determine mode for login/resume check due to sun time calculation error ({e}). Defaulting to '{mode_to_apply}'.")
            except Exception as e_sun:
                log.exception(f"API: Unexpected error determining mode for login/resume check ({e_sun}). Defaulting to '{mode_to_apply}'.")
        else:
            log.warning("API: Location/Timezone not fully configured for login/resume check. Defaulting to 'night'.")
        
        log.info(f"API: Applying mode '{mode_to_apply}' for login/resume check.")
        return _apply_settings_for_mode(mode_to_apply)

    except exc.FluxFceError as e: # Includes critical theme errors
        log.error(f"API: Error during 'run-login-check': {e}")
        return False
    except Exception as e: 
        log.exception(f"API: Unexpected error during 'run-login-check': {e}")
        return False