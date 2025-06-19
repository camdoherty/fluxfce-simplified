# fluxfce_core/background_manager.py
"""
Manages saving and loading of XFCE4 desktop background profiles.

This module is responsible for interacting with the XFCE desktop to get/set
background properties, including multi-monitor and image-based backgrounds.
Its logic is heavily inspired by the xapply.py script.
"""

import logging
import re
import time
from pathlib import Path
from typing import Any

from . import helpers
from .exceptions import XfceError

log = logging.getLogger(__name__)

# --- Configuration ---
PROFILE_DIR = helpers.pathlib.Path.home() / ".config" / "fluxfce" / "backgrounds"

# --- Mappings for XFCE Properties ---
IMAGE_STYLE_MAP = {
    "none": 0, "centered": 1, "tiled": 2, "stretched": 3,
    "scaled": 4, "zoomed": 5, "span": 6
}
COLOR_STYLE_MAP = {"solid": 0, "horizontal": 1, "vertical": 2}

STYLE_IMAGE_MAP = {v: k for k, v in IMAGE_STYLE_MAP.items()}
STYLE_COLOR_MAP = {v: k for k, v in COLOR_STYLE_MAP.items()}

# --- MODIFICATION: Point to system-wide assets location ---
# The package will install assets here.
ASSETS_DIR = Path("/usr/share/fluxfce/assets")
# --- END MODIFICATION ---

DEFAULT_DAY_ASSET = ASSETS_DIR / "default-day.png"
DEFAULT_NIGHT_ASSET = ASSETS_DIR / "default-night.png"

DEFAULT_DAY_PROFILE_CONTENT = f"""
monitor=--span--
type=image
image_path={DEFAULT_DAY_ASSET}
image_style=span
"""

DEFAULT_NIGHT_PROFILE_CONTENT = f"""
monitor=--span--
type=image
image_path={DEFAULT_NIGHT_ASSET}
image_style=span
"""


