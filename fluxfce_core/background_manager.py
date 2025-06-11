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

# --- Default Profile Content ---
DEFAULT_DAY_PROFILE_CONTENT = """
monitor=--span--
type=image
image_path=/home/cad/dev/fluxfce-simplified/fluxfce_core/assets/default-day.png
image_style=span
"""

DEFAULT_NIGHT_PROFILE_CONTENT = """
monitor=--span--
type=image
image_path=/home/cad/dev/fluxfce-simplified/fluxfce_core/assets/default-night.png
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
        if not match: return
        values = [v.strip() for v in match.group(1).split(',')]
        if len(values) != 4: return
        helpers.run_command(["xfconf-query", "-c", "xfce4-desktop", "-p", prop_path, "-r"])
        cmd = ["xfconf-query", "-c", "xfce4-desktop", "-p", prop_path, "-n"]
        for val in values: cmd.extend(["-t", "double", "-s", val])
        helpers.run_command(cmd, check=False)

    def _reset_monitor_props(self, monitor_name: str) -> None:
        log.debug(f" -> Clearing properties for monitor {monitor_name}")
        prop_path = f"/backdrop/screen0/monitor{monitor_name}"
        cmd = ["xfconf-query", "-c", "xfce4-desktop", "-p", prop_path, "-rR"]
        helpers.run_command(cmd)

    # --- Private Helpers for System Info ---
    def _get_connected_monitors(self) -> list[str]:
        _, stdout, _ = helpers.run_command(["xrandr"], capture=True)
        if stdout is None: return []
        return [line.split()[0] for line in stdout.splitlines() if " connected" in line]

    def _get_primary_monitor(self) -> str | None:
        _, stdout, _ = helpers.run_command(["xrandr"], capture=True)
        if stdout is None: return None
        for line in stdout.splitlines():
            if " primary " in line: return line.split()[0]
        monitors = self._get_connected_monitors()
        return monitors[0] if monitors else None

    # --- Public API ---
    def install_default_profiles(self) -> None:
        log.info("Installing default background profiles...")
        primary_monitor = self._get_primary_monitor()
        if not primary_monitor:
            log.warning("Could not determine primary monitor; cannot create default profiles.")
            return
        try:
            day_profile_path = PROFILE_DIR / "default-day.profile"
            day_content = DEFAULT_DAY_PROFILE_CONTENT.format(primary_monitor=primary_monitor)
            day_profile_path.write_text(day_content.strip())
            night_profile_path = PROFILE_DIR / "default-night.profile"
            night_content = DEFAULT_NIGHT_PROFILE_CONTENT.format(primary_monitor=primary_monitor)
            night_profile_path.write_text(night_content.strip())
        except OSError as e:
            raise XfceError(f"Failed to write default profiles: {e}") from e

    def save_current_to_profile(self, profile_name: str) -> None:
        profile_path = PROFILE_DIR / f"{profile_name}.profile"
        log.info(f"Scanning settings to save to profile: '{profile_name}'")
        all_props = self._list_props("/backdrop")
        span_prop = next((p for p in all_props if p.endswith("/image-style") and self._get_prop(p) == "6"), None)
        if span_prop:
            image_path_prop = span_prop.replace("/image-style", "/last-image")
            span_image_path = self._get_prop(image_path_prop)
            if span_image_path:
                content = ["monitor=--span--", "type=image", f"image_path={span_image_path}", "image_style=span"]
                profile_path.write_text("\n".join(content) + "\n")
                log.info(f"Profile saved to {profile_path}")
                return
        profile_blocks = []
        for monitor in self._get_connected_monitors():
            base_path = f"/backdrop/screen0/monitor{monitor}"
            monitor_props = self._list_props(base_path)
            if not monitor_props: continue
            workspaces = sorted(list(set(re.findall(r'(workspace\d+)', " ".join(monitor_props)))))
            for workspace in workspaces:
                ws_path = f"{base_path}/{workspace}"
                rgba1_raw = self._get_prop(f"{ws_path}/rgba1")
                rgba1_str = f"rgba({','.join(rgba1_raw.splitlines())})" if rgba1_raw else None
                rgba2_raw = self._get_prop(f"{ws_path}/rgba2")
                rgba2_str = f"rgba({','.join(rgba2_raw.splitlines())})" if rgba2_raw else None
                settings = {"image_path": self._get_prop(f"{ws_path}/last-image"), "image_style": self._get_prop(f"{ws_path}/image-style"), "color_style": self._get_prop(f"{ws_path}/color-style"), "rgba1": rgba1_str, "rgba2": rgba2_str}
                if not any(v for k, v in settings.items() if k != 'rgba1' and k != 'rgba2'): continue
                block = [f"monitor={monitor}", f"workspace={workspace}"]
                image_style_name = STYLE_IMAGE_MAP.get(int(settings['image_style'] or -1), "none")
                if settings['image_path'] and image_style_name != "none":
                    block.extend(["type=image", f"image_path={settings['image_path']}", f"image_style={image_style_name}"])
                else:
                    color_style_name = STYLE_COLOR_MAP.get(int(settings['color_style'] or 0), "solid")
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
            log.info(f"Profile saved to {profile_path}")

    def load_profile(self, profile_name: str) -> None:
        """Loads a desktop background configuration from a profile file."""
        profile_path = PROFILE_DIR / f"{profile_name}.profile"
        if not profile_path.is_file():
            raise XfceError(f"Background profile '{profile_name}' not found at: {profile_path}")

        # --- START: CORRECTED CODE BLOCK ---
        # The upfront reset loop has been removed to prevent the flash of default wallpaper.
        # We now go directly to applying the new settings.
        log.info(f"Applying background profile '{profile_name}'...")
        # --- END: CORRECTED CODE BLOCK ---

        content = profile_path.read_text()
        settings_map = dict(line.split('=', 1) for line in content.splitlines() if '=' in line)

        if settings_map.get("monitor") == "--span--":
            log.info(f"Applying 'Span screens' profile: {profile_name}")
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
                if not block: continue
                settings = dict(line.split('=', 1) for line in block.splitlines() if '=' in line)
                monitor, workspace = settings.get("monitor"), settings.get("workspace")
                if not monitor or not workspace: continue
                base_path = f"/backdrop/screen0/monitor{monitor}/{workspace}"
                log.debug(f" -> Applying to: {monitor}/{workspace}")
                if settings.get("type") == "image":
                    self._set_prop(f"{base_path}/image-style", "int", IMAGE_STYLE_MAP[settings["image_style"]])
                    self._set_prop(f"{base_path}/last-image", "string", settings["image_path"])
                elif settings.get("type") in ("solid_color", "gradient"):
                    self._set_prop(f"{base_path}/image-style", "int", 0)
                    if settings.get("type") == "solid_color":
                        self._set_prop(f"{base_path}/color-style", "int", COLOR_STYLE_MAP["solid"])
                    else:
                        self._set_prop(f"{base_path}/color-style", "int", COLOR_STYLE_MAP.get(settings.get("gradient_direction"), 2))
                    if "color1" in settings: self._set_rgba_prop(f"{base_path}/rgba1", settings["color1"])
                    if "color2" in settings: self._set_rgba_prop(f"{base_path}/rgba2", settings["color2"])

        log.debug("Reloading desktop...")
        time.sleep(0.2)
        helpers.run_command(["xfdesktop", "--reload"])
        log.info(f"Profile '{profile_name}' applied successfully.")