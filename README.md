# lightfx - DRAFT README

**lightfx** is a powerful desktop appearance manager for Linux. It automatically transitions your desktop between profiles at local sunrise and sunset and allows you to switch between custom user-defined looks instantly.

It features a robust profile system, smooth screen temperature transitions, and native support for both **XFCE** and **Linux Mint Cinnamon** desktop environments.

## Features

-   **Profile-Based Theming:** Save your complete desktop look—themes, icons, cursors, background, and screen settings—into self-contained profile files.
-   **Automatic Sunrise/Sunset Switching:** Assign "Day" and "Night" profiles to be applied automatically based on precise, location-aware sun calculations.
-   **Slow Transitions:** Optionally enable smooth, gradual changes in screen temperature and brightness over a configurable duration, eliminating jarring shifts.
-   **Multi-Desktop Support:** Works natively on both **XFCE** and **Linux Mint Cinnamon**.
-   **Manual Control:** Instantly apply any of your custom-made profiles (e.g., "Work," "Gaming," "Reading") via a powerful system tray menu or command-line interface.
-   **Low Resource Usage:** Uses `systemd` user timers for efficient, event-based scheduling, avoiding a persistent background daemon.

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd lightfx

# Run the interactive installer
./lightfx_cli.py install
```
This command verifies dependencies, creates default Day/Night profiles, and installs and enables the necessary `systemd` user units.

## Usage

`lightfx` is primarily controlled via its system tray icon. Right-click the icon to:
-   Enable or disable automatic sunrise/sunset transitions.
-   Apply any defined profile (Day, Night, or custom) instantly.
-   Save the current desktop look as a new profile or overwrite an existing one.

### Command-Line Interface

-   `lightfx profile list`: See all your saved profiles.
-   `lightfx profile apply <name>`: Apply a profile.
-   `lightfx profile create <name>`: Save your current look as a new profile.
-   `lightfx schedule assign <sunrise|sunset> <name>`: Change which profile is used for automatic transitions.

## Configuration

-   **`~/.config/lightfx/config.ini`**: Controls application behavior, such as scheduling and slow transition settings.
-   **`~/.config/lightfx/profiles/`**: This directory contains your appearance profiles (e.g., `default-day.profile`). Each `.profile` is a simple `ini` file that defines a complete look.
