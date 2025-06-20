# ~/dev/fluxfce-simplified/fluxfce_core/systemd.py
"""
Systemd user unit management for FluxFCE.

This module is responsible for creating, installing, managing, and removing
the systemd user units (timers and services) required for FluxFCE's
automatic scheduling and theme application on login/resume.
It defines the templates for these units and interacts with `systemctl`.
"""

import logging
import pathlib
import sys
from datetime import datetime # For type hinting in write_dynamic_event_timer_unit_file
from typing import Optional

# Import helpers and exceptions from within the same package
from . import helpers
from .exceptions import DependencyError, SystemdError

log = logging.getLogger(__name__)

# --- Constants ---
_APP_NAME = "fluxfce" # Application name, used in unit descriptions and names
SYSTEMD_USER_DIR = pathlib.Path.home() / ".config" / "systemd" / "user"

# --- Static Unit Names and File Paths ---
SCHEDULER_TIMER_NAME = f"{_APP_NAME}-scheduler.timer"
SCHEDULER_SERVICE_NAME = f"{_APP_NAME}-scheduler.service"
APPLY_TRANSITION_SERVICE_TEMPLATE_NAME = f"{_APP_NAME}-apply-transition@.service"
LOGIN_SERVICE_NAME = f"{_APP_NAME}-login.service"
RESUME_SERVICE_NAME = f"{_APP_NAME}-resume.service"
USER_SLEEP_TARGET_NAME = "sleep.target" # User-level anchor for sleep.target

SCHEDULER_TIMER_FILE = SYSTEMD_USER_DIR / SCHEDULER_TIMER_NAME
SCHEDULER_SERVICE_FILE = SYSTEMD_USER_DIR / SCHEDULER_SERVICE_NAME
APPLY_TRANSITION_SERVICE_TEMPLATE_FILE = SYSTEMD_USER_DIR / APPLY_TRANSITION_SERVICE_TEMPLATE_NAME
LOGIN_SERVICE_FILE = SYSTEMD_USER_DIR / LOGIN_SERVICE_NAME
RESUME_SERVICE_FILE = SYSTEMD_USER_DIR / RESUME_SERVICE_NAME
USER_SLEEP_TARGET_FILE = SYSTEMD_USER_DIR / USER_SLEEP_TARGET_NAME # Path for user-level sleep.target

# --- Dynamic Unit Names (filenames for timers generated at runtime) ---
SUNRISE_EVENT_TIMER_NAME = f"{_APP_NAME}-sunrise-event.timer"
SUNSET_EVENT_TIMER_NAME = f"{_APP_NAME}-sunset-event.timer"

# --- Lists for Management ---
STATIC_UNIT_FILES_MAP = {
    SCHEDULER_TIMER_NAME: SCHEDULER_TIMER_FILE,
    SCHEDULER_SERVICE_NAME: SCHEDULER_SERVICE_FILE,
    APPLY_TRANSITION_SERVICE_TEMPLATE_NAME: APPLY_TRANSITION_SERVICE_TEMPLATE_FILE,
    LOGIN_SERVICE_NAME: LOGIN_SERVICE_FILE,
    RESUME_SERVICE_NAME: RESUME_SERVICE_FILE,
    USER_SLEEP_TARGET_NAME: USER_SLEEP_TARGET_FILE, # Added user-level sleep.target
}

DYNAMIC_EVENT_TIMER_NAMES = [
    SUNRISE_EVENT_TIMER_NAME,
    SUNSET_EVENT_TIMER_NAME,
]

# ALL_POTENTIAL_FLUXFCE_UNIT_NAMES includes all units that fluxfce might create or manage,
# including the user-level sleep.target for cleanup with reset-failed.
ALL_POTENTIAL_FLUXFCE_UNIT_NAMES = [
    SCHEDULER_TIMER_NAME,
    SCHEDULER_SERVICE_NAME,
    f"{_APP_NAME}-apply-transition@day.service",
    f"{_APP_NAME}-apply-transition@night.service",
    LOGIN_SERVICE_NAME,
    RESUME_SERVICE_NAME,
    SUNRISE_EVENT_TIMER_NAME,
    SUNSET_EVENT_TIMER_NAME,
    USER_SLEEP_TARGET_NAME, # Added for reset-failed
]

