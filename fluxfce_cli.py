#!/usr/bin/env python3

"""
fluxfce (CLI) - Simplified Desktop Theming Tool

Command-line interface for managing automatic theme/background/screen
switching for supported desktop environments using the fluxfce_core library.
"""

import argparse
import configparser
import json
import logging
import pathlib
import shutil
import subprocess
import sys
from datetime import datetime

# Import the refactored core library API and exceptions
try:
    import fluxfce_core
    from fluxfce_core import exceptions as core_exc
    from fluxfce_core import (
        SCHEDULER_TIMER_NAME, SCHEDULER_SERVICE_NAME,
        LOGIN_SERVICE_NAME, RESUME_SERVICE_NAME
    )
    from fluxfce_core import config as core_config
    from fluxfce_core import install_default_background_profiles
except ImportError as e:
    print(f"Error: Failed to import the fluxfce_core library: {e}", file=sys.stderr)
    print("Ensure fluxfce_core is installed or available in your Python path.", file=sys.stderr)
    sys.exit(1)

# --- Global Variables ---
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
SCRIPT_PATH = str(pathlib.Path(__file__).resolve())
PYTHON_EXECUTABLE = sys.executable
DEPENDENCY_CHECKER_SCRIPT_NAME = "fluxfce_deps_check.py"
TIMEZONES_JSON_PATH = SCRIPT_DIR / "fluxfce_core" / "assets" / "timezones.json"

log = logging.getLogger("fluxfce_cli")

# --- ANSI Color Codes for Terminal Output ---
# Check if stdout is a TTY (interactive terminal) to decide whether to use colors.
IS_TTY = sys.stdout.isatty()

class AnsiColors:
    GREEN = "\033[92m" if IS_TTY else ""
    RED = "\033[91m" if IS_TTY else ""
    YELLOW = "\033[93m" if IS_TTY else ""
    RESET = "\033[0m" if IS_TTY else ""


# --- CLI Logging Setup ---
def setup_cli_logging(verbose: bool):
    """Configures logging for the CLI based on verbosity."""
    cli_log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(name)s: %(message)s")

    log.setLevel(cli_log_level)
    if log.hasHandlers():
        log.handlers.clear()

    core_log_level = logging.DEBUG if verbose else logging.WARNING
    core_logger = logging.getLogger("fluxfce_core")
    core_logger.setLevel(core_log_level)
    if not core_logger.hasHandlers():
        core_handler = logging.StreamHandler(sys.stderr)
        core_formatter = logging.Formatter("%(levelname)s: fluxfce_core: %(message)s")
        core_handler.setFormatter(core_formatter)
        core_logger.addHandler(core_handler)
        core_logger.propagate = False

    if cli_log_level <= logging.INFO:
        info_handler = logging.StreamHandler(sys.stdout)
        info_formatter = logging.Formatter("%(message)s")
        info_handler.setFormatter(info_formatter)
        info_handler.setLevel(logging.INFO)
        info_handler.addFilter(lambda record: record.levelno == logging.INFO)
        log.addHandler(info_handler)

    error_handler = logging.StreamHandler(sys.stderr)
    error_formatter = logging.Formatter("%(levelname)s: %(name)s: %(message)s")
    error_handler.setFormatter(error_formatter)
    error_handler.setLevel(logging.DEBUG if verbose else logging.WARNING)
    log.addHandler(error_handler)

    log.propagate = False
    if verbose:
        log.debug("Verbose logging enabled for fluxfce_cli.")
        core_logger.debug("Verbose logging enabled for fluxfce_core (via CLI).")


