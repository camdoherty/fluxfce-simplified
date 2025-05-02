# fluxfce_core/exceptions.py
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