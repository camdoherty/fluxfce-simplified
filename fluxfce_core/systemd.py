# fluxfce_core/systemd.py

import logging
import pathlib
from datetime import datetime
from typing import Optional

from . import helpers
from .exceptions import DependencyError, SystemdError

log = logging.getLogger(__name__)

# --- Constants ---
_APP_NAME = "fluxfce"

# --- MODIFICATION: Define TWO separate directories ---
# The location for STATIC units installed by the package.
# This path is still needed for context but is not written to by the app.
SYSTEMD_INSTALL_DIR = pathlib.Path("/usr/lib/systemd/user")
# The location for DYNAMIC units created by the app at runtime.
SYSTEMD_USER_CONFIG_DIR = pathlib.Path.home() / ".config" / "systemd" / "user"
# --- END MODIFICATION ---

# --- Unit Names ---
SCHEDULER_TIMER_NAME = f"{_APP_NAME}-scheduler.timer"
SCHEDULER_SERVICE_NAME = f"{_APP_NAME}-scheduler.service"
LOGIN_SERVICE_NAME = f"{_APP_NAME}-login.service"
RESUME_SERVICE_NAME = f"{_APP_NAME}-resume.service"
SUNRISE_EVENT_TIMER_NAME = f"{_APP_NAME}-sunrise-event.timer"
SUNSET_EVENT_TIMER_NAME = f"{_APP_NAME}-sunset-event.timer"

# --- Helper list for `reset-failed` ---
ALL_POTENTIAL_FLUXFCE_UNIT_NAMES = [
    SCHEDULER_TIMER_NAME,
    SCHEDULER_SERVICE_NAME,
    f"{_APP_NAME}-apply-transition@day.service",
    f"{_APP_NAME}-apply-transition@night.service",
    LOGIN_SERVICE_NAME,
    RESUME_SERVICE_NAME,
    SUNRISE_EVENT_TIMER_NAME,
    SUNSET_EVENT_TIMER_NAME,
]

class SystemdManager:
    """Handles interactions with systemd user units for fluxfce."""

    def __init__(self):
        self.app_name = _APP_NAME
        try:
            helpers.check_dependencies(["systemctl"])
        except DependencyError as e:
            raise SystemdError(f"Cannot initialize SystemdManager: {e}") from e

    def _run_systemctl(
        self, args: list[str], check_errors: bool = True, capture_output: bool = False
    ) -> tuple[int, str, str]:
        """Runs a systemctl --user command."""
        cmd = ["systemctl", "--user", *args]
        try:
            code, stdout, stderr = helpers.run_command(cmd, check=False, capture=capture_output)
            if code != 0 and check_errors:
                err_details = stderr.strip() if stderr else stdout.strip()
                log.error(f"systemctl --user {' '.join(args)} failed (code {code}). Details: '{err_details}'")
            return code, stdout, stderr
        except Exception as e:
            raise SystemdError(f"Unexpected error running systemctl command: {e}") from e

    def remove_dynamic_timers(self):
        """Stops and removes only the dynamic timer files from the user's config."""
        log.info("Removing dynamic sunrise/sunset event timers from user config...")
        dynamic_timer_names = [SUNRISE_EVENT_TIMER_NAME, SUNSET_EVENT_TIMER_NAME]
        
        self._run_systemctl(["stop", *dynamic_timer_names], check_errors=False, capture_output=True)
        log.debug("Attempted to stop dynamic event timers.")

        for timer_name in dynamic_timer_names:
            timer_path = SYSTEMD_USER_CONFIG_DIR / timer_name
            try:
                if timer_path.exists():
                    timer_path.unlink()
                    log.debug(f"Removed dynamic timer file: {timer_path}")
            except OSError as e:
                log.warning(f"Could not remove dynamic timer {timer_path}: {e}")
        
        # After removing files, reload the daemon to make it forget about them.
        self._run_systemctl(["daemon-reload"], capture_output=True)
        log.debug("Systemd daemon reloaded after removing dynamic timers.")

    def write_dynamic_event_timer_unit_file(
        self,
        mode: str, 
        utc_execution_time: datetime,
    ) -> bool:
        """Creates or overwrites a dynamic event timer file in the user's config directory."""
        if mode not in ["day", "night"]:
            raise ValueError(f"Invalid mode '{mode}' for dynamic event timer.")

        if utc_execution_time.tzinfo is None:
            raise ValueError("utc_execution_time must be timezone-aware.")

        timer_name = SUNRISE_EVENT_TIMER_NAME if mode == "day" else SUNSET_EVENT_TIMER_NAME
        # MODIFICATION: Write to the user's local systemd directory
        timer_file_path = SYSTEMD_USER_CONFIG_DIR / timer_name
        
        service_instance_to_trigger = f"{self.app_name}-apply-transition@{mode}.service"
        on_calendar_utc_str = utc_execution_time.strftime('%Y-%m-%d %H:%M:%S UTC')

        timer_content = f"""\
[Unit]
Description={self.app_name}: Event Timer for {mode.capitalize()} Transition (Dynamic)
Requires={service_instance_to_trigger}

[Timer]
Unit={service_instance_to_trigger}
OnCalendar={on_calendar_utc_str}
Persistent=true
AccuracySec=1s
WakeSystem=false

[Install]
# Dynamic timers are not "WantedBy" but are started/stopped by the scheduler.
"""
        try:
            # Ensure the user's local systemd directory exists
            SYSTEMD_USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            timer_file_path.write_text(timer_content, encoding="utf-8")
            log.info(f"Written dynamic timer file: {timer_file_path} for event at {on_calendar_utc_str}")
            return True
        except OSError as e:
            raise SystemdError(f"Failed to write dynamic timer file {timer_file_path}: {e}") from e