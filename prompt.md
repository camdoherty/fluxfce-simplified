
**Implement the following targeted code changes into `fluxfce-simplified`. Create a new branch called 'FIX: systemd login / resume logic - June 18th'**
---

### 1. Update `fluxfce_core/systemd.py`

This is the most critical change. We will modify the `resume` service to call a new, dedicated command and remove the unreliable `sleep`. We will also shorten the excessive `sleep` on the `login` service for a better user experience.

```python
# ~/dev/fluxfce-simplified/fluxfce_core/systemd.py

# ... (imports and other constants remain the same) ...

# --- Static Unit Names and File Paths ---
# ... (no changes here) ...
RESUME_SERVICE_NAME = f"{_APP_NAME}-resume.service" # This is what we're targeting

# ... (other constants remain the same) ...

# --- Unit File Templates ---

_LOGIN_SERVICE_TEMPLATE = """\
[Unit]
Description={app_name}: Apply theme on login
After=graphical-session.target xfce4-session.target plasma-workspace.target gnome-session.target
Requires=graphical-session.target
ConditionEnvironment=DISPLAY
[Service]
Type=oneshot
# A 20-second sleep on every login is excessive.
# We reduce this to a much more reasonable 5 seconds.
ExecStartPre=/bin/sleep 5
ExecStart={python_executable} "{script_path}" run-login-check
StandardError=journal
[Install]
WantedBy=graphical-session.target
"""

_RESUME_SERVICE_TEMPLATE = """\
[Unit]
Description={app_name} - Apply theme after system resume
# Ensure we run after the session itself starts trying to resume.
After=sleep.target graphical-session.target xfce4-session.target
Requires=graphical-session.target
ConditionEnvironment=DISPLAY

[Service]
Type=oneshot
# REMOVED: The unreliable ExecStartPre=/bin/sleep 15
# The new command handles waiting intelligently.
ExecStart={python_executable} "{script_path}" run-resume-check
StandardError=journal

[Install]
WantedBy=sleep.target
"""

# ... (the rest of the file, including SystemdManager class, remains the same) ...
```

**Reasoning:**

*   **`_RESUME_SERVICE_TEMPLATE`**:
    *   `After=... xfce4-session.target`: We add this to be explicit that our service should only run after the main XFCE session process has been started by systemd.
    *   `ExecStartPre=/bin/sleep 15`: This line is **removed**. It is the source of the unreliability.
    *   `ExecStart=... run-resume-check`: The service now calls a new, dedicated CLI command. This command will contain the intelligent waiting logic.
*   **`_LOGIN_SERVICE_TEMPLATE`**:
    *   `ExecStartPre=/bin/sleep 5`: Reduced the login delay from 20 seconds to 5. This is a quality-of-life improvement, as a 20s delay on every login is very noticeable. The primary bug fix is in the resume service.

---

### 2. Update `fluxfce_core/desktop_manager.py`

Here we will add the core logic for the new `run-resume-check` command. This function will contain the D-Bus polling loop to wait for the XFCE session.

```python
# fluxfce_core/desktop_manager.py

from __future__ import annotations

import logging
import time # <-- ADD THIS IMPORT
from datetime import datetime
from typing import Literal

from . import config as cfg
from . import helpers, xfce
from .background_manager import BackgroundManager
from .exceptions import FluxFceError, ValidationError

log = logging.getLogger(__name__)

# ... (_cfg_mgr_desktop, _load_cfg, _apply_single_mode, apply_mode, set_defaults_from_current, determine_current_period, handle_internal_apply remain the same) ...


def _wait_for_xfconfd(timeout: int = 45) -> bool:
    """
    Waits for the xfconfd D-Bus service to be available on the session bus.
    This is a reliable signal that the XFCE session is ready for configuration changes.

    Args:
        timeout: Maximum seconds to wait before giving up.

    Returns:
        True if the service becomes available, False if it times out.
    """
    log.info(f"Waiting up to {timeout}s for the XFCE session to become ready...")
    start_time = time.monotonic()
    dbus_cmd = [
        "gdbus", "call", "--session",
        "--dest", "org.xfce.Xfconf",
        "--object-path", "/",
        "--method", "org.freedesktop.DBus.Peer.Ping"
    ]

    while time.monotonic() - start_time < timeout:
        # We don't need to check for errors; a non-zero exit code means the service is not ready.
        code, _, _ = helpers.run_command(dbus_cmd, check_errors=False, capture=True)
        if code == 0:
            log.info("XFCE session is ready (xfconfd responded to ping).")
            # A tiny extra pause for good measure as the final desktop components paint.
            time.sleep(1)
            return True

        log.debug("xfconfd not ready yet, waiting...")
        time.sleep(2)  # Poll every 2 seconds

    log.error(f"Timed out after {timeout} seconds waiting for xfconfd. The desktop may be unstable or failed to resume correctly.")
    return False


def handle_run_login_check() -> bool:
    """Called on login to apply the correct theme for the current time."""
    log.info("DesktopManager: Handling 'run-login-check'...")
    conf = _load_cfg()
    mode_to_apply = determine_current_period(conf)
    log.info(f"Login check determined mode '{mode_to_apply}'. Applying now.")
    return apply_mode(mode_to_apply)


def handle_run_resume_check() -> bool:
    """
    Called on system resume. Waits for the session to be ready, then applies the theme.
    This is the core of the bug fix.
    """
    log.info("DesktopManager: Handling 'run-resume-check'...")
    if _wait_for_xfconfd():
        # The session is ready. Now we can safely run the standard check/apply logic.
        return handle_run_login_check()
    else:
        # The wait timed out, so we do nothing to avoid breaking the session.
        log.warning("Skipping theme application on resume due to timeout.")
        return False
```

