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
            helpers.check_dependencies(['systemd-cat'])
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
        log.debug("Getting pending fluxfce 'at' jobs...")
        pending_jobs = []
        try:
            code, stdout, stderr = helpers.run_command(['atq'])

            # `atq` returns non-zero when queue is empty, check stderr
            if code != 0 and "queue is empty" not in stderr.lower():
                raise SchedulerError(f"atq command failed (code {code}): {stderr}")
            if not stdout: # Queue is empty
                log.debug("atq: Queue is empty.")
                return []

            # Parse 'atq' output (basic parsing, focuses on Job ID)
            job_id_pattern = re.compile(r'^(\d+)\s+.*') # Grab leading job ID
            job_ids_found = []
            for line in stdout.splitlines():
                match = job_id_pattern.match(line.strip())
                if match:
                    job_ids_found.append(match.group(1))

            # For each job ID, check if it's ours using 'at -c' and the marker
            for job_id in job_ids_found:
                 log.debug(f"Checking job ID {job_id} for marker '{AT_JOB_TAG}'...")
                 code_show, stdout_show, stderr_show = helpers.run_command(['at', '-c', job_id])

                 if code_show != 0:
                      # Log warning but continue; job might have been removed between atq and at -c
                      log.warning(f"Failed to get content of 'at' job {job_id}: {stderr_show}")
                      continue

                 if AT_JOB_TAG in stdout_show:
                      log.debug(f"Found fluxfce marker in job {job_id}")
                      # Extract time string from 'atq' output line (best effort)
                      time_str = "Unknown Time"
                      for line in stdout.splitlines(): # Re-iterate atq output
                          if line.strip().startswith(job_id):
                              time_match = re.search(r'^\d+\s+([\w\s\d:.-]+)\s+[a-z]\s+\w+', line.strip())
                              if time_match:
                                   time_str = time_match.group(1).strip()
                              break

                      # Extract command details (mode)
                      command = "unknown command"
                      mode = "unknown"
                      # Look for the internal-apply command structure within the 'at -c' output
                      # Example structure inside: systemd-cat [...] /path/to/fluxfce internal-apply --mode day # fluxfce_marker
                      cmd_match = re.search(r'internal-apply\s+--mode\s+(\w+)', stdout_show)
                      if cmd_match:
                           command = f"internal-apply --mode {cmd_match.group(1)}"
                           mode = cmd_match.group(1) if cmd_match.group(1) in ['day', 'night'] else 'unknown'

                      pending_jobs.append({
                          'id': job_id,
                          'time_str': time_str,
                          'command': command,
                          'mode': mode
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
        log.info("Clearing previously scheduled fluxfce transitions...")
        jobs_to_clear = self._get_pending_jobs() # Can raise SchedulerError

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
                    # Log error but continue trying to remove others
                    log.error(f"Failed to remove 'at' job {job_id}: {stderr} (code: {code})")
                    all_cleared = False
            except Exception as e:
                 # Catch unexpected errors during 'atrm' call
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
            SchedulerError: If clearing old jobs or scheduling new jobs fails.
            CalculationError: If sun times cannot be calculated.
            ValidationError: If timezone is invalid.
            FileNotFoundError: If python_exe_path or script_exe_path do not exist.
            Exception: For other unexpected errors.
        """
        log.info(f"Calculating and scheduling transitions for {lat}, {lon} (TZ: {tz_name})...")

        # Ensure executable paths exist
        if not pathlib.Path(python_exe_path).is_file():
            raise FileNotFoundError(f"Python executable not found: {python_exe_path}")
        if not pathlib.Path(script_exe_path).is_file():
             raise FileNotFoundError(f"Target script not found: {script_exe_path}")


        # 1. Clear existing jobs first (raises SchedulerError on failure)
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

        # 3. Collect potential future events in the next ~48h
        potential_events: Dict[datetime, str] = {}
        for target_date in [today, tomorrow]:
            try:
                sun_times = sun.get_sun_times(lat, lon, target_date, tz_name) # Raises CalculationError/ValidationError
                # Only consider events strictly in the future
                if sun_times['sunrise'] > now_local:
                    potential_events[sun_times['sunrise']] = 'day'
                if sun_times['sunset'] > now_local:
                    potential_events[sun_times['sunset']] = 'night'
            except CalculationError as e:
                log.warning(f"Could not calculate sun times for {target_date} ({lat},{lon}): {e}. Skipping.")
            # Allow ValidationError (bad tz) to propagate up

        if not potential_events:
            log.warning("No future sunrise/sunset events found to schedule in the next ~48 hours.")
            return False # Not an error, just nothing to schedule

        # 4. Determine the *very next* sunrise and sunset from the potential events
        next_sunrise_event: Optional[datetime] = None
        next_sunset_event: Optional[datetime] = None
        # Sort events chronologically
        for event_time, mode in sorted(potential_events.items()):
            if mode == 'day' and next_sunrise_event is None:
                next_sunrise_event = event_time
            if mode == 'night' and next_sunset_event is None:
                next_sunset_event = event_time
            # Optimization: Stop searching once we found the first of each
            if next_sunrise_event and next_sunset_event:
                break

        # 5. Create the final dictionary of jobs to schedule (at most one sunrise, one sunset)
        final_events_to_schedule: Dict[datetime, str] = {}
        if next_sunrise_event:
            final_events_to_schedule[next_sunrise_event] = 'day'
            log.debug(f"Selected next sunrise event for scheduling: {next_sunrise_event.isoformat()}")
        if next_sunset_event:
            final_events_to_schedule[next_sunset_event] = 'night'
            log.debug(f"Selected next sunset event for scheduling: {next_sunset_event.isoformat()}")

        if not final_events_to_schedule:
             # This case should be rare if potential_events wasn't empty
             log.warning("No suitable future events found after filtering. Cannot schedule.")
             return False

        # 6. Proceed with scheduling the selected events via 'at' and 'systemd-cat'
        scheduled_count = 0
        schedule_failed = False
        safe_python_exe = shlex.quote(python_exe_path)
        safe_script_path = shlex.quote(script_exe_path)

        for event_time, mode in sorted(final_events_to_schedule.items()):
            # Format for 'at' command (HH:MM YYYY-MM-DD)
            at_time_str = event_time.strftime('%H:%M %Y-%m-%d')

            # Construct the command to be executed by 'at', wrapped in systemd-cat
            # This ensures the output of the fluxfce command goes to the journal
            systemd_cat_command_list = [
                'systemd-cat',
                '-t', SYSTEMD_CAT_TAG, # Tag for journald
                '--level-prefix=false', # Don't prefix journal lines with level
                safe_python_exe,
                safe_script_path,
                'internal-apply', # The command the target script must understand
                '--mode', mode
            ]
            # Append our marker tag *outside* the systemd-cat call, so 'at -c' can find it easily
            command_to_pipe_to_at = ' '.join(systemd_cat_command_list) + f" {AT_JOB_TAG}"
            log.debug(f"Scheduling command via 'at {at_time_str}': {command_to_pipe_to_at}")

            try:
                code, stdout, stderr = helpers.run_command(['at', at_time_str], input_str=command_to_pipe_to_at)

                if code == 0:
                    log.info(f"Successfully scheduled '{mode}' transition for {event_time.isoformat()} via 'at'.")
                    # stderr often contains job number, e.g., "job 17 at Mon Oct 30 06:30:00 2023"
                    if stderr: log.debug(f"'at' command output: {stderr}")
                    scheduled_count += 1
                else:
                    log.error(f"Failed to schedule '{mode}' transition for {at_time_str} using 'at': {stderr} (code: {code})")
                    schedule_failed = True # Mark failure but continue trying others

            except Exception as e:
                 log.exception(f"Error running 'at' command for {mode} at {at_time_str}: {e}")
                 schedule_failed = True # Mark failure

        log.info(f"Scheduling complete ({scheduled_count} jobs scheduled).")

        if schedule_failed:
             # Raise an error if any individual 'at' command failed
             raise SchedulerError(f"One or more 'at' commands failed during scheduling ({scheduled_count} succeeded). Check logs.")

        return scheduled_count > 0 # Return True only if we actually scheduled something

    def list_scheduled_transitions(self) -> List[Dict[str, str]]:
        """
        Returns a list of pending fluxfce transition jobs.

        Returns:
            A list of job dictionaries: [{'id': str, 'time_str': str, 'command': str, 'mode': str}, ...]

        Raises:
            SchedulerError: If listing jobs fails.
        """
        return self._get_pending_jobs()