# --- Unit File Templates ---

_SCHEDULER_TIMER_TEMPLATE = """\
[Unit]
Description={app_name}: Daily Timer to Reschedule Sunrise/Sunset Event Timers
PartOf=timers.target

[Timer]
Unit={scheduler_service_name}
OnCalendar=daily
RandomizedDelaySec=15min
Persistent=true
AccuracySec=1m

[Install]
WantedBy=timers.target
"""

_SCHEDULER_SERVICE_TEMPLATE = """\
[Unit]
Description={app_name}: Daily Service to Reschedule Sunrise/Sunset Event Timers
After=time-set.target

[Service]
Type=oneshot
ExecStart={python_executable} "{script_path}" schedule-dynamic-transitions
StandardOutput=journal
StandardError=journal
"""

_APPLY_TRANSITION_TEMPLATE = """\
[Unit]
Description={app_name}: Apply %I Mode Transition
PartOf=graphical-session.target
After=graphical-session.target xfce4-session.target
ConditionEnvironment=DISPLAY

[Service]
Type=oneshot
ExecStart={python_executable} "{script_path}" internal-apply --mode %i
StandardOutput=journal
StandardError=journal
"""

_LOGIN_SERVICE_TEMPLATE = """\
[Unit]
Description={app_name}: Apply theme on first login
; This service runs once after the graphical session starts.
; It waits a few seconds for the desktop environment (e.g., XFCE panel, desktop)
; to finish loading before applying the theme, preventing race conditions.
After=graphical-session.target xfce4-session.target plasma-workspace.target gnome-session.target
Requires=graphical-session.target
ConditionEnvironment=DISPLAY

[Service]
Type=oneshot
; A short delay to ensure the desktop environment is fully initialized.
ExecStartPre=/bin/sleep 5
ExecStart={python_executable} "{script_path}" run-login-check
StandardError=journal

[Install]
WantedBy=graphical-session.target
"""

_RESUME_SERVICE_TEMPLATE = """\
[Unit]
Description={app_name}: Apply theme after system resume from sleep/suspend
; This service is separate from the login service as it's triggered by a
; different system event (resuming from sleep) via the user-level sleep.target.
After=sleep.target graphical-session.target
Requires=graphical-session.target
ConditionEnvironment=DISPLAY

[Service]
Type=oneshot
; A very short delay for the graphics stack to re-initialize after resume.
ExecStartPre=/bin/sleep 2
ExecStart={python_executable} "{script_path}" run-login-check
StandardError=journal

[Install]
; This is enabled into the user's 'sleep.target.wants', which is activated
; by the system when suspend/resume/hibernate actions occur.
WantedBy=sleep.target
"""

_USER_SLEEP_TARGET_TEMPLATE = """\
[Unit]
Description={app_name} User-Level Sleep Target Anchor
Documentation=man:systemd.special(7)
RefuseManualStart=yes
RefuseManualStop=yes
DefaultDependencies=no

[Install]
"""

_STATIC_UNIT_TEMPLATES = {
    SCHEDULER_TIMER_NAME: _SCHEDULER_TIMER_TEMPLATE,
    SCHEDULER_SERVICE_NAME: _SCHEDULER_SERVICE_TEMPLATE,
    APPLY_TRANSITION_SERVICE_TEMPLATE_NAME: _APPLY_TRANSITION_TEMPLATE,
    LOGIN_SERVICE_NAME: _LOGIN_SERVICE_TEMPLATE,
    RESUME_SERVICE_NAME: _RESUME_SERVICE_TEMPLATE,
    USER_SLEEP_TARGET_NAME: _USER_SLEEP_TARGET_TEMPLATE, # Added template for user sleep.target
}


