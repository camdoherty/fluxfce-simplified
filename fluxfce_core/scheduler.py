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
from . import config as cfg 
from . import exceptions as exc
from . import helpers, sun, systemd as sysd 

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

_cfg_mgr_scheduler = cfg.ConfigManager()

def _load_scheduler_config() -> configparser.ConfigParser:
    """Loads configuration for scheduler functions."""
    try:
        return _cfg_mgr_scheduler.load_config()
    except exc.ConfigError as e:
        log.error(f"Scheduler: Failed to load configuration: {e}")
        raise
    except Exception as e:
        log.exception(f"Scheduler: Unexpected error loading configuration: {e}")
        raise exc.FluxFceError(f"Scheduler: Unexpected error loading configuration: {e}") from e

_sysd_mgr_scheduler = sysd.SystemdManager()

def handle_schedule_dynamic_transitions_command(
    python_exe_path: str, script_exe_path: str
) -> bool:
    """
    Calculates next sun events, writes dynamic systemd timer files, reloads the
    systemd daemon, and starts the dynamic timers.
    Called by the fluxfce-scheduler.service.
    """
    log.info("Scheduler: Handling 'schedule-dynamic-transitions' command...")
    try:
        current_config = _load_scheduler_config()
        lat = helpers.latlon_str_to_float(current_config.get("Location", "LATITUDE"))
        lon = helpers.latlon_str_to_float(current_config.get("Location", "LONGITUDE"))
        tz_name = current_config.get("Location", "TIMEZONE")
        local_tz = ZoneInfo(tz_name)
        now_local = datetime.now(local_tz)
        next_event_times: dict[str, Optional[datetime]] = {"day": None, "night": None}

        for day_offset in range(2):
            target_date = now_local.date() + timedelta(days=day_offset)
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
        
        # --- START OF FIX ---
        # Stop any previously running dynamic timers before creating new ones.
        # This prevents having multiple versions of the timer running.
        timers_to_stop = []
        if (sysd.SYSTEMD_USER_DIR / sysd.SUNRISE_EVENT_TIMER_NAME).exists():
            timers_to_stop.append(sysd.SUNRISE_EVENT_TIMER_NAME)
        if (sysd.SYSTEMD_USER_DIR / sysd.SUNSET_EVENT_TIMER_NAME).exists():
            timers_to_stop.append(sysd.SUNSET_EVENT_TIMER_NAME)

        if timers_to_stop:
            log.debug(f"Stopping existing dynamic timers: {', '.join(timers_to_stop)}")
            _sysd_mgr_scheduler._run_systemctl(["stop", *timers_to_stop], check_errors=False)

        # Write the new timer unit files
        utc_tz = ZoneInfo("UTC")
        if next_event_times["day"]:
            utc_event_time = next_event_times["day"].astimezone(utc_tz)
            _sysd_mgr_scheduler.write_dynamic_event_timer_unit_file("day", utc_event_time)
            log.info(f"Scheduler: Dynamic timer for SUNRISE prepared for: {next_event_times['day']}")
        else:
            (sysd.SYSTEMD_USER_DIR / sysd.SUNRISE_EVENT_TIMER_NAME).unlink(missing_ok=True)

        if next_event_times["night"]:
            utc_event_time = next_event_times["night"].astimezone(utc_tz)
            _sysd_mgr_scheduler.write_dynamic_event_timer_unit_file("night", utc_event_time)
            log.info(f"Scheduler: Dynamic timer for SUNSET prepared for: {next_event_times['night']}")
        else:
            (sysd.SYSTEMD_USER_DIR / sysd.SUNSET_EVENT_TIMER_NAME).unlink(missing_ok=True)

        # Reload the daemon to make it aware of the new/changed timer files
        _sysd_mgr_scheduler._run_systemctl(["daemon-reload"])

        # Start the timers. This "arms" them to fire at their scheduled time.
        # It will NOT trigger the service immediately because we removed Persistent=true.
        timers_to_start = []
        if next_event_times["day"]:
            timers_to_start.append(sysd.SUNRISE_EVENT_TIMER_NAME)
        if next_event_times["night"]:
            timers_to_start.append(sysd.SUNSET_EVENT_TIMER_NAME)

        if timers_to_start:
            log.info(f"Arming dynamic timers: {', '.join(timers_to_start)}")
            _sysd_mgr_scheduler._run_systemctl(["start", *timers_to_start])
        else:
            log.warning("Scheduler: No sun event timers could be scheduled (e.g., polar day/night).")
        # --- END OF FIX ---
        
        return True

    except (exc.ConfigError, exc.ValidationError, exc.SystemdError, exc.FluxFceError, ZoneInfoNotFoundError) as e:
        log.error(f"Scheduler: Failed to schedule dynamic transitions: {e}")
        return False
    except Exception as e:
        log.exception(f"Scheduler: Unexpected error during 'schedule-dynamic-transitions': {e}")
        return False

