# fluxfce

**fluxfce** automates switching your XFCE desktop appearance between **Day** and **Night** modes at local sunrise and sunset. It uses an adapted NOAA algorithm for precise timing and relies on **Systemd user timers** for low-resource scheduling.

Manages Gtk theme, desktop background, and screen temperature / brightness

<p align="center">
  <img src="logo.png" alt="fluxfce Logo Placeholder" width="150">
</p>

---

## Features

- **Automatic Sunrise/Sunset Switching:** Transitions your desktop look at the correct local time.
- **Profile-Based Customization:** Simply set up your desktop how you like it for day or night, and save that entire look to a profile with a single command.
- **Comprehensive Appearance Control:**
  - GTK & Window Manager Theme (`xfconf`)
  - Desktop Background (any type supported by XFCE, including images, gradients, or solid colors)
  - Screen Temperature & Brightness (via `xsct`)
- **Location Aware:** Calculates sun times based on user-configured latitude, longitude, and IANA timezone.
- **Low Resource Usage:** Uses `systemd` user timers, avoiding a persistent background daemon.
- **Robust Systemd Integration:** Installs user units for:
    - Daily recalculation of sunrise/sunset event timers.
    - Precise transitions at sunrise and sunset.
    - Applying the correct theme on login and resume from suspend.
- **Manual Overrides:** Instantly apply a mode and optionally disable automatic scheduling.
- **Simple Configuration:** Manages settings in a clean INI file at `~/.config/fluxfce/config.ini`.
- **Status Reporting:** Provides a clear status of configuration, sun times, and scheduler state.

## Requirements

- **Linux Distribution:** An XFCE distribution with `systemd`.
  - **Tested On:** Ubuntu 22.04+ (Xubuntu), Linux Mint 21.x+ (XFCE).
  - *Should work on:* Debian, Fedora XFCE, Arch XFCE, etc. (dependency package names may vary).
- **Desktop Environment:** XFCE 4.x
- **Python:** Python 3.9+ (for `zoneinfo` library).
- **Dependencies:**
  - `systemd` (user instance must be running).
  - `xsct`: For screen temperature/brightness control.
  - `xfconf-query`: Core XFCE configuration tool.
  - `xfdesktop`: XFCE desktop manager.
  - `xrandr`: For multi-monitor awareness.

## Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/camdoherty/fluxfce-simplified.git
    cd fluxfce-simplified
    ```

2.  **Run the interactive installer:**
    ```bash
    ./fluxfce_cli.py install
    ```
    This master command handles everything:
    - Checks for the correct Python version.
    - Verifies all required command-line dependencies and offers to install them via `apt` on Debian/Ubuntu systems.
    - Creates an initial configuration file (`~/.config/fluxfce/config.ini`), prompting for your location for accurate sun calculations.
    - Installs and enables the necessary `systemd` user units for full automation.

3.  **Make `fluxfce` available in your PATH (Recommended):**
    For easy access, create a symbolic link.
    ```bash
    # Ensure ~/.local/bin exists and is in your PATH
    mkdir -p ~/.local/bin
    
    # Add ~/.local/bin to PATH in your shell's config file if it's not already there
    # For bash, add this to ~/.bashrc:
    # export PATH="$HOME/.local/bin:$PATH"
    
    # Create the symlink
    ln -s "$(pwd)/fluxfce_cli.py" ~/.local/bin/fluxfce
    ```

## Usage

The recommended workflow is to set your desired Day and Night looks first.

#### **1. Configure Your Day/Night Appearance (Crucial Step)**

Set your desired XFCE theme, desktop background(s), and screen temperature/brightness for **Daytime**, then save it by running:

```bash
fluxfce set-default --mode day
```

Next, set up your preferred look for **Nighttime**, and save it:

```bash
fluxfce set-default --mode night
```

This saves your complete desktop state into profile files, which `fluxfce` will use for transitions.

#### **2. Manage Scheduling**

-   **`enable`**: Enables automatic scheduling. Runs the scheduler once to set timers for the next sunrise/sunset.
-   **`disable`**: Disables automatic scheduling.
-   **`status`**: Shows current configuration, sun times, and `systemd` timer status. Use `-v` for more detail.
-   **`install`**: The initial setup command.
-   **`uninstall`**: Removes all `systemd` units and offers to delete the configuration directory.

#### **3. Manual Overrides**

-   **`day`** / **`night`**: Temporarily apply a mode. Automatic scheduling remains active and will trigger the next transition as scheduled.
-   **`force-day`** / **`force-night`**: Apply a mode **and** disable automatic scheduling.

## Configuration

The main configuration file is located at `~/.config/fluxfce/config.ini`. While `install` and `set-default` handle most settings, you can edit it manually.

**Example `config.ini`:**
```ini
[Location]
latitude = 43.65N
longitude = 79.38W
timezone = America/Toronto

[GUI]
opacity = 0.85
widget_opacity = 0.9

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

- **Background settings are stored in profiles** at `~/.config/fluxfce/backgrounds/`. The `set-default` command creates and updates these files for you. You can edit them manually to tweak background settings.
- **`xsct_temp`** and **`xsct_bright`**: An empty value will cause `xsct` to be reset to its default state.

## Troubleshooting

-   **Verbose Logging:** Run any command with the `-v` flag for detailed output: `fluxfce -v status`.

-   **Check Dependency Script:** To re-run the dependency checker manually:
    ```bash
    ./fluxfce_deps_check.py
    ```

-   **Systemd Timers and Services:**
    -   **List all `fluxfce` timers** to see when they will next run:
        ```bash
        systemctl --user list-timers --all | grep fluxfce
        ```
    -   **View logs for a specific unit** (e.g., the scheduler service):
        ```bash
        journalctl --user -u fluxfce-scheduler.service -e --no-pager
        ```
        *(Replace `fluxfce-scheduler.service` with any unit name, like `fluxfce-apply-transition@night.service` or `fluxfce-resume.service`)*.

## License

MIT
