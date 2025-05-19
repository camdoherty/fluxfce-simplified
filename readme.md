# fluxfce - XFCE Auto-Theming Utility

**Fluxfce** automates switching XFCE desktop appearance (GTK Theme, Background Color/Gradient, Screen Temperature/Brightness) between configured Day and Night modes based on local sunrise and sunset times. It uses an adapted NOAA algorithm to calculate transition times. **Systemd user timers** are used for precise, low-resource scheduling and applying themes on login/resume.

This is a refactored and simplified version focusing on core functionality, reliability, and maintainability.

<p align="center">
  <img src="logo.png" alt="fluxfce Logo Placeholder" width="150">
</p>

---

## Features

- **Automatic Switching:** Automatically transitions between Day and Night modes at local sunrise and sunset.
- **Easy Default Setting:** Save your current desktop look as the new default for Day or Night mode (`fluxfce set-default --mode day`).
- **Component Control:** Adjusts:
  - GTK Theme (`Net/ThemeName`)
  - Desktop Background (Solid color or vertical/horizontal gradient via `xfce4-desktop` properties)
  - Screen Temperature & Brightness (via `xsct`)
- **Location Aware:** Calculates sunrise/sunset times based on user-configured latitude, longitude, and IANA timezone.
- **Timezone Detection:** Attempts to automatically detect system timezone during initial install.
- **Low Resource Usage:** Uses systemd user timers, avoiding a persistent custom background daemon.
- **Systemd Integration:** Installs systemd user units (`.timer`, `.service`) for:
    - Daily rescheduling of sunrise/sunset event timers.
    - Triggering theme transitions at precise sunrise/sunset times.
    - Applying the correct theme on login and resume from suspend.
- **Manual Overrides:** Easily force Day or Night mode (`force-day`, `force-night`). Manual overrides disable automatic scheduling.
- **Simple Configuration:** Uses a clear INI file (`~/.config/fluxfce/config.ini`).
- **Status Reporting:** Check current configuration, calculated times, and systemd timer status (`status`).

## Requirements

- **Linux Distribution:** Designed for XFCE distributions with systemd.
  - **Primary Targets:** Ubuntu 22.04+ (Xubuntu), Linux Mint 21.x+ (XFCE), Debian 11+ (XFCE).
  - *May work on other systemd-based XFCE distributions (e.g., Fedora XFCE, Arch XFCE) with adjustments to package names for dependencies.*
- **Desktop Environment:** XFCE 4.x
- **Python:** Python 3.9+ (due to `zoneinfo` usage).
- **System Tools & Services (Dependencies):**
  - **`systemd`:** User instance must be operational.
  - **`xsct`:** For screen temperature and brightness control.
    - Installation on **Ubuntu 24.04 (Noble Numbat) and newer (or equivalent Linux Mint/Debian versions)**:
      ```bash
      sudo apt update
      sudo apt install xsct
      ```
    - Installation on **older Ubuntu/Debian versions (e.g., Ubuntu 22.04, Debian 11) or if `apt install xsct` fails**:
      `xsct` typically requires manual compilation from source:
      1.  Install build dependencies:
          ```bash
          sudo apt update
          sudo apt install build-essential libx11-dev libxrandr-dev git
          ```
      2.  Clone, compile, and install `xsct`:
          ```bash
          git clone https://github.com/faf0/xsct.git
          cd xsct
          sudo make install  # Installs to /usr/local/bin by default
          ```
          *(Alternatively, install to `~/.local/bin`: `make PREFIX=~/.local install` and ensure `~/.local/bin` is in your PATH)*
  - **Core XFCE/System Tools** (Usually pre-installed on XFCE systems):
    - `xfconf-query` (from `xfce4-utils` or similar)
    - `xfdesktop` (from `xfdesktop4` or similar, for background reloads)
    - `timedatectl` (part of systemd)

## Installation

1.  **Clone the repository (or download the source code):**
    ```bash
    git clone https://github.com/yourusername/fluxfce.git # Replace with actual URL
    cd fluxfce
    ```

2.  **Run the install command:**
    ```bash
    python3 fluxfce_cli.py install
    ```
    The script will:
    *   Check for Python version.
    *   Check for required system dependencies using `fluxfce_deps_check.py` and guide you through installing missing ones (like `xsct` via `apt`, or provide manual instructions for `xsct`).
    *   Prompt you for location (latitude/longitude) and attempt to detect your timezone for accurate sun time calculations if a configuration file doesn't exist.
    *   Install systemd user units for automatic operation.
    *   Enable scheduling, which sets up timers for the next sunrise/sunset and ensures the current desktop appearance matches the current solar period.

3.  **Make the `fluxfce` command easily accessible (if not using `pip install .` in the future):**
    The `install` script will provide instructions. A common method is:
    *   Ensure `~/.local/bin` is in your `PATH`. Add if necessary:
        ```bash
        # Add to your ~/.bashrc or ~/.zshrc, then source it or restart terminal
        export PATH="$HOME/.local/bin:$PATH"
        ```
    *   Make the main script executable:
        ```bash
        chmod +x ./fluxfce_cli.py
        ```
    *   Create a symbolic link:
        ```bash
        SCRIPT_ABS_PATH=$(readlink -f ./fluxfce_cli.py) # Or use: SCRIPT_ABS_PATH=$(pwd)/fluxfce_cli.py
        mkdir -p ~/.local/bin
        ln -s -f "$SCRIPT_ABS_PATH" ~/.local/bin/fluxfce # Added -f to force overwrite if exists
        ```

4.  **(Recommended) Configure Day/Night Appearance:**
    Set your desired XFCE theme, background color/gradient, and screen temperature/brightness for **Daytime**, then run:
    ```bash
    fluxfce set-default --mode day
    ```
    Then, set your desired look for **Nighttime**, and run:
    ```bash
    fluxfce set-default --mode night
    ```
    `fluxfce` will save these settings to its configuration file. When `fluxfce enable` is run, or when the scheduled transitions occur, these configured settings will be applied.

## Usage

```bash
fluxfce <command> [options]