**Reasoning:**

*   `_wait_for_xfconfd()`: This new private function implements the robust waiting mechanism. It uses `gdbus` to ping the `org.xfce.Xfconf` service. This is a lightweight, dependency-free (on modern systems) way to verify the session is alive and ready. It will poll for up to 45 seconds before timing out.
*   `handle_run_resume_check()`: This new public function is called by the `resume` systemd service. It orchestrates the process: first, it calls `_wait_for_xfconfd()`. If successful, it then calls the *existing* `handle_run_login_check()` function to perform the theme application, perfectly reusing your existing code.

---

### 3. Update the API and CLI to expose the new command

We need to plumb the new function through the API facade and add it to the command-line parser so `systemd` can call it.

#### `fluxfce_core/api.py`
```python
# fluxfce_core/api.py

# ... (other imports) ...

# ... (other API functions) ...

def handle_run_login_check() -> bool:
    """API Façade: Relays to desktop_manager.handle_run_login_check."""
    log.debug("API Facade: Relaying 'run-login-check' to desktop_manager.")
    return desktop_manager.handle_run_login_check()


def handle_run_resume_check() -> bool:
    """API Façade: Relays to desktop_manager.handle_run_resume_check."""
    log.debug("API Facade: Relaying 'run-resume-check' to desktop_manager.")
    return desktop_manager.handle_run_resume_check()


# --- Status Function ---
# ... (rest of the file is unchanged) ...
```

#### `fluxfce_core/__init__.py`
```python
# fluxfce_core/__init__.py

# ... (other imports) ...

from .api import (
    # ... (all other api functions) ...
    handle_internal_apply,
    handle_run_login_check,
    handle_run_resume_check,  # <-- ADD THIS LINE
    handle_schedule_dynamic_transitions_command,
    # ... (all other api functions) ...
)

# ... (rest of the file) ...
```

#### `fluxfce_cli.py`
```python
# fluxfce_cli.py

# ... (imports and other setup) ...

def main():
    """Parses command-line arguments and dispatches to appropriate command handlers."""
    # ... (parser setup) ...

    # Internal commands, hidden from public help
    parser_internal_apply = subparsers.add_parser("internal-apply", help=argparse.SUPPRESS)
    parser_internal_apply.add_argument("--mode", choices=["day", "night"], required=True, dest="internal_mode")
    subparsers.add_parser("schedule-dynamic-transitions", help=argparse.SUPPRESS)
    subparsers.add_parser("run-login-check", help=argparse.SUPPRESS)
    subparsers.add_parser("run-resume-check", help=argparse.SUPPRESS) # <-- ADD THIS LINE

    args = parser.parse_args()
    setup_cli_logging(args.verbose)
    # ... (try/except block) ...

        # ... (all other elif command blocks) ...

        elif args.command == "run-login-check":
            success = fluxfce_core.handle_run_login_check()
            exit_code = 0 if success else 1

        elif args.command == "run-resume-check": # <-- ADD THIS BLOCK
            success = fluxfce_core.handle_run_resume_check()
            exit_code = 0 if success else 1
            
        else:
            log.error(f"Unknown command: {args.command}")
    # ... (rest of the file) ...

if __name__ == "__main__":
    main()
```

