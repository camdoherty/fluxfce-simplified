# fluxfce - XFCE Auto-Theming Utility

pre-update for image support

**Fluxfce** automates switching XFCE desktop appearance (GTK Theme, Background Color/Gradient, Screen Temperature/Brightness) between user-defined Day and Night modes at sunrise and sunset times. It uses an adapted NOAA algorithm to calculate transition times. **Systemd user timers** are used for precise, low-resource scheduling.

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
  - **Core XFCE/System Tools** (Usually pre-installed on XFCE systems):
    - `xfconf-query` (from `xfce4-utils` or similar)
    - `xfdesktop` (from `xfdesktop4` or similar, for background reloads)
    - `timedatectl` (part of systemd)

## Installation

1.  **Clone the repository (or download the source code):**

    ```bash
    git clone https://github.com/camdoherty/fluxfce-simplified.git
    cd fluxfce
    ```

2.  **Run the install command:**

    ```bash
    python3 fluxfce_cli.py install
    ```
    The script will:
    - Check for Python version.
    - Check for required system dependencies using `fluxfce_deps_check.py` and guide you through installing missing ones (like `xsct` via `apt`).
    - Prompt you for location (latitude/longitude) and attempt to detect your timezone for accurate sun time calculations if a configuration file doesn't exist.
    - Install systemd user units for automatic operation.
    - Enable scheduling, which sets up timers for the next sunrise/sunset and ensures the current desktop appearance matches the current solar period.

3.  **Make the `fluxfce` command easily accessible (if not using `pip install .` in the future):**

    The `install` script will provide instructions. A common method is:
    - Ensure `~/.local/bin` is in your `PATH`. Add if necessary:
      ```bash
      # Add to your ~/.bashrc or ~/.zshrc, then source it or restart terminal
      export PATH="$HOME/.local/bin:$PATH"
      ```
    - Make the main script executable:
      ```bash
      chmod +x ./fluxfce_cli.py
      ```
    - Create a symbolic link:
      ```bash
      SCRIPT_ABS_PATH=$(readlink -f ./fluxfce_cli.py) # Or use: SCRIPT_ABS_PATH=$(pwd)/fluxfce_cli.py
      mkdir -p ~/.local/bin
      ln -s -f "$SCRIPT_ABS_PATH" ~/.local/bin/fluxfce # -f forces overwrite if symlink exists
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
```

**Commands:**

- `install` — Performs dependency checks, interactive setup (if needed), installs systemd units, and enables automatic scheduling.
- `uninstall` — Removes systemd units and clears schedule (prompts to remove config).
- `day` — Apply Day Mode settings now without disabling automatic scheduling.
- `night` — Apply Night Mode settings now without disabling automatic scheduling.
- `enable` — Enables automatic scheduling (sets up systemd timers for sunrise/sunset and ensures current appearance matches the solar period).
- `disable` — Disable automatic scheduling (stops and disables relevant systemd timers).
- `status` — Show config, calculated times, and systemd timer/service status.
- `force-day` — Apply Day Mode settings now **and disable** automatic scheduling.
- `force-night` — Apply Night Mode settings now **and disable** automatic scheduling.
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
- **`xsct_temp` (Screen Temperature):** In Kelvin (e.g., 3700, 6500). If empty for Day mode, `xsct` typically resets to its default (temperature and brightness are usually reset together for day mode if either is empty).
- **`xsct_bright` (Screen Brightness):** Factor (e.g., 0.8, 1.0). If empty for Day mode, `xsct` typically resets to its default.

## Troubleshooting

- **Verbose Output:** Always try running `fluxfce` with the `-v` flag first to get more detailed logs:
  ```bash
  fluxfce -v status
  fluxfce -v enable
  # etc.
  ```
- **Dependency Check Script:**
  The `fluxfce install` command runs `fluxfce_deps_check.py` automatically. If you need to re-run it manually (e.g., after system changes):
  ```bash
  python3 ./fluxfce_deps_check.py 
  ```
  (Assuming `fluxfce_deps_check.py` is in the same directory as `fluxfce_cli.py`).

- **Systemd User Units & Timers:**
  - **List FluxFCE Timers:** See if `fluxfce` timers are scheduled and their next run times:
    ```bash
    systemctl --user list-timers --all | grep fluxfce
    ```
  - **Check Status of Specific FluxFCE Units:** (Replace `fluxfce-unit-name` with the actual unit, e.g., `fluxfce-scheduler.timer` or `fluxfce-apply-transition@day.service`)
    ```bash
    systemctl --user status fluxfce-unit-name
    ```
    Common units to check: `fluxfce-scheduler.timer`, `fluxfce-scheduler.service`, `fluxfce-sunrise-event.timer`, `fluxfce-sunset-event.timer`, `fluxfce-apply-transition@day.service`, `fluxfce-apply-transition@night.service`, `fluxfce-login.service`, `fluxfce-resume.service`.
  - **View Journal Logs for Specific Units:** For detailed error messages:
    ```bash
    journalctl --user -u fluxfce-scheduler.service -e --no-pager
    journalctl --user -u fluxfce-apply-transition@day.service -e --no-pager 
    # etc. for other fluxfce units. '-e' jumps to end, '--no-pager' prints to console.
    ```

- **Configuration File Path:** Ensure your config is at `~/.config/fluxfce/config.ini`.

- **Manual Theme Application Test (via Systemd Service):** To test if a specific mode application service is working correctly:
  ```bash
  # Ensure you are in the opposite mode first (e.g., run 'fluxfce force-day')
  # Then to test night mode application:
  systemctl --user start fluxfce-apply-transition@night.service
  # Check your desktop. Then check the journal for this unit if issues occurred:
  # journalctl --user -u fluxfce-apply-transition@night.service -e --no-pager
  ```

## License

MIT