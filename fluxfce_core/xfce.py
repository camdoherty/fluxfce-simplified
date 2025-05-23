# ~/dev/fluxfce-simplified/fluxfce_core/xfce.py
"""
XFCE desktop environment interaction for FluxFCE.

This module provides the `XfceHandler` class, which encapsulates all
direct interactions with XFCE settings. This includes getting/setting
GTK themes, desktop background colors/gradients, and screen
temperature/brightness using `xfconf-query` and `xsct` utilities.
"""

import logging
import re
import subprocess
import time
from typing import Any, Optional

# Import helpers and exceptions from within the same package
from . import helpers
from .exceptions import DependencyError, ValidationError, XfceError

log = logging.getLogger(__name__)

# --- XFCE Constants ---
XFCONF_CHANNEL = "xfce4-desktop"
XFCONF_THEME_CHANNEL = "xsettings"
XFCONF_THEME_PROPERTY = "/Net/ThemeName"


class XfceHandler:
    """Handles interactions with XFCE settings via xfconf-query and xsct."""

    def __init__(self):
        """Check for essential dependencies."""
        try:
            helpers.check_dependencies(["xfconf-query", "xsct"])
        except DependencyError as e:
            raise XfceError(f"Cannot initialize XfceHandler: {e}") from e

    def find_desktop_paths(self) -> list[str]:
        """
        Finds relevant XFCE desktop property base paths for background settings.
        These paths usually correspond to specific monitor/workspace combinations.
        Returns a sorted list of potential base property paths.
        """
        log.debug(f"Querying {XFCONF_CHANNEL} for background property paths...")
        cmd = ["xfconf-query", "-c", XFCONF_CHANNEL, "-l"]
        try:
            code, stdout, stderr = helpers.run_command(cmd)
            if code != 0:
                raise XfceError(
                    f"Failed to list xfconf properties in channel {XFCONF_CHANNEL}: {stderr} (code: {code})"
                )

            paths = set()
            # Regex: (any_path_ending_with_workspace_number)/last-image
            prop_pattern_workspace = re.compile(
                r"(/backdrop/screen\d+/[\w.-]+/workspace\d+)/last-image$"
            )
            # Regex: (any_path_ending_with_monitor_name_or_id)/last-image
            prop_pattern_monitor = re.compile(
                r"(/backdrop/screen\d+/[\w.-]+)/last-image$"
            )

            # Prioritize more specific per-workspace paths
            for line in stdout.splitlines():
                match = prop_pattern_workspace.match(line.strip())
                if match:
                    paths.add(match.group(1))
            
            # Add per-monitor paths (these are often the effective ones if single-workspace-mode is true)
            # Or if no workspace-specific paths were found for "last-image"
            for line in stdout.splitlines():
                match = prop_pattern_monitor.match(line.strip())
                if match:
                    # Avoid adding a monitor path if its workspace sub-paths are already included
                    # (e.g., if we have .../monitorX/workspace0, don't also add .../monitorX unless distinct)
                    # This logic is a bit simplified; a more robust check might be needed for complex cases.
                    # For now, we add both and let get_background_settings iterate.
                    paths.add(match.group(1))


            if not paths:
                # Fallback to a common default if absolutely no paths found by pattern
                # This is less likely to be effective but provides a last resort.
                default_paths_to_try = [
                    "/backdrop/screen0/monitor0/workspace0", # Generic workspace
                    "/backdrop/screen0/monitor0"             # Generic monitor
                ]
                for default_path in default_paths_to_try:
                    cmd_check = ["xfconf-query", "-c", XFCONF_CHANNEL, "-p", f"{default_path}/last-image"]
                    # Check if property exists, don't care about value. check=False to handle non-zero for non-existent.
                    code_check, _, _ = helpers.run_command(cmd_check, check=False, capture=True)
                    if code_check == 0: # Property exists
                        log.warning(f"Using fallback default path: {default_path} as it seems to exist.")
                        paths.add(default_path)
                        break # Use the first default path that exists

                if not paths: # Still no paths
                    raise XfceError("Could not find any XFCE background property paths.")

            # Sort for consistent processing order, though XFCE's priority is not based on this sort.
            sorted_paths = sorted(list(paths), key=len, reverse=False) # Try shorter (often more general or primary) paths first
            log.info(f"Found {len(sorted_paths)} potential background paths: {sorted_paths}")
            return sorted_paths

        except Exception as e:
            if isinstance(e, XfceError):
                raise
            log.exception(f"Error finding desktop paths: {e}")
            raise XfceError(f"An unexpected error occurred while finding desktop paths: {e}") from e

    def get_gtk_theme(self) -> str:
        log.debug(f"Getting GTK theme from {XFCONF_THEME_CHANNEL} {XFCONF_THEME_PROPERTY}")
        cmd = ["xfconf-query", "-c", XFCONF_THEME_CHANNEL, "-p", XFCONF_THEME_PROPERTY]
        try:
            code, stdout, stderr = helpers.run_command(cmd)
            if code != 0:
                raise XfceError(f"Failed to query GTK theme: {stderr} (code: {code})") from None
            if not stdout: # Should not happen if code is 0, but good check
                raise XfceError("GTK theme query returned success but empty output.")
            log.info(f"Current GTK theme: {stdout}")
            return stdout
        except Exception as e:
            if isinstance(e, XfceError): raise
            log.exception(f"Error getting GTK theme: {e}")
            raise XfceError(f"An unexpected error occurred while getting GTK theme: {e}") from e

    def set_gtk_theme(self, theme_name: str) -> bool:
        if not theme_name:
            raise ValidationError("Theme name cannot be empty.")
        log.info(f"Setting GTK theme to: {theme_name}")
        cmd = ["xfconf-query", "-c", XFCONF_THEME_CHANNEL, "-p", XFCONF_THEME_PROPERTY, "-s", theme_name]
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

    def get_background_settings(self) -> dict[str, Any]:
        """
        Gets background settings (style, colors) by checking candidate paths.
        It uses the first path found that is configured for 'Color' mode and 
        from which all color data can be successfully read.
        """
        candidate_paths = self.find_desktop_paths()
        if not candidate_paths: # find_desktop_paths should raise if it finds nothing
            raise XfceError("No candidate desktop paths found by find_desktop_paths.")

        log.debug(f"Attempting to get background settings from candidate paths: {candidate_paths}")

        # --- Nested helper functions ---
        def _get_prop_for_path(base_path_arg: str, prop_name: str) -> Optional[str]:
            prop_path = f"{base_path_arg}/{prop_name}"
            cmd = ["xfconf-query", "-c", XFCONF_CHANNEL, "-p", prop_path]
            try:
                code, stdout, stderr = helpers.run_command(cmd, capture=True) # Ensure capture
                if code != 0:
                    if "does not exist" in stderr.lower():
                        log.debug(f"Property {prop_path} does not exist for candidate path.")
                    else:
                        log.warning(f"Could not query {prop_path} for candidate path {base_path_arg}: {stderr} (code: {code})")
                    return None 
                return stdout.strip()
            except Exception as e: # Includes FileNotFoundError if xfconf-query isn't there
                log.warning(f"Unexpected error getting property {prop_path} for {base_path_arg}: {e}")
                return None

        def _parse_rgba_for_path(base_path_arg: str, prop_name: str) -> Optional[list[float]]:
            prop_path = f"{base_path_arg}/{prop_name}"
            cmd = ["xfconf-query", "-c", XFCONF_CHANNEL, "-p", prop_path]
            code, stdout, stderr = helpers.run_command(cmd, capture=True) # Ensure capture
            if code != 0:
                if "does not exist" in stderr.lower():
                    log.debug(f"RGBA property {prop_path} does not exist for candidate path {base_path_arg}.")
                else:
                    log.warning(f"Could not query {prop_name} from {base_path_arg}: {stderr} (code: {code})")
                return None

            float_values = []
            num_pattern = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*$") # Non-capturing group for decimal part
            for line in stdout.splitlines():
                match = num_pattern.match(line)
                if match:
                    try:
                        float_values.append(float(match.group(1)))
                    except ValueError: 
                        log.warning(f"ValueError converting '{match.group(1)}' to float from {prop_path}")
                        continue 
            if len(float_values) == 4:
                log.debug(f"Parsed {prop_name} values from {base_path_arg}: {float_values}")
                return float_values
            else:
                log.warning(f"Could not parse 4 float values for {prop_name} from {base_path_arg} (found {len(float_values)}). Output:\n{stdout}")
                return None

        def _floats_to_hex(rgba_floats: Optional[list[float]]) -> Optional[str]:
            if not rgba_floats or len(rgba_floats) != 4:
                log.debug(f"_floats_to_hex: Invalid input (not a list of 4 floats): {rgba_floats}")
                return None
            try:
                r_f, g_f, b_f = rgba_floats[0], rgba_floats[1], rgba_floats[2] # Alpha (rgba_floats[3]) ignored for hex
                
                r = max(0, min(255, int(r_f * 255 + 0.5)))
                g = max(0, min(255, int(g_f * 255 + 0.5)))
                b = max(0, min(255, int(b_f * 255 + 0.5)))
                
                hex_str = f"{r:02X}{g:02X}{b:02X}"
                log.debug(f"Converted floats {rgba_floats} to hex '{hex_str}'")
                return hex_str
            except (ValueError, TypeError, IndexError) as e:
                log.error(f"Error converting float list {rgba_floats} to hex: {e}")
                return None
        
        # --- Iterate through candidate paths ---
        valid_settings_found = [] # List to store (path, settings_dict)

        for path_to_check in candidate_paths:
            log.debug(f"Checking candidate path for background settings: {path_to_check}")
            
            image_style = _get_prop_for_path(path_to_check, "image-style")
            if image_style != "1": # "1" is for 'Color' mode
                log.debug(f"Path {path_to_check} not in 'Color' mode (image-style: {image_style}). Skipping.")
                continue

            color_style = _get_prop_for_path(path_to_check, "color-style")
            if color_style is None or color_style not in ("0", "1", "2"): # solid, horizontal, vertical
                log.debug(f"Path {path_to_check} has invalid/missing color-style ({color_style}). Skipping.")
                continue

            current_settings_from_path = {"hex1": None, "hex2": None, "dir": None}

            rgba1_floats = _parse_rgba_for_path(path_to_check, "rgba1")
            current_settings_from_path["hex1"] = _floats_to_hex(rgba1_floats)
            if not current_settings_from_path["hex1"]:
                log.warning(f"Failed to parse primary color (rgba1) from path {path_to_check}. Skipping this path.")
                continue 

            if color_style == "0":  # Solid
                current_settings_from_path["dir"] = "s"
                current_settings_from_path["hex2"] = None 
            elif color_style in ("1", "2"):  # Gradient (horizontal or vertical)
                current_settings_from_path["dir"] = "h" if color_style == "1" else "v"
                rgba2_floats = _parse_rgba_for_path(path_to_check, "rgba2")
                current_settings_from_path["hex2"] = _floats_to_hex(rgba2_floats)
                if not current_settings_from_path["hex2"]:
                    log.warning(f"Path {path_to_check} is gradient mode but failed to parse secondary color (rgba2). Skipping this path.")
                    continue
            
            log.info(
                f"Successfully parsed background settings from {path_to_check}: "
                f"Dir={current_settings_from_path['dir']}, Hex1={current_settings_from_path['hex1']}, "
                f"Hex2={current_settings_from_path.get('hex2', 'N/A')}"
            )
            valid_settings_found.append((path_to_check, current_settings_from_path))

        if not valid_settings_found:
            raise XfceError("Could not find any xfconf path actively configured for color background settings among candidates.")

        if len(valid_settings_found) == 1:
            # Only one valid path found, return its settings
            path, settings = valid_settings_found[0]
            log.info(f"Using background settings from the only valid path: {path}")
            return settings

        # Multiple valid paths found, check for discrepancies and prioritize
        # Sort by path length (ascending) to prioritize shorter (often more general or primary) paths when multiple settings are found.
        valid_settings_found.sort(key=lambda item: len(item[0]), reverse=False)

        # Check if all settings are identical
        first_settings = valid_settings_found[0][1]
        all_same = True
        for _, settings in valid_settings_found[1:]:
            if settings != first_settings:
                all_same = False
                break
        
        chosen_path, chosen_settings = valid_settings_found[0] # Default to the shortest path after sorting

        if not all_same:
            log.warning(
                "Multiple XFCE paths have different valid background color settings. "
                "This might indicate a misconfiguration or varied settings across workspaces/monitors."
            )
            # Log all differing settings
            for path, settings in valid_settings_found:
                log.warning(
                    f"  Path: {path}, Settings: Dir={settings['dir']}, "
                    f"Hex1={settings['hex1']}, Hex2={settings.get('hex2', 'N/A')}"
                )
            
            # Check if there are multiple paths with the same minimum length but different settings
            min_len = len(chosen_path)
            ties_with_min_len_and_diff_settings = []
            for path, settings in valid_settings_found:
                if len(path) == min_len and settings != chosen_settings:
                    ties_with_min_len_and_diff_settings.append((path,settings))
            
            if ties_with_min_len_and_diff_settings:
                 log.warning(
                    f"Multiple paths have the same minimum length ({min_len}) but different settings. "
                    f"Arbitrarily choosing settings from path: {chosen_path}"
                 )
        
        log_message = f"Using background settings from path: {chosen_path} (Dir={chosen_settings['dir']}, Hex1={chosen_settings['hex1']}, Hex2={chosen_settings.get('hex2', 'N/A')})"
        if not all_same:
            log_message += " (chosen based on shortest path length among differing configurations)"
        log.info(log_message)
        return chosen_settings


    def set_background(self, hex1: str, hex2: Optional[str], direction: str) -> bool:
        log.info(f"Setting background: Dir={direction}, Hex1={hex1}, Hex2={hex2 or 'N/A'}")
        paths = self.find_desktop_paths()
        if not paths:
            raise XfceError("No desktop paths found by find_desktop_paths to apply background settings.")

        try:
            rgba1_list = helpers.hex_to_rgba_doubles(hex1)
        except ValidationError as e:
            raise ValidationError(f"Invalid format for hex1 '{hex1}': {e}") from e

        rgba2_list = None
        if direction in ("h", "v"):
            if not hex2: # hex2 is required for gradients
                raise ValidationError(f"Gradient direction '{direction}' specified but hex2 is missing.")
            try:
                rgba2_list = helpers.hex_to_rgba_doubles(hex2)
            except ValidationError as e:
                raise ValidationError(f"Invalid format for hex2 '{hex2}': {e}") from e
        elif direction == "s":
            if hex2 is not None and hex2.strip() != "": # Ensure hex2 is effectively None or empty for solid
                log.warning(f"Ignoring hex2='{hex2}' because direction='s' (solid) was specified.")
                # No need to explicitly set rgba2_list to None here, as it's already initialized to None
        else:
            raise ValidationError(f"Invalid background direction: '{direction}'. Must be 's', 'h', or 'v'.")

        image_style_val = "1"  # Color mode
        color_style_val = "0"  # Default to Solid
        if direction == "h": color_style_val = "1"
        elif direction == "v": color_style_val = "2"

        overall_success = True
        for base_path in paths:
            log.debug(f"Applying background settings to XFCE path: {base_path}")
            path_apply_success = True
            
            # Sequence of commands for xfconf-query
            commands_to_run = []
            commands_to_run.append(["xfconf-query", "-c", XFCONF_CHANNEL, "-p", f"{base_path}/image-path", "-n", "-t", "string", "-s", ""])
            commands_to_run.append(["xfconf-query", "-c", XFCONF_CHANNEL, "-p", f"{base_path}/image-style", "-n", "-t", "int", "-s", image_style_val])
            commands_to_run.append(["xfconf-query", "-c", XFCONF_CHANNEL, "-p", f"{base_path}/color-style", "-n", "-t", "int", "-s", color_style_val])
            
            # RGBA1: Reset then Set
            commands_to_run.append(["xfconf-query", "-c", XFCONF_CHANNEL, "-p", f"{base_path}/rgba1", "-r"])
            cmd_rgba1_set = ["xfconf-query", "-c", XFCONF_CHANNEL, "-p", f"{base_path}/rgba1", "-n"]
            for val_comp in rgba1_list: cmd_rgba1_set.extend(["-t", "double", "-s", f"{val_comp:.6f}"])
            commands_to_run.append(cmd_rgba1_set)

            # RGBA2: Reset. If gradient, then Set.
            commands_to_run.append(["xfconf-query", "-c", XFCONF_CHANNEL, "-p", f"{base_path}/rgba2", "-r"])
            if rgba2_list: # Only set rgba2 if it's a gradient and rgba2_list is populated
                cmd_rgba2_set = ["xfconf-query", "-c", XFCONF_CHANNEL, "-p", f"{base_path}/rgba2", "-n"]
                for val_comp in rgba2_list: cmd_rgba2_set.extend(["-t", "double", "-s", f"{val_comp:.6f}"])
                commands_to_run.append(cmd_rgba2_set)
            
            commands_to_run.append(["xfconf-query", "-c", XFCONF_CHANNEL, "-p", f"{base_path}/last-image", "-n", "-t", "string", "-s", ""])

            for cmd in commands_to_run:
                code, _, stderr = helpers.run_command(cmd, check=False, capture=True) # Always capture for this
                if code != 0:
                    is_reset_cmd = "-r" in cmd
                    prop_missing_err = "property" in stderr.lower() and "does not exist" in stderr.lower()
                    if is_reset_cmd and prop_missing_err:
                        log.debug(f"Property {cmd[4]} did not exist for reset (ignoring for path {base_path}): {stderr}")
                    else:
                        log.error(f"Failed command for {base_path}: {' '.join(cmd)} - Code: {code}, Stderr: {stderr}")
                        path_apply_success = False
                        break # Stop processing commands for this path if a critical one fails

            if not path_apply_success:
                overall_success = False # If any path fails, mark overall as potentially problematic
                log.warning(f"Settings failed to apply completely for path: {base_path}. Continuing with other paths.")
        
        self.reload_xfdesktop()

        if not overall_success:
            # If any path failed, this indicates an issue.
            # Depending on strictness, this could still be considered a "success" if primary monitor worked.
            # For now, let's log and return true if at least one path succeeded implicitly (no XfceError raised)
            log.warning("Background settings may not have applied to all detected XFCE paths. Check logs.")
            # Raising an error might be too strict if some paths are irrelevant/stale.
            # The critical part is that the *visually active* path gets set.
        else:
            log.info("Background settings applied successfully to all detected XFCE paths.")
        
        return overall_success


    def get_screen_settings(self) -> dict[str, Any]:
        log.debug("Getting screen settings via xsct")
        cmd = ["xsct"]
        try:
            code, stdout, stderr = helpers.run_command(cmd, capture=True)
            if code != 0:
                if "unknown" in stderr.lower() or "usage:" in stderr.lower() or "failed" in stderr.lower():
                    log.info("xsct appears off or failed to query. Assuming default screen settings (temp/bright will be None).")
                    return {"temperature": None, "brightness": None}
                else:
                    raise XfceError(f"xsct command failed unexpectedly (code {code}): {stderr}")

            temp: Optional[int] = None
            brightness: Optional[float] = None
            combined_match = re.search(r"temperature\s+~\s+(\d+)\s+([\d.]+)", stdout, re.IGNORECASE)
            if combined_match:
                log.debug("xsct output matched combined regex pattern.")
                try:
                    temp = int(combined_match.group(1))
                    brightness = float(combined_match.group(2))
                except (ValueError, IndexError) as e:
                    log.warning(f"Could not parse values from combined xsct regex match: {e}. Output: '{stdout}'")
            
            if temp is None or brightness is None: # Try separate if combined failed or didn't match
                log.debug("Combined regex failed or partial, trying separate regexes for xsct.")
                temp_match = re.search(r"(?:temperature|temp)\s*[:~]?\s*(\d+)K?", stdout, re.IGNORECASE)
                bright_match = re.search(r"(?:brightness|bright)\s*[:~]?\s*([\d.]+)", stdout, re.IGNORECASE)
                if temp_match:
                    try: temp = int(temp_match.group(1))
                    except (ValueError, IndexError): log.warning(f"Could not parse temperature from separate xsct match: '{stdout}'")
                else: log.debug(f"No separate temperature pattern in xsct output: '{stdout}'")
                
                if bright_match:
                    try: brightness = float(bright_match.group(1))
                    except (ValueError, IndexError): log.warning(f"Could not parse brightness from separate xsct match: '{stdout}'")
                else: log.debug(f"No separate brightness pattern in xsct output: '{stdout}'")

            if temp is not None and brightness is not None:
                log.info(f"Retrieved screen settings: Temp={temp}, Brightness={brightness:.2f}")
                return {"temperature": temp, "brightness": brightness}
            else: # If either is still None
                log.info(f"Could not parse both temp/brightness from xsct output. Assuming default. Output: '{stdout}'")
                return {"temperature": None, "brightness": None}

        except XfceError: raise
        except Exception as e:
            log.exception(f"Error getting screen settings: {e}")
            raise XfceError(f"An unexpected error occurred getting screen settings: {e}") from e

    def set_screen_temp(self, temp: Optional[int], brightness: Optional[float]) -> bool:
        if temp is not None and brightness is not None:
            if not (1000 <= temp <= 10000):
                raise ValidationError(f"Temperature value {temp}K is outside typical range (1000-10000).")
            if not (0.1 <= brightness <= 2.0): # Looser check for brightness
                log.warning(f"Brightness value {brightness} is outside a very common range (0.1-1.0), but attempting to set.")
            log.info(f"Setting screen: Temp={temp}, Brightness={brightness:.2f}")
            cmd_args = ["xsct", str(temp), f"{brightness:.2f}"]
        else:
            log.info("Resetting screen temperature/brightness (xsct -x)")
            cmd_args = ["xsct", "-x"]
        try:
            code, _, stderr = helpers.run_command(cmd_args, capture=True)
            if code != 0:
                raise XfceError(f"Failed to set screen via xsct: {stderr} (code: {code})")
            log.debug("Successfully set screen temperature/brightness.")
            return True
        except Exception as e:
            if isinstance(e, (XfceError, ValidationError)): raise
            log.exception(f"Error setting screen temperature/brightness: {e}")
            raise XfceError(f"An unexpected error occurred setting screen temperature/brightness: {e}") from e

    def reload_xfdesktop(self):
        log.debug("Reloading xfdesktop...")
        cmd = ["xfdesktop", "--reload"]
        try:
            helpers.check_dependencies(["xfdesktop"])
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            # Adding a small delay to give xfdesktop a moment to process the reload.
            # This is a heuristic and might not be sufficient in all system load conditions.
            # If issues persist with background not updating, this delay might be a factor.
            time.sleep(0.5) 
            log.debug("xfdesktop --reload command issued and initial delay passed.")
        except DependencyError:
            log.warning("xfdesktop command not found, skipping reload.")
        except Exception as e: # Catch other Popen errors
            log.warning(f"Exception trying to reload xfdesktop: {e}")