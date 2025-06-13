# ~/dev/fluxfce-simplified/fluxfce_core/scheduler.py

import logging
import pathlib
import re
import shlex
from datetime import datetime, timedelta

# zoneinfo needed for datetime comparison within scheduling logic
try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:
    raise ImportError(
        "Required module 'zoneinfo' not found. FluxFCE requires Python 3.9+."
    )

# Import helpers, sun calculation, and exceptions
from . import helpers, sun, exceptions # Added exceptions for SchedulerError
from .exceptions import (
    CalculationError,
    DependencyError,
    SchedulerError,
    ValidationError,
)
import configparser # Added for type hinting
from .systemd import SystemdManager, SYSTEMD_USER_DIR, TRANSITION_SERVICE_TEMPLATE_NAME # Added systemd imports
import pathlib # Added pathlib

log = logging.getLogger(__name__)

# --- New Constants for Dynamic Timers ---
FLUXFCE_DAY_TRANSITION_TIMER = "fluxfce-start-day-transition.timer"
FLUXFCE_NIGHT_TRANSITION_TIMER = "fluxfce-start-night-transition.timer"
DYNAMIC_TIMER_NAMES = [FLUXFCE_DAY_TRANSITION_TIMER, FLUXFCE_NIGHT_TRANSITION_TIMER]
_APP_NAME = "fluxfce" # Local app name, consider if this should be from a central place

# --- Helper function for timer content ---
def _get_transition_timer_content(mode: str, calendar_time_str: str, app_name: str) -> str:
    """Generates the content for a transition timer unit file."""
    # Assuming TRANSITION_SERVICE_TEMPLATE_NAME is "fluxfce-transition@.service"
    # Construct instance name like "fluxfce-transition@day.service"
    instance_name_base = TRANSITION_SERVICE_TEMPLATE_NAME.split('@.')[0]
    transition_service_instance = f"{instance_name_base}@{mode}.service"

    return f"""\
[Unit]
Description={app_name}: Gradual Screen Transition Trigger for {mode.capitalize()}
Unit={transition_service_instance}
After=graphical-session.target
PartOf=graphical-session.target

[Timer]
OnCalendar={calendar_time_str}
Persistent=true
AccuracySec=1min

[Install]
WantedBy=timers.target
"""

