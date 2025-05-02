# ~/dev/fluxfce-simplified/fluxfce_core/systemd.py

import logging
import pathlib
import sys # To get sys.executable
from typing import List, Tuple, Optional # <--- CORRECTED IMPORT

# Import helpers and exceptions from within the same package
from . import helpers
from .exceptions import SystemdError, DependencyError

log = logging.getLogger(__name__)

# --- Constants ---
# Base application name used in unit names
_APP_NAME = "fluxfce" # Use a private constant to avoid namespace clash if APP_NAME is elsewhere

# Systemd User Directory Path
SYSTEMD_USER_DIR = pathlib.Path.home() / ".config" / "systemd" / "user"

# Systemd Unit Names
LOGIN_SERVICE_NAME = f"{_APP_NAME}-login.service"
SCHEDULER_SERVICE_NAME = f"{_APP_NAME}-scheduler.service"
SCHEDULER_TIMER_NAME = f"{_APP_NAME}-scheduler.timer"

# Systemd Unit File Paths
LOGIN_SERVICE_FILE = SYSTEMD_USER_DIR / LOGIN_SERVICE_NAME
SCHEDULER_SERVICE_FILE = SYSTEMD_USER_DIR / SCHEDULER_SERVICE_NAME
SCHEDULER_TIMER_FILE = SYSTEMD_USER_DIR / SCHEDULER_TIMER_NAME

# List of units managed by this module
MANAGED_UNITS = [SCHEDULER_TIMER_NAME, SCHEDULER_SERVICE_NAME, LOGIN_SERVICE_NAME]
MANAGED_UNIT_FILES = [SCHEDULER_TIMER_FILE, SCHEDULER_SERVICE_FILE, LOGIN_SERVICE_FILE]


# --- Unit File Templates ---

# Service to run the daily scheduler (calls 'schedule-jobs' command)
_SCHEDULER_SERVICE_TEMPLATE = """\
[Unit]
Description={app_name} - Daily Job Scheduler
After=timers.target network-online.target
Wants=network-online.target

[Service]
Type=oneshot
# Execute the command handler responsible for scheduling 'at' jobs
ExecStart={python_executable} "{script_path}" schedule-jobs
# Log stderr to journal
StandardError=journal

[Install]
WantedBy=default.target
"""

# Timer to trigger the daily scheduler service
_SCHEDULER_TIMER_TEMPLATE = """\
[Unit]
Description={app_name} - Trigger daily calculation of sunrise/sunset jobs
Requires={scheduler_service_name}

[Timer]
# Trigger the associated service unit
Unit={scheduler_service_name}
# Run once a day (can be adjusted if needed)
OnCalendar=daily
# Spread load, wait up to 15 min after midnight + 1h tolerance
AccuracySec=1h
RandomizedDelaySec=15min
# Ensure timer activates even if missed due to shutdown
Persistent=true

[Install]
WantedBy=timers.target
"""

# Service to run theme check on login (calls 'run-login-check' command)
_LOGIN_SERVICE_TEMPLATE = """\
[Unit]
Description={app_name} - Apply theme on login
# Run after the main graphical session targets are up
After=graphical-session.target plasma-workspace.target gnome-session.target
Requires=graphical-session.target

[Service]
Type=oneshot
# Add a delay to allow desktop settings services to fully load
ExecStartPre=/bin/sleep 20
# Execute the command handler responsible for checking/applying theme on login
ExecStart={python_executable} "{script_path}" run-login-check
# Log stderr to journal
StandardError=journal

[Install]
# Ensure this service is started as part of the graphical session
WantedBy=graphical-session.target
"""