# --- Output Formatting ---
def print_status(status_data: dict, verbose: bool = False):
    """Formats and prints the status dictionary with colors."""
    log.info("--- fluxfce Status ---")
    summary = status_data.get("summary", {})

    log.info("\n[Scheduling Status]")
    
    status_text = summary.get("overall_status", "[UNKNOWN]")
    if "[OK]" in status_text:
        status_str = f"{AnsiColors.GREEN}{status_text}{AnsiColors.RESET}"
    elif "[DISABLED]" in status_text or "[ERROR]" in status_text:
        status_str = f"{AnsiColors.RED}{status_text}{AnsiColors.RESET}"
    else:  # For "[UNKNOWN]"
        status_str = f"{AnsiColors.YELLOW}{status_text}{AnsiColors.RESET}"
    
    if summary.get("overall_status"):
        log.info(f"  Overall Status:  {status_str} {summary.get('status_message', '')}")

    if summary.get("recommendation"):
        log.info(f"  Recommendation:  {summary['recommendation']}")

    if summary.get("overall_status") == "[OK]":
        log.info("\n[Upcoming Events]")
        next_trans_time = summary.get("next_transition_time")
        next_trans_mode = summary.get("next_transition_mode")

        if next_trans_time and next_trans_mode:
            now = datetime.now(next_trans_time.tzinfo)
            delta = next_trans_time - now
            hours, rem = divmod(delta.total_seconds(), 3600)
            minutes, _ = divmod(rem, 60)
            
            if delta.total_seconds() < 0: time_left_str = "in the past"
            elif hours >= 1: time_left_str = f"in approx. {int(hours)}h {int(minutes)}m"
            else: time_left_str = "soon"
            
            log.info(f"  Next Transition: Apply '{next_trans_mode}' mode at {next_trans_time.strftime('%H:%M:%S')} ({time_left_str})")
        
        if resched_time := summary.get("reschedule_time"):
            log.info(f"  Daily Reschedule: Next check at {resched_time.strftime('%a %H:%M:%S')}")

    if verbose:
        log.info("\n--- Verbose Details ---")
        log.info("\n[Configuration]")
        if status_data["config"].get("error"):
            log.info(f"  Error loading config: {status_data['config']['error']}")
        else:
            cfg = status_data['config']
            log.info(f"  Location:         {cfg.get('latitude', 'N/A')}, {cfg.get('longitude', 'N/A')}")
            log.info(f"  Timezone:         {cfg.get('timezone', 'N/A')}")
            log.info(f"  Light Theme:      {cfg.get('light_theme', 'N/A')}")
            log.info(f"  Dark Theme:       {cfg.get('dark_theme', 'N/A')}")
            log.info(f"  Day BG Profile:   {cfg.get('day_bg_profile', 'N/A')}")
            log.info(f"  Night BG Profile: {cfg.get('night_bg_profile', 'N/A')}")

        log.info("\n[Calculated Sun Times (Today)]")
        if status_data["sun_times"].get("error"):
            log.info(f"  Error: {status_data['sun_times']['error']}")
        elif status_data["sun_times"].get("sunrise") and status_data["sun_times"].get("sunset"):
            log.info(f"  Sunrise:          {status_data['sun_times']['sunrise'].isoformat(sep=' ', timespec='seconds')}")
            log.info(f"  Sunset:           {status_data['sun_times']['sunset'].isoformat(sep=' ', timespec='seconds')}")
        else:
            log.info("  Could not be calculated.")
        log.info(f"  Current Period:   {status_data.get('current_period', 'unknown').capitalize()}")

        log.info("\n[Systemd Services (Login/Resume/Scheduler)]")
        systemd = status_data.get("systemd_services", {})
        if systemd.get("error"):
            log.info(f"  Error checking services: {systemd['error']}")
        else:
            log.info(f"  Scheduler Service ({SCHEDULER_SERVICE_NAME}): {systemd.get('scheduler_service', 'Unknown')}")
            log.info(f"  Login Service ({LOGIN_SERVICE_NAME}): {systemd.get('login_service', 'Unknown')}")
            log.info(f"  Resume Service ({RESUME_SERVICE_NAME}): {systemd.get('resume_service', 'Unknown')}")
    else:
        log.info("\n(Run with -v for detailed configuration and systemd service status)")
    log.info("-" * 25)


# --- User Interaction Helpers ---
def ask_yes_no_cli(prompt: str, default_yes: bool = False) -> bool:
    """Asks a yes/no question and returns True for yes, False for no."""
    suffix = "[Y/n]" if default_yes else "[y/N]"
    while True:
        try:
            print(f"{prompt} {suffix}: ", end="", flush=True)
            response = input().strip().lower()
            if not response: return default_yes
            if response in ["y", "yes"]: return True
            if response in ["n", "no"]: return False
            print(f"{AnsiColors.YELLOW}[WARN] Invalid input. Please enter 'y' or 'n'.{AnsiColors.RESET}")
        except (EOFError, KeyboardInterrupt):
            print("\nPrompt interrupted. Assuming 'no'.")
            return False

