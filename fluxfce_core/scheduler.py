# ~/dev/fluxfce-simplified/fluxfce_core/scheduler.py

import logging
import pathlib
import re
import shlex
from datetime import date, datetime, timedelta
from typing import List, Tuple, Optional, Dict

# zoneinfo needed for datetime comparison within scheduling logic
try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:
    raise ImportError("Required module 'zoneinfo' not found. FluxFCE requires Python 3.9+.")

# Import helpers, sun calculation, and exceptions
from . import helpers
from . import sun
from .exceptions import SchedulerError, CalculationError, ValidationError, DependencyError

log = logging.getLogger(__name__)

# --- Constants ---
# Tag used to identify jobs scheduled by this application in the 'at' queue
AT_JOB_TAG = f"# fluxfce_marker"
# Name used for systemd-cat logging identifier
SYSTEMD_CAT_TAG = "fluxfce-atjob"


class AtdScheduler:
    """Handles scheduling and clearing of theme transition jobs via 'at'. """

    def __init__(self):
        """Check for essential dependencies."""
        try:
            # Core `at` commands needed for scheduling/clearing
            helpers.check_dependencies(['at', 'atq', 'atrm'])
            # systemd-cat needed for logging scheduled job output
            # systemctl needed for getting user environment
            helpers.check_dependencies(['systemd-cat', 'systemctl']) # <--- ADDED systemctl check
        except DependencyError as e:
            raise SchedulerError(f"Cannot initialize AtdScheduler: {e}") from e
        # Ensure atd service itself is running
        try:
             helpers.check_atd_service()
        except Exception as e: # Catch DependencyError or FluxFceError from check_atd_service
             raise SchedulerError(f"Cannot initialize AtdScheduler: 'atd' service check failed: {e}") from e


    def _get_pending_jobs(self) -> List[Dict[str, str]]:
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
            code, stdout, stderr = helpers.run_command(['atq'])
            if code != 0 and "queue is empty" not in stderr.lower():
                raise SchedulerError(f"atq command failed (code {code}): {stderr}")
            if not stdout:
                log.debug("atq: Queue is empty.")
                return []

            job_id_pattern = re.compile(r'^(\d+)\s+.*')
            job_ids_found = []
            for line in stdout.splitlines():
                match = job_id_pattern.match(line.strip())
                if match:
                    job_ids_found.append(match.group(1))

            for job_id in job_ids_found:
                 log.debug(f"Checking job ID {job_id} for marker '{AT_JOB_TAG}'...")
                 code_show, stdout_show, stderr_show = helpers.run_command(['at', '-c', job_id])
                 if code_show != 0:
                      log.warning(f"Failed to get content of 'at' job {job_id}: {stderr_show}")
                      continue
                 if AT_JOB_TAG in stdout_show:
                      log.debug(f"Found fluxfce marker in job {job_id}")
                      time_str = "Unknown Time"
                      for line in stdout.splitlines():
                          if line.strip().startswith(job_id):
                              time_match = re.search(r'^\d+\s+([\w\s\d:.-]+)\s+[a-z]\s+\w+', line.strip())
                              if time_match:
                                   time_str = time_match.group(1).strip()
                              break
                      command = "unknown command"
                      mode = "unknown"
                      cmd_match = re.search(r'internal-apply\s+--mode\s+(\w+)', stdout_show)
                      if cmd_match:
                           command = f"internal-apply --mode {cmd_match.group(1)}"
                           mode = cmd_match.group(1) if cmd_match.group(1) in ['day', 'night'] else 'unknown'
                      pending_jobs.append({
                          'id': job_id, 'time_str': time_str, 'command': command, 'mode': mode
                      })
                      log.debug(f"Found relevant pending job: {pending_jobs[-1]}")
            return pending_jobs
        except Exception as e:
            if isinstance(e, SchedulerError): raise
            log.exception(f"Error getting pending 'at' jobs: {e}")
            raise SchedulerError(f"An unexpected error occurred getting pending 'at' jobs: {e}") from e


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
            job_id = job['id']
            log.debug(f"Removing 'at' job {job_id}...")
            try:
                code, _, stderr = helpers.run_command(['atrm', job_id])
                if code == 0:
                    log.info(f"Removed scheduled job {job_id} ({job['command']} at {job['time_str']})")
                    cleared_count += 1
                else:
                    log.error(f"Failed to remove 'at' job {job_id}: {stderr} (code: {code})")
                    all_cleared = False
            except Exception as e:
                 log.exception(f"Error removing 'at' job {job_id}: {e}")
                 all_cleared = False
        log.info(f"Finished clearing jobs ({cleared_count} removed). Success: {all_cleared}")
        return all_cleared

    def schedule_transitions(
        self,
        lat: float,
        lon: float,
        tz_name: str,
        python_exe_path: str,
        script_exe_path: str
        ) -> bool:
        """
        Calculates the next sunrise and sunset, clears old jobs, and schedules
        new 'at' jobs for the transitions using systemd-cat for logging.
        Attempts to inject DISPLAY and XAUTHORITY environment variables into the job.

        Args:
            lat: Latitude for sun calculation.
            lon: Longitude for sun calculation.
            tz_name: IANA timezone name.
            python_exe_path: Absolute path to the Python interpreter to use.
            script_exe_path: Absolute path to the script that 'at' should execute
                             (this script should handle the 'internal-apply' command).

        Returns:
            True if at least one transition was successfully scheduled.
            False if no future transitions could be determined or scheduling failed.

        Raises:
            SchedulerError, CalculationError, ValidationError, FileNotFoundError, Exception
        """
        log.info(f"Calculating and scheduling transitions for {lat}, {lon} (TZ: {tz_name})...")

        # Ensure executable paths exist
        if not pathlib.Path(python_exe_path).is_file():
            raise FileNotFoundError(f"Python executable not found: {python_exe_path}")
        if not pathlib.Path(script_exe_path).is_file():
             raise FileNotFoundError(f"Target script not found: {script_exe_path}")

        # 1. Clear existing jobs first
        self.clear_scheduled_transitions()

        # 2. Get current time and timezone info
        try:
            tz_info = ZoneInfo(tz_name)
            now_local = datetime.now(tz_info)
            today = now_local.date()
            tomorrow = today + timedelta(days=1)
        except ZoneInfoNotFoundError:
             raise ValidationError(f"Invalid Timezone '{tz_name}' during scheduling.")
        except Exception as e:
             raise SchedulerError(f"Error getting current time/date for timezone '{tz_name}': {e}") from e

        # --- START Environment Injection Logic ---
        env_prefix = ""
        try:
            log.debug("Attempting to get user environment via systemctl show-environment")
            # Make sure 'systemctl' dependency was checked in __init__
            code_env, stdout_env, stderr_env = helpers.run_command(['systemctl', '--user', 'show-environment'])
            if code_env == 0 and stdout_env:
                display_var = None
                xauthority_var = None
                for line in stdout_env.splitlines():
                    if line.startswith("DISPLAY="):
                        # Use shlex.quote directly on the value part for safety
                        display_val = line.split("=", 1)[1]
                        display_var = shlex.quote(display_val) # Store quoted value
                    elif line.startswith("XAUTHORITY="):
                        xauth_val = line.split("=", 1)[1]
                        xauthority_var = shlex.quote(xauth_val) # Store quoted value

                if display_var:
                    # Use the already quoted variables
                    env_prefix += f"export DISPLAY={display_var}; "
                    log.debug(f"Found DISPLAY variable (quoted): {display_var}")
                    if xauthority_var:
                        env_prefix += f"export XAUTHORITY={xauthority_var}; "
                        log.debug(f"Found XAUTHORITY variable (quoted): {xauthority_var}")
                    else:
                        log.warning("Found DISPLAY but not XAUTHORITY in user environment. xsct might still fail if XAUTHORITY is required.")
                else:
                    log.warning("Could not find DISPLAY variable in systemctl user environment. xsct calls in 'at' jobs will likely fail.")
            else:
                log.warning(f"systemctl show-environment failed (code {code_env}) or returned empty. Cannot inject environment for 'at' jobs. Stderr: {stderr_env}")
        except Exception as e:
            log.warning(f"Failed to get or parse user environment: {e}. Cannot inject environment for 'at' jobs.")
        # --- END Environment Injection Logic ---


        # 3. Collect potential future events in the next ~48h
        potential_events: Dict[datetime, str] = {}
        for target_date in [today, tomorrow]:
            try:
                sun_times = sun.get_sun_times(lat, lon, target_date, tz_name) # Raises CalculationError/ValidationError
                if sun_times['sunrise'] > now_local:
                    potential_events[sun_times['sunrise']] = 'day'
                if sun_times['sunset'] > now_local:
                    potential_events[sun_times['sunset']] = 'night'
            except CalculationError as e:
                log.warning(f"Could not calculate sun times for {target_date} ({lat},{lon}): {e}. Skipping.")

        if not potential_events:
            log.warning("No future sunrise/sunset events found to schedule in the next ~48 hours.")
            return False

        # 4. Determine the *very next* sunrise and sunset from the potential events
        next_sunrise_event: Optional[datetime] = None
        next_sunset_event: Optional[datetime] = None
        for event_time, mode in sorted(potential_events.items()):
            if mode == 'day' and next_sunrise_event is None: next_sunrise_event = event_time
            if mode == 'night' and next_sunset_event is None: next_sunset_event = event_time
            if next_sunrise_event and next_sunset_event: break

        # 5. Create the final dictionary of jobs to schedule
        final_events_to_schedule: Dict[datetime, str] = {}
        if next_sunrise_event:
            final_events_to_schedule[next_sunrise_event] = 'day'
            log.debug(f"Selected next sunrise event for scheduling: {next_sunrise_event.isoformat()}")
        if next_sunset_event:
            final_events_to_schedule[next_sunset_event] = 'night'
            log.debug(f"Selected next sunset event for scheduling: {next_sunset_event.isoformat()}")

        if not final_events_to_schedule:
             log.warning("No suitable future events found after filtering. Cannot schedule.")
             return False

        # 6. Proceed with scheduling the selected events via 'at' and 'systemd-cat'
        scheduled_count = 0
        schedule_failed = False
        safe_python_exe = shlex.quote(python_exe_path)
        safe_script_path = shlex.quote(script_exe_path)

        for event_time, mode in sorted(final_events_to_schedule.items()):
            at_time_str = event_time.strftime('%H:%M %Y-%m-%d')

            systemd_cat_command_list = [
                'systemd-cat',
                '-t', SYSTEMD_CAT_TAG,
                '--level-prefix=false',
                safe_python_exe,
                safe_script_path,
                'internal-apply',
                '--mode', mode
            ]
            # Prepend environment exports (if any found) to the command string
            command_to_pipe_to_at = f"{env_prefix}{' '.join(systemd_cat_command_list)} {AT_JOB_TAG}"

            log.debug(f"Scheduling command via 'at {at_time_str}': {command_to_pipe_to_at}")

            try:
                code, stdout, stderr = helpers.run_command(['at', at_time_str], input_str=command_to_pipe_to_at)
                if code == 0:
                    log.info(f"Successfully scheduled '{mode}' transition for {event_time.isoformat()} via 'at'.")
                    if stderr: log.debug(f"'at' command output: {stderr}")
                    scheduled_count += 1
                else:
                    log.error(f"Failed to schedule '{mode}' transition for {at_time_str} using 'at': {stderr} (code: {code})")
                    schedule_failed = True
            except Exception as e:
                 log.exception(f"Error running 'at' command for {mode} at {at_time_str}: {e}")
                 schedule_failed = True

        log.info(f"Scheduling complete ({scheduled_count} jobs scheduled).")

        if schedule_failed:
             raise SchedulerError(f"One or more 'at' commands failed during scheduling ({scheduled_count} succeeded). Check logs.")

        return scheduled_count > 0

    def list_scheduled_transitions(self) -> List[Dict[str, str]]:
        """
        Returns a list of pending fluxfce transition jobs.

        Returns:
            A list of job dictionaries: [{'id': str, 'time_str': str, 'command': str, 'mode': str}, ...]

        Raises:
            SchedulerError: If listing jobs fails.
        """
        return self._get_pending_jobs()