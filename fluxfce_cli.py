#!/usr/bin/env python3

"""
fluxfce (CLI) - Simplified XFCE Theming Tool (Systemd Timer Version)

Command-line interface for managing automatic XFCE theme/background/screen
switching based on sunrise/sunset times using the fluxfce_core library.
This version uses systemd timers for scheduling, replacing atd.
"""

import argparse
import logging
import pathlib
import shutil
import subprocess
import sys

# Import the refactored core library API and exceptions
try:
    import fluxfce_core
    from fluxfce_core import exceptions as core_exc
    # For accessing constants like SCHEDULER_TIMER_NAME etc. directly if needed for output
    from fluxfce_core import (
        SCHEDULER_TIMER_NAME, SCHEDULER_SERVICE_NAME,
        LOGIN_SERVICE_NAME, RESUME_SERVICE_NAME,
        # SUNRISE_EVENT_TIMER_NAME, SUNSET_EVENT_TIMER_NAME # Not directly used in CLI output string formatting yet
    )
    from fluxfce_core import config as core_config # For CONFIG_FILE in enable command
except ImportError as e:
    print(f"Error: Failed to import the fluxfce_core library: {e}", file=sys.stderr)
    print(
        "Ensure fluxfce_core is installed or available in your Python path.",
        file=sys.stderr,
    )
    sys.exit(1)

# --- Global Variables ---
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
SCRIPT_PATH = str(pathlib.Path(__file__).resolve())
PYTHON_EXECUTABLE = sys.executable
DEPENDENCY_CHECKER_SCRIPT_NAME = "fluxfce_deps_check.py" # Assumed to be updated

log = logging.getLogger("fluxfce_cli")


# --- CLI Logging Setup ---
def setup_cli_logging(verbose: bool):
    """Configures logging for the CLI based on verbosity."""
    cli_log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=logging.WARNING, format="%(levelname)s: %(name)s: %(message)s"
    )

    log.setLevel(cli_log_level)
    if log.hasHandlers():
        log.handlers.clear()

    core_log_level = logging.DEBUG if verbose else logging.WARNING
    core_logger = logging.getLogger("fluxfce_core")
    core_logger.setLevel(core_log_level)
    if not core_logger.hasHandlers(): # Ensure core logger gets a handler if basicConfig didn't cover it
        core_handler = logging.StreamHandler(sys.stderr) # Core logs to stderr by default
        core_formatter = logging.Formatter("%(levelname)s: fluxfce_core: %(message)s")
        core_handler.setFormatter(core_formatter)
        core_logger.addHandler(core_handler)
        core_logger.propagate = False

    if cli_log_level <= logging.INFO:
        info_handler = logging.StreamHandler(sys.stdout)
        info_formatter = logging.Formatter("%(message)s") # CLI info messages are direct
        info_handler.setFormatter(info_formatter)
        info_handler.setLevel(logging.INFO)
        info_handler.addFilter(lambda record: record.levelno == logging.INFO)
        log.addHandler(info_handler)

    # General CLI errors/warnings/debug to stderr
    error_handler = logging.StreamHandler(sys.stderr)
    error_formatter = logging.Formatter("%(levelname)s: %(name)s: %(message)s") # Show CLI name
    error_handler.setFormatter(error_formatter)
    error_handler.setLevel(logging.DEBUG if verbose else logging.WARNING) # Capture debug for verbose
    log.addHandler(error_handler)

    log.propagate = False
    if verbose:
        log.debug("Verbose logging enabled for fluxfce_cli.")
        core_logger.debug("Verbose logging enabled for fluxfce_core (via CLI).")


