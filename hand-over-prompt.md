**Project Handover: fluxfce-simplified v0.1**

**Context:**
You are taking over development for `fluxfce-simplified` (v0.1), a Python CLI tool designed to automatically switch the XFCE desktop appearance (GTK theme, background color/gradient, screen temperature/brightness via `xsct`) based on calculated local sunrise and sunset times.

**Your Role & Required Skills:**
You are a software engineer and Linux system administrator. You possess deep knowledge of:
*   Python (3.9+)
*   Linux Command-Line Tools: `xfconf-query`, `xsct`, **`systemctl`**, `journalctl`, `timedatectl`, `git`, `make`, standard shell utilities.
*   XFCE Desktop Environment: Configuration concepts (`xfconf`), theming.
*   Systemd: User sessions, `.service` and `.timer` units, targets (esp. `sleep.target`, `graphical-session.target`), `journalctl`.
*   Software Architecture: Separation of concerns, API design.
*   Debugging Techniques: Analyzing logs, tracebacks, system states.

**Codebase:**
*   The codebase for `fluxfce-simplified` v0.1 is included as `codebase.txt` accompanying this prompt.

**Tasks:**
*   Analyze and review the codebase, ensuring you have a thorough understanding of the intended functionality of fluxfce-simplified.
*   **Focus on code related to installation (ie `fluxfce install`), and the setup and creation systemd units. Assist with debugging and resoloving the following:**

```
~ ❯ fluxfce install
...
--- Step 3: Installing systemd units ---
Created symlink /home/cad/.config/systemd/user/graphical-session.target.wants/fluxfce-login.service → /home/cad/.config/systemd/user/fluxfce-login.service.
Created symlink /home/cad/.config/systemd/user/suspend.target.wants/fluxfce-resume.service → /home/cad/.config/systemd/user/fluxfce-resume.service.
Unit /home/cad/.config/systemd/user/fluxfce-resume.service is added as a dependency to a non-existent unit suspend.target. # note this issue
Created symlink /home/cad/.config/systemd/user/timers.target.wants/fluxfce-scheduler.timer → /home/cad/.config/systemd/user/fluxfce-scheduler.timer.
Static systemd units installed.

--- Step 4: Enabling automatic scheduling ---
Failed to stop fluxfce-sunrise-event.timer: Unit fluxfce-sunrise-event.timer not loaded. # note this line
Failed to stop fluxfce-sunset-event.timer: Unit fluxfce-sunset-event.timer not loaded. # note this line
Automatic theme scheduling enabled via systemd timers.
```

**Note:**
*   It may be necessary to do research to determine the correct approach to craeting the dynamic systemd units.




**Your objective**
*   Assist in debugging fluxfce-simplified





**Core Goal of `fluxfce`:**
To automatically apply user-defined "Day" and "Night" appearance settings (Theme, Background, Screen Temp) at the correct local sunrise and sunset times, while remaining reliable across logins, reboots, and suspend/resume cycles, using minimal system resources when idle.

**Architecture Overview:**
The project is split into two main parts:
1.  `fluxfce_core` (Python Package): Contains all backend logic, isolated from the UI.
    *   `api.py`: Public functions acting as the interface for external callers.
    *   `config.py`: `ConfigManager` class, handles `config.ini` (no presets).
    *   `exceptions.py`: Custom exception classes.
    *   `helpers.py`: Utility functions (`run_command`, validators, timezone detection).
    *   `scheduler.py`: `AtdScheduler` class, manages `at` jobs.
    *   `sun.py`: Sunrise/sunset calculation logic.
    *   `systemd.py`: `SystemdManager` class, manages systemd user units.
    *   `xfce.py`: `XfceHandler` class, interacts with `xfconf-query` and `xsct`.
    *   `__init__.py`: Exports the public API elements.
2.  `fluxfce_cli.py`: The command-line interface script. Uses `argparse`, calls functions from `fluxfce_core`, handles user output and error reporting.

