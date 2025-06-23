# lightfx_core/__init__.py

# Make exceptions available directly
from .exceptions import (
    CalculationError,
    ConfigError,
    DependencyError,
    LightFXError,
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
    handle_internal_apply,
    handle_run_login_check,
    handle_schedule_dynamic_transitions_command,
    install_default_background_profiles,  # <-- ADDED THIS LINE
    install_lightfx,
    save_configuration,
    set_default_from_current,
    uninstall_lightfx,
)

# --- Make core constants accessible ---
from .config import CONFIG_DIR, CONFIG_FILE, DEFAULT_CONFIG
from .helpers import detect_system_timezone

# --- ADD SYSTEMD CONSTANTS ---
from .systemd import (
    LOGIN_SERVICE_NAME,
    RESUME_SERVICE_NAME,
    SCHEDULER_SERVICE_NAME,
    SCHEDULER_TIMER_NAME,
    SUNRISE_EVENT_TIMER_NAME,
    SUNSET_EVENT_TIMER_NAME,
)

__all__ = [
    # Constants from config.py
    "CONFIG_DIR",
    "CONFIG_FILE",
    "DEFAULT_CONFIG",
    # Constants from systemd.py
    "LOGIN_SERVICE_NAME",
    "RESUME_SERVICE_NAME",
    "SCHEDULER_SERVICE_NAME",
    "SCHEDULER_TIMER_NAME",
    "SUNRISE_EVENT_TIMER_NAME",
    "SUNSET_EVENT_TIMER_NAME",
    # Exceptions
    "CalculationError",
    "ConfigError",
    "DependencyError",
    "LightFXError",
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
    "install_default_background_profiles",  # <-- AND ADDED THIS LINE
    "install_lightfx",
    "save_configuration",
    "set_default_from_current",
    "uninstall_lightfx",
    # Internal Handlers (available for CLI, routed through api.py)
    "handle_internal_apply",
    "handle_run_login_check",
    "handle_schedule_dynamic_transitions_command",
    # Helper Functions
    "detect_system_timezone",
]