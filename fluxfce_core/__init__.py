# fluxfce_core/__init__.py

# Make exceptions available directly
from .exceptions import (
    CalculationError,
    ConfigError,
    DependencyError,
    FluxFceError,
    SystemdError,
    ValidationError,
    XfceError,
)

# Make public API functions (now via the api.py facade) available
from .api import (
    apply_manual_mode,
    apply_temporary_mode,
    disable_scheduling,
    enable_scheduling,
    get_current_config,
    get_status,
    handle_internal_apply, # Called by CLI
    handle_run_login_check,    # Called by CLI
    handle_schedule_dynamic_transitions_command, # Called by CLI
    install_fluxfce,
    save_configuration,
    set_default_from_current,
    uninstall_fluxfce,
)

# --- Make core constants accessible ---
from .config import CONFIG_DIR, CONFIG_FILE, DEFAULT_CONFIG # Added DEFAULT_CONFIG for cli.py
from .helpers import detect_system_timezone # If CLI needs it directly

# --- ADD SYSTEMD CONSTANTS ---
from .systemd import (
    LOGIN_SERVICE_NAME,
    RESUME_SERVICE_NAME,
    SCHEDULER_SERVICE_NAME,
    SCHEDULER_TIMER_NAME,
    SUNRISE_EVENT_TIMER_NAME, # For CLI status output if needed
    SUNSET_EVENT_TIMER_NAME,  # For CLI status output if needed
)

__all__ = [
    # Constants from config.py
    "CONFIG_DIR",
    "CONFIG_FILE",
    "DEFAULT_CONFIG",
    # Constants from systemd.py (ensure these are what CLI's print_status needs)
    "LOGIN_SERVICE_NAME",
    "RESUME_SERVICE_NAME",
    "SCHEDULER_SERVICE_NAME",
    "SCHEDULER_TIMER_NAME",
    "SUNRISE_EVENT_TIMER_NAME", # Make available if CLI uses them
    "SUNSET_EVENT_TIMER_NAME",  # Make available if CLI uses them
    # Exceptions
    "CalculationError",
    "ConfigError",
    "DependencyError",
    "FluxFceError",
    "SystemdError",
    "ValidationError",
    "XfceError",
    # API Functions (from api.py facade)
    "apply_manual_mode",
    "apply_temporary_mode",
    "disable_scheduling",
    "enable_scheduling",
    "get_current_config",
    "get_status",
    "install_fluxfce",
    "save_configuration",
    "set_default_from_current",
    "uninstall_fluxfce",
    # Internal Handlers (available for CLI, routed through api.py)
    "handle_internal_apply",
    "handle_run_login_check",
    "handle_schedule_dynamic_transitions_command",
    # Helper Functions
    "detect_system_timezone",
]