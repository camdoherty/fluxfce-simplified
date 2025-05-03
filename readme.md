# fluxfce v0.1 - XFCE auto-theming utility

**Fluxfce** automates switching XFCE desktop appearance (GTK Theme, Background, Screen Temperature) between configured Day and Night modes based on local sunrise and sunset times. It uses an adapted NOAA algorithm to calculate transition times. systemd and `atd` scheduler are used for precise, low-resource scheduling.

This is **v0.1**, a refactored and simplified version focusing on core functionality and maintainability.

<p align="center">
  <img src="logo.png" alt="fluxfce Logo Placeholder" width="150">
</p>

---

## Features (v0.1)

- **Automatic Switching:** Automatically transitions between Day and Night modes at local sunrise and sunset. 
- **Component Control:** Adjusts:
  - GTK Theme (`Net/ThemeName`)
  - Desktop Background (Solid color or vertical/horizontal gradient via `xfce4-desktop` properties)
  - Screen Temperature & Brightness (via `xsct`
  - Background image switching to be added 
- **Location Aware:** Calculates sunrise/sunset times based on user-configured latitude, longitude, and IANA timezone.
- **Timezone Detection:** Attempts to automatically detect system timezone during initial install.
- **Low Resource Usage:** Uses the system `atd` service for scheduling transitions, avoiding a persistent background daemon.
- **Systemd Integration:** Installs systemd user units (`.timer`, `.service`) for reliable daily rescheduling and applying the correct theme on login.
- **Manual Overrides:** Easily force Day or Night mode (`force-day`, `force-night`). Manual overrides temporarily disable automatic scheduling.
- **Simple Configuration:** Uses a clear INI file (`~/.config/fluxfce/config.ini`).
- **Easy Default Setting:** Save your current desktop look as the new default for Day or Night mode (`set-default`).
- **Status Reporting:** Check current configuration, calculated times, and scheduled jobs (`status`).

*(Features removed from the original script for simplicity: presets, direct `set` commands for individual components, `config` command for editing, `toggle` command.)*

## Requirements

- **Linux Distribution:** Tested on systemd-based distributions (e.g., Ubuntu, Fedora, Debian, Arch).
- **Desktop Environment:** XFCE 4.x
- **Python:** Python 3.9+ (due to `zoneinfo` usage)
- **External Commands (Dependencies):**
  - `atd` service (install package `at`, enable with `sudo systemctl enable --now atd`)
  - `xfconf-query` (installed with XFCE)
  - `xsct` (install package `xsct`)
  - `systemctl` (part of systemd)
  - `at`, `atq`, `atrm` (part of the `at` package)
  - `xfdesktop` (for background reloads)
  - `shutil.which` (provided by Python)

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/camdoherty/fluxfce-simplified.git fluxfce
   cd fluxfce
   ```
2. **Run the install command:**
   ```bash
   python3 fluxfce_cli.py install
   ```
   _You might need to run `sudo systemctl enable --now atd` separately if the `atd` service isn't running._

3. **Make the command accessible:**

   Ensure `~/.local/bin` is in your `PATH`:
   ```bash
   mkdir -p ~/.local/bin
   echo $PATH
   # If ~/.local/bin is not listed, add the following to your ~/.bashrc or ~/.zshrc:
   export PATH="$HOME/.local/bin:$PATH"
   source ~/.bashrc
   ```

   Make the script executable:
   ```bash
   chmod +x ./fluxfce_cli.py
   ```

   Create a symbolic link:
   ```bash
   SCRIPT_ABS_PATH=$(readlink -f ./fluxfce_cli.py)
   ln -s "$SCRIPT_ABS_PATH" ~/.local/bin/fluxfce
   ```

4. **(Optional but recommended) Configure appearance:**

   - Set your desired XFCE theme, background color/gradient, and screen temperature/brightness for Daytime, then run:
     ```bash
     fluxfce set-default --mode day
     ```
   - Set your desired look for Nighttime, then run:
     ```bash
     fluxfce set-default --mode night
     ```

## Usage

```bash
fluxfce <command> [options]
```

**Commands:**
- `install` — Install systemd units and enable automatic scheduling.
- `uninstall` — Remove systemd units and clear schedule (prompts to remove config).
- `enable` — Enable automatic scheduling (schedules transitions).
- `disable` — Disable automatic scheduling (clears scheduled transitions).
- `status` — Show config, calculated times, and schedule status.
- `force-day` — Apply Day Mode settings now (disables automatic scheduling).
- `force-night` — Apply Night Mode settings now (disables automatic scheduling).
- `set-default --mode {day,night}` — Save current desktop look as the new default for Day or Night mode.

**Options:**
- `-h`, `--help` — Show this help message and exit.
- `-v`, `--verbose` — Enable detailed logging output.

## Configuration

Fluxfce uses an INI file located at `~/.config/fluxfce/config.ini`. Example:

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

- **Background (`bg_dir`):** `s` = Solid, `h` = Horizontal gradient, `v` = Vertical gradient.
- **Screen Temperature/Brightness:** Defaults reset during Day if left empty.

## Troubleshooting

Use verbose logging:
```bash
fluxfce -v <command>
```

Check systemd user units:
```bash
systemctl --user status fluxfce-scheduler.timer \
    fluxfce-scheduler.service fluxfce-login.service
```

View journal logs:
```bash
journalctl --user -u fluxfce-scheduler.timer
journalctl --user -u fluxfce-scheduler.service
journalctl --user -u fluxfce-login.service
journalctl --user -t fluxfce-atjob
```

Check `at` queue:
```bash
atq
```

Verify dependencies and `atd` service:
```bash
sudo systemctl status atd
```

Verify config path: `~/.config/fluxfce/config.ini`


## License

MIT
