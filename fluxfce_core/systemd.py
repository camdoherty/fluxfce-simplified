# ~/dev/fluxfce-simplified/fluxfce_core/systemd.py

import logging
import pathlib
import sys
from typing import List, Optional, Tuple

# Import helpers and exceptions from within the same package
from . import helpers
from .exceptions import DependencyError, SystemdError

log = logging.getLogger(__name__)

# --- Constants ---
_APP_NAME = "fluxfce"
SYSTEMD_USER_DIR = pathlib.Path.home() / ".config" / "systemd" / "user"

# Systemd Unit Names
LOGIN_SERVICE_NAME = f"{_APP_NAME}-login.service"
SCHEDULER_SERVICE_NAME = f"{_APP_NAME}-scheduler.service"
SCHEDULER_TIMER_NAME = f"{_APP_NAME}-scheduler.timer"
RESUME_SERVICE_NAME = f"{_APP_NAME}-resume.service"  # <-- ADDED

# Systemd Unit File Paths
LOGIN_SERVICE_FILE = SYSTEMD_USER_DIR / LOGIN_SERVICE_NAME
SCHEDULER_SERVICE_FILE = SYSTEMD_USER_DIR / SCHEDULER_SERVICE_NAME
SCHEDULER_TIMER_FILE = SYSTEMD_USER_DIR / SCHEDULER_TIMER_NAME
RESUME_SERVICE_FILE = SYSTEMD_USER_DIR / RESUME_SERVICE_NAME  # <-- ADDED

# List of units managed by this module
MANAGED_UNITS = [
    SCHEDULER_TIMER_NAME,
    SCHEDULER_SERVICE_NAME,
    LOGIN_SERVICE_NAME,
    RESUME_SERVICE_NAME,  # <-- ADDED
]
MANAGED_UNIT_FILES = [
    SCHEDULER_TIMER_FILE,
    SCHEDULER_SERVICE_FILE,
    LOGIN_SERVICE_FILE,
    RESUME_SERVICE_FILE,  # <-- ADDED
]


# --- Unit File Templates ---

# (Keep _SCHEDULER_SERVICE_TEMPLATE as is)
_SCHEDULER_SERVICE_TEMPLATE = """\
[Unit]
Description={app_name} - Daily Job Scheduler
After=timers.target
Wants=network-online.target
[Service]
Type=oneshot
ExecStart={python_executable} "{script_path}" schedule-jobs
StandardError=journal
[Install]
WantedBy=default.target
"""

# (Keep _SCHEDULER_TIMER_TEMPLATE as is)
_SCHEDULER_TIMER_TEMPLATE = """\
[Unit]
Description={app_name} - Trigger daily calculation of sunrise/sunset jobs
Requires={scheduler_service_name}
[Timer]
Unit={scheduler_service_name}
OnCalendar=daily
AccuracySec=1h
RandomizedDelaySec=15min
Persistent=true
[Install]
WantedBy=timers.target
"""

# (Keep _LOGIN_SERVICE_TEMPLATE as is)
_LOGIN_SERVICE_TEMPLATE = """\
[Unit]
Description={app_name} - Apply theme on login
After=graphical-session.target plasma-workspace.target gnome-session.target
Requires=graphical-session.target
[Service]
Type=oneshot
ExecStartPre=/bin/sleep 20
ExecStart={python_executable} "{script_path}" run-login-check
StandardError=journal
[Install]
WantedBy=graphical-session.target
"""

# --- ADDED RESUME SERVICE TEMPLATE ---
_RESUME_SERVICE_TEMPLATE = """\
[Unit]
Description={app_name} - Apply theme after system resume
# Ensure this runs after returning from sleep/hibernate
After=sleep.target

[Service]
Type=oneshot
# Add a delay to allow desktop environment to fully resume
ExecStartPre=/bin/sleep 5
ExecStart={python_executable} "{script_path}" run-login-check
StandardError=journal

[Install]
# This service should be started by the sleep target upon resume
WantedBy=sleep.target
"""
# --- END ADDED TEMPLATE ---