class SystemdManager:
    """Handles creation, installation, and removal of systemd user units for fluxfce."""

    def __init__(self):
        """Check for systemctl dependency."""
        self.app_name = _APP_NAME
        try:
            helpers.check_dependencies(["systemctl"])
        except DependencyError as e:
            log.error(f"SystemdManager initialization failed: {e}")
            raise SystemdError(f"Cannot initialize SystemdManager: {e}") from e

    def _run_systemctl(
        self, args: list[str], check_errors: bool = True, capture_output: bool = False
    ) -> tuple[int, str, str]:
        """Runs a systemctl --user command."""
        cmd = ["systemctl", "--user", *args]
        try:
            # helpers.run_command captures output if capture_output is True.
            # It handles stripping stdout/stderr.
            code, stdout, stderr = helpers.run_command(cmd, check=False, capture=capture_output)
            if code != 0 and check_errors:
                # Log error only if check_errors is True and command failed.
                # stdout/stderr will be from the captured output if capture_output was True.
                # If not captured, they'll be empty strings from helpers.run_command.
                err_details = stderr.strip() if stderr else stdout.strip() # Prefer stderr for error details
                log.error(
                    f"systemctl --user {' '.join(args)} failed (code {code}). Details: '{err_details}'"
                )
            return code, stdout, stderr # stdout/stderr are already strings
        except FileNotFoundError:
            log.error(f"systemctl command not found when trying to run: systemctl --user {' '.join(args)}")
            raise DependencyError("systemctl command not found.")
        except Exception as e:
            log.exception(f"Unexpected error running systemctl command: systemctl --user {' '.join(args)}")
            raise SystemdError(
                f"Unexpected error running systemctl command 'systemctl --user {' '.join(args)}': {e}"
            ) from e

    def check_user_instance(self) -> bool:
        """
        Checks if the systemd user instance appears to be running and in a usable state.
        Raises SystemdError if the instance is not in a good state.
        """
        log.debug("Checking systemd user instance status...")
        code, stdout, stderr = self._run_systemctl(
            ["is-system-running"], check_errors=False, capture_output=True
        )
        
        status_output = stdout.strip().lower()

        if code == 0: # is-system-running returns 0 for "running", "degraded", etc.
            if status_output == "running":
                log.info(f"Systemd user instance reported: '{status_output}'.")
                return True
            elif status_output == "degraded":
                log.warning(
                    f"Systemd user instance reported: '{status_output}'. "
                    f"{self.app_name} functionality might be limited or unreliable."
                )
                return True # Still allow proceeding but with a stronger warning.
            else:
                # Other states like "stopping", "offline", "initializing", "starting"
                error_msg = (
                    f"Systemd user instance is in an ambiguous state: '{status_output}' (exit code {code}). "
                    f"While not a fatal error state according to 'is-system-running', "
                    f"this state may prevent {self.app_name} from operating correctly. "
                    f"Stderr: '{stderr.strip()}'"
                )
                log.warning(error_msg) 
                return True # Allow proceeding but highlight potential issues.
        else: # Non-zero usually means a more significant issue or "offline"
            error_msg = (
                f"Systemd user instance is not in a usable state "
                f"(command 'is-system-running' exit code: {code}, status: '{status_output}'). "
                f"Stderr: '{stderr.strip()}'. "
                f"{self.app_name} cannot proceed with systemd operations."
            )
            log.error(error_msg)
            raise SystemdError(error_msg)

    def install_units(
        self, script_path: str, python_executable: Optional[str] = None
    ) -> bool:
        """
        Creates and installs the static systemd user units for fluxfce.
        Enables the login, resume, and main scheduler timer services.
        """
        log.info(f"Installing static systemd user units for {self.app_name}...")
        self.check_user_instance()

        py_exe = python_executable or sys.executable
        script_abs_path = str(pathlib.Path(script_path).resolve())

        if not pathlib.Path(py_exe).is_file():
            raise FileNotFoundError(f"Python executable for systemd units not found: {py_exe}")
        if not pathlib.Path(script_abs_path).is_file():
            raise FileNotFoundError(f"Target script for systemd units not found: {script_abs_path}")

        try:
            SYSTEMD_USER_DIR.mkdir(parents=True, exist_ok=True)
            log.debug(f"Ensured systemd user directory exists: {SYSTEMD_USER_DIR}")
        except OSError as e:
            raise SystemdError(
                f"Failed to create systemd user directory {SYSTEMD_USER_DIR}: {e}"
            ) from e

        for unit_name, unit_file_path in STATIC_UNIT_FILES_MAP.items():
            template_content = _STATIC_UNIT_TEMPLATES.get(unit_name)
            if not template_content:
                log.error(f"Internal error: No template found for static unit {unit_name}, skipping.")
                continue
            
            # The user-level sleep.target template does not need these specific format args
            # but format will ignore extra keys.
            formatted_content = template_content.format(
                app_name=self.app_name,
                python_executable=py_exe,
                script_path=script_abs_path,
                scheduler_service_name=SCHEDULER_SERVICE_NAME,
            )
            try:
                unit_file_path.write_text(formatted_content, encoding="utf-8")
                log.info(f"Written systemd unit file: {unit_file_path}")
            except OSError as e:
                raise SystemdError(
                    f"Failed to write systemd unit file {unit_file_path}: {e}"
                ) from e

        reload_code, _, reload_err = self._run_systemctl(["daemon-reload"], capture_output=True)
        if reload_code != 0:
            raise SystemdError(f"systemctl daemon-reload failed: {reload_err.strip()}")
        log.debug("Systemd daemon-reload successful.")

        # Enable essential static units.
        # api.enable_scheduling() will handle --now for SCHEDULER_TIMER_NAME
        # and the setup of dynamic event timers.
        # The user-level sleep.target does not need to be "enabled" itself.
        services_to_enable_on_install = [
            LOGIN_SERVICE_NAME,
            RESUME_SERVICE_NAME,
            SCHEDULER_TIMER_NAME 
        ]
        for service_name in services_to_enable_on_install:
            enable_code, _, enable_err = self._run_systemctl(["enable", service_name], capture_output=True)
            if enable_code != 0:
                # For resume service and sleep.target, a specific warning about non-existent target
                # is now handled by creating the user-level sleep.target.
                # Other enable errors are still critical.
                error_msg = (
                    f"Failed to enable essential systemd unit '{service_name}' during installation. "
                    f"Stderr: '{enable_err.strip()}'. "
                    f"{self.app_name} may not function correctly."
                )
                log.error(error_msg)
                raise SystemdError(error_msg) 
            else:
                log.info(f"Enabled systemd unit: {service_name}")
        
        log.info(f"Static systemd units for {self.app_name} installed and essential services enabled successfully.")
        return True

    def remove_units(self) -> bool:
        """Stops, disables, and removes all static and dynamic fluxfce systemd user units."""
        log.info(f"Removing all {self.app_name} systemd user units...")
        
        units_to_stop_and_disable = [
            SCHEDULER_TIMER_NAME, SCHEDULER_SERVICE_NAME, # Scheduler components
            LOGIN_SERVICE_NAME, RESUME_SERVICE_NAME,      # Login/Resume hooks
            *DYNAMIC_EVENT_TIMER_NAMES,                   # Dynamic sunrise/sunset timers
            # Potentially running instances of the apply transition service
            f"{_APP_NAME}-apply-transition@day.service",
            f"{_APP_NAME}-apply-transition@night.service",
        ]
        
        # Stop units
        for unit_name in units_to_stop_and_disable:
             self._run_systemctl(["stop", unit_name], check_errors=False, capture_output=True)
        log.debug(f"Attempted to stop all potentially running {self.app_name} units/timers.")

        # Disable units that were explicitly enabled (static ones + scheduler timer)
        # Dynamic timers are not "enabled" in the same persistent way.
        # The user-level sleep.target isn't "enabled" either.
        units_to_disable_persistently = [
            SCHEDULER_TIMER_NAME,
            LOGIN_SERVICE_NAME,
            RESUME_SERVICE_NAME
        ]
        for unit_name in units_to_disable_persistently:
            self._run_systemctl(["disable", unit_name], check_errors=False, capture_output=True)
        log.debug(f"Attempted to disable static units: {', '.join(units_to_disable_persistently)}")

        # Remove all files defined in STATIC_UNIT_FILES_MAP (includes user_sleep_target)
        for unit_file_path in STATIC_UNIT_FILES_MAP.values():
            try:
                unit_file_path.unlink(missing_ok=True)
                log.debug(f"Removed unit file: {unit_file_path} (if it existed)")
            except OSError as e:
                log.warning(f"Error removing unit file {unit_file_path}: {e} (continuing)")

        # Remove dynamic timer files
        for dynamic_timer_name in DYNAMIC_EVENT_TIMER_NAMES:
            dynamic_file_path = SYSTEMD_USER_DIR / dynamic_timer_name
            try:
                dynamic_file_path.unlink(missing_ok=True)
                log.debug(f"Removed dynamic timer file: {dynamic_file_path} (if it existed)")
            except OSError as e:
                log.warning(f"Error removing dynamic timer file {dynamic_file_path}: {e} (continuing)")
        
        reload_code, _, reload_err = self._run_systemctl(["daemon-reload"], capture_output=True)
        if reload_code != 0:
            log.warning(f"systemctl daemon-reload failed during unit removal: {reload_err.strip()}. State might be inconsistent.")
        else:
            log.debug("Systemd daemon-reload successful after unit removal.")

        # Use ALL_POTENTIAL_FLUXFCE_UNIT_NAMES for reset-failed
        reset_code, _, reset_err = self._run_systemctl(["reset-failed", *ALL_POTENTIAL_FLUXFCE_UNIT_NAMES], check_errors=False, capture_output=True)
        if reset_code !=0:
            log.debug(f"reset-failed command for some units may have reported issues: {reset_err.strip()}")
        else:
            log.debug(f"Attempted reset-failed for all {self.app_name} units.")
        
        log.info(f"{self.app_name} systemd units removed.")
        return True

    def write_dynamic_event_timer_unit_file(
        self,
        mode: str, 
        utc_execution_time: datetime,
    ) -> bool:
        """
        Creates or overwrites a dynamic event timer file.
        The timer triggers an instance of APPLY_TRANSITION_SERVICE_TEMPLATE_NAME.
        `utc_execution_time` MUST be timezone-aware and set to UTC.
        """
        if mode not in ["day", "night"]:
            log.error(f"Invalid mode '{mode}' specified for dynamic event timer generation.")
            return False # Or raise error

        if utc_execution_time.tzinfo is None or utc_execution_time.tzinfo.utcoffset(utc_execution_time) is None:
            msg = f"utc_execution_time for dynamic timer ({mode}) must be UTC and timezone-aware."
            log.error(msg)
            raise ValueError(msg)

        timer_name = SUNRISE_EVENT_TIMER_NAME if mode == "day" else SUNSET_EVENT_TIMER_NAME
        timer_file_path = SYSTEMD_USER_DIR / timer_name
        
        service_instance_to_trigger = f"{_APP_NAME}-apply-transition@{mode}.service"
        # Systemd OnCalendar expects UTC if the timezone is specified as 'UTC'
        on_calendar_utc_str = utc_execution_time.strftime('%Y-%m-%d %H:%M:%S UTC')

        timer_content = f"""\
[Unit]
Description={self.app_name}: Event Timer for {mode.capitalize()} Transition (Dynamic)
; This timer requires the corresponding apply-transition@mode.service instance
Requires={service_instance_to_trigger}

[Timer]
Unit={service_instance_to_trigger}
OnCalendar={on_calendar_utc_str}
; The login and resume services handle missed transitions, so Persistent=true
; is not needed here and its presence causes a race condition on first run.
AccuracySec=1s
; Don't wake a sleeping system just for this timer
WakeSystem=false

[Install]
; Dynamic timers are not typically "WantedBy" other targets directly.
; They are started/stopped by the application logic (e.g., via fluxfce-scheduler.service)
"""
        try:
            SYSTEMD_USER_DIR.mkdir(parents=True, exist_ok=True) # Ensure dir exists
            timer_file_path.write_text(timer_content, encoding="utf-8")
            log.info(f"Written dynamic timer file: {timer_file_path} for event at {on_calendar_utc_str}")
            return True
        except OSError as e:
            log.error(f"Failed to write dynamic timer file {timer_file_path}: {e}")
            raise SystemdError(f"Failed to write dynamic timer file {timer_file_path}: {e}") from e
        except ValueError as e: # Catch other errors like strftime issues if any
            log.error(f"Error preparing dynamic timer content for {mode}: {e}")
            raise