class SystemdManager:
    """Handles creation, installation, and removal of systemd user units."""

    def __init__(self):
        """Check for systemctl dependency."""
        try:
            helpers.check_dependencies(['systemctl'])
        except DependencyError as e:
            raise SystemdError(f"Cannot initialize SystemdManager: {e}") from e

    def _run_systemctl(self, args: List[str], check_errors: bool = True) -> Tuple[int, str, str]:
        """
        Runs a systemctl --user command.

        Args:
            args: List of arguments to pass after 'systemctl --user'.
            check_errors: If True (default), log an error if the command fails.

        Returns:
            Tuple (return_code, stdout, stderr) from helpers.run_command.

        Raises:
            SystemdError: If run_command encounters unexpected errors.
        """
        cmd = ['systemctl', '--user'] + args
        try:
            code, stdout, stderr = helpers.run_command(cmd, check=False) # Don't use check=True here
            if code != 0 and check_errors:
                # Log specific systemctl failures
                log.error(f"systemctl --user {' '.join(args)} failed (code {code}): {stderr}")
            return code, stdout, stderr
        except FileNotFoundError:
            # Should be caught by __init__, but safeguard
            raise DependencyError("systemctl command not found.")
        except Exception as e:
            # Catch other run_command errors
            log.exception(f"Unexpected error running systemctl command: {e}")
            raise SystemdError(f"Unexpected error running systemctl command: {e}") from e

    def check_user_instance(self) -> bool:
        """
        Checks if the systemd user instance appears active enough.

        Returns:
            True if the instance is running or degraded.

        Raises:
            SystemdError: If the instance is not running or the check fails.
        """
        log.debug("Checking systemd user instance status...")
        # Use 'is-system-running' which gives more nuanced status
        # See: https://www.freedesktop.org/software/systemd/man/systemctl.html#is-system-running
        code, stdout, stderr = self._run_systemctl(['is-system-running'], check_errors=False)

        # Exit code 0 usually means running/operational.
        # Exit code 1 usually means degraded/initializing/stopping.
        # Other codes mean failure.
        if code == 0:
            status = stdout.strip() if stdout.strip() else "running"
            log.info(f"Systemd user instance status: {status}")
            return True
        elif code == 1:
            status = stdout.strip() if stdout.strip() else "degraded/other"
            log.warning(f"Systemd user instance status: {status}. Proceeding cautiously.")
            return True # Accept degraded state for installation purposes
        else:
            status = stdout.strip() if stdout.strip() else "failed/unknown"
            error_msg = f"Systemd user instance is not running or degraded (code: {code}, status: '{status}'). Systemd setup cannot proceed. Stderr: {stderr}"
            log.error(error_msg)
            raise SystemdError(error_msg)

    def install_units(self, script_path: str, python_executable: Optional[str] = None) -> bool:
        """
        Creates and enables the systemd user units for scheduler and login.

        Args:
            script_path: Absolute path to the fluxfce script that handles
                         'schedule-jobs' and 'run-login-check' commands.
            python_executable: Absolute path to the python interpreter to use.
                               Defaults to sys.executable.

        Returns:
            True if all units were written and enabled successfully.

        Raises:
            SystemdError: If writing files fails, systemd commands fail, or
                          user instance is not running.
            FileNotFoundError: If script_path or python_executable is invalid.
        """
        log.info("Installing systemd user units...")
        if not self.check_user_instance():
             # Error already logged by check_user_instance
             # Raising SystemdError to signal failure reason
             raise SystemdError("Systemd user instance check failed. Cannot install units.")

        py_exe = python_executable or sys.executable
        script_abs_path = str(pathlib.Path(script_path).resolve())

        # Validate paths
        if not pathlib.Path(py_exe).is_file():
             raise FileNotFoundError(f"Python executable not found: {py_exe}")
        if not pathlib.Path(script_abs_path).is_file():
             raise FileNotFoundError(f"Target script not found: {script_abs_path}")

        units_content = {
            LOGIN_SERVICE_FILE: _LOGIN_SERVICE_TEMPLATE.format(
                app_name=_APP_NAME,
                python_executable=py_exe,
                script_path=script_abs_path
            ),
            SCHEDULER_SERVICE_FILE: _SCHEDULER_SERVICE_TEMPLATE.format(
                app_name=_APP_NAME,
                python_executable=py_exe,
                script_path=script_abs_path
            ),
            SCHEDULER_TIMER_FILE: _SCHEDULER_TIMER_TEMPLATE.format(
                app_name=_APP_NAME,
                scheduler_service_name=SCHEDULER_SERVICE_NAME,
            ),
        }

        # Create directory
        try:
            SYSTEMD_USER_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise SystemdError(f"Failed to create systemd user directory {SYSTEMD_USER_DIR}: {e}") from e

        # Write unit files
        for file_path, content in units_content.items():
            try:
                file_path.write_text(content, encoding='utf-8')
                log.debug(f"Created systemd unit file: {file_path}")
            except IOError as e:
                raise SystemdError(f"Failed to write systemd unit file {file_path}: {e}") from e

        # Reload daemon, enable timer (which starts service), enable login service
        try:
            code_reload, _, err_reload = self._run_systemctl(['daemon-reload'])
            if code_reload != 0:
                 raise SystemdError(f"systemctl daemon-reload failed: {err_reload}")

            # Enable and start the timer (which pulls in the service)
            # --now ensures the timer starts immediately if enabled
            code_enable_timer, _, err_enable_timer = self._run_systemctl(['enable', '--now', SCHEDULER_TIMER_NAME])
            if code_enable_timer != 0:
                 raise SystemdError(f"Failed to enable/start {SCHEDULER_TIMER_NAME}: {err_enable_timer}")

            # Enable the login service (doesn't start it now, waits for login target)
            code_enable_login, _, err_enable_login = self._run_systemctl(['enable', LOGIN_SERVICE_NAME])
            if code_enable_login != 0:
                 # Log warning but don't necessarily fail install if only login service enable fails?
                 # Or treat as critical? Let's treat as critical for now.
                 raise SystemdError(f"Failed to enable {LOGIN_SERVICE_NAME}: {err_enable_login}")

            log.info("Systemd units installed and enabled successfully.")
            return True

        except Exception as e:
            if isinstance(e, (SystemdError, FileNotFoundError)): raise
            log.exception(f"Unexpected error during systemd unit installation: {e}")
            raise SystemdError(f"Unexpected error during systemd unit installation: {e}") from e

    def remove_units(self) -> bool:
        """
        Stops, disables, and removes the systemd user units managed by fluxfce.

        Returns:
            True if the process completed without critical errors (warnings are possible).
            False if major errors occurred during stop/disable or reload.

        Raises:
            SystemdError: For critical failures in systemctl commands.
        """
        log.info("Removing fluxfce systemd user units...")
        units_exist = any(f.exists() for f in MANAGED_UNIT_FILES)
        overall_success = True

        try:
            # Stop and disable units first. Use check_errors=False to avoid immediate failure.
            log.debug(f"Disabling/stopping {SCHEDULER_TIMER_NAME}...")
            code_stop_timer, _, err_stop_timer = self._run_systemctl(['disable', '--now', SCHEDULER_TIMER_NAME], check_errors=False)
            if code_stop_timer != 0:
                 log.warning(f"Failed to disable/stop {SCHEDULER_TIMER_NAME} (may already be removed): {err_stop_timer}")
                 # Don't mark overall failure for stop/disable if unit might be gone

            log.debug(f"Disabling {LOGIN_SERVICE_NAME}...")
            code_disable_login, _, err_disable_login = self._run_systemctl(['disable', LOGIN_SERVICE_NAME], check_errors=False)
            if code_disable_login != 0:
                 log.warning(f"Failed to disable {LOGIN_SERVICE_NAME} (may already be removed): {err_disable_login}")
                 # Don't mark overall failure

            # Attempt to remove files
            removed_files = False
            for f in MANAGED_UNIT_FILES:
                if f.exists():
                    try:
                        f.unlink()
                        log.info(f"Removed {f}")
                        removed_files = True
                    except OSError as e:
                        log.warning(f"Failed to remove unit file {f}: {e}")
                        # Consider this a non-critical warning

            # Reload daemon if units existed or we removed files
            if removed_files or units_exist:
                log.debug("Reloading systemd user daemon...")
                code_reload, _, err_reload = self._run_systemctl(['daemon-reload'])
                if code_reload != 0:
                     # This is more serious as units might be left in a bad state
                     log.error(f"systemctl daemon-reload failed: {err_reload}")
                     overall_success = False
                     # Raise here? Or just return False? Let's return False.
                else:
                     log.debug("Daemon reloaded.")

                # Reset failed state just in case stop/disable failed earlier
                log.debug("Resetting failed state for managed units...")
                self._run_systemctl(['reset-failed'] + MANAGED_UNITS, check_errors=False)

            log.info(f"Systemd unit removal process finished. Success: {overall_success}")
            return overall_success

        except Exception as e:
            if isinstance(e, SystemdError): raise
            log.exception(f"Unexpected error during systemd unit removal: {e}")
            raise SystemdError(f"Unexpected error during systemd unit removal: {e}") from e

    # Potential future addition: get_unit_status methods
    # def get_unit_status(self, unit_name: str) -> Dict[str, str]:
    #     """ Gets basic status info for a specific user unit. """
    #     # ... implementation using systemctl show / is-active / is-enabled ...
    #     pass