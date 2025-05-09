# fluxfce - XFCE Auto-Theming Utility

**Fluxfce** automates switching XFCE desktop appearance (GTK Theme, Background Color/Gradient, Screen Temperature/Brightness) between configured Day and Night modes based on local sunrise and sunset times. It uses an adapted NOAA algorithm to calculate transition times. Systemd and the `atd` scheduler are used for precise, low-resource scheduling.

This is a refactored and simplified version focusing on core functionality, reliability, and maintainability.

<p align="center">
  <img src="logo.png" alt="fluxfce Logo Placeholder" width="150">
</p>

---

## Features

- **Automatic Switching:** Automatically transitions between Day and Night modes at local sunrise and sunset.
- **Component Control:** Adjusts:
  - GTK Theme (`Net/ThemeName`)
  - Desktop Background (Solid color or vertical/horizontal gradient via `xfce4-desktop` properties)
  - Screen Temperature & Brightness (via `xsct`)
  - *(Support for background image switching is planned for a future version)*
- **Location Aware:** Calculates sunrise/sunset times based on user-configured latitude, longitude, and IANA timezone.
- **Timezone Detection:** Attempts to automatically detect system timezone during initial install.
- **Low Resource Usage:** Uses the system `atd` service for scheduling transitions, avoiding a persistent background daemon.
- **Systemd Integration:** Installs systemd user units (`.timer`, `.service`) for reliable daily rescheduling and applying the correct theme on login and resume from suspend.
- **Manual Overrides:** Easily force Day or Night mode (`force-day`, `force-night`). Manual overrides temporarily disable automatic scheduling.
- **Simple Configuration:** Uses a clear INI file (`~/.config/fluxfce/config.ini`).
- **Easy Default Setting:** Save your current desktop look as the new default for Day or Night mode (`set-default`).
- **Status Reporting:** Check current configuration, calculated times, and scheduled jobs (`status`).

## Requirements

- **Linux Distribution:** Designed for systemd-based distributions with XFCE.
  - **Primary Targets:** Ubuntu 22.04+ (Xubuntu), Linux Mint 21.x+ (XFCE), Debian 11+ (XFCE).
  - *May work on other systemd-based XFCE distributions (e.g., Fedora XFCE, Arch XFCE) with adjustments to package names for dependencies.*
- **Desktop Environment:** XFCE 4.x
- **Python:** Python 3.9+ (due to `zoneinfo` usage).
- **System Tools & Services (Dependencies):**
  - **`atd` service:** For scheduling transitions.
    - Installation: Usually via the `at` package (e.g., `sudo apt install at`).
    - Activation: Must be enabled and running (e.g., `sudo systemctl enable --now atd`).
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
    - `systemctl`, `timedatectl` (part of systemd)
    - `at`, `atq`, `atrm` (from the `at` package)

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
    *   Check for required system dependencies and guide you through installing missing ones (like `at` or `xsct` via `apt`, or provide manual instructions for `xsct`).
    *   Prompt you for location (latitude/longitude) and attempt to detect your timezone for accurate sun time calculations if a configuration file doesn't exist.
    *   Install systemd user units for automatic operation.
    *   Enable scheduling.

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
        ```    *   Create a symbolic link:
        ```bash
        SCRIPT_ABS_PATH=$(readlink -f ./fluxfce_cli.py) # Or use: SCRIPT_ABS_PATH=$(pwd)/fluxfce_cli.py
        mkdir -p ~/.local/bin
        ln -s "$SCRIPT_ABS_PATH" ~/.local/bin/fluxfce
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
    `fluxfce` will save these settings to its configuration file.

## Usage

```bash
fluxfce <command> [options]
```

**Commands:**
- `install` — Performs dependency checks, interactive setup (if needed), installs systemd units, and enables automatic scheduling.
- `uninstall` — Removes systemd units and clears schedule (prompts to remove config).
- `enable` — Enables automatic scheduling (schedules transitions).
- `disable` — Disable automatic scheduling (clears scheduled transitions).
- `status` — Show config, calculated times, and schedule status.
- `force-day` — Apply Day Mode settings now (disables automatic scheduling).
- `force-night` — Apply Night Mode settings now (disables automatic scheduling).
- `set-default --mode {day,night}` — Save current desktop look as the new default for Day or Night mode.

**Options:**
- `-h`, `--help` — Show this help message and exit.
- `-v`, `--verbose` — Enable detailed logging output for `fluxfce` operations.

## Configuration

Fluxfce uses an INI file located at `~/.config/fluxfce/config.ini`.
The `fluxfce install` command will help you create this initially. You can edit it manually later.

**Example `config.ini`:**
```ini
[Location]
latitude = 43.65N
longitude = 79.38W
timezone = America/Toronto

[Themes]
light_theme = Adwaita
dark_theme = Adwaita-dark

[BackgroundDay]
bg_dir = v
bg_hex1 = ADD8E6
bg_hex2 = 87CEEB

[ScreenDay]
xsct_temp = 6500
xsct_bright = 1.0

[BackgroundNight]
bg_dir = v
bg_hex1 = 1E1E2E
bg_hex2 = 000000

[ScreenNight]
xsct_temp = 4500
xsct_bright = 0.85
```

- **`bg_dir` (Background Direction):**
  - `s` = Solid color (uses `bg_hex1` only)
  - `h` = Horizontal gradient (uses `bg_hex1` and `bg_hex2`)
  - `v` = Vertical gradient (uses `bg_hex1` and `bg_hex2`)
- **`xsct_temp` (Screen Temperature):** In Kelvin (e.g., 3700, 6500). If empty for Day mode, `xsct` typically resets to its default.
- **`xsct_bright` (Screen Brightness):** Factor (e.g., 0.8, 1.0). If empty for Day mode, `xsct` typically resets to its default.

## Troubleshooting

- **Verbose Output:** Always try running `fluxfce` with the `-v` flag first to get more detailed logs:
  ```bash
  fluxfce -v status
  fluxfce -v enable
  ```
- **Dependency Check Script:**
  If you suspect system dependencies are the issue, and if the `fluxfce install` guidance wasn't sufficient, you can re-run the dependency check. If a separate script (e.g., `fluxfce_dependency_setup.py`) was provided with fluxfce:
  ```bash
  python3 /path/to/fluxfce_dependency_setup.py
  ```
  Otherwise, the `fluxfce install` command itself performs these checks.

- **Check `atd` Service:**
  ```bash
  sudo systemctl status atd
  ```
  Ensure it's active and enabled. If not:
  ```bash
  sudo apt install at # If not installed
  sudo systemctl enable --now atd
  ```

- **Check `at` Queue:** See if `fluxfce` jobs are scheduled:
  ```bash
  atq
  ```

- **Systemd User Units:** Check the status of `fluxfce`'s own services:
  ```bash
  systemctl --user status fluxfce-scheduler.timer fluxfce-scheduler.service fluxfce-login.service fluxfce-resume.service
  ```

- **View Journal Logs:** For more detailed error messages from `fluxfce` services:
  ```bash
  journalctl --user -u fluxfce-scheduler.timer
  journalctl --user -u fluxfce-scheduler.service
  journalctl --user -u fluxfce-login.service
  journalctl --user -u fluxfce-resume.service
  journalctl --user -t fluxfce-atjob # For output from the actual theme transitions
  ```

- **Configuration File Path:** Ensure your config is at `~/.config/fluxfce/config.ini`.

## License

MIT
