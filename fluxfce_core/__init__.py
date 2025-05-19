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
    handle_schedule_dynamic_transitions_command, # <--- CORRECTED NAME
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
    # SchedulerError, # No longer needed as scheduler.py is removed
    SystemdError,
    ValidationError,
    XfceError,
)

# --- Make selected helper functions accessible ---
from .helpers import detect_system_timezone

# --- ADD SYSTEMD CONSTANTS ---
from .systemd import (
    LOGIN_SERVICE_NAME,
    RESUME_SERVICE_NAME,
    SCHEDULER_SERVICE_NAME,
    SCHEDULER_TIMER_NAME,
    # Constants for dynamic timer names are not typically exported here,
    # as they are implementation details of the systemd/api interaction.
)

# Optionally define __all__ to control wildcard imports and document public interface
__all__ = [
    # Constants
    "CONFIG_DIR",
    "CONFIG_FILE",
    "LOGIN_SERVICE_NAME",
    "RESUME_SERVICE_NAME",
    "SCHEDULER_SERVICE_NAME",
    "SCHEDULER_TIMER_NAME",
    # Exceptions
    "CalculationError",
    "ConfigError",
    "DependencyError",
    "FluxFceError",
    # "SchedulerError", # Removed
    "SystemdError",
    "ValidationError",
    "XfceError",
    # API Functions
    "apply_manual_mode",
    "disable_scheduling",
    "enable_scheduling",
    "get_current_config",
    "get_status",
    "install_fluxfce",
    "save_configuration",
    "set_default_from_current",
    "uninstall_fluxfce",
    # Internal Handlers (for CLI use)
    "handle_internal_apply",
    "handle_run_login_check",
    "handle_schedule_dynamic_transitions_command", # <--- CORRECTED NAME
    # Helper Functions
    "detect_system_timezone",
]