# --- New public function to schedule dynamic systemd timers ---
def schedule_dynamic_transitions(config: configparser.ConfigParser, systemd_mgr: SystemdManager, sun_times: dict, app_name: str = _APP_NAME) -> bool:
    log.info("Scheduling dynamic systemd transitions...")
    try:
        enabled = config.getboolean("Transitions", "ENABLED", fallback=True)
        duration_minutes = config.getint("Transitions", "DURATION_MINUTES", fallback=15)

        if not enabled or duration_minutes <= 0:
            log.info("Gradual transitions are disabled or duration is invalid. Removing any existing dynamic timers.")
            _remove_dynamic_transition_timers(systemd_mgr)
            return True # Successfully did nothing or cleaned up

        # Ensure timezone is available for localizing 'now'
        try:
            tz_str = config.get("Location", "TIMEZONE")
            if not tz_str: # Fallback if empty string
                tz_str = "UTC"
                log.warning("Timezone in config is empty, falling back to UTC for transition scheduling.")
            tz = ZoneInfo(tz_str)
        except (configparser.NoOptionError, configparser.NoSectionError):
            log.warning("Timezone not found in config, falling back to UTC for transition scheduling.")
            tz = ZoneInfo("UTC") # Default to UTC if not found
        except ZoneInfoNotFoundError:
            log.error(f"Invalid timezone '{tz_str}' in config. Cannot schedule dynamic transitions.")
            _remove_dynamic_transition_timers(systemd_mgr) # Attempt cleanup
            return False

        now_local = datetime.now(tz)

        timers_to_create = []
        if "sunrise" in sun_times and sun_times["sunrise"]:
            sunrise_transition_start = sun_times["sunrise"] - timedelta(minutes=duration_minutes)
            if sunrise_transition_start > now_local:
                timers_to_create.append({
                    "file_path": SYSTEMD_USER_DIR / FLUXFCE_DAY_TRANSITION_TIMER,
                    "content": _get_transition_timer_content("day", sunrise_transition_start.strftime("%Y-%m-%d %H:%M:%S"), app_name),
                    "name": FLUXFCE_DAY_TRANSITION_TIMER
                })
            else:
                log.info(f"Calculated day transition start time {sunrise_transition_start.strftime('%Y-%m-%d %H:%M:%S')} is in the past. Not scheduling.")


        if "sunset" in sun_times and sun_times["sunset"]:
            sunset_transition_start = sun_times["sunset"] - timedelta(minutes=duration_minutes)
            if sunset_transition_start > now_local:
                timers_to_create.append({
                    "file_path": SYSTEMD_USER_DIR / FLUXFCE_NIGHT_TRANSITION_TIMER,
                    "content": _get_transition_timer_content("night", sunset_transition_start.strftime("%Y-%m-%d %H:%M:%S"), app_name),
                    "name": FLUXFCE_NIGHT_TRANSITION_TIMER
                })
            else:
                log.info(f"Calculated night transition start time {sunset_transition_start.strftime('%Y-%m-%d %H:%M:%S')} is in the past. Not scheduling.")


        if not timers_to_create:
            log.info("No future transition start times to schedule. Ensuring old dynamic timers are removed.")
            _remove_dynamic_transition_timers(systemd_mgr) # Clean up any existing ones
            return True

        files_changed = False
        for timer_def in timers_to_create:
            try:
                if timer_def["file_path"].exists():
                    existing_content = timer_def["file_path"].read_text(encoding="utf-8")
                    if existing_content == timer_def["content"]:
                        log.debug(f"Timer file {timer_def['name']} already exists with correct content.")
                    else:
                        timer_def["file_path"].write_text(timer_def["content"], encoding="utf-8")
                        log.info(f"Updated systemd timer unit file: {timer_def['file_path']}")
                        files_changed = True
                else:
                    timer_def["file_path"].write_text(timer_def["content"], encoding="utf-8")
                    log.info(f"Created systemd timer unit file: {timer_def['file_path']}")
                    files_changed = True
            except OSError as e:
                log.error(f"Failed to write systemd timer unit file {timer_def['file_path']}: {e}")
                # If one file write fails, it's critical, attempt cleanup of what might have been written
                _remove_dynamic_transition_timers(systemd_mgr)
                return False

        if files_changed:
            code_reload, _, err_reload = systemd_mgr._run_systemctl(["daemon-reload"])
            if code_reload != 0:
                log.error(f"systemctl daemon-reload failed: {err_reload}")
                _remove_dynamic_transition_timers(systemd_mgr) # Attempt cleanup
                return False

        all_timers_started = True
        for timer_def in timers_to_create:
            code_enable, _, err_enable = systemd_mgr._run_systemctl(["enable", "--now", timer_def["name"]])
            if code_enable != 0:
                log.error(f"Failed to enable/start timer {timer_def['name']}: {err_enable}")
                all_timers_started = False
            else:
                log.info(f"Enabled and started timer: {timer_def['name']}")

        if not all_timers_started:
             log.warning("One or more dynamic transition timers failed to start. State may be inconsistent.")
             # Depending on desired atomicity, may want to _remove_dynamic_transition_timers here and return False
             # For now, consider it a partial success if files were written and daemon reloaded.

        log.info("Dynamic transition timers scheduling process completed.")
        return True # Returns true if process completed, even if some timers failed to start (they are logged)

    except (configparser.NoSectionError, configparser.NoOptionError, ValueError) as e:
        log.error(f"Configuration error for dynamic transitions: {e}")
        _remove_dynamic_transition_timers(systemd_mgr)
        return False
    except ZoneInfoNotFoundError as e: # Already handled above, but as a safeguard
        log.error(f"ZoneInfo error during dynamic transition scheduling: {e}")
        _remove_dynamic_transition_timers(systemd_mgr)
        return False
    except Exception as e:
        log.exception(f"Unexpected error scheduling dynamic transitions: {e}")
        _remove_dynamic_transition_timers(systemd_mgr)
        return False

