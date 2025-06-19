# fluxfce_core/scheduler.py
"""
Manages Systemd-based scheduling for FluxFCE.

This module handles the creation and management of dynamic systemd timers
for sunrise/sunset events and the main daily scheduler task.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

# Imports from within fluxfce_core
from . import config as cfg # For get_current_config via _load_config_with_defaults if not passed
from . import exceptions as exc
from . import helpers, sun, systemd as sysd # Use sysd alias for clarity

# For type hinting configparser object if passed directly
import configparser 

# zoneinfo needed for sun time calculations here
try:
    from zoneinfo import (
        ZoneInfo,
        ZoneInfoNotFoundError,
    )
except ImportError:
    raise ImportError(
        "Required module 'zoneinfo' not found. FluxFCE requires Python 3.9+."
    )

log = logging.getLogger(__name__)

# --- Private Helper to Load Config (if needed, similar to desktop_manager) ---
# This assumes we might need to load config if not passed around explicitly
# Or, these functions can be modified to accept a config_obj if preferred
_cfg_mgr_scheduler = cfg.ConfigManager() # Module-level instance

def _load_scheduler_config() -> configparser.ConfigParser:
    """Loads configuration for scheduler functions."""
    # This reuses the existing ConfigManager logic.
    # No need to re-implement _load_config_with_defaults here if it's generic enough.
    # Let's assume get_current_config from api.py (or its future equivalent) is preferred.
    # For now, we'll replicate a simple load for self-containment,
    # but this could be refactored to use a shared config loading utility.
    try:
        return _cfg_mgr_scheduler.load_config()
    except exc.ConfigError as e:
        log.error(f"Scheduler: Failed to load configuration: {e}")
        raise
    except Exception as e:
        log.exception(f"Scheduler: Unexpected error loading configuration: {e}")
        raise exc.FluxFceError(f"Scheduler: Unexpected error loading configuration: {e}") from e

_sysd_mgr_scheduler = sysd.SystemdManager() # Module-level instance for SystemdManager


# --- Scheduling Functions (Moved from api.py) ---

def handle_schedule_dynamic_transitions_command() -> bool:
    """
    Calculates next sun events, writes dynamic systemd timer files, reloads the
    systemd daemon, and starts the dynamic timers.
    Called by the fluxfce-scheduler.service.
    """
    log.info("Scheduler: Handling 'schedule-dynamic-transitions' command...")
    try:
        # current_config = get_current_config() # Original call
        current_config = _load_scheduler_config() # Use local loader or pass config_obj

        lat_str = current_config.get("Location", "LATITUDE")
        lon_str = current_config.get("Location", "LONGITUDE")
        tz_name = current_config.get("Location", "TIMEZONE")

        if not all([lat_str, lon_str, tz_name, 
                    lat_str != "Not Set", lon_str != "Not Set", tz_name != "Not Set"]):
            raise exc.ConfigError("Scheduler: Location (latitude, longitude, timezone) not fully configured.")

        lat = helpers.latlon_str_to_float(lat_str)
        lon = helpers.latlon_str_to_float(lon_str)
        
        try:
            local_tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError as e_tz:
            raise exc.ConfigError(f"Scheduler: Invalid timezone in configuration: {tz_name}") from e_tz

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
                log.warning(f"Scheduler: Could not calculate sun times for {target_date}: {e}")
            if next_event_times["day"] and next_event_times["night"]:
                break
        
        _sysd_mgr_scheduler._run_systemctl(
            ["stop", sysd.SUNRISE_EVENT_TIMER_NAME, sysd.SUNSET_EVENT_TIMER_NAME],
            check_errors=False, capture_output=True
        )

        scheduled_any_timer = False
        utc_tz = ZoneInfo("UTC")

        if next_event_times["day"]:
            utc_event_time = next_event_times["day"].astimezone(utc_tz)
            _sysd_mgr_scheduler.write_dynamic_event_timer_unit_file("day", utc_event_time)
            scheduled_any_timer = True
            log.info(f"Scheduler: Dynamic timer for SUNRISE prepared for: {utc_event_time.isoformat()}")
        else:
            log.warning("Scheduler: No upcoming sunrise event found. Removing existing timer if any.")
            (sysd.SYSTEMD_USER_DIR / sysd.SUNRISE_EVENT_TIMER_NAME).unlink(missing_ok=True)

        if next_event_times["night"]:
            utc_event_time = next_event_times["night"].astimezone(utc_tz)
            _sysd_mgr_scheduler.write_dynamic_event_timer_unit_file("night", utc_event_time)
            scheduled_any_timer = True
            log.info(f"Scheduler: Dynamic timer for SUNSET prepared for: {utc_event_time.isoformat()}")
        else:
            log.warning("Scheduler: No upcoming sunset event found. Removing existing timer if any.")
            (sysd.SYSTEMD_USER_DIR / sysd.SUNSET_EVENT_TIMER_NAME).unlink(missing_ok=True)

        _sysd_mgr_scheduler._run_systemctl(["daemon-reload"], capture_output=True)

        if next_event_times["day"]:
            _sysd_mgr_scheduler._run_systemctl(["start", sysd.SUNRISE_EVENT_TIMER_NAME], check_errors=False, capture_output=True)
        if next_event_times["night"]:
            _sysd_mgr_scheduler._run_systemctl(["start", sysd.SUNSET_EVENT_TIMER_NAME], check_errors=False, capture_output=True)
        
        if not scheduled_any_timer:
            log.warning("Scheduler: No sun event timers could be scheduled (e.g. polar day/night).")
        else:
            log.info("Scheduler: Dynamic event timers (re)written, daemon reloaded, and timers (re)started.")
        return True

    except (exc.ConfigError, exc.ValidationError, exc.SystemdError, exc.FluxFceError) as e:
        log.error(f"Scheduler: Failed to schedule dynamic transitions: {e}")
        return False
    except Exception as e:
        log.exception(f"Scheduler: Unexpected error during 'schedule-dynamic-transitions': {e}")
        return False

# In fluxfce_core/scheduler.py

def enable_scheduling() -> bool:
    """
    Enables automatic theme transitions by running the dynamic scheduler once
    and STARTING the main static scheduler timer.
    """
    log.info("Scheduler: Starting scheduling with systemd timers...")
    try:
        # Run once to set the sunrise/sunset timers for today.
        define_schedule_ok = handle_schedule_dynamic_transitions_command()
        if not define_schedule_ok:
            log.warning("Scheduler: Initial definition of dynamic event timers failed, but proceeding to start the main daily scheduler.")

        # --- THIS IS THE FIX ---
        # We START the timer, we don't 'enable' it again.
        code, _, stderr = _sysd_mgr_scheduler._run_systemctl(
            ["start", sysd.SCHEDULER_TIMER_NAME], capture_output=True
        )
        # --- END OF THE FIX ---
        if code != 0:
            raise exc.SystemdError(
                f"Scheduler: Failed to start main scheduler timer ({sysd.SCHEDULER_TIMER_NAME}): {stderr.strip()}"
            )
        
        log.info(f"Scheduler: Main scheduler ({sysd.SCHEDULER_TIMER_NAME}) started.")
        return True
        
    except (exc.SystemdError, exc.FluxFceError) as e: 
        log.error(f"Scheduler: Failed to start scheduling: {e}")
        raise 
    except Exception as e: 
        log.exception(f"Scheduler: Unexpected error starting scheduling: {e}")
        raise exc.FluxFceError(f"Scheduler: An unexpected error occurred while starting scheduling: {e}") from e

def disable_scheduling() -> bool:
    """
    Disables automatic theme transitions by STOPPING the main timer
    and removing the dynamic timers.
    """
    log.info("Scheduler: Stopping scheduling and removing dynamic systemd timers...")
    try:
        # --- THIS IS THE FIX ---
        # We STOP the timer. We no longer run 'disable'.
        _sysd_mgr_scheduler._run_systemctl(["stop", sysd.SCHEDULER_TIMER_NAME], check_errors=False, capture_output=True)
        # --- END OF THE FIX ---
        log.debug(f"Scheduler: Main scheduler timer ({sysd.SCHEDULER_TIMER_NAME}) stopped.")

        _sysd_mgr_scheduler.remove_dynamic_timers()
        
        _sysd_mgr_scheduler._run_systemctl(["reset-failed", *sysd.ALL_POTENTIAL_FLUXFCE_UNIT_NAMES], check_errors=False, capture_output=True)

        log.info("Scheduler: Scheduling stopped successfully.")
        return True

    except (exc.SystemdError, exc.FluxFceError) as e:
        log.error(f"Scheduler: Failed to stop scheduling: {e}")
        raise
    except Exception as e:
        log.exception(f"Scheduler: Unexpected error stopping scheduling: {e}")
        raise exc.FluxFceError(f"Scheduler: An unexpected error occurred while stopping scheduling: {e}") from e