# --- Output Formatting ---
def print_status(status_data: dict):
    """Formats and prints the status dictionary."""
    log.info("--- fluxfce Status ---")

    log.info("\n[Configuration]")
    if status_data["config"].get("error"):
        log.info(f"  Error loading config: {status_data['config']['error']}")
    else:
        log.info(f"  Location:      {status_data['config'].get('latitude', 'N/A')}, {status_data['config'].get('longitude', 'N/A')}")
        log.info(f"  Timezone:      {status_data['config'].get('timezone', 'N/A')}")
        log.info(f"  Light Theme:   {status_data['config'].get('light_theme', 'N/A')}")
        log.info(f"  Dark Theme:    {status_data['config'].get('dark_theme', 'N/A')}")

    log.info("\n[Calculated Sun Times (Today)]")
    if status_data["sun_times"].get("error"):
        log.info(f"  Error: {status_data['sun_times']['error']}")
    elif status_data["sun_times"].get("sunrise") and status_data["sun_times"].get("sunset"):
        sunrise_dt = status_data["sun_times"]["sunrise"]
        sunset_dt = status_data["sun_times"]["sunset"]
        try:
            log.info(f"  Sunrise:       {sunrise_dt.isoformat(sep=' ', timespec='seconds')}")
            log.info(f"  Sunset:        {sunset_dt.isoformat(sep=' ', timespec='seconds')}")
        except Exception:
            log.info(f"  Sunrise:       {sunrise_dt}")
            log.info(f"  Sunset:        {sunset_dt}")
    else:
        log.info("  Could not be calculated (check config/location).")
    log.info(f"  Current Period:  {status_data.get('current_period', 'unknown').capitalize()}")

    log.info("\n[Systemd Scheduling Timers]")
    schedule_info = status_data.get("schedule", {})
    if schedule_info.get("error"):
        log.info(f"  Error checking systemd timers: {schedule_info['error']}")
    else:
        timers = schedule_info.get("timers", {})
        if not timers and not schedule_info.get("info"): # No timers and no specific info message
             log.info("  Scheduler status unknown or no fluxfce timers found.")
        elif schedule_info.get("info"): # E.g. "No fluxfce timers found or listed."
             log.info(f"  Status: {schedule_info.get('info')}")

        for timer_name, details in timers.items():
            log.info(f"  Timer: {timer_name}")
            log.info(f"    Status:    {details.get('enabled', 'N/A')}, {details.get('active', 'N/A')}")
            log.info(f"    Next Run:  {details.get('next_run', 'N/A')}")
            #log.info(f"    Time Left: {details.get('time_left', 'N/A')}")
            log.info(f"    Last Run:  {details.get('last_run', 'N/A')}")
            log.info(f"    Activates: {details.get('activates', 'N/A')}")
        
        is_enabled = any(
            SCHEDULER_TIMER_NAME in name and ("Enabled" in details.get("enabled","") and "Active" in details.get("active",""))
            for name, details in timers.items()
        )
        if not timers and not schedule_info.get("error") and not schedule_info.get("info"):
             log.info("  Status: Disabled (No fluxfce timers configured or found)")
        elif not is_enabled and not schedule_info.get("error"):
            log.info("  Overall Status: Scheduling may be disabled or timers not active.")
            log.info("  (Run 'fluxfce enable' to enable automatic scheduling)")


    log.info("\n[Systemd Services (Login/Resume/Scheduler)]")
    systemd_services = status_data.get("systemd_services", {})
    if systemd_services.get("error"):
        log.info(f"  Error checking systemd services: {systemd_services['error']}")
    else:
        log.info(f"  Scheduler Timer State Checker ({SCHEDULER_SERVICE_NAME}): {systemd_services.get('scheduler_service', 'Unknown')}")
        log.info(f"  Login Service ({LOGIN_SERVICE_NAME}): {systemd_services.get('login_service', 'Unknown')}")
        log.info(f"  Resume Service ({RESUME_SERVICE_NAME}): {systemd_services.get('resume_service', 'Unknown')}")
        log.info("  (For detailed logs/status, use 'systemctl --user status ...' or 'journalctl --user -u ...')")

    log.info("-" * 25)


# --- User Interaction Helper ---
def ask_yes_no_cli(prompt: str, default_yes: bool = False) -> bool:
    """Asks a yes/no question and returns True for yes, False for no."""
    suffix = "[Y/n]" if default_yes else "[y/N]"
    while True:
        try:
            print(f"{prompt} {suffix}: ", end="", flush=True) # Direct print for prompt
            response = input().strip().lower()
            if not response:
                return default_yes
            if response in ["y", "yes"]:
                return True
            if response in ["n", "no"]:
                return False
            print("[WARN] Invalid input. Please enter 'y' or 'n'.") # Direct print for feedback
        except EOFError:
            print()
            return default_yes
        except KeyboardInterrupt:
            print("\nPrompt interrupted. Assuming 'no'.")
            return False