### Summary of Actions

1.  **Modify the Systemd Unit:** Replaced the unreliable `sleep` in the resume service with a call to a new, dedicated command.
2.  **Implement the Wait Logic:** Created a new function in `desktop_manager.py` that actively waits for the XFCE session's D-Bus service to be ready before proceeding.
3.  **Reuse Existing Code:** Once the session is confirmed to be ready, the new function calls the existing theme-application logic, minimizing new code and risk.
4.  **Plumb the New Command:** Exposed the new function through the API and CLI layers so that the updated systemd unit can call it.

After implementing these changes, you will need to run `fluxfce install` again to write the updated systemd unit files to your system. This will make your application significantly more robust and eliminate the black screen issue on resume.





------


**Your role:**
You are a veteran Python programmer and Linux (XFCE) developer. You possess all skills and knowledge necessary to assist with development and debugging the included `fluxfce` Python project.

**Pre-work:**
Thoroughly analyze the `fluxfce` code base included as a single text file `codebase-2025-06-17.txt`.

You should have a complete understanding of how `fluxfce` functions and it's indended goals. 

**Issue:**
Currently, whenever `fluxfce` applies a theme, the theme is only partially applied. To fully apply a theme from the command line, including the title bars and borders, you must also set the corresponding theme for the window manager. This is done by using a separate xfconf-query command that targets the xfwm4 channel.

`fluxfce` currently sends a command like: `xfconf-query -c xsettings -p /Net/ThemeName -s "Materia-dark-compact"` to apply a theme.

Any time `fluxfce` applies a theme it needs to update both the the application and window decoration themes. Something like:
`xfconf-query -c xsettings -p /Net/ThemeName -s "Materia-dark-compact"`, AND,
`xfconf-query -c xfwm4 -p /general/theme -s "Materia-dark-compact"`

**Task:**

When you are confident that you fully understand the project and, the issue and how to fix it, proceed to update all necessary code to resolve the issue.

Provide complete functions or methods, etc, so I can easily copy/paste the code to implement.

Double check all code for correctness.





, the theme is applied but the title bar and borders of windows don't update with the theme's colors. Ie the theme, "Materia-dark-compact" has a dark title bars and borders but when I run that command the title bar and borders don't change at all. If I open `xfce4-settings` and click "Materia-dark-compact" theme in the GUI, the title bar and borders then apply correctly.

What causes this behavior and what is the command to fully apply a theme from cli?
xfconf-query -c xsettings -p /Net/ThemeName -s "Materia-dark-compact"
xfconf-query -c xfwm4 -p /general/theme -s "Materia-dark-compact"






Focus on the code related to systemd and scheduling. The scheduler service that runs shortly after midnight schedules the dynamic timers for upcoming sunrise/sunset events, but **when the scheduler service ran between 12:10 AM and 12:13 AM, 'Day Mode' was partially applied (xsct temperature and desktop background changed but Gtk theme did not.)


**Task:**
Review all relevant code and diagnose the issue.



When generating code, provide complete functions or methods, etc, or complete scripts if substantial changes are required.






Assist with debugging the following issue:



Example config files for reference:

```
~ ❯ cat ~/.config/fluxfce/config.ini
[Location]
latitude = 43.65N
longitude = 79.38W
timezone = America/Toronto

[Appearance]
light_theme = Arc-Lighter
dark_theme = Materia-dark-compact
day_background_profile = default-day
night_background_profile = default-night

[ScreenDay]
xsct_temp = 6500
xsct_bright = 1.00

[ScreenNight]
xsct_temp = 5000
xsct_bright = 1.00


~ ❯ cat ~/.config/fluxfce/backgrounds/default-day.profile
monitor=HDMI-0
workspace=workspace0
type=gradient
gradient_direction=vertical
color1=rgba(0.870588,0.866667,0.854902,1.000000)
color2=rgba(0.000000,0.000000,0.000000,1.000000)

monitor=DP-0
workspace=workspace0
type=gradient
gradient_direction=vertical
color1=rgba(0.870588,0.866667,0.854902,1.000000)
color2=rgba(0.000000,0.000000,0.000000,1.000000)

monitor=DP-2
workspace=workspace0
type=image
image_path=/home/cad/Pictures/purpAbstract-4k-wide-cropped.jpg
image_style=span
```

---


**Your role:**
You are a veteran Python programmer and Linux (XFCE) developer. You possess all skills and knowledge necessary to assist with debugging and development of the `fluxfce` python project.

**Task:**
Thoroughly analyze the `fluxfce` code base and the three config files below. The code base is attached as a single text file, `codebase-2025-06-14.txt`. The config files are 'built' during install (`fluxfce install`)

You should have a complete understanding of how `fluxfce` works. 

Assist with debugging the following issue:


**Issue:**
Currently, if a day or night desktop background profile is saved with background color(s), eg:

```
cat ~/.config/fluxfce/backgrounds/default-day.profile
monitor=HDMI-0
workspace=workspace0
type=solid_color
color1=rgba(Value is an array with 4 items:,,1.000000,1.000000,1.000000,1.000000)

monitor=DP-0
workspace=workspace0
type=solid_color
color1=rgba(Value is an array with 4 items:,,1.000000,1.000000,1.000000,1.000000)

monitor=DP-2
workspace=workspace0
type=solid_color
color1=rgba(Value is an array with 4 items:,,1.000000,1.000000,1.000000,1.000000)

```

When I try to apply that profile with the `Apply Now` button, I get:

```
INFO: fluxfce_core.api: API Facade: Applying temporary mode 'day' (scheduling remains active)...
INFO: fluxfce_core.desktop_manager: Applying day mode appearance...
INFO: fluxfce_core.xfce: Setting GTK theme to: Adwaita
INFO: fluxfce_core.background_manager: Applying background profile 'default-day'...
WARNING: fluxfce_core.background_manager: Could not parse RGBA string: rgba(Value is an array with 4 items:,,1.000000,1.000000,1.000000,1.000000)
WARNING: fluxfce_core.background_manager: Could not parse RGBA string: rgba(Value is an array with 4 items:,,1.000000,1.000000,1.000000,1.000000)
WARNING: fluxfce_core.background_manager: Could not parse RGBA string: rgba(Value is an array with 4 items:,,1.000000,1.000000,1.000000,1.000000)
INFO: fluxfce_core.background_manager: Profile 'default-day' applied successfully.
```

I suspect this is related to the way the `Apply Now` logic parses the saved profile file.


Review the relevant code and propose a solution.












 - config.ini: installed to `~/.config/fluxfce/config.ini` 
```
[Location]
latitude = 43.65N
longitude = 79.38W
timezone = America/Toronto

[Appearance]
light_theme = Adwaita
dark_theme = Adwaita-dark
day_background_profile = default-day
night_background_profile = default-night

[ScreenDay]
xsct_temp = 6500
xsct_bright = 1.0

[ScreenNight]
xsct_temp = 4500
xsct_bright = 0.85
```

 - default-day.profile: installed to, `~/.config/fluxfce/backgrounds/default-day.profile` # see note bellow 
```
monitor=--span--
type=image
image_path=/home/cad/dev/fluxfce-simplified/fluxfce_core/assets/default-day.png
image_style=span%
```

 - default-night.profile: installed to, `~/.config/fluxfce/backgrounds/default-night.profile` # see note bellow 
```
monitor=--span--
type=image
image_path=/home/cad/dev/fluxfce-simplified/fluxfce_core/assets/default-night.png
image_style=span%
```

**Task 2:**

Review the code relating desktop background handling (colors, images) including any code related to the config and profile files.

The current default-day.profile/default-night.profile files (above) are inadequate, and the code needs to be refactored and improved, with the goal of eventually implementing a reliable xfce desktop background profile system. For now let's get it working with the default-day.profile default-night.profile

See the below command/output:
```
xfconf-query -c xfce4-desktop -l -v
/backdrop/screen0/monitorDP-0/workspace0/color-style     0
/backdrop/screen0/monitorDP-0/workspace0/image-style     0
/backdrop/screen0/monitorDP-0/workspace0/last-image      /usr/share/backgrounds/xfce/xfce-shapes.svg
/backdrop/screen0/monitorDP-0/workspace0/rgba1           <<UNSUPPORTED>>
/backdrop/screen0/monitorDP-0/workspace0/rgba2           <<UNSUPPORTED>>
/backdrop/screen0/monitorDP-2/workspace0/color-style     0
/backdrop/screen0/monitorDP-2/workspace0/image-style     0
/backdrop/screen0/monitorDP-2/workspace0/last-image      /home/cad/dev/fluxfce-simplified/fluxfce_core/assets/default-night.png
/backdrop/screen0/monitorDP-2/workspace0/rgba1           <<UNSUPPORTED>>
/backdrop/screen0/monitorDP-2/workspace0/rgba2           <<UNSUPPORTED>>
```
This command shows the properties for each monitor and workspace which can have several properties. The default-day.profile/default-night.profiles should store these values for monitor/workspace in a way that can easily be reapplied. Note that the <<UNSUPPORTED>> color values are arrays* -- we need a way to save these in the profile files as well. Below are examples of commands that reveal back ground color arrays:


Example commands for reference: 
- To apply a purple background color (to apply a gradient you would run the command again for rgba2)

```
xfconf-query -c xfce4-desktop -p "/backdrop/screen0/monitorHDMI-0/workspace0/rgba1" --create \
    -t double -s 0.380392 \
    -t double -s 0.207843 \
    -t double -s 0.513725 \
    -t double -s 1.000000
```

- To retreive background color(s) (this is a gradient)
```
 ❯ xfconf-query -c xfce4-desktop -p /backdrop/screen0/monitorDP-2/workspace0/rgba1
Value is an array with 4 items:

0.380392
0.207843
0.513725
1.000000

~ ❯ xfconf-query -c xfce4-desktop -p /backdrop/screen0/monitorDP-2/workspace0/rgba2
Value is an array with 4 items:

0.000000
0.000000
0.000000
1.000000
```


**(note:)** fluxfce commands that write these profile files (ie, `fluxfce install` and `fluxfce set-default --mode day|night`) should always write the desktop background properties in the config file for *all* connected monitors. Example (very rough):

```
monitor/workspace /backdrop/screen0/monitorDP-2
color-style     0
image-style     0
last-image      /home/cad/dev/fluxfce-simplified/fluxfce_core/assets/default-night.png
rgba1           <easily parsable array>
rgba2           <easily parsable array>


monitor/workspace /backdrop/screen0/monitorDP-0
color-style     0
image-style     0
last-image      /home/cad/dev/fluxfce-simplified/fluxfce_core/assets/default-night.png
rgba1           <array>
rgba2           <array>

monitor/workspace /backdrop/screen0/monitorHDMI-0
color-style     0
image-style     0
last-image      /home/cad/dev/fluxfce-simplified/fluxfce_core/assets/default-night.png
rgba1           <easily parsable array>
rgba2           <easily parsable array>
```

---

Review the prompt above and rewrite it 

 of the best way to structure the.profile files and apply the the xfce desktop background configurations reliably regardless of background configurations.




when the primary monitor has an image spanned and, and when applying settings, the primary monitor should be applied first.


 of the best way to structure the.profile files and apply the the xfce desktop background configurations reliably regardless of background configurations.








Apply to all workspaces




Focus on the install logic (fluxfce install).
The goal is to make the install process interactive and user friendly while retaining or improving functionality.

Notice how config.ini is installed to ~/.config/fluxfce/config.ini

default config.ini:


```
Example command to apply a purple color
xfconf-query -c xfce4-desktop -p "/backdrop/screen0/monitorHDMI-0/workspace0/rgba1" --create \
    -t double -s 0.380392 \
    -t double -s 0.207843 \
    -t double -s 0.513725 \
    -t double -s 1.000000
```


```
~ ❯ xfconf-query -c xfce4-desktop \
  -p /backdrop/screen0/monitorDP-0/workspace0/rgba1
Value is an array with 4 items:

0.149020
0.635294
0.411765
1.000000
```



xfconf-query -c xfce4-desktop -l -v | grep rgb    
/backdrop/screen0/monitorDP-0/workspace0/rgba1           <<UNSUPPORTED>>
/backdrop/screen0/monitorDP-0/workspace0/rgba2           <<UNSUPPORTED>>
/backdrop/screen0/monitorDP-2/workspace0/rgba1           <<UNSUPPORTED>>
/backdrop/screen0/monitorDP-2/workspace0/rgba2           <<UNSUPPORTED>>
/backdrop/screen0/monitorHDMI-0/workspace0/rgba1         <<UNSUPPORTED>>
/backdrop/screen0/monitorHDMI-0/workspace0/rgba2         <<UNSUPPORTED>>



All connected monitors need to hav