def _interactive_setup() -> configparser.ConfigParser:
    """
    Guides the user through an interactive setup for the first run.
    Detects timezone and offers to set coordinates from a local database.
    """
    log.info("First-time setup: No configuration file found.")
    log.info("Let's configure your location for sunrise/sunset calculations.")
    
    config_obj = core_config.ConfigManager().load_config()
    user_tz = None

    # 1. TIMEZONE
    detected_tz = fluxfce_core.detect_system_timezone()
    if detected_tz and ask_yes_no_cli(f"Detected timezone '{detected_tz}'. Use this?", default_yes=True):
        user_tz = detected_tz
    else:
        while True:
            try:
                tz_input = input("Please enter your IANA timezone (e.g., America/Toronto, Europe/London): ").strip()
                from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
                ZoneInfo(tz_input)
                user_tz = tz_input
                break
            except ZoneInfoNotFoundError:
                log.error(f"'{tz_input}' is not a valid IANA timezone. Please try again.")
            except (EOFError, KeyboardInterrupt):
                log.error("\nSetup interrupted. Cannot continue without a timezone.")
                sys.exit(1)
    config_obj.set("Location", "TIMEZONE", user_tz)

    # 2. COORDINATES (with suggestion from JSON)
    coords_set = False
    if TIMEZONES_JSON_PATH.exists() and user_tz:
        try:
            with TIMEZONES_JSON_PATH.open("r", encoding="utf-8") as f:
                tz_data = json.load(f)
            for city, data in tz_data.items():
                if data.get("timezone") == user_tz:
                    lat, lon = data.get("latitude"), data.get("longitude")
                    prompt = f"Found a match for '{user_tz}': {city}. Use these coordinates ({lat}, {lon})?"
                    if ask_yes_no_cli(prompt, default_yes=True):
                        config_obj.set("Location", "LATITUDE", lat)
                        config_obj.set("Location", "LONGITUDE", lon)
                        coords_set = True
                    break
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Could not load or parse timezones.json: {e}. Proceeding with manual entry.")
    
    if not coords_set:
        log.info("\nPlease provide your geographic coordinates.")
        log.info("You can find them at a site like https://www.latlong.net/")
        while True:
            try:
                lat_input = input("Enter Latitude (e.g., 43.65N): ").strip()
                fluxfce_core.helpers.latlon_str_to_float(lat_input)
                config_obj.set("Location", "LATITUDE", lat_input)
                break
            except core_exc.ValidationError as e:
                log.error(f"Invalid latitude format: {e}")
            except (EOFError, KeyboardInterrupt):
                log.error("\nSetup interrupted. Cannot continue without coordinates.")
                sys.exit(1)
                
        while True:
            try:
                lon_input = input("Enter Longitude (e.g., 79.38W): ").strip()
                fluxfce_core.helpers.latlon_str_to_float(lon_input)
                config_obj.set("Location", "LONGITUDE", lon_input)
                break
            except core_exc.ValidationError as e:
                log.error(f"Invalid longitude format: {e}")
            except (EOFError, KeyboardInterrupt):
                log.error("\nSetup interrupted. Cannot continue without coordinates.")
                sys.exit(1)
            
    log.info(f"{AnsiColors.GREEN}Location configured successfully.{AnsiColors.RESET}")
    return config_obj