# --- Helper function to remove dynamic systemd timers ---
def _remove_dynamic_transition_timers(systemd_mgr: SystemdManager) -> bool:
    log.info("Attempting to remove dynamic transition timers...")
    removed_any_files = False
    any_timers_existed = False

    for timer_name in DYNAMIC_TIMER_NAMES:
        timer_file = SYSTEMD_USER_DIR / timer_name
        if timer_file.exists():
            any_timers_existed = True
            log.debug(f"Found dynamic timer file: {timer_file}. Attempting to stop, disable, and remove.")
            # Stop and disable the timer first
            code_stop, _, err_stop = systemd_mgr._run_systemctl(["disable", "--now", timer_name], check_errors=False)
            if code_stop != 0:
                log.warning(f"Failed to disable/stop timer {timer_name}: {err_stop}")

            try:
                timer_file.unlink()
                log.info(f"Successfully removed dynamic timer file: {timer_file}")
                removed_any_files = True
            except OSError as e:
                log.error(f"Failed to remove dynamic timer file {timer_file}: {e}")
                # If unlinking fails, this is an issue, but try to continue with others.

    if any_timers_existed: # Only reload if timers were found (even if removal failed for some)
        log.debug("Dynamic timers existed, reloading systemd daemon and resetting failed states.")
        code_reload, _, err_reload = systemd_mgr._run_systemctl(["daemon-reload"])
        if code_reload != 0:
            log.error(f"systemctl daemon-reload failed after attempting to remove timers: {err_reload}")
            # This is problematic for system state, but function should report based on file removal.

        # Reset failed state for these timers regardless of whether they were successfully removed
        systemd_mgr._run_systemctl(["reset-failed", *DYNAMIC_TIMER_NAMES], check_errors=False)
    else:
        log.info("No dynamic transition timer files found to remove.")

    # Success means we tried to remove everything we found. If unlink failed, it's logged.
    # If daemon-reload failed, it's logged.
    return True # Best effort removal

# --- Constants ---
# Tag used to identify jobs scheduled by this application in the 'at' queue
AT_JOB_TAG = "# fluxfce_marker"
# Name used for systemd-cat logging identifier
SYSTEMD_CAT_TAG = "fluxfce-atjob"


