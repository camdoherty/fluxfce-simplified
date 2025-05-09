# ~/dev/fluxfce-simplified/fluxfce_core/__init__.py

# Make exceptions available directly via fluxfce_core.FluxFceError etc.
# Make public API functions available directly via fluxfce_core.get_status etc.
from .api import (
    apply_manual_mode,
    disable_scheduling,
    enable_scheduling,
    get_current_config,
    get_status,
    # Internal handlers needed by the CLI/script entry point
    handle_internal_apply,
    handle_run_login_check,
    handle_schedule_jobs_command,
    install_fluxfce,
    save_configuration,
    set_default_from_current,
    uninstall_fluxfce,
)

# --- Make core constants accessible ---
from .config import CONFIG_DIR, CONFIG_FILE
from .exceptions import (
    CalculationError,
    ConfigError,
    DependencyError,
    FluxFceError,
    SchedulerError,
    SystemdError,
    ValidationError,
    XfceError,
)

# --- Make selected helper functions accessible ---
from .helpers import detect_system_timezone

# --- ADD SYSTEMD CONSTANTS ---
from .systemd import (  # Import specific names
    LOGIN_SERVICE_NAME,
    RESUME_SERVICE_NAME,  # <--- ADD THIS LINE
    SCHEDULER_SERVICE_NAME,
    SCHEDULER_TIMER_NAME,
)

# Optionally define __all__ to control wildcard imports and document public interface
__all__ = [
    # Constants
    "CONFIG_DIR",
    "CONFIG_FILE",
    "LOGIN_SERVICE_NAME",
    "RESUME_SERVICE_NAME",  # <--- ADD THIS LINE
    "SCHEDULER_SERVICE_NAME",
    "SCHEDULER_TIMER_NAME",
    "CalculationError",
    "ConfigError",
    "DependencyError",
    # Exceptions
    "FluxFceError",
    "SchedulerError",
    "SystemdError",
    "ValidationError",
    "XfceError",
    "apply_manual_mode",
    # Helper Functions
    "detect_system_timezone",
    "disable_scheduling",
    "enable_scheduling",
    "get_current_config",
    "get_status",
    "handle_internal_apply",
    "handle_run_login_check",
    "handle_schedule_jobs_command",
    # API Functions
    "install_fluxfce",
    "save_configuration",
    "set_default_from_current",
    "uninstall_fluxfce",
]