def enable_scheduling(
    python_exe_path: str,
    script_exe_path: str,
) -> bool:
    """
    Enables automatic theme transitions by enabling and immediately triggering
    the main scheduler timer. The timer's service will then create the dynamic
    sunrise/sunset event timers.
    """
    # Note: The application of the current theme (via handle_run_login_check)
    # is handled by the calling function in api.py after this function succeeds.

    log.info("Scheduler: Enabling scheduling with systemd timers...")
    try:
        # The '--now' flag is the correct, idempotent way to enable a timer and
        # ensure its associated service runs once immediately. This first run
        # will call 'schedule-dynamic-transitions' to set the initial schedule.
        # This restores the correct logic from the stable branch.
        code, _, stderr = _sysd_mgr_scheduler._run_systemctl(
            ["enable", "--now", sysd.SCHEDULER_TIMER_NAME], capture_output=True
        )
        if code != 0:
            raise exc.SystemdError(
                f"Scheduler: Failed to enable main scheduler timer ({sysd.SCHEDULER_TIMER_NAME}): {stderr.strip()}"
            )

        log.info(f"Scheduler: Main scheduler ({sysd.SCHEDULER_TIMER_NAME}) enabled and started for initial run.")
        log.info("Scheduler: Scheduling setup completed successfully by scheduler module.")
        return True

    except (exc.SystemdError, exc.FluxFceError) as e:
        log.error(f"Scheduler: Failed to enable scheduling: {e}")
        raise
    except Exception as e:
        log.exception(f"Scheduler: Unexpected error enabling scheduling: {e}")
        raise exc.FluxFceError(f"Scheduler: An unexpected error occurred while enabling scheduling: {e}") from e

def disable_scheduling() -> bool:
    """
    Disables automatic theme transitions.
    """
    log.info("Scheduler: Disabling scheduling and removing dynamic systemd timers...")
    try:
        # Define all units related to scheduling that need to be managed.
        # FIX: Added 'sysd.' prefix to all constants.
        scheduling_units = [
            sysd.SCHEDULER_TIMER_NAME,
            sysd.SUNRISE_EVENT_TIMER_NAME,
            sysd.SUNSET_EVENT_TIMER_NAME,
            sysd.SCHEDULER_SERVICE_NAME
        ]

        # Stop and disable the main scheduler timer first.
        _sysd_mgr_scheduler._run_systemctl(["stop", sysd.SCHEDULER_TIMER_NAME], check_errors=False, capture_output=True)
        _sysd_mgr_scheduler._run_systemctl(["disable", sysd.SCHEDULER_TIMER_NAME], check_errors=False, capture_output=True)
        log.debug(f"Scheduler: Main scheduler timer ({sysd.SCHEDULER_TIMER_NAME}) stopped and disabled.")

        # Stop the dynamic event timers.
        _sysd_mgr_scheduler._run_systemctl(["stop", sysd.SUNRISE_EVENT_TIMER_NAME], check_errors=False, capture_output=True)
        _sysd_mgr_scheduler._run_systemctl(["stop", sysd.SUNSET_EVENT_TIMER_NAME], check_errors=False, capture_output=True)
        log.debug("Scheduler: Dynamic event timers stopped.")

        # 1. Reset the failed state of all scheduling units while systemd still knows about them.
        _sysd_mgr_scheduler._run_systemctl(["reset-failed", *scheduling_units], check_errors=False, capture_output=True)
        log.debug(f"Scheduler: Attempted to reset failed state for: {', '.join(scheduling_units)}")

        # 2. Now, remove the dynamic timer files from the filesystem.
        # FIX: Added 'sysd.' prefix to constants.
        for timer_name in [sysd.SUNRISE_EVENT_TIMER_NAME, sysd.SUNSET_EVENT_TIMER_NAME]:
            timer_path = sysd.SYSTEMD_USER_DIR / timer_name
            try:
                timer_path.unlink(missing_ok=True)
                log.debug(f"Scheduler: Removed {timer_name} (if it existed).")
            except OSError as e:
                log.warning(f"Scheduler: Could not remove {timer_name}: {e}")

        # 3. Finally, tell systemd to reload, forgetting the units whose files were just removed.
        _sysd_mgr_scheduler._run_systemctl(["daemon-reload"], capture_output=True)
        log.debug("Scheduler: Systemd daemon reloaded.")
        
        log.info("Scheduler: Scheduling disabled successfully.")
        return True

    except (exc.SystemdError, exc.FluxFceError) as e:
        log.error(f"Scheduler: Failed to disable scheduling: {e}")
        raise
    except Exception as e:
        log.exception(f"Scheduler: Unexpected error disabling scheduling: {e}")
        raise exc.FluxFceError(f"Scheduler: An unexpected error occurred while disabling scheduling: {e}") from e

    except (exc.SystemdError, exc.FluxFceError) as e:
        log.error(f"Scheduler: Failed to disable scheduling: {e}")
        raise
    except Exception as e:
        log.exception(f"Scheduler: Unexpected error disabling scheduling: {e}")
        raise exc.FluxFceError(f"Scheduler: An unexpected error occurred while disabling scheduling: {e}") from e