# --- Main Execution Logic ---
def main():
    """Parses command-line arguments and dispatches to appropriate command handlers."""
    parser = argparse.ArgumentParser(
        description="fluxfce (CLI): Manage XFCE appearance via sunrise/sunset timing.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
Examples:
  fluxfce install          # Interactive setup, install units, and enable scheduling
  fluxfce status -v        # Show detailed status, including profiles and services
  fluxfce day              # Apply Day mode now without disabling auto switching
  fluxfce enable           # Enable automatic scheduling (sets up systemd timers)
  fluxfce set-default --mode day # Save current desktop look as the new Day default
  fluxfce uninstall        # Remove systemd units and schedule (prompts for config removal)
""",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable detailed logging output.")
    subparsers = parser.add_subparsers(dest="command", title="Commands", required=True)

    subparsers.add_parser("install", help="Install systemd units and enable automatic scheduling.")
    subparsers.add_parser("uninstall", help="Remove systemd units & clear schedule (prompts to remove config).")
    subparsers.add_parser("day", help="Apply Day Mode settings now (leaves auto scheduling enabled).")
    subparsers.add_parser("night", help="Apply Night Mode settings now (leaves auto scheduling enabled).")
    subparsers.add_parser("enable", help="Enable automatic scheduling (configures systemd timers).")
    subparsers.add_parser("disable", help="Disable automatic scheduling (clears relevant systemd timers).")
    subparsers.add_parser("status", help="Show config, calculated times, and schedule status.")
    subparsers.add_parser("force-day", help="Apply Day Mode settings now (disables auto scheduling).")
    subparsers.add_parser("force-night", help="Apply Night Mode settings now (disables auto scheduling).")
    
    parser_set_default = subparsers.add_parser("set-default", help="Save current desktop look as the new default for Day or Night mode.")
    parser_set_default.add_argument("--mode", choices=["day", "night"], required=True, dest="default_mode")

    # Internal commands, hidden from public help
    parser_internal_apply = subparsers.add_parser("internal-apply", help=argparse.SUPPRESS)
    parser_internal_apply.add_argument("--mode", choices=["day", "night"], required=True, dest="internal_mode")
    subparsers.add_parser("schedule-dynamic-transitions", help=argparse.SUPPRESS)
    subparsers.add_parser("run-login-check", help=argparse.SUPPRESS)

    args = parser.parse_args()
    setup_cli_logging(args.verbose)
    exit_code = 0

    try:
        log.debug(f"Running command: {args.command}")

        if args.command == "install":
            log.info("--- Step 1: Checking system dependencies ---")
            dep_checker = SCRIPT_DIR / DEPENDENCY_CHECKER_SCRIPT_NAME
            if not dep_checker.exists():
                log.error(f"Dependency checker '{DEPENDENCY_CHECKER_SCRIPT_NAME}' not found.")
                sys.exit(1)
            
            process = subprocess.run([PYTHON_EXECUTABLE, str(dep_checker)], check=False)
            if process.returncode != 0:
                log.error("Dependency check/setup failed. Aborting installation.")
                sys.exit(1)
            log.info(f"{AnsiColors.GREEN}--- Dependency check complete ---{AnsiColors.RESET}")

            log.info("\n--- Step 2: Configuring FluxFCE application settings ---")
            if not fluxfce_core.CONFIG_FILE.exists():
                config_obj = _interactive_setup()
                fluxfce_core.save_configuration(config_obj)
            else:
                log.info(f"Existing configuration found at {fluxfce_core.CONFIG_FILE}. Skipping interactive setup.")
            log.info(f"{AnsiColors.GREEN}--- FluxFCE application configuration complete ---{AnsiColors.RESET}")

            # DE-aware step: Install DE-specific default background profiles
            de = fluxfce_core.helpers.get_desktop_environment()
            if de == "XFCE":
                log.info("\n--- Step 2b: Installing default background profiles for XFCE ---")
                fluxfce_core.install_default_background_profiles()
            elif de == "CINNAMON":
                log.info("\n--- Step 2b: Installing default background profiles for Cinnamon ---")
                # Import the new function
                from fluxfce_core.api import install_default_cinnamon_profiles
                install_default_cinnamon_profiles()

            log.info("Default background profiles created. Use 'fluxfce set-default' to customize them.")

            log.info("\n--- Step 3: Installing systemd units ---")
            fluxfce_core.install_fluxfce(script_path=SCRIPT_PATH, python_executable=PYTHON_EXECUTABLE)

            log.info("\n--- Step 4: Enabling automatic scheduling ---")
            fluxfce_core.enable_scheduling(python_exe_path=PYTHON_EXECUTABLE, script_exe_path=SCRIPT_PATH)

            log.info("\n" + "-"*45 + f"\n {AnsiColors.GREEN}fluxfce installed and enabled successfully.{AnsiColors.RESET} \n" + "-"*45)
            log.info("Tip: Configure your look using 'fluxfce set-default --mode day|night'.")
            
            if ask_yes_no_cli("\nLaunch the graphical user interface now?", default_yes=True):
                gui_script_path = SCRIPT_DIR / "fluxfce_gui.py"
                if gui_script_path.exists():
                    log.info(f"Launching GUI from: {gui_script_path}")
                    try:
                        subprocess.Popen(
                            [PYTHON_EXECUTABLE, str(gui_script_path)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            start_new_session=True, # Detach from terminal
                        )
                    except Exception as e:
                        log.error(f"Failed to launch the GUI: {e}")
                else:
                    log.error(f"Could not find the GUI script at {gui_script_path}")

        elif args.command == "uninstall":
            log.info("Starting uninstallation (system components)...")
            fluxfce_core.uninstall_fluxfce()
            log.info("FluxFCE systemd units removed and schedule cleared.")

            config_dir_path = fluxfce_core.CONFIG_DIR
            if config_dir_path.exists():
                log.warning(f"\nConfiguration directory found at: {config_dir_path}")
                if ask_yes_no_cli("Do you want to REMOVE this configuration directory and all profiles?", default_yes=False):
                    try:
                        shutil.rmtree(config_dir_path)
                        log.info(f"Removed configuration directory: {config_dir_path}")
                    except OSError as e:
                        log.error(f"Error removing config directory {config_dir_path}: {e}")
                else:
                    log.info("Configuration directory kept.")
            log.info("\n--- Uninstallation Complete ---")

        elif args.command == "day":
            log.info("Applying Day mode (scheduling will remain active)...")
            fluxfce_core.apply_temporary_mode("day")

        elif args.command == "night":
            log.info("Applying Night mode (scheduling will remain active)...")
            fluxfce_core.apply_temporary_mode("night")

        elif args.command == "enable":
            log.info("Enabling scheduling via systemd timers...")
            if not core_config.CONFIG_FILE.exists():
                log.error(f"Config file {core_config.CONFIG_FILE} not found. Run 'install' first.")
                exit_code = 1
            else:
                fluxfce_core.enable_scheduling(python_exe_path=PYTHON_EXECUTABLE, script_exe_path=SCRIPT_PATH)
                log.info("Automatic theme scheduling enabled.")

        elif args.command == "disable":
            log.info("Disabling scheduling (systemd timers)...")
            fluxfce_core.disable_scheduling()
            log.info("Automatic theme scheduling disabled.")

        elif args.command == "status":
            status = fluxfce_core.get_status()
            print_status(status, verbose=args.verbose)

        elif args.command == "force-day":
            log.info("Forcing Day mode and disabling scheduling...")
            fluxfce_core.apply_manual_mode("day")

        elif args.command == "force-night":
            log.info("Forcing Night mode and disabling scheduling...")
            fluxfce_core.apply_manual_mode("night")

        elif args.command == "set-default":
            mode = args.default_mode
            log.info(f"Setting current look as default for {mode.capitalize()} mode...")
            log.info("This will save the current GTK theme, screen settings, and overwrite the")
            log.info(f"'{mode}' background profile with your current desktop background(s).")
            fluxfce_core.set_default_from_current(mode)
            log.info(f"Current desktop settings saved as default for {mode.capitalize()} mode.")

        elif args.command == "internal-apply":
            success = fluxfce_core.handle_internal_apply(args.internal_mode)
            exit_code = 0 if success else 1
        
        elif args.command == "schedule-dynamic-transitions":
            success = fluxfce_core.handle_schedule_dynamic_transitions_command(
                python_exe_path=PYTHON_EXECUTABLE, script_exe_path=SCRIPT_PATH
            )
            exit_code = 0 if success else 1

        elif args.command == "run-login-check":
            success = fluxfce_core.handle_run_login_check()
            exit_code = 0 if success else 1
        else:
            log.error(f"Unknown command: {args.command}")
            parser.print_help(sys.stderr)
            exit_code = 1

    except core_exc.FluxFceError as e:
        log.error(f"{AnsiColors.RED}FluxFCE Error: {e}{AnsiColors.RESET}", exc_info=args.verbose)
        exit_code = 1
    except Exception as e_main:
        log.error(f"{AnsiColors.RED}An unexpected error occurred in CLI: {e_main}{AnsiColors.RESET}", exc_info=True)
        exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()