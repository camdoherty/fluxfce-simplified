# ~/dev/fluxfce-simplified/fluxfce_core/xfce.py

import logging
import re
import subprocess
import time
from typing import List, Tuple, Optional, Dict, Any

# Import helpers and exceptions from within the same package
from . import helpers
from .exceptions import XfceError, DependencyError, ValidationError

log = logging.getLogger(__name__)

# --- XFCE Constants ---
XFCONF_CHANNEL = "xfce4-desktop"
XFCONF_THEME_CHANNEL = "xsettings"
XFCONF_THEME_PROPERTY = "/Net/ThemeName"


class XfceHandler:
    """Handles interactions with XFCE settings via xfconf-query and xsct."""

    def __init__(self):
        """Check for essential dependencies."""
        # Check dependencies needed by most methods during instantiation
        try:
            helpers.check_dependencies(['xfconf-query', 'xsct'])
            # xfdesktop is checked only when reload is called
        except DependencyError as e:
            # Make dependency issues during init fatal for this handler
            raise XfceError(f"Cannot initialize XfceHandler: {e}") from e

    def find_desktop_paths(self) -> List[str]:
        """
        Finds relevant XFCE desktop property base paths for background settings.

        These paths usually correspond to specific monitor/workspace combinations.

        Returns:
            A sorted list of base property paths (e.g., '/backdrop/screen0/monitorDP-1/workspace0').

        Raises:
            XfceError: If xfconf-query fails or no background paths can be found.
        """
        log.debug(f"Querying {XFCONF_CHANNEL} for background property paths...")
        cmd = ['xfconf-query', '-c', XFCONF_CHANNEL, '-l']
        try:
            code, stdout, stderr = helpers.run_command(cmd)
            if code != 0:
                raise XfceError(f"Failed to list xfconf properties in channel {XFCONF_CHANNEL}: {stderr} (code: {code})")

            paths = set()
            # Prioritize monitor + workspace combo paths
            prop_pattern = re.compile(r'(/backdrop/screen\d+/[\w-]+/workspace\d+)/last-image$')
            for line in stdout.splitlines():
                match = prop_pattern.match(line.strip())
                if match:
                    paths.add(match.group(1))

            # Fallback to monitor level only if no workspace paths found
            if not paths:
                log.debug("No workspace-specific paths found, checking monitor-level paths.")
                monitor_pattern = re.compile(r'(/backdrop/screen\d+/[\w-]+)/last-image$')
                for line in stdout.splitlines():
                     match = monitor_pattern.match(line.strip())
                     # Ensure it's not a parent of an already found workspace path
                     if match and match.group(1) not in [p.rsplit('/', 1)[0] for p in paths if '/' in p]:
                         paths.add(match.group(1))

            if not paths:
                # Last resort default check (less reliable) - adapted from original
                default_path_guess = "/backdrop/screen0/monitorHDMI-0/workspace0" # Example
                cmd_check = ['xfconf-query', '-c', XFCONF_CHANNEL, '-p', f"{default_path_guess}/last-image"]
                code_check, _, _ = helpers.run_command(cmd_check, capture=False) # Don't capture, just check exit code
                if code_check == 0:
                     log.warning(f"Could not detect specific paths, using default guess: {default_path_guess}")
                     paths.add(default_path_guess)
                else:
                     raise XfceError("Could not find any XFCE background property paths (checked workspace, monitor, and default guess).")

            sorted_paths = sorted(list(paths))
            log.info(f"Found {len(sorted_paths)} potential background paths: {sorted_paths}")
            return sorted_paths

        except Exception as e:
            if isinstance(e, XfceError): raise # Re-raise our specific errors
            log.exception(f"Error finding desktop paths: {e}")
            raise XfceError(f"An unexpected error occurred while finding desktop paths: {e}") from e

    def get_gtk_theme(self) -> str:
        """
        Gets the current GTK theme name using xfconf-query.

        Returns:
            The current GTK theme name.

        Raises:
            XfceError: If the xfconf-query command fails.
        """
        log.debug(f"Getting GTK theme from {XFCONF_THEME_CHANNEL} {XFCONF_THEME_PROPERTY}")
        cmd = ['xfconf-query', '-c', XFCONF_THEME_CHANNEL, '-p', XFCONF_THEME_PROPERTY]
        try:
            code, stdout, stderr = helpers.run_command(cmd)
            if code != 0:
                raise XfceError(f"Failed to query GTK theme: {stderr} (code: {code})")
            if not stdout:
                 raise XfceError("GTK theme query returned success code but empty output.")
            log.info(f"Current GTK theme: {stdout}")
            return stdout
        except Exception as e:
             if isinstance(e, XfceError): raise
             log.exception(f"Error getting GTK theme: {e}")
             raise XfceError(f"An unexpected error occurred while getting GTK theme: {e}") from e

    def set_gtk_theme(self, theme_name: str) -> bool:
        """
        Sets the GTK theme using xfconf-query.

        Args:
            theme_name: The name of the theme to set.

        Returns:
            True if the command executes successfully (code 0).

        Raises:
            XfceError: If the xfconf-query command fails (returns non-zero).
            ValidationError: If theme_name is empty.
        """
        if not theme_name:
            raise ValidationError("Theme name cannot be empty.")

        log.info(f"Setting GTK theme to: {theme_name}")
        cmd = ['xfconf-query', '-c', XFCONF_THEME_CHANNEL, '-p', XFCONF_THEME_PROPERTY, '-s', theme_name]
        try:
            code, _, stderr = helpers.run_command(cmd)
            if code != 0:
                raise XfceError(f"Failed to set GTK theme to '{theme_name}': {stderr} (code: {code})")
            log.debug(f"Successfully set GTK theme to '{theme_name}'")
            return True
        except Exception as e:
            if isinstance(e, (XfceError, ValidationError)): raise
            log.exception(f"Error setting GTK theme: {e}")
            raise XfceError(f"An unexpected error occurred while setting GTK theme: {e}") from e

    def get_background_settings(self) -> Dict[str, Any]:
        """
        Gets background settings (style, colors) from the first detected path.

        Returns:
            A dictionary containing:
            {'hex1': str, 'hex2': str|None, 'dir': 's'|'h'|'v'}
            'hex2' is None for solid colors ('s').
            Returns None only if background is not set to 'Color' mode.

        Raises:
            XfceError: If paths cannot be found, essential properties cannot be read,
                       or parsing fails critically.
        """
        paths = self.find_desktop_paths() # Raises XfceError if none found
        base_path = paths[0] # Use the first path for consistency
        log.debug(f"Getting background settings from primary path: {base_path}")

        settings = {'hex1': None, 'hex2': None, 'dir': None}

        def _get_xfconf_prop(prop_name: str) -> Optional[str]:
            """Internal helper to get a single string property value."""
            prop_path = f"{base_path}/{prop_name}"
            cmd = ['xfconf-query', '-c', XFCONF_CHANNEL, '-p', prop_path]
            try:
                code, stdout, stderr = helpers.run_command(cmd)
                if code != 0:
                    # Don't raise if property simply doesn't exist, just return None
                    if "does not exist" in stderr.lower():
                        log.debug(f"Property {prop_path} does not exist.")
                        return None
                    raise XfceError(f"xfconf-query failed for '{prop_path}': {stderr} (code: {code})")
                return stdout.strip()
            except Exception as e:
                if isinstance(e, XfceError): raise
                log.exception(f"Unexpected error getting property {prop_path}: {e}")
                raise XfceError(f"Unexpected error getting property {prop_path}: {e}") from e

        def _parse_rgba_output(prop_name: str) -> Optional[List[float]]:
            """Parses multi-line xfconf-query output for rgba arrays."""
            prop_path = f"{base_path}/{prop_name}"
            cmd = ['xfconf-query', '-c', XFCONF_CHANNEL, '-p', prop_path]
            code, stdout, stderr = helpers.run_command(cmd)
            if code != 0:
                if "does not exist" in stderr.lower():
                    log.warning(f"RGBA property {prop_path} does not exist.")
                    return None
                log.warning(f"Could not query {prop_name} from {base_path}: {stderr} (code: {code})")
                return None # Non-critical if rgba isn't set, maybe

            float_values = []
            # Match lines containing only a float/int number (more robust)
            num_pattern = re.compile(r'^\s*(-?\d+(\.\d+)?)\s*$')
            for line in stdout.splitlines():
                match = num_pattern.match(line)
                if match:
                    try:
                        float_values.append(float(match.group(1)))
                    except ValueError: # Should not happen with regex
                        continue
            if len(float_values) == 4:
                 log.debug(f"Parsed {prop_name} values: {float_values}")
                 return float_values
            else:
                 log.warning(f"Could not parse 4 float values from {prop_name} output ({len(float_values)} found). Output:\n{stdout}")
                 return None

        def _floats_to_hex(rgba_floats: Optional[List[float]]) -> Optional[str]:
             """Converts list of [r,g,b,a] floats (0.0-1.0) to 6-digit Hex."""
             if not rgba_floats or len(rgba_floats) != 4:
                 return None
             try:
                 r = int(rgba_floats[0] * 255 + 0.5)
                 g = int(rgba_floats[1] * 255 + 0.5)
                 b = int(rgba_floats[2] * 255 + 0.5)
                 # Clamp values to 0-255 range
                 r = max(0, min(255, r))
                 g = max(0, min(255, g))
                 b = max(0, min(255, b))
                 hex_str = f"{r:02X}{g:02X}{b:02X}"
                 log.debug(f"Converted floats {rgba_floats} to hex '{hex_str}'")
                 return hex_str
             except (ValueError, TypeError, IndexError) as e:
                 log.error(f"Error converting float list {rgba_floats} to hex: {e}")
                 return None # Conversion error

        # --- Main Logic ---
        try:
            image_style = _get_xfconf_prop("image-style")
            color_style = _get_xfconf_prop("color-style")

            # Check if background is set to 'Color' mode (image-style = 1)
            if image_style != '1':
                 log.info(f"Background image-style is not 'Color' (value: {image_style}). Cannot get color settings.")
                 # Return an empty dict or specific indicator? Let's raise.
                 raise XfceError(f"Background mode is not 'Color' (image-style={image_style}).")

            if color_style is None:
                 raise XfceError(f"Could not retrieve essential 'color-style' property from {base_path}.")

            # Get RGBA1 and convert to Hex1
            rgba1_floats = _parse_rgba_output("rgba1")
            settings['hex1'] = _floats_to_hex(rgba1_floats)
            if not settings['hex1']:
                 raise XfceError("Failed to parse or convert primary background color (rgba1).")

            # Determine direction and get secondary color if needed
            if color_style == '0': # Solid
                settings['dir'] = 's'
                settings['hex2'] = None # Explicitly None
            elif color_style in ('1', '2'): # Horizontal or Vertical gradient
                settings['dir'] = 'h' if color_style == '1' else 'v'
                rgba2_floats = _parse_rgba_output("rgba2")
                settings['hex2'] = _floats_to_hex(rgba2_floats)
                if not settings['hex2']:
                     # Don't fail if secondary fails, just log and set hex2 to None
                     log.warning("Failed to parse or convert secondary gradient color (rgba2). Treating as solid.")
                     settings['hex2'] = None # Fallback, might mismatch 'dir' but safer than error
                     # Or should we try to make hex2 = hex1? Maybe just None is better.
            else:
                raise XfceError(f"Unknown background color-style found: {color_style}")

            log.info(f"Retrieved background: Dir={settings['dir']}, Hex1={settings['hex1']}, Hex2={settings.get('hex2', 'N/A')}")
            return settings

        except Exception as e:
            if isinstance(e, XfceError): raise
            log.exception(f"Error getting background settings: {e}")
            raise XfceError(f"An unexpected error occurred getting background settings: {e}") from e


    def set_background(self, hex1: str, hex2: Optional[str], direction: str) -> bool:
        """
        Sets the background to solid or gradient color across all detected paths.

        Args:
            hex1: The primary hex color string (6 digits).
            hex2: The secondary hex color string (6 digits), or None for solid.
            direction: 's' (solid), 'h' (horizontal), or 'v' (vertical).

        Returns:
            True if settings were applied successfully to all paths.

        Raises:
            XfceError: If paths cannot be found or critical xfconf-query commands fail.
            ValidationError: If hex formats are invalid or inputs are inconsistent
                             (e.g., gradient dir without hex2).
        """
        log.info(f"Setting background: Dir={direction}, Hex1={hex1}, Hex2={hex2}")
        paths = self.find_desktop_paths() # Raises XfceError if none found

        # --- Validate Inputs ---
        try:
            rgba1_list = helpers.hex_to_rgba_doubles(hex1)
        except ValidationError as e:
            raise ValidationError(f"Invalid format for hex1 '{hex1}': {e}") from e

        rgba2_list = None
        if direction in ('h', 'v'):
            if not hex2:
                raise ValidationError("Gradient direction specified but hex2 is missing.")
            try:
                rgba2_list = helpers.hex_to_rgba_doubles(hex2)
            except ValidationError as e:
                raise ValidationError(f"Invalid format for hex2 '{hex2}': {e}") from e
        elif direction == 's':
            if hex2 is not None:
                 log.warning(f"Ignoring hex2='{hex2}' because direction='s' (solid) was specified.")
                 hex2 = None # Ensure hex2 is None internally for solid
        else:
            raise ValidationError(f"Invalid background direction: '{direction}'. Must be 's', 'h', or 'v'.")

        # Determine xfconf style values
        image_style = '1' # Color mode
        if direction == 's': color_style = '0'
        elif direction == 'h': color_style = '1'
        else: color_style = '2' # 'v'

        overall_success = True
        for base_path in paths:
            log.debug(f"Applying background settings to path: {base_path}")
            path_success = True

            try:
                # Set styles using --create (-n) and type (-t)
                style_cmds = [
                    ['xfconf-query', '-c', XFCONF_CHANNEL, '-p', f"{base_path}/image-style", '-n', '-t', 'int', '-s', image_style],
                    ['xfconf-query', '-c', XFCONF_CHANNEL, '-p', f"{base_path}/color-style", '-n', '-t', 'int', '-s', color_style],
                ]
                # Command for rgba1 (always set)
                rgba1_cmd = ['xfconf-query', '-c', XFCONF_CHANNEL, '-p', f"{base_path}/rgba1", '-n']
                for val in rgba1_list: rgba1_cmd.extend(['-t', 'double', '-s', f"{val:.6f}"])

                # Command for rgba2 (set if gradient, reset if solid)
                if rgba2_list:
                    rgba2_cmd = ['xfconf-query', '-c', XFCONF_CHANNEL, '-p', f"{base_path}/rgba2", '-n']
                    for val in rgba2_list: rgba2_cmd.extend(['-t', 'double', '-s', f"{val:.6f}"])
                else:
                    # Reset rgba2 property if switching to solid color
                    rgba2_cmd = ['xfconf-query', '-c', XFCONF_CHANNEL, '-p', f"{base_path}/rgba2", '-r']

                # Command to reset last-image (forces reload of solid/gradient)
                reset_img_cmd = ['xfconf-query', '-c', XFCONF_CHANNEL, '-p', f"{base_path}/last-image", '-n', '-t', 'string', '-s', '']

                # Execute commands for this path
                all_cmds = style_cmds + [rgba1_cmd, rgba2_cmd, reset_img_cmd]
                for cmd in all_cmds:
                    code, _, stderr = helpers.run_command(cmd, check=False) # Don't check, handle code manually
                    if code != 0:
                        # Reset failures (-r or last-image) are often non-fatal warnings
                        is_reset_cmd = '-r' in cmd or '/last-image' in cmd[4]
                        if is_reset_cmd and "does not exist" in stderr.lower():
                             log.debug(f"Ignoring non-existent property reset for {' '.join(cmd)}: {stderr}")
                        elif is_reset_cmd:
                             log.warning(f"Non-critical failure for {base_path}: {' '.join(cmd)} - {stderr}")
                        else:
                             # Critical failure setting style or color
                             log.error(f"Failed command for {base_path}: {' '.join(cmd)} - {stderr}")
                             path_success = False
                             overall_success = False # Mark overall failure
                             # Continue to next command/path? Or break? Let's continue for now.

            except Exception as e:
                 # Catch unexpected errors during command construction/execution for this path
                 log.exception(f"Error applying background settings to path {base_path}: {e}")
                 path_success = False
                 overall_success = False

        # Reload desktop once after trying all paths
        self.reload_xfdesktop()

        if not overall_success:
             # Raise error if any critical command failed for any path
             raise XfceError("Background settings failed for one or more properties/paths. Check logs.")

        log.info("Background settings applied successfully to all detected paths.")
        return True

    def get_screen_settings(self) -> Dict[str, Any]:
        """
        Gets screen temperature and brightness via xsct. Attempts different parsing
        strategies based on common xsct output formats.

        Returns:
            A dictionary {'temperature': int|None, 'brightness': float|None}.
            Returns None for values if xsct is off, fails to report, or output
            cannot be parsed.

        Raises:
            XfceError: If the xsct command fails unexpectedly.
        """
        log.debug("Getting screen settings via xsct")
        cmd = ['xsct']
        try:
            code, stdout, stderr = helpers.run_command(cmd)

            if code != 0:
                # Check if stderr indicates expected "off" states or usage errors
                if "unknown" in stderr.lower() or "usage:" in stderr.lower() or "failed" in stderr.lower():
                     log.info("xsct appears off or failed to query. Assuming default screen settings.")
                     return {'temperature': None, 'brightness': None}
                else:
                     # Unexpected error from xsct
                     raise XfceError(f"xsct command failed unexpectedly (code {code}): {stderr}")

            temp = None
            brightness = None

            # --- Strategy 1: Combined Regex (Handles 'temp ~ TTTT B.BB') ---
            # Match pattern like: Screen #: temperature ~ <temp_digits> <brightness_float>
            combined_match = re.search(r'temperature\s+~\s+(\d+)\s+([\d.]+)', stdout, re.IGNORECASE)
            if combined_match:
                log.debug("xsct output matched combined regex pattern.")
                try:
                    temp = int(combined_match.group(1))
                    brightness = float(combined_match.group(2))
                    log.info(f"Retrieved screen settings (combined): Temp={temp}, Brightness={brightness:.2f}")
                    return {'temperature': temp, 'brightness': brightness}
                except (ValueError, IndexError) as e:
                    log.warning(f"Could not parse values from combined xsct regex match: {e}. Output: '{stdout}'")
                    # Fall through to Strategy 2 if parsing combined match failed

            # --- Strategy 2: Separate Regexes (Handles 'Temp: TTTTK\nBright: B.BB') ---
            if temp is None or brightness is None: # Only proceed if Strategy 1 failed
                 log.debug("Combined regex failed or produced invalid values, trying separate regexes.")
                 temp_match = re.search(r'(?:temperature|temp)\s*[:~]?\s*(\d+)K?', stdout, re.IGNORECASE)
                 bright_match = re.search(r'(?:brightness|bright)\s*[:~]?\s*([\d.]+)', stdout, re.IGNORECASE)

                 if temp_match:
                     try:
                         temp = int(temp_match.group(1))
                     except (ValueError, IndexError):
                         log.warning(f"Could not parse temperature from separate xsct regex match: '{stdout}'")
                 else:
                      log.warning(f"Could not find temperature pattern using separate regex: '{stdout}'")

                 if bright_match:
                     try:
                         brightness = float(bright_match.group(1))
                     except (ValueError, IndexError):
                         log.warning(f"Could not parse brightness from separate xsct regex match: '{stdout}'")
                 else:
                      # This is the warning you were seeing previously
                      log.warning(f"Could not find brightness pattern using separate regex: '{stdout}'")

                 # Return values only if *both* were successfully parsed separately
                 if temp is not None and brightness is not None:
                      log.info(f"Retrieved screen settings (separate): Temp={temp}, Brightness={brightness:.2f}")
                      return {'temperature': temp, 'brightness': brightness}

            # --- Fallback: Parsing failed ---
            log.info(f"Could not parse both temp/brightness from xsct output using known patterns. Assuming default. Output: '{stdout}'")
            return {'temperature': None, 'brightness': None}

        except XfceError:
             raise # Re-raise specific XfceErrors
        except Exception as e:
             log.exception(f"Error getting screen settings: {e}")
             raise XfceError(f"An unexpected error occurred getting screen settings: {e}") from e

    def set_screen_temp(self, temp: Optional[int], brightness: Optional[float]) -> bool:
        """
        Sets screen temperature/brightness using xsct.

        Args:
            temp: Temperature in Kelvin (e.g., 4500), or None to reset.
            brightness: Brightness (e.g., 0.85), or None to reset.
                        If one is None, both are treated as None for reset.

        Returns:
            True if the command executes successfully.

        Raises:
            XfceError: If the xsct command fails.
            ValidationError: If temp/brightness values are unreasonable (basic check).
        """
        if temp is not None and brightness is not None:
            # Basic sanity checks
            if not (1000 <= temp <= 10000):
                 # Raise validation error for clearly bad values
                 raise ValidationError(f"Temperature value {temp}K is outside the typical range (1000-10000).")
            if not (0.1 <= brightness <= 2.0):
                 # Warn for brightness as it's sometimes allowed outside 0-1
                 log.warning(f"Brightness value {brightness} is outside the typical range (0.1-2.0).")
                 # raise ValidationError(f"Brightness value {brightness} is outside the typical range (0.1-2.0).")

            log.info(f"Setting screen: Temp={temp}, Brightness={brightness:.2f}")
            cmd = ['xsct', str(temp), f"{brightness:.2f}"]
        else:
            log.info("Resetting screen temperature/brightness (xsct -x)")
            cmd = ['xsct', '-x']

        try:
            code, _, stderr = helpers.run_command(cmd)
            if code != 0:
                raise XfceError(f"Failed to set screen temperature/brightness via xsct: {stderr} (code: {code})")
            log.debug("Successfully set screen temperature/brightness.")
            return True
        except Exception as e:
            if isinstance(e, (XfceError, ValidationError)): raise
            log.exception(f"Error setting screen temperature/brightness: {e}")
            raise XfceError(f"An unexpected error occurred setting screen temperature/brightness: {e}") from e

    def reload_xfdesktop(self):
        """Reloads the xfdesktop process to apply potential background changes."""
        log.debug("Reloading xfdesktop...")
        cmd = ['xfdesktop', '--reload']
        try:
             # Check if command exists first
             helpers.check_dependencies(['xfdesktop'])
             # Run in background, don't wait, ignore output/errors as it's best-effort
             subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
             time.sleep(0.5) # Brief pause allow process to start
             log.debug("xfdesktop --reload command issued.")
        except DependencyError:
             log.warning("xfdesktop command not found, skipping reload.")
        except Exception as e:
             log.warning(f"Exception trying to reload xfdesktop: {e}")