class SystemdManager:
    """Handles creation, installation, and removal of systemd user units."""

    def __init__(self):
        """Check for systemctl dependency."""
        try:
            helpers.check_dependencies(["systemctl"])
        except DependencyError as e:
            raise SystemdError(f"Cannot initialize SystemdManager: {e}") from e

    def _run_systemctl(
        self, args: List[str], check_errors: bool = True
    ) -> Tuple[int, str, str]:
        """Runs a systemctl --user command."""
        # This method remains unchanged
        cmd = ["systemctl", "--user"] + args
        try:
            code, stdout, stderr = helpers.run_command(cmd, check=False)
            if code != 0 and check_errors:
                log.error(
                    f"systemctl --user {' '.join(args)} failed (code {code}): {stderr}"
                )
            return code, stdout, stderr
        except FileNotFoundError:
            raise DependencyError("systemctl command not found.")
        except Exception as e:
            log.exception(f"Unexpected error running systemctl command: {e}")
            raise SystemdError(
                f"Unexpected error running systemctl command: {e}"
            ) from e

    def check_user_instance(self) -> bool:
        """Checks if the systemd user instance appears active enough."""
        # This method remains unchanged
        log.debug("Checking systemd user instance status...")
        code, stdout, stderr = self._run_systemctl(
            ["is-system-running"], check_errors=False
        )
        if code == 0:
            status = stdout.strip() if stdout.strip() else "running"
            log.info(f"Systemd user instance status: {status}")
            return True
        elif code == 1:
            status = stdout.strip() if stdout.strip() else "degraded/other"
            log.warning(
                f"Systemd user instance status: {status}. Proceeding cautiously."
            )
            return True
        else:
            status = stdout.strip() if stdout.strip() else "failed/unknown"
            error_msg = f"Systemd user instance is not running or degraded (code: {code}, status: '{status}'). Systemd setup cannot proceed. Stderr: {stderr}"
            log.error(error_msg)
            raise SystemdError(error_msg)

    # --- UPDATED install_units ---
    def install_units(
        self, script_path: str, python_executable: Optional[str] = None
    ) -> bool:
        """
        Creates and enables the systemd user units for scheduler, login, and resume.

        Args:
            script_path: Absolute path to the fluxfce script.
            python_executable: Absolute path to the python interpreter. Defaults to sys.executable.

        Returns: True if all units were written and enabled successfully.
        Raises: SystemdError, FileNotFoundError
        """
        log.info("Installing systemd user units...")
        if not self.check_user_instance():
            raise SystemdError(
                "Systemd user instance check failed. Cannot install units."
            )

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
                script_path=script_abs_path,
            ),
            SCHEDULER_SERVICE_FILE: _SCHEDULER_SERVICE_TEMPLATE.format(
                app_name=_APP_NAME,
                python_executable=py_exe,
                script_path=script_abs_path,
            ),
            SCHEDULER_TIMER_FILE: _SCHEDULER_TIMER_TEMPLATE.format(
                app_name=_APP_NAME,
                scheduler_service_name=SCHEDULER_SERVICE_NAME,
            ),
            # --- ADD RESUME SERVICE CONTENT ---
            RESUME_SERVICE_FILE: _RESUME_SERVICE_TEMPLATE.format(
                app_name=_APP_NAME,
                python_executable=py_exe,
                script_path=script_abs_path,
            ),
            # --- END ADD ---
        }

        # Create directory
        try:
            SYSTEMD_USER_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise SystemdError(
                f"Failed to create systemd user directory {SYSTEMD_USER_DIR}: {e}"
            ) from e

        # Write unit files
        for file_path, content in units_content.items():
            try:
                file_path.write_text(content, encoding="utf-8")
                log.debug(f"Created systemd unit file: {file_path}")
            except OSError as e:
                raise SystemdError(
                    f"Failed to write systemd unit file {file_path}: {e}"
                ) from e

        # Reload daemon, enable units
        try:
            code_reload, _, err_reload = self._run_systemctl(["daemon-reload"])
            if code_reload != 0:
                raise SystemdError(f"systemctl daemon-reload failed: {err_reload}")

            # Enable and start the timer
            code_enable_timer, _, err_enable_timer = self._run_systemctl(
                ["enable", "--now", SCHEDULER_TIMER_NAME]
            )
            if code_enable_timer != 0:
                raise SystemdError(
                    f"Failed to enable/start {SCHEDULER_TIMER_NAME}: {err_enable_timer}"
                )

            # Enable the login service
            code_enable_login, _, err_enable_login = self._run_systemctl(
                ["enable", LOGIN_SERVICE_NAME]
            )
            if code_enable_login != 0:
                raise SystemdError(
                    f"Failed to enable {LOGIN_SERVICE_NAME}: {err_enable_login}"
                )

            # --- ADD ENABLE FOR RESUME SERVICE ---
            code_enable_resume, _, err_enable_resume = self._run_systemctl(
                ["enable", RESUME_SERVICE_NAME]
            )
            if code_enable_resume != 0:
                raise SystemdError(
                    f"Failed to enable {RESUME_SERVICE_NAME}: {err_enable_resume}"
                )
            # --- END ADD ---

            log.info(
                "Systemd units (scheduler, login, resume) installed and enabled successfully."
            )
            return True
        except Exception as e:
            if isinstance(e, (SystemdError, FileNotFoundError)):
                raise
            log.exception(f"Unexpected error during systemd unit enabling: {e}")
            raise SystemdError(
                f"Unexpected error during systemd unit enabling: {e}"
            ) from e

    # --- END UPDATED install_units ---

    # --- UPDATED remove_units ---
    def remove_units(self) -> bool:
        """
        Stops, disables, and removes all managed systemd user units.

        Returns: True if the process completed without critical errors.
        Raises: SystemdError for critical failures.
        """
        log.info("Removing fluxfce systemd user units...")
        # Uses the updated MANAGED_UNIT_FILES and MANAGED_UNITS constants
        units_exist = any(f.exists() for f in MANAGED_UNIT_FILES)
        overall_success = True

        try:
            # Stop and disable units first. Use check_errors=False.
            log.debug(f"Disabling/stopping {SCHEDULER_TIMER_NAME}...")
            code_stop_timer, _, err_stop_timer = self._run_systemctl(
                ["disable", "--now", SCHEDULER_TIMER_NAME], check_errors=False
            )
            if code_stop_timer != 0:
                log.warning(f"Failed to disable/stop {SCHEDULER_TIMER_NAME}...")

            log.debug(f"Disabling {LOGIN_SERVICE_NAME}...")
            code_disable_login, _, err_disable_login = self._run_systemctl(
                ["disable", LOGIN_SERVICE_NAME], check_errors=False
            )
            if code_disable_login != 0:
                log.warning(f"Failed to disable {LOGIN_SERVICE_NAME}...")

            # --- ADD DISABLE FOR RESUME SERVICE ---
            log.debug(f"Disabling {RESUME_SERVICE_NAME}...")
            code_disable_resume, _, err_disable_resume = self._run_systemctl(
                ["disable", RESUME_SERVICE_NAME], check_errors=False
            )
            if code_disable_resume != 0:
                log.warning(f"Failed to disable {RESUME_SERVICE_NAME}...")
            # --- END ADD ---

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

            # Reload daemon if units existed or we removed files
            if removed_files or units_exist:
                log.debug("Reloading systemd user daemon...")
                code_reload, _, err_reload = self._run_systemctl(["daemon-reload"])
                if code_reload != 0:
                    log.error(f"systemctl daemon-reload failed: {err_reload}")
                    overall_success = False
                else:
                    log.debug("Daemon reloaded.")

                # Use the updated MANAGED_UNITS constant
                log.debug("Resetting failed state for managed units...")
                self._run_systemctl(
                    ["reset-failed"] + MANAGED_UNITS, check_errors=False
                )

            log.info(
                f"Systemd unit removal process finished. Success: {overall_success}"
            )
            return overall_success
        except Exception as e:
            if isinstance(e, SystemdError):
                raise
            log.exception(f"Unexpected error during systemd unit removal: {e}")
            raise SystemdError(
                f"Unexpected error during systemd unit removal: {e}"
            ) from e

    # --- END UPDATED remove_units ---