**Key Features Implemented (v0.1):**
*   `install`: Sets up systemd units, creates default config (detects TZ, prompts coords), enables scheduling.
*   `uninstall`: Removes systemd units, clears schedule, prompts to remove config dir.
*   `enable`: Enables automatic scheduling (sets N-day `at` job buffer).
*   `disable`: Disables automatic scheduling (clears `at` jobs).
*   `status`: Shows current configuration, calculated sun times, schedule, systemd status.
*   `force-day`/`force-night`: Applies the specified mode now and disables automatic scheduling.
*   `set-default --mode <day|night>`: Saves the *current* desktop appearance as the default for the specified mode in `config.ini`.
*   Automatic theme application on Login and Resume via dedicated systemd services (`run-login-check` command).

**Key Features Explicitly REMOVED from original design:**
*   Preset system (`save`, `apply`, etc.)
*   Direct component setters (`set background`, `set theme`)
*   `config --get/--set` command
*   `toggle` command
*   State file (`~/.config/fluxfce/state`) - Deemed redundant.

**Technical Details & Design Decisions:**
*   **Scheduling:** Uses a **daily systemd user timer** (`fluxfce-scheduler.timer` with `Persistent=true`) which triggers a service (`fluxfce-scheduler.service`) to run `fluxfce schedule-jobs`. This calculates sunrise/sunset for the next **N=7 days** and schedules ~14 individual `at` jobs using `atd`. This provides robustness against missed scheduler runs. *Alternatives (daemon, chaining `at`, long-term pre-calc) were evaluated and rejected due to fragility, complexity, or lack of significant benefit.*
*   **Environment for `atd`:** `xsct` and `xfconf-query` need `DISPLAY`/`XAUTHORITY`. The `scheduler.schedule_transitions` function attempts to fetch these using `systemctl --user show-environment` and injects them as `export` commands into the script run by the `at` job.
*   **Resume Handling:** A dedicated systemd user service (`fluxfce-resume.service`) triggered by `sleep.target` runs the `run-login-check` command after resuming from suspend/hibernate to ensure the correct theme is applied.
*   **`xsct` Installation:** Requires manual compilation/installation from source (`https://github.com/faf0/xsct.git`) as it's typically not in package repositories.
*   **Configuration:** Single `config.ini` file. Edits should be reflected automatically within ~24hrs (by daily scheduler) or immediately upon next `enable` command.



**Config File:**
*   **Example Config File:**
```
~/.config/fluxfce/config.ini
[Location]
latitude = 43.65N
longitude = 79.38W
timezone = America/Toronto

[Themes]
light_theme = Adwaita
dark_theme = Adwaita-dark

[BackgroundDay]
bg_hex1 = ADD8E6
bg_hex2 = 87CEEB
bg_dir = v

[ScreenDay]
xsct_temp = 6500
xsct_bright = 1.0

[BackgroundNight]
bg_hex1 = 1E1E2E
bg_hex2 = 000000
bg_dir = v

[ScreenNight]
xsct_temp = 4500
xsct_bright = 0.85
```



**Please procceed**


   development task will likely involve addressing the "Known Issues / Immediate Next Steps", starting with **implementing automated tests** for the `fluxfce_core` library or creating the **packaging setup** (`pyproject.toml`). Await further instructions on which to prioritize.



**Known Issues / Immediate Next Steps:**
1.  **Automated Testing:** The project completely lacks automated tests (unit/integration). This is the highest priority before adding significant new features or distributing widely.
2.  **Packaging:** No `pyproject.toml` or `setup.py` exists. Installation relies on manual PATH setup (symlink recommended). Proper packaging using `pip` is needed.
3.  **Documentation:** Docstrings within `fluxfce_core` are sparse. The `README.md` needs review and potentially minor updates based on the final code state.
4.  **Real-world Testing:** Needs more testing across different XFCE versions, login managers, and suspend/resume scenarios. Confirm `xsct` env injection works reliably across systems.
