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
    Calculates next sun events and fades, writes dynamic systemd timer files,
    reloads the systemd daemon, and starts the dynamic timers.
    Called by the fluxfce-scheduler.service.
    """
    log.info("Scheduler: Handling 'schedule-dynamic-transitions' command...")
    try:
        current_config = _load_scheduler_config()

        # --- Read Location Config ---
        lat_str = current_config.get("Location", "LATITUDE")
        lon_str = current_config.get("Location", "LONGITUDE")
        tz_name = current_config.get("Location", "TIMEZONE")

        if not all([lat_str, lon_str, tz_name, lat_str != "Not Set", lon_str != "Not Set", tz_name != "Not Set"]):
            raise exc.ConfigError("Scheduler: Location (latitude, longitude, timezone) not fully configured.")

        lat = helpers.latlon_str_to_float(lat_str)
        lon = helpers.latlon_str_to_float(lon_str)
        local_tz = ZoneInfo(tz_name)

        # --- Read Fade Config ---
        fade_enabled = current_config.getboolean("Fade Transition", "FADE_ENABLED", fallback=False)
        fade_duration = current_config.getint("Fade Transition", "FADE_DURATION_MINUTES", fallback=0)
        fade_offset = current_config.getint("Fade Transition", "FADE_OFFSET_MINUTES", fallback=0)

        # --- Calculate Next Events ---
        now_local = datetime.now(local_tz)
        today_local = now_local.date()
        next_event_times: dict[str, Optional[datetime]] = {"day": None, "night": None}

        for day_offset in range(2):  # Check today and tomorrow
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

        # --- Stop Existing Timers ---
        timers_to_stop = []
        if (sysd.SYSTEMD_USER_DIR / sysd.SUNRISE_EVENT_TIMER_NAME).exists():
            timers_to_stop.append(sysd.SUNRISE_EVENT_TIMER_NAME)
        if (sysd.SYSTEMD_USER_DIR / sysd.SUNSET_EVENT_TIMER_NAME).exists():
            timers_to_stop.append(sysd.SUNSET_EVENT_TIMER_NAME)
        for mode in ["day", "night"]:
            fade_timer_name = f"{sysd._APP_NAME}-fade@{mode}.timer"
            if (sysd.SYSTEMD_USER_DIR / fade_timer_name).exists():
                timers_to_stop.append(fade_timer_name)

        if timers_to_stop:
            log.debug(f"Stopping existing dynamic timers: {', '.join(timers_to_stop)}")
            _sysd_mgr_scheduler._run_systemctl(["stop", *timers_to_stop], check_errors=False, capture_output=True)

        # --- Prepare and Start New Timers ---
        utc_tz = ZoneInfo("UTC")
        timers_to_start = []
        
        # Schedule main sunrise/sunset event timers
        if event_time := next_event_times.get("day"):
            utc_event_time = event_time.astimezone(utc_tz)
            _sysd_mgr_scheduler.write_dynamic_event_timer_unit_file("day", utc_event_time)
            timers_to_start.append(sysd.SUNRISE_EVENT_TIMER_NAME)
            log.info(f"Scheduler: Main SUNRISE event timer prepared for: {utc_event_time.isoformat()}")

        if event_time := next_event_times.get("night"):
            utc_event_time = event_time.astimezone(utc_tz)
            _sysd_mgr_scheduler.write_dynamic_event_timer_unit_file("night", utc_event_time)
            timers_to_start.append(sysd.SUNSET_EVENT_TIMER_NAME)
            log.info(f"Scheduler: Main SUNSET event timer prepared for: {utc_event_time.isoformat()}")

        # Schedule fade timers if enabled
        if fade_enabled and fade_duration > 0:
            log.info("Fade is enabled, preparing fade timers.")
            for mode, event_time in next_event_times.items():
                if event_time:
                    fade_start_time = event_time + timedelta(minutes=fade_offset) - timedelta(minutes=fade_duration)
                    if fade_start_time > now_local:
                        utc_fade_time = fade_start_time.astimezone(utc_tz)
                        _sysd_mgr_scheduler.write_dynamic_fade_timer_unit_file(mode, utc_fade_time)
                        fade_timer_name = f"{sysd._APP_NAME}-fade@{mode}.timer"
                        timers_to_start.append(fade_timer_name)
                        log.info(f"Scheduler: FADE to {mode.upper()} timer prepared for: {utc_fade_time.isoformat()}")
                    else:
                        log.info(f"Fade start time for {mode} is in the past, skipping fade timer.")
        
        _sysd_mgr_scheduler._run_systemctl(["daemon-reload"], capture_output=True)

        if timers_to_start:
            _sysd_mgr_scheduler._run_systemctl(["start", *timers_to_start], check_errors=False, capture_output=True)
            log.info(f"Scheduler: Started dynamic timers: {', '.join(timers_to_start)}")
        else:
            log.warning("Scheduler: No sun event or fade timers could be scheduled.")
        
        return True

    except (exc.ConfigError, exc.ValidationError, exc.SystemdError, exc.FluxFceError) as e:
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
    Enables automatic theme transitions:
    1. Defines dynamic event timers for the next sunrise/sunset.
    2. Enables AND starts the main daily scheduler timer (`fluxfce-scheduler.timer`).
    """
    # Note: The application of the current theme (via handle_run_login_check)
    # is handled by the calling function in api.py after this function succeeds.

    log.info("Scheduler: Enabling scheduling with dynamic systemd timers...")
    try:
        define_schedule_ok = handle_schedule_dynamic_transitions_command(
            python_exe_path=python_exe_path, script_exe_path=script_exe_path
        )
        if not define_schedule_ok:
            log.warning("Scheduler: Initial definition of dynamic event timers failed or scheduled nothing, "
                        "but proceeding to enable the main daily scheduler.")

        # Enable the main scheduler timer. This makes it persistent across reboots.
        enable_code, _, enable_stderr = _sysd_mgr_scheduler._run_systemctl(
            ["enable", sysd.SCHEDULER_TIMER_NAME], capture_output=True
        )
        if enable_code != 0:
            raise exc.SystemdError(
                f"Scheduler: Failed to enable main scheduler timer ({sysd.SCHEDULER_TIMER_NAME}): {enable_stderr.strip()}"
            )
        
        # Start the main scheduler timer. This arms it for the current session
        # so it will run tomorrow without requiring a reboot.
        start_code, _, start_stderr = _sysd_mgr_scheduler._run_systemctl(
            ["start", sysd.SCHEDULER_TIMER_NAME], capture_output=True
        )
        if start_code != 0:
            # This is not a fatal error for the install process, as the timer is
            # still enabled and will start on the next login. Log a warning.
            log.warning(
                f"Scheduler: Could not start main scheduler timer ({sysd.SCHEDULER_TIMER_NAME}) "
                f"in current session: {start_stderr.strip()}. It will become active on the next login."
            )

        log.info(f"Scheduler: Main scheduler ({sysd.SCHEDULER_TIMER_NAME}) enabled and activated.")
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
            sysd.SCHEDULER_SERVICE_NAME,
            f"{sysd._APP_NAME}-fade@.timer",
        ]

        # Stop and disable the main scheduler timer first.
        _sysd_mgr_scheduler._run_systemctl(["stop", sysd.SCHEDULER_TIMER_NAME], check_errors=False, capture_output=True)
        _sysd_mgr_scheduler._run_systemctl(["disable", sysd.SCHEDULER_TIMER_NAME], check_errors=False, capture_output=True)
        log.debug(f"Scheduler: Main scheduler timer ({sysd.SCHEDULER_TIMER_NAME}) stopped and disabled.")

        # Stop the dynamic event timers.
        _sysd_mgr_scheduler._run_systemctl(["stop", sysd.SUNRISE_EVENT_TIMER_NAME], check_errors=False, capture_output=True)
        _sysd_mgr_scheduler._run_systemctl(["stop", sysd.SUNSET_EVENT_TIMER_NAME], check_errors=False, capture_output=True)
        _sysd_mgr_scheduler._run_systemctl(["stop", f"{sysd._APP_NAME}-fade@day.timer"], check_errors=False, capture_output=True)
        _sysd_mgr_scheduler._run_systemctl(["stop", f"{sysd._APP_NAME}-fade@night.timer"], check_errors=False, capture_output=True)
        log.debug("Scheduler: Dynamic event timers stopped.")
        log.debug("Scheduler: Dynamic fade timers stopped.")

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

        # Remove dynamic fade timer files.
        for mode in ["day", "night"]:
            fade_timer_name = f"{sysd._APP_NAME}-fade@{mode}.timer"
            timer_path = sysd.SYSTEMD_USER_DIR / fade_timer_name
            try:
                timer_path.unlink(missing_ok=True)
                log.debug(f"Scheduler: Removed {fade_timer_name} (if it existed).")
            except OSError as e:
                log.warning(f"Scheduler: Could not remove {fade_timer_name}: {e}")

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