class BackgroundManager:
    """Handles saving and loading of XFCE background profiles."""

    def __init__(self):
        """Ensures the profile directory exists."""
        try:
            helpers.check_dependencies(["xfconf-query", "xrandr", "xfdesktop"])
            PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        except (helpers.DependencyError, OSError) as e:
            raise XfceError(f"Cannot initialize BackgroundManager: {e}") from e

    # --- Private Helpers for xfconf ---
    def _get_prop(self, prop_path: str) -> str | None:
        cmd = ["xfconf-query", "-c", "xfce4-desktop", "-p", prop_path]
        ret_code, stdout, _ = helpers.run_command(cmd, capture=True)
        return stdout if ret_code == 0 else None

    def _list_props(self, prop_path: str) -> list[str]:
        cmd = ["xfconf-query", "-c", "xfce4-desktop", "-p", prop_path, "-l"]
        ret_code, stdout, _ = helpers.run_command(cmd, capture=True)
        return stdout.splitlines() if ret_code == 0 else []

    def _set_prop(self, prop_path: str, prop_type: str, value: Any) -> None:
        cmd = ["xfconf-query", "-c", "xfce4-desktop", "-p", prop_path, "--create", "-t", prop_type, "-s", str(value)]
        helpers.run_command(cmd)

    def _set_rgba_prop(self, prop_path: str, rgba_string: str) -> None:
        match = re.search(r'rgba\(([\d.,\s]+)\)', rgba_string)
        if not match:
            log.warning(f"Could not parse RGBA string: {rgba_string}")
            return
        
        values = [v.strip() for v in match.group(1).split(',')]
        if len(values) != 4:
            log.warning(f"Invalid number of values in RGBA string: {rgba_string}")
            return

        helpers.run_command(["xfconf-query", "-c", "xfce4-desktop", "-p", prop_path, "-r"], check=False)
        cmd = ["xfconf-query", "-c", "xfce4-desktop", "-p", prop_path, "-n", "-t", "double", "-s", values[0], "-t", "double", "-s", values[1], "-t", "double", "-s", values[2], "-t", "double", "-s", values[3]]
        helpers.run_command(cmd)
        log.debug(f"Set RGBA property '{prop_path}' with values {values}")

    # --- Private Helpers for System Info ---
    def _get_connected_monitors(self) -> list[str]:
        ret_code, stdout, _ = helpers.run_command(["xrandr"], capture=True)
        if ret_code != 0 or not stdout:
            log.warning("Could not run xrandr to get monitor list.")
            return []
        return [line.split()[0] for line in stdout.splitlines() if " connected" in line]

    def _get_primary_monitor(self) -> str | None:
        ret_code, stdout, _ = helpers.run_command(["xrandr"], capture=True)
        if ret_code != 0 or not stdout:
            return None
        for line in stdout.splitlines():
            if " primary " in line:
                return line.split()[0]
        monitors = self._get_connected_monitors()
        return monitors[0] if monitors else None

    # --- Public API ---
    def install_default_profiles(self) -> None:
        log.info("Installing default background profiles...")
        if not DEFAULT_DAY_ASSET.is_file() or not DEFAULT_NIGHT_ASSET.is_file():
            log.error("Default background assets not found. Skipping profile installation.")
            log.error(f"Looked for: {DEFAULT_DAY_ASSET} and {DEFAULT_NIGHT_ASSET}")
            return
            
        try:
            day_profile_path = PROFILE_DIR / "default-day.profile"
            day_profile_path.write_text(DEFAULT_DAY_PROFILE_CONTENT.strip())
            night_profile_path = PROFILE_DIR / "default-night.profile"
            night_profile_path.write_text(DEFAULT_NIGHT_PROFILE_CONTENT.strip())
            log.info(f"Wrote default day profile to {day_profile_path}")
            log.info(f"Wrote default night profile to {night_profile_path}")
        except OSError as e:
            raise XfceError(f"Failed to write default profiles: {e}") from e

    def save_current_to_profile(self, profile_name: str) -> None:
        """Saves the current desktop background state for all monitors to a profile."""
        profile_path = PROFILE_DIR / f"{profile_name}.profile"
        log.info(f"Scanning settings to save to profile: '{profile_name}'")

        # --- START OF BUG FIX ---
        # The flawed special-case logic for span detection has been removed.
        # The code now proceeds directly to the robust, per-monitor loop,
        # which correctly handles all configurations.
        # --- END OF BUG FIX ---

        profile_blocks = []
        for monitor in self._get_connected_monitors():
            base_path = f"/backdrop/screen0/monitor{monitor}"
            monitor_props = self._list_props(base_path)
            if not monitor_props:
                log.debug(f"No backdrop properties found for monitor {monitor}, skipping.")
                continue
            
            workspaces = sorted(list(set(re.findall(r'(workspace\d+)', " ".join(monitor_props)))))
            if not workspaces: workspaces = ['workspace0']

            for workspace in workspaces:
                ws_path = f"{base_path}/{workspace}"
                
                def get_parsed_rgba_string(raw_output: str | None) -> str | None:
                    """Parses xfconf-query output to extract only float values."""
                    if not raw_output:
                        return None
                    
                    values = []
                    for line in raw_output.splitlines():
                        line = line.strip()
                        try:
                            # Attempt to convert to float to validate it's a number
                            float(line)
                            values.append(line)
                        except (ValueError, TypeError):
                            # Ignore non-numeric lines like "Value is an array..." and empty lines
                            continue
                    
                    # Only return a formatted string if we found valid values
                    return f"rgba({','.join(values)})" if values else None

                rgba1_raw = self._get_prop(f"{ws_path}/rgba1")
                rgba1_str = get_parsed_rgba_string(rgba1_raw)
                
                rgba2_raw = self._get_prop(f"{ws_path}/rgba2")
                rgba2_str = get_parsed_rgba_string(rgba2_raw)
                # --- END OF BUG FIX ---

                settings = {
                    "image_path": self._get_prop(f"{ws_path}/last-image"),
                    "image_style": self._get_prop(f"{ws_path}/image-style"),
                    "color_style": self._get_prop(f"{ws_path}/color-style"),
                    "rgba1": rgba1_str,
                    "rgba2": rgba2_str,
                }
                
                if not any(v for k, v in settings.items() if k not in ['rgba1', 'rgba2'] and v is not None):
                    log.debug(f"No meaningful settings for {monitor}/{workspace}, skipping.")
                    continue
                
                block = [f"monitor={monitor}", f"workspace={workspace}"]
                image_style_val = settings.get('image_style')
                image_style_name = STYLE_IMAGE_MAP.get(int(image_style_val) if image_style_val else -1, "none")
                
                if settings.get('image_path') and image_style_name != "none":
                    block.extend(["type=image", f"image_path={settings['image_path']}", f"image_style={image_style_name}"])
                else:
                    color_style_val = settings.get('color_style')
                    color_style_name = STYLE_COLOR_MAP.get(int(color_style_val) if color_style_val else 0, "solid")
                    if color_style_name == "solid":
                        block.append("type=solid_color")
                        if settings['rgba1']: block.append(f"color1={settings['rgba1']}")
                    else:
                        block.extend(["type=gradient", f"gradient_direction={color_style_name}"])
                        if settings['rgba1']: block.append(f"color1={settings['rgba1']}")
                        if settings['rgba2']: block.append(f"color2={settings['rgba2']}")
                
                profile_blocks.append("\n".join(block))

        if profile_blocks:
            profile_path.write_text("\n\n".join(profile_blocks) + "\n")
            log.info(f"Profile saved to {profile_path} with {len(profile_blocks)} configuration block(s).")
        else:
            log.warning(f"No active background settings found to save for profile '{profile_name}'.")

    def load_profile(self, profile_name: str) -> None:
        """Loads a desktop background configuration from a profile file."""
        profile_path = PROFILE_DIR / f"{profile_name}.profile"
        if not profile_path.is_file():
            raise XfceError(f"Background profile '{profile_name}' not found at: {profile_path}")

        log.info(f"Applying background profile '{profile_name}'...")
        content = profile_path.read_text()
        
        if "monitor=--span--" in content:
            log.info(f"Applying 'Span screens' profile: {profile_name}")
            settings_map = dict(line.split('=', 1) for line in content.splitlines() if '=' in line)
            image_path = settings_map.get("image_path")
            primary_monitor = self._get_primary_monitor()
            if not primary_monitor or not image_path:
                raise XfceError("Primary monitor not found or image_path missing in span profile.")
            
            base_path = f"/backdrop/screen0/monitor{primary_monitor}/workspace0"
            self._set_prop(f"{base_path}/image-style", "int", IMAGE_STYLE_MAP["span"])
            self._set_prop(f"{base_path}/last-image", "string", image_path)

            for monitor in self._get_connected_monitors():
                if monitor != primary_monitor:
                    other_base = f"/backdrop/screen0/monitor{monitor}/workspace0"
                    self._set_prop(f"{other_base}/image-style", "int", IMAGE_STYLE_MAP["none"])
        else:
            log.debug(f"Applying per-monitor settings for profile: {profile_name}")
            blocks = re.split(r'\n\s*\n', content.strip())
            for block in blocks:
                if not block.strip(): continue
                settings = dict(line.split('=', 1) for line in block.splitlines() if '=' in line)
                monitor, workspace = settings.get("monitor"), settings.get("workspace")
                if not monitor or not workspace:
                    log.warning(f"Skipping malformed block in profile '{profile_name}': {block}")
                    continue
                
                base_path = f"/backdrop/screen0/monitor{monitor}/{workspace}"
                log.debug(f" -> Applying to: {monitor}/{workspace}")
                
                if settings.get("type") == "image":
                    style_name = settings.get("image_style", "scaled")
                    style_id = IMAGE_STYLE_MAP.get(style_name, 4)
                    self._set_prop(f"{base_path}/image-style", "int", style_id)
                    if "image_path" in settings:
                         self._set_prop(f"{base_path}/last-image", "string", settings["image_path"])

                elif settings.get("type") in ("solid_color", "gradient"):
                    self._set_prop(f"{base_path}/image-style", "int", IMAGE_STYLE_MAP["none"])
                    
                    if settings.get("type") == "solid_color":
                        self._set_prop(f"{base_path}/color-style", "int", COLOR_STYLE_MAP["solid"])
                    else: # gradient
                        direction = settings.get("gradient_direction", "vertical")
                        style_id = COLOR_STYLE_MAP.get(direction, 2)
                        self._set_prop(f"{base_path}/color-style", "int", style_id)

                    if "color1" in settings:
                        self._set_rgba_prop(f"{base_path}/rgba1", settings["color1"])
                    if "color2" in settings:
                        self._set_rgba_prop(f"{base_path}/rgba2", settings["color2"])

        log.debug("Reloading desktop to apply all changes...")
        time.sleep(0.2)
        helpers.run_command(["xfdesktop", "--reload"])
        log.info(f"Profile '{profile_name}' applied successfully.")