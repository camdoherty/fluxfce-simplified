# lightfx_core/exceptions.py
"""
Custom exception classes for the FluxFCE core library.

These exceptions provide more specific error information than built-in
exceptions, allowing for more targeted error handling by callers.
All custom exceptions inherit from the base `FluxFceError`.
"""
class FluxFceError(Exception):
    """Base exception for fluxfce core errors."""

    pass


class ConfigError(FluxFceError):
    """Errors related to configuration loading, saving, or validation."""

    pass


class CalculationError(FluxFceError):
    """Errors during sunrise/sunset calculation."""

    pass


class XfceError(FluxFceError):
    """Errors interacting with xfconf-query or xsct."""

    pass


class SchedulerError(FluxFceError):
    """Errors interacting with atd (at, atq, atrm)."""

    pass


class SystemdError(FluxFceError):
    """Errors interacting with systemctl."""

    pass


class DependencyError(FluxFceError):
    """Errors due to missing external command dependencies."""

    pass


class ValidationError(FluxFceError):
    """Errors for invalid user input or data formats."""

    pass