class AtdScheduler:
    """Handles scheduling and clearing of theme transition jobs via 'at'."""

    def __init__(self):
        """Check for essential dependencies."""
        try:
            # Core `at` commands needed for scheduling/clearing
            helpers.check_dependencies(["at", "atq", "atrm"])
            # systemd-cat needed for logging scheduled job output
            # systemctl needed for getting user environment
            helpers.check_dependencies(
                ["systemd-cat", "systemctl"]
            )  # <--- ADDED systemctl check
            self.systemd_mgr = SystemdManager() # Instantiate SystemdManager
        except DependencyError as e:
            raise SchedulerError(f"Cannot initialize AtdScheduler: {e}") from e
        # Ensure atd service itself is running
        try:
            helpers.check_atd_service()
        except (
            Exception
        ) as e:  # Catch DependencyError or FluxFceError from check_atd_service
            raise SchedulerError(
                f"Cannot initialize AtdScheduler: 'atd' service check failed: {e}"
            ) from e

    def _get_pending_jobs(self) -> list[dict[str, str]]:
        """
        Gets list of pending 'at' jobs created by fluxfce.

        Returns:
            A list of dictionaries, where each dict represents a job:
            [{'id': str, 'time_str': str, 'command': str, 'mode': 'day'|'night'|'unknown'}, ...]

        Raises:
            SchedulerError: If `atq` or `at -c` commands fail unexpectedly.
        """
        # This method remains unchanged from your provided version
        log.debug("Getting pending fluxfce 'at' jobs...")
        pending_jobs = []
        try:
            code, stdout, stderr = helpers.run_command(["atq"])
            if code != 0 and "queue is empty" not in stderr.lower():
                raise SchedulerError(f"atq command failed (code {code}): {stderr}")
            if not stdout:
                log.debug("atq: Queue is empty.")
                return []

            job_id_pattern = re.compile(r"^(\d+)\s+.*")
            job_ids_found = []
            for line in stdout.splitlines():
                match = job_id_pattern.match(line.strip())
                if match:
                    job_ids_found.append(match.group(1))

            for job_id in job_ids_found:
                log.debug(f"Checking job ID {job_id} for marker '{AT_JOB_TAG}'...")
                code_show, stdout_show, stderr_show = helpers.run_command(
                    ["at", "-c", job_id]
                )
                if code_show != 0:
                    log.warning(
                        f"Failed to get content of 'at' job {job_id}: {stderr_show}"
                    )
                    continue
                if AT_JOB_TAG in stdout_show:
                    log.debug(f"Found fluxfce marker in job {job_id}")
                    time_str = "Unknown Time"
                    for line in stdout.splitlines():
                        if line.strip().startswith(job_id):
                            time_match = re.search(
                                r"^\d+\s+([\w\s\d:.-]+)\s+[a-z]\s+\w+", line.strip()
                            )
                            if time_match:
                                time_str = time_match.group(1).strip()
                            break
                    command = "unknown command"
                    mode = "unknown"
                    cmd_match = re.search(
                        r"internal-apply\s+--mode\s+(\w+)", stdout_show
                    )
                    if cmd_match:
                        command = f"internal-apply --mode {cmd_match.group(1)}"
                        mode = (
                            cmd_match.group(1)
                            if cmd_match.group(1) in ["day", "night"]
                            else "unknown"
                        )
                    pending_jobs.append(
                        {
                            "id": job_id,
                            "time_str": time_str,
                            "command": command,
                            "mode": mode,
                        }
                    )
                    log.debug(f"Found relevant pending job: {pending_jobs[-1]}")
            return pending_jobs
        except Exception as e:
            if isinstance(e, SchedulerError):
                raise
            log.exception(f"Error getting pending 'at' jobs: {e}")
            raise SchedulerError(
                f"An unexpected error occurred getting pending 'at' jobs: {e}"
            ) from e

    def clear_scheduled_transitions(self) -> bool:
        """
        Removes all pending 'at' jobs created by this script (identified by AT_JOB_TAG).

        Returns:
            True if all identified jobs were successfully removed or no jobs were found.
            False if errors occurred during removal of one or more jobs.

        Raises:
            SchedulerError: If listing jobs fails or unexpected errors occur.
        """
        # This method remains unchanged from your provided version
        log.info("Clearing previously scheduled fluxfce transitions...")
        jobs_to_clear = self._get_pending_jobs()
        if not jobs_to_clear:
            log.info("No relevant 'at' jobs found to clear.")
            return True
        all_cleared = True
        cleared_count = 0
        for job in jobs_to_clear:
            job_id = job["id"]
            log.debug(f"Removing 'at' job {job_id}...")
            try:
                code, _, stderr = helpers.run_command(["atrm", job_id])
                if code == 0:
                    log.info(
                        f"Removed scheduled job {job_id} ({job['command']} at {job['time_str']})"
                    )
                    cleared_count += 1
                else:
                    log.error(
                        f"Failed to remove 'at' job {job_id}: {stderr} (code: {code})"
                    )
                    all_cleared = False
            except Exception as e:
                log.exception(f"Error removing 'at' job {job_id}: {e}")
                all_cleared = False
        log.info(
            f"Finished clearing jobs ({cleared_count} removed). Success: {all_cleared}"
        )

        # Additionally remove dynamic systemd transition timers
        log.info("Additionally removing dynamic systemd transition timers...")
        dynamic_timers_cleared_ok = _remove_dynamic_transition_timers(self.systemd_mgr)
        if not dynamic_timers_cleared_ok:
            # _remove_dynamic_transition_timers logs its own errors, this is just a summary
            log.warning("Removal of dynamic systemd transition timers encountered issues or reported partial success.")
            # Depending on how critical this is, you might want to ensure all_cleared reflects this.
            # For now, _remove_dynamic_transition_timers is best-effort and returns True unless it hits a major snag.

        return all_cleared and dynamic_timers_cleared_ok # True if both 'at' and dynamic timers cleared successfully

    def schedule_transitions(
        self,
        lat: float,
        lon: float,
        tz_name: str,
        python_exe_path: str,
        script_exe_path: str,
        days_to_schedule: int = 7,  # <-- Added parameter with default
    ) -> bool:
        """
        Calculates sunrise/sunset for the next N days, clears old jobs, and
        schedules new 'at' jobs for all future transitions within that window.
        Attempts to inject DISPLAY and XAUTHORITY environment variables into the job.

        Args:
            lat: Latitude for sun calculation.
            lon: Longitude for sun calculation.
            tz_name: IANA timezone name.
            python_exe_path: Absolute path to the Python interpreter.
            script_exe_path: Absolute path to the fluxfce script.
            days_to_schedule: Number of days ahead to calculate and schedule (default: 7).

        Returns:
            True if at least one transition was successfully scheduled.
            False if no future transitions could be determined or scheduling failed.

        Raises:
            SchedulerError, CalculationError, ValidationError, FileNotFoundError, Exception
        """
        if not isinstance(days_to_schedule, int) or days_to_schedule <= 0:
            log.warning(
                f"Invalid days_to_schedule value ({days_to_schedule}), using default 7."
            )
            days_to_schedule = 7

        log.info(
            f"Calculating and scheduling transitions for next {days_to_schedule} days for {lat}, {lon} (TZ: {tz_name})..."
        )

        # Validate paths
        if not pathlib.Path(python_exe_path).is_file():
            raise FileNotFoundError(f"Python executable not found: {python_exe_path}")
        if not pathlib.Path(script_exe_path).is_file():
            raise FileNotFoundError(f"Target script not found: {script_exe_path}")

        # 1. Clear existing jobs first
        self.clear_scheduled_transitions()  # Raises SchedulerError on failure

        # 2. Get current time and timezone info
        try:
            tz_info = ZoneInfo(tz_name)
            now_local = datetime.now(tz_info)
            today = now_local.date()
        except ZoneInfoNotFoundError:
            raise ValidationError(f"Invalid Timezone '{tz_name}' during scheduling.")
        except Exception as e:
            raise SchedulerError(
                f"Error getting current time/date for timezone '{tz_name}': {e}"
            ) from e

        # 3. Get Environment Injection Logic
        env_prefix = ""
        try:
            log.debug(
                "Attempting to get user environment via systemctl show-environment"
            )
            code_env, stdout_env, stderr_env = helpers.run_command(
                ["systemctl", "--user", "show-environment"]
            )
            if code_env == 0 and stdout_env:
                display_var = None
                xauthority_var = None
                for line in stdout_env.splitlines():
                    if line.startswith("DISPLAY="):
                        display_val = line.split("=", 1)[1]
                        display_var = shlex.quote(display_val)
                    elif line.startswith("XAUTHORITY="):
                        xauth_val = line.split("=", 1)[1]
                        xauthority_var = shlex.quote(xauth_val)
                if display_var:
                    env_prefix += f"export DISPLAY={display_var}; "
                    log.debug(f"Found DISPLAY variable (quoted): {display_var}")
                    if xauthority_var:
                        env_prefix += f"export XAUTHORITY={xauthority_var}; "
                        log.debug(
                            f"Found XAUTHORITY variable (quoted): {xauthority_var}"
                        )
                    else:
                        log.warning(
                            "Found DISPLAY but not XAUTHORITY in user environment. xsct might still fail if XAUTHORITY is required."
                        )
                else:
                    log.warning(
                        "Could not find DISPLAY variable in systemctl user environment. xsct calls in 'at' jobs will likely fail."
                    )
            else:
                log.warning(
                    f"systemctl show-environment failed (code {code_env}) or returned empty. Cannot inject environment for 'at' jobs. Stderr: {stderr_env}"
                )
        except Exception as e:
            log.warning(
                f"Failed to get or parse user environment: {e}. Cannot inject environment for 'at' jobs."
            )

        # 4. Collect potential future events for the next N days
        potential_events: dict[datetime, str] = {}
        for i in range(days_to_schedule):  # <-- Loop N days
            target_date = today + timedelta(days=i)
            try:
                sun_times = sun.get_sun_times(
                    lat, lon, target_date, tz_name
                )  # Raises CalculationError/ValidationError
                # Only consider events strictly in the future relative to 'now'
                if sun_times["sunrise"] > now_local:
                    potential_events[sun_times["sunrise"]] = "day"
                if sun_times["sunset"] > now_local:
                    potential_events[sun_times["sunset"]] = "night"
            except CalculationError as e:
                log.warning(
                    f"Could not calculate sun times for {target_date} ({lat},{lon}): {e}. Skipping date."
                )
            except ValidationError as e:  # Should only happen once if TZ is bad
                log.error(
                    f"Invalid timezone '{tz_name}' during sun time calculation: {e}"
                )
                raise  # Propagate validation error

        if not potential_events:
            log.warning(
                f"No future sunrise/sunset events found to schedule in the next {days_to_schedule} days."
            )
            return False  # Nothing to schedule

        # 5. Sort events chronologically
        final_events_to_schedule = dict(sorted(potential_events.items()))
        log.info(
            f"Found {len(final_events_to_schedule)} events to schedule in the next {days_to_schedule} days."
        )

        # 6. Proceed with scheduling ALL selected events
        scheduled_count = 0
        schedule_failed = False
        safe_python_exe = shlex.quote(python_exe_path)
        safe_script_path = shlex.quote(script_exe_path)

        for event_time, mode in final_events_to_schedule.items():
            at_time_str = event_time.strftime("%H:%M %Y-%m-%d")
            systemd_cat_command_list = [
                "systemd-cat",
                "-t",
                SYSTEMD_CAT_TAG,
                "--level-prefix=false",
                safe_python_exe,
                safe_script_path,
                "internal-apply",
                "--mode",
                mode,
            ]
            command_to_pipe_to_at = (
                f"{env_prefix}{' '.join(systemd_cat_command_list)} {AT_JOB_TAG}"
            )
            log.debug(f"Scheduling '{mode}' for {at_time_str}...")

            try:
                code, stdout, stderr = helpers.run_command(
                    ["at", at_time_str], input_str=command_to_pipe_to_at
                )
                if code == 0:
                    log.info(
                        f"Successfully scheduled '{mode}' transition for {event_time.isoformat()} via 'at'."
                    )
                    if stderr:
                        log.debug(f"'at' command output: {stderr}")
                    scheduled_count += 1
                else:
                    log.error(
                        f"Failed to schedule '{mode}' transition for {at_time_str} using 'at': {stderr} (code: {code})"
                    )
                    schedule_failed = True
            except Exception as e:
                log.exception(
                    f"Error running 'at' command for {mode} at {at_time_str}: {e}"
                )
                schedule_failed = True

        log.info(
            f"Scheduling complete ({scheduled_count} / {len(final_events_to_schedule)} jobs successfully scheduled)."
        )

        if schedule_failed:
            raise SchedulerError(
                f"One or more 'at' commands failed during scheduling ({scheduled_count} succeeded). Check logs."
            )

        return scheduled_count > 0

    def list_scheduled_transitions(self) -> list[dict[str, str]]:
        """
        Returns a list of pending fluxfce transition jobs.

        Returns:
            A list of job dictionaries: [{'id': str, 'time_str': str, 'command': str, 'mode': str}, ...]

        Raises:
            SchedulerError: If listing jobs fails.
        """
        return self._get_pending_jobs()
