# ~/dev/fluxfce-simplified/fluxfce_core/__init__.py

# Make exceptions available directly via fluxfce_core.FluxFceError etc.
from .exceptions import *

# --- Make core constants accessible ---
from .config import CONFIG_DIR, CONFIG_FILE # <--- ADD CONFIG_FILE
from .systemd import SCHEDULER_TIMER_NAME, SCHEDULER_SERVICE_NAME, LOGIN_SERVICE_NAME

# --- Make selected helper functions accessible ---
from .helpers import detect_system_timezone # <--- ADD THIS LINE

# Make public API functions available directly via fluxfce_core.get_status etc.
from .api import (
    install_fluxfce,
    uninstall_fluxfce,
    enable_scheduling,
    disable_scheduling,
    apply_manual_mode,
    set_default_from_current,
    get_status,
    save_configuration, # <--- ADD THIS (will be created next)
    get_current_config, # <--- ADD THIS (will be created next)
    # Internal handlers needed by the CLI/script entry point
    handle_internal_apply,
    handle_schedule_jobs_command,
    handle_run_login_check,
)

# Optionally define __all__ to control wildcard imports and document public interface
__all__ = [
    # Constants
    'CONFIG_DIR', 'CONFIG_FILE', # <--- ADD CONFIG_FILE
    'SCHEDULER_TIMER_NAME',
    'SCHEDULER_SERVICE_NAME',
    'LOGIN_SERVICE_NAME',
    # Exceptions
    'FluxFceError', 'ConfigError', 'CalculationError', 'XfceError',
    'SchedulerError', 'SystemdError', 'DependencyError', 'ValidationError',
    # Helper Functions
    'detect_system_timezone', # <--- ADD THIS LINE
    # API Functions
    'install_fluxfce', 'uninstall_fluxfce', 'enable_scheduling',
    'disable_scheduling', 'apply_manual_mode', 'set_default_from_current',
    'get_status', 'save_configuration', 'get_current_config', # <--- ADD SAVE/GET CONFIG
    'handle_internal_apply', 'handle_schedule_jobs_command',
    'handle_run_login_check',
]