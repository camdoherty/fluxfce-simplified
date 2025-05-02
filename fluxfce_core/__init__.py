# ~/dev/fluxfce-simplified/fluxfce_core/__init__.py

# Make exceptions available directly via fluxfce_core.FluxFceError etc.
from .exceptions import *

# --- Make core constants accessible ---
from .config import CONFIG_DIR
# --- ADD SYSTEMD CONSTANTS ---
from .systemd import SCHEDULER_TIMER_NAME, SCHEDULER_SERVICE_NAME, LOGIN_SERVICE_NAME

# Make public API functions available directly via fluxfce_core.get_status etc.
from .api import (
    install_fluxfce,
    uninstall_fluxfce,
    enable_scheduling,
    disable_scheduling,
    apply_manual_mode,
    set_default_from_current,
    get_status,
    # Internal handlers needed by the CLI/script entry point
    handle_internal_apply,
    handle_schedule_jobs_command,
    handle_run_login_check,
    # Add any other API functions needed
)

# Optionally define __all__ to control wildcard imports and document public interface
__all__ = [
    # Constants
    'CONFIG_DIR',
    'SCHEDULER_TIMER_NAME',     # <--- ADD
    'SCHEDULER_SERVICE_NAME',   # <--- ADD
    'LOGIN_SERVICE_NAME',       # <--- ADD
    # Exceptions
    'FluxFceError', 'ConfigError', 'CalculationError', 'XfceError',
    'SchedulerError', 'SystemdError', 'DependencyError', 'ValidationError',
    # API Functions
    'install_fluxfce', 'uninstall_fluxfce', 'enable_scheduling',
    'disable_scheduling', 'apply_manual_mode', 'set_default_from_current',
    'get_status', 'handle_internal_apply', 'handle_schedule_jobs_command',
    'handle_run_login_check',
]