# --- Main Execution Logic ---
def main():
    """Parses command-line arguments and dispatches to appropriate command handlers."""
    parser = argparse.ArgumentParser(
        description="fluxfce (CLI): Manage XFCE appearance via sunrise/sunset timing (Systemd Timer Version).",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
Examples:
  fluxfce install          # Interactive setup, install units, and enable scheduling
  fluxfce status           # Show current status and configuration
  fluxfce day              # Apply Day mode now without disabling auto switching
  fluxfce night            # Apply Night mode now without disabling auto switching
  fluxfce enable           # Enable automatic scheduling (sets up systemd timers)
  fluxfce disable          # Disable automatic scheduling (clears systemd timers)
  fluxfce force-day        # Apply Day mode now and disable auto switching
  fluxfce force-night      # Apply Night mode now and disable auto switching
  fluxfce set-default --mode day # Save current desktop look as the new Day default
  fluxfce uninstall        # Remove systemd units and clear schedule (prompts for config removal)
""",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable detailed logging output."
    )
    subparsers = parser.add_subparsers(dest="command", title="Commands", required=True)

    subparsers.add_parser("install", help="Install systemd units and enable automatic scheduling.")
    subparsers.add_parser("uninstall", help="Remove systemd units & clear schedule (prompts to remove config).")
    subparsers.add_parser("day", help="Apply Day Mode settings now (leaves automatic scheduling enabled).")
    subparsers.add_parser("night", help="Apply Night Mode settings now (leaves automatic scheduling enabled).")
    subparsers.add_parser("enable", help="Enable automatic scheduling (configures systemd timers).")
    subparsers.add_parser("disable", help="Disable automatic scheduling (clears relevant systemd timers).")
    subparsers.add_parser("status", help="Show config, calculated times, and schedule status.")
    subparsers.add_parser("force-day", help="Apply Day Mode settings now (disables automatic scheduling).")
    subparsers.add_parser("force-night", help="Apply Night Mode settings now (disables automatic scheduling).")
    
    parser_set_default = subparsers.add_parser(
        "set-default", help="Save current desktop look as the new default for Day or Night mode."
    )
    parser_set_default.add_argument(
        "--mode", choices=["day", "night"], required=True, dest="default_mode",
        help="Specify whether to save as the Day or Night default."
    )

    # Internal commands, hidden from public help
    parser_internal_apply = subparsers.add_parser("internal-apply", help=argparse.SUPPRESS)
    parser_internal_apply.add_argument(
        "--mode", choices=["day", "night"], required=True, dest="internal_mode"
    )
    subparsers.add_parser("schedule-dynamic-transitions", help=argparse.SUPPRESS) # New internal command
    subparsers.add_parser("run-login-check", help=argparse.SUPPRESS)


    args = parser.parse_args()
    setup_cli_logging(args.verbose)
    exit_code = 0

    try:
        log.debug(f"Running command: {args.command}")
        log.debug(f"Script path: {SCRIPT_PATH}")
        log.debug(f"Python executable: {PYTHON_EXECUTABLE}")

        if args.command == "install":
            log.info("--- Step 1: Checking system dependencies ---")
            dependency_checker_script = SCRIPT_DIR / DEPENDENCY_CHECKER_SCRIPT_NAME
            if not dependency_checker_script.exists():
                log.error(f"Dependency checker script '{DEPENDENCY_CHECKER_SCRIPT_NAME}' not found in {SCRIPT_DIR}")
                sys.exit(1)
            
            log.info(f"Executing dependency checker: {dependency_checker_script}...")
            process = subprocess.run([PYTHON_EXECUTABLE, str(dependency_checker_script)], check=False, capture_output=False)
            if process.returncode != 0:
                log.error(f"Dependency check/setup failed (exit code: {process.returncode}). Aborting installation.")
                sys.exit(1)
            log.info("System dependency check passed or issues addressed.")
            log.info("--- Dependency check complete ---")

            log.info("\n--- Step 2: Configuring FluxFCE application settings ---")
            config_existed = fluxfce_core.CONFIG_FILE.exists()
            config_obj = fluxfce_core.get_current_config() # Loads or creates with defaults
            needs_saving = False

            run_interactive_setup = False
            if not config_existed:
                run_interactive_setup = True
                log.info("Configuration file not found. Starting interactive setup.")
            else:
                loc_section = "Location"
                current_lat = config_obj.get(loc_section, "LATITUDE", fallback=None)
                current_lon = config_obj.get(loc_section, "LONGITUDE", fallback=None)
                if (current_lat == core_config.DEFAULT_CONFIG[loc_section]["LATITUDE"] and \
                    current_lon == core_config.DEFAULT_CONFIG[loc_section]["LONGITUDE"]) or \
                   not current_lat or not current_lon:
                    log.info("Existing config found, but location seems default/missing.")
                    if ask_yes_no_cli("Run interactive setup for location/timezone?", default_yes=True):
                        run_interactive_setup = True
                    else:
                        log.info("Skipping interactive setup. Using current/default config values.")
                else:
                    log.info(f"Existing configuration found at {fluxfce_core.CONFIG_FILE}. Using it.")
            
            if run_interactive_setup:
                detected_tz = fluxfce_core.detect_system_timezone()
                current_tz_in_config = config_obj.get("Location", "TIMEZONE", fallback=core_config.DEFAULT_CONFIG["Location"]["TIMEZONE"])
                final_tz = current_tz_in_config

                if detected_tz:
                    print(f"\nDetected system timezone: '{detected_tz}'") # Direct print for interaction
                    if detected_tz != final_tz:
                        if ask_yes_no_cli(f"Use detected timezone '{detected_tz}' (current is '{final_tz}')?", default_yes=True):
                            final_tz = detected_tz
                    else:
                        print(f"Detected timezone matches current/default ('{final_tz}').")
                else:
                    print(f"\nCould not detect system timezone. Current is '{final_tz}'.")
                
                if config_obj.get("Location", "TIMEZONE") != final_tz:
                    config_obj.set("Location", "TIMEZONE", final_tz)
                    needs_saving = True
                print(f"Using timezone: {final_tz}")

                print("\nPlease provide location coordinates (e.g., 43.65N, 79.38W). Press Enter for defaults.")
                prompt_default_lat = config_obj.get("Location", "LATITUDE", fallback=core_config.DEFAULT_CONFIG["Location"]["LATITUDE"])
                prompt_default_lon = config_obj.get("Location", "LONGITUDE", fallback=core_config.DEFAULT_CONFIG["Location"]["LONGITUDE"])
                
                try:
                    lat_input = input(f"Enter Latitude [{prompt_default_lat}]: ").strip()
                    lon_input = input(f"Enter Longitude [{prompt_default_lon}]: ").strip()
                    
                    chosen_lat = lat_input if lat_input else prompt_default_lat
                    chosen_lon = lon_input if lon_input else prompt_default_lon

                    fluxfce_core.helpers.latlon_str_to_float(chosen_lat) # Validate
                    fluxfce_core.helpers.latlon_str_to_float(chosen_lon) # Validate

                    if config_obj.get("Location", "LATITUDE") != chosen_lat or \
                       config_obj.get("Location", "LONGITUDE") != chosen_lon:
                        config_obj.set("Location", "LATITUDE", chosen_lat)
                        config_obj.set("Location", "LONGITUDE", chosen_lon)
                        needs_saving = True
                    print(f"Using coordinates: Latitude={chosen_lat}, Longitude={chosen_lon}")
                except (EOFError, KeyboardInterrupt): print("\nInput skipped. Using previous/default coordinates.")
                except core_exc.ValidationError as e: print(f"\nWarning: Invalid coordinate input ({e}). Using previous/default.")
                except Exception as e_coord: print(f"\nWarning: Unexpected error ({e_coord}). Using previous/default.")
            
            if needs_saving or not config_existed:
                log.info("Saving initial/updated FluxFCE configuration...")
                fluxfce_core.save_configuration(config_obj)
            log.info("--- FluxFCE application configuration complete ---")

            log.info("\n--- Step 3: Installing systemd units ---")
            fluxfce_core.install_fluxfce(script_path=SCRIPT_PATH, python_executable=PYTHON_EXECUTABLE)
            log.info("Static systemd units installed.")

            log.info("\n--- Step 4: Enabling automatic scheduling ---")
            # This will set up initial dynamic timers and enable the main scheduler.timer
            fluxfce_core.enable_scheduling(python_exe_path=PYTHON_EXECUTABLE, script_exe_path=SCRIPT_PATH)
            log.info("Automatic theme scheduling enabled via systemd timers.")

            log.info("\n" + "-" * 45 + "\n fluxfce installed and enabled successfully. \n" + "-" * 45 + "\n")
            # ... (Instructions for PATH setup remain similar) ...
            user_bin_dir = pathlib.Path.home() / ".local" / "bin"
            log.info("IMPORTANT: To run 'fluxfce' easily from your terminal, ensure")
            log.info(f"the script ({pathlib.Path(SCRIPT_PATH).name}) or a symlink to it is in your PATH.")
            log.info(f"Recommended: ln -s -f \"{SCRIPT_PATH}\" \"{user_bin_dir / 'fluxfce'}\" (after ensuring {user_bin_dir} is in PATH)")
            log.info("\nTip: Configure Day/Night appearance using 'fluxfce set-default --mode day|night'.")
            log.info("Check 'fluxfce status' to see the current setup.")

        elif args.command == "uninstall":
            log.info("Starting uninstallation (system components)...")
            # disable_scheduling is now called within uninstall_fluxfce in the API
            fluxfce_core.uninstall_fluxfce()
            log.info("FluxFCE systemd units removed and schedule cleared/dynamic timers removed.")

            config_dir_path = fluxfce_core.CONFIG_DIR
            if config_dir_path.exists():
                log.warning(f"\nConfiguration directory found at: {config_dir_path}")
                if ask_yes_no_cli("Do you want to REMOVE this configuration directory?", default_yes=False):
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
            log.info("Day mode applied. Automatic scheduling remains active.")

        elif args.command == "night":
            log.info("Applying Night mode (scheduling will remain active)...")
            fluxfce_core.apply_temporary_mode("night")
            log.info("Night mode applied. Automatic scheduling remains active.")

        elif args.command == "enable":
            log.info("Enabling scheduling via systemd timers...")
            if not core_config.CONFIG_FILE.exists(): # Use imported core_config
                log.error(f"Configuration file {core_config.CONFIG_FILE} not found.")
                log.error("Please run 'fluxfce install' first or ensure config is in place.")
                exit_code = 1
            else:
                fluxfce_core.enable_scheduling(
                    python_exe_path=PYTHON_EXECUTABLE, script_exe_path=SCRIPT_PATH
                )
                log.info("Automatic theme scheduling enabled using systemd timers.")
                log.info("Run 'fluxfce status' to see scheduled timers.")

        elif args.command == "disable":
            log.info("Disabling scheduling (systemd timers)...")
            fluxfce_core.disable_scheduling()
            log.info("Automatic theme scheduling disabled (main scheduler & dynamic event timers stopped/removed).")

        elif args.command == "status":
            status = fluxfce_core.get_status()
            print_status(status)

        elif args.command == "force-day":
            log.info("Forcing Day mode...")
            fluxfce_core.apply_manual_mode("day") # This also disables scheduling
            log.info("Day mode applied. Automatic scheduling (systemd timers) disabled.")

        elif args.command == "force-night":
            log.info("Forcing Night mode...")
            fluxfce_core.apply_manual_mode("night") # This also disables scheduling
            log.info("Night mode applied. Automatic scheduling (systemd timers) disabled.")

        elif args.command == "set-default":
            mode = args.default_mode
            log.info(f"Setting current look as default for {mode} mode...")
            fluxfce_core.set_default_from_current(mode)
            log.info(f"Current desktop settings saved as default for {mode.capitalize()} mode.")
            log.info("(Run 'fluxfce enable' to (re)activate scheduling with new defaults).")

        elif args.command == "internal-apply":
            mode = args.internal_mode
            log.debug(f"CLI: Executing internal-apply for mode '{mode}' (called by systemd service)")
            success = fluxfce_core.handle_internal_apply(mode)
            exit_code = 0 if success else 1
        
        elif args.command == "schedule-dynamic-transitions": # New internal command
            log.debug("CLI: Executing schedule-dynamic-transitions (called by systemd scheduler service)")
            success = fluxfce_core.handle_schedule_dynamic_transitions_command(
                python_exe_path=PYTHON_EXECUTABLE, script_exe_path=SCRIPT_PATH
            )
            exit_code = 0 if success else 1

        elif args.command == "run-login-check":
            log.debug("CLI: Executing run-login-check (called by systemd login/resume service)")
            success = fluxfce_core.handle_run_login_check()
            exit_code = 0 if success else 1
        else:
            log.error(f"Unknown command: {args.command}")
            parser.print_help(sys.stderr)
            exit_code = 1

    except core_exc.FluxFceError as e:
        log.error(f"FluxFCE Error: {e}", exc_info=args.verbose)
        exit_code = 1
    except Exception as e_main: # Catchall for unexpected errors
        log.error(f"An unexpected error occurred in CLI: {e_main}", exc_info=True)
        exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()