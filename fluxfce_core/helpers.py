# ~/dev/fluxfce-simplified/fluxfce_core/helpers.py

import logging
import re
import shutil
import subprocess
from typing import List, Tuple, Optional

# Import custom exceptions from within the same package
from .exceptions import DependencyError, ValidationError, FluxFceError

# Setup a logger specific to this module for internal debugging
log = logging.getLogger(__name__)

# --- Command Execution ---

def run_command(
    cmd_list: List[str], check: bool = False, capture: bool = True, input_str: Optional[str] = None
) -> Tuple[int, str, str]:
    """
    Runs an external command and returns its status, stdout, and stderr.

    Args:
        cmd_list: The command and its arguments as a list of strings.
        check: If True, raise CalledProcessError if the command returns non-zero.
               (Note: Generally, we'll use check=False and handle errors based
               on the return code in the calling function for more specific
               exception types).
        capture: If True (default), capture stdout and stderr. If False, they are
                 not captured (sent to system stdout/stderr).
        input_str: Optional string to pass as standard input to the command.

    Returns:
        A tuple containing: (return_code, stdout_str, stderr_str).
        stdout_str and stderr_str will be empty if capture=False.

    Raises:
        FileNotFoundError: If the command executable is not found.
        subprocess.CalledProcessError: If check=True and the command fails.
        Exception: For other unexpected subprocess errors.
    """
    log.debug(f"Running command: {' '.join(cmd_list)}")
    stdin_pipe = subprocess.PIPE if input_str is not None else None
    stdout_pipe = subprocess.PIPE if capture else None
    stderr_pipe = subprocess.PIPE if capture else None

    try:
        process = subprocess.run(
            cmd_list,
            check=check,  # Let CalledProcessError be raised if check is True
            input=input_str,
            stdout=stdout_pipe,
            stderr=stderr_pipe,
            text=True,
            encoding='utf-8'
        )
        stdout = process.stdout.strip() if process.stdout and capture else ""
        stderr = process.stderr.strip() if process.stderr and capture else ""
        log.debug(f"Command '{cmd_list[0]}' finished with code {process.returncode}")
        if stdout and capture: log.debug(f"stdout: {stdout[:200]}...") # Log truncated stdout
        if stderr and capture: log.debug(f"stderr: {stderr[:200]}...") # Log truncated stderr
        return process.returncode, stdout, stderr
    except FileNotFoundError as e:
        # This specific error is often critical and worth propagating
        log.error(f"Command not found: {cmd_list[0]} - {e}")
        raise FileNotFoundError(f"Required command '{cmd_list[0]}' not found in PATH.") from e
    except subprocess.CalledProcessError as e:
        # Log details if check=True caused the exception
        # The caller should handle this if check=True was intentional
        stdout = e.stdout.strip() if e.stdout and capture else ""
        stderr = e.stderr.strip() if e.stderr and capture else ""
        log.warning(f"Command failed with exit code {e.returncode}: {' '.join(cmd_list)}")
        if stdout: log.warning(f"stdout: {stdout[:200]}...")
        if stderr: log.warning(f"stderr: {stderr[:200]}...")
        raise # Re-raise the original exception if check=True
    except Exception as e:
        log.exception(f"An unexpected error occurred running command: {' '.join(cmd_list)} - {e}")
        # Wrap unexpected errors in our base exception type
        raise FluxFceError(f"Unexpected error running command '{cmd_list[0]}': {e}") from e


# --- Dependency Checks ---

def check_dependencies(deps: List[str]) -> bool:
    """
    Checks if required external commands exist in PATH using shutil.which.

    Args:
        deps: A list of command names to check (e.g., ['xfconf-query', 'xsct']).

    Returns:
        True if all dependencies are found.

    Raises:
        DependencyError: If one or more dependencies are not found.
    """
    log.debug(f"Checking for dependencies: {', '.join(deps)}")
    missing = []
    for dep in deps:
        if shutil.which(dep) is None: # shutil.which returns None if not found
            missing.append(dep)

    if missing:
        error_msg = f"Missing required command(s): {', '.join(missing)}. Please install them."
        log.error(error_msg)
        raise DependencyError(error_msg)

    log.debug(f"All dependencies checked successfully: {', '.join(deps)}")
    return True

def check_atd_service() -> bool:
    """
    Checks if the 'atd' service appears to be running via systemctl.

    Returns:
        True if the service is detected as active.

    Raises:
        DependencyError: If 'systemctl' command is not found.
        FluxFceError: For unexpected errors during the check or if the
                      service is confirmed not to be active.
    """
    log.debug("Checking if atd service is active...")
    # Ensure systemctl exists first
    check_dependencies(['systemctl'])

    try:
        # Check system service first
        code_sys, _, err_sys = run_command(['systemctl', 'is-active', '--quiet', 'atd.service'])
        # --quiet: return code 0 for active, non-zero otherwise (usually 3 for inactive)

        if code_sys == 0:
            log.debug("System 'atd' service reported as active.")
            return True

        log.debug(f"System 'atd' not active (code: {code_sys}). Checking user service...")
        # Check user service as fallback (less common for atd)
        code_user, _, err_user = run_command(['systemctl', '--user', 'is-active', '--quiet', 'atd.service'])

        if code_user == 0:
            log.debug("User 'atd' service reported as active.")
            return True

        # If neither is active
        error_msg = "The 'atd' service (system or user) is not active. Automatic scheduling requires 'atd'. Please install and enable it (e.g., 'sudo systemctl enable --now atd')."
        log.error(error_msg)
        # Use FluxFceError as it's a runtime state issue, not a missing binary
        raise FluxFceError(error_msg)

    except FileNotFoundError: # Should be caught by check_dependencies, but belts and suspenders
        raise DependencyError("The 'systemctl' command was not found, cannot check 'atd' status.")
    except Exception as e:
        # Catch potential errors from run_command itself or re-raised CalledProcessError
        log.exception(f"Failed to check 'atd' status: {e}")
        raise FluxFceError(f"Failed to check 'atd' status: {e}") from e


# --- Data Validation ---

def latlon_str_to_float(coord_str: str) -> float:
    """
    Converts Lat/Lon string (e.g., '43.65N', '79.38W') to float degrees.

    Args:
        coord_str: The coordinate string to parse.

    Returns:
        The coordinate as a float value.

    Raises:
        ValidationError: If the format is invalid or the value is out of range.
    """
    if not isinstance(coord_str, str):
        raise ValidationError(f"Invalid input type for coordinate: expected string, got {type(coord_str)}")

    coord_strip = coord_str.strip().upper()
    match = re.match(r'^(\d+(\.\d+)?)([NSEW])$', coord_strip)
    if not match:
        raise ValidationError(f"Invalid coordinate format: '{coord_str}'. Use format like '43.65N' or '79.38W'.")

    try:
        value = float(match.group(1))
    except ValueError:
         # Should not happen with the regex, but safeguard
         raise ValidationError(f"Could not convert value part '{match.group(1)}' to float.")

    direction = match.group(3)
    if direction in ('S', 'W'):
        value = -value

    # Range check
    if direction in ('N', 'S') and not (-90 <= value <= 90):
         raise ValidationError(f"Latitude out of range (-90 to 90): {value} ({coord_str})")
    if direction in ('E', 'W') and not (-180 <= value <= 180):
         raise ValidationError(f"Longitude out of range (-180 to 180): {value} ({coord_str})")

    log.debug(f"Converted coordinate '{coord_str}' to {value}")
    return value

def hex_to_rgba_doubles(hex_color: str) -> List[float]:
    """
    Converts a 6-digit hex color string (#RRGGBB or RRGGBB) to RGBA doubles
    [R, G, B, A] (0.0-1.0), with Alpha always 1.0.

    Args:
        hex_color: The 6-digit hex color string.

    Returns:
        A list of four floats [R, G, B, A] between 0.0 and 1.0.

    Raises:
        ValidationError: If the hex string format is invalid.
    """
    if not isinstance(hex_color, str):
        raise ValidationError(f"Invalid input type for hex color: expected string, got {type(hex_color)}")

    hex_strip = hex_color.lstrip('#')
    if not re.match(r'^[0-9a-fA-F]{6}$', hex_strip):
        raise ValidationError(f"Invalid 6-digit hex color format: '{hex_color}'")

    try:
        r = int(hex_strip[0:2], 16) / 255.0
        g = int(hex_strip[2:4], 16) / 255.0
        b = int(hex_strip[4:6], 16) / 255.0
        rgba = [r, g, b, 1.0] # R, G, B, Alpha
        log.debug(f"Converted hex '{hex_color}' to RGBA {rgba}")
        return rgba
    except ValueError as e:
        # Should not happen with regex, but safeguard
        raise ValidationError(f"Could not convert hex components to integer: '{hex_color}' - {e}") from e

# --- Logging Setup (Simplified for Core Library) ---

def setup_library_logging(level=logging.WARNING):
    """
    Configures basic logging for the fluxfce_core library components.
    This is primarily intended for internal debugging and might be overridden
    by the calling application (GUI/CLI). By default, sets a higher level
    to avoid polluting the output of the consuming application unless
    debugging is explicitly enabled.
    """
    # Configure logging for the entire 'fluxfce_core' package namespace
    package_logger = logging.getLogger('fluxfce_core')

    # Avoid adding multiple handlers if called repeatedly
    if not package_logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        package_logger.addHandler(handler)

    package_logger.setLevel(level)
    log.info(f"fluxfce_core logging configured to level: {logging.getLevelName(level)}")

# Example of how to potentially enable debug logging from outside:
# import logging
# from fluxfce_core import helpers
# helpers.setup_library_logging(level=logging.DEBUG)