# fluxfce

*requires review*

**fluxfce** automates switching your desktop appearance between user-defined **Day** and **Night** modes at local sunrise and sunset. It supports both **XFCE** and **Linux Mint Cinnamon** desktop environments.

It manages GTK theme, desktop background, and screen temperature/brightness using an adapted NOAA algorithm for precise timing. `systemd` timers are used use for lightweight scheduling without a persistent daemon.

<p align="center">
  <img src="logo.png" alt="fluxfce Logo" width="150">
</p>

---

## Features

-   **Multi-Desktop Support:** Works natively on both **XFCE** and **Linux Mint Cinnamon**.
-   **Automatic Sunrise/Sunset Switching:** Transitions your desktop look at the correct local time.
-   **Profile-Based Customization:** Set up your desktop how you like it for day or night, and save that entire look to a profile with a single command (`fluxfce set-default`).
-   **Comprehensive Appearance Control:** Adjusts:
    -   GTK & Window Manager Theme.
    -   Cinnamon's native "prefer-dark" color scheme.
    -   Desktop Background (any type supported by your DE, including images, gradients, or solid colors).
    -   Screen Temperature & Brightness (via `xsct`).
-   **Location Aware:** Calculates sunrise/sunset based on user-configured latitude, longitude, and IANA timezone.
-   **Low Resource Usage:** Uses `systemd` user timers, avoiding a persistent background daemon.
-   **Robust Systemd Integration:** Installs user units for:
    -   Daily recalculation of sunrise/sunset event timers.
    -   Precise transitions at sunrise and sunset.
    -   Applying the correct theme on login and resume from suspend.
-   **Simple Configuration:** Manages settings in clean INI and .profile files.

## Requirements

#### General Requirements
-   **Python:** Python 3.9+ (for `zoneinfo` library).
-   **System:** A Linux distribution with `systemd`.
-   **Screen Control:** `xsct` (for screen temperature/brightness).

#### Desktop-Specific Requirements

The installer will check for these based on your environment.

-   **For XFCE:**
    -   `xfconf-query` (core configuration tool)
    -   `xfdesktop` (desktop manager for background reloads)
    -   `xrandr` (for multi-monitor awareness)

-   **For Cinnamon:**
    -   `gsettings` (core configuration tool)
    -   `gdbus` (for checking session readiness)

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
    -   Detects your desktop environment (XFCE or Cinnamon).
    -   Verifies all required command-line dependencies for your DE.
    -   Creates an initial configuration file (`~/.config/fluxfce/config.ini`), prompting for your location.
    -   Installs and enables the necessary `systemd` user units for full automation.

3.  **Make `fluxfce` available in your PATH (Recommended):**
    For easy access from any terminal location, create a symbolic link.
    ```bash
    # Ensure ~/.local/bin exists and is in your PATH
    mkdir -p ~/.local/bin
    
    # Create the symlink (run from within the cloned directory)
    ln -s "$(pwd)/fluxfce_cli.py" ~/.local/bin/fluxfce
    ```

## Usage

The recommended workflow is to set your desired Day and Night looks first.

#### **1. Configure Your Appearance (Crucial Step)**

Set up your desktop exactly how you want it for **Daytime** (theme, background, screen color), then save this state by running:

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

Configuration is split between a main settings file and background profile files.

#### Main Config: `~/.config/fluxfce/config.ini`

This file holds your location, theme names, and screen settings.

```ini
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

#### Background Profiles: `~/.config/fluxfce/backgrounds/`

The `fluxfce set-default` command creates and manages these files for you.

-   **XFCE profiles** (e.g., `default-day.profile`) are complex and store detailed properties for each monitor.
-   **Cinnamon profiles** (e.g., `cinnamon-default-day.profile`) are simple INI files. Example:
    ```ini
    [Background]
    type = image
    image_path = /path/to/your/day-wallpaper.jpg
    ```

## Troubleshooting

-   **Verbose Logging:** Always run commands with the `-v` flag first for detailed output: `fluxfce -v status`.

-   **Check Systemd Units:**
    -   **List all `fluxfce` timers** to see when they will next run:
        ```bash
        systemctl --user list-timers --all | grep fluxfce
        ```
    -   **Check the status of all `fluxfce` units** at once:
        ```bash
        systemctl --user status 'fluxfce-*.service' 'fluxfce-*.timer'
        ```
    -   **View logs for a specific unit** (e.g., the scheduler service):
        ```bash
        journalctl --user -u fluxfce-scheduler.service -e --no-pager
        ```
        *(Replace the unit name as needed, e.g., `fluxfce-apply-transition@night.service`)*.

-   **Manual Service Test:** To manually trigger a transition and test the service:
    ```bash
    # Test the 'night' mode transition
    systemctl --user start fluxfce-apply-transition@night.service
    
    # Check the logs if it failed, paying attention to any errors from
    # XfceHandler or CinnamonHandler.
    journalctl --user -u fluxfce-apply-transition@night.service
    ```

## License

MIT