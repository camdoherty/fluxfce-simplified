#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
fluxfce (CLI) - Simplified XFCE Theming Tool

Command-line interface for managing automatic XFCE theme/background/screen
switching based on sunrise/sunset times using the fluxfce_core library.
"""

import argparse
import logging
import os
import sys
import traceback
import pathlib
import shutil
from datetime import datetime
from fluxfce_core import helpers as core_helpers
from fluxfce_core import config as core_config

# Import the refactored core library API and exceptions
try:
    # Import the package itself
    import fluxfce_core
    # Import the exceptions submodule separately if needed, or rely on __init__.py exposing them
    from fluxfce_core import exceptions as core_exc
except ImportError as e:
    print(f"Error: Failed to import the fluxfce_core library: {e}", file=sys.stderr)
    print("Ensure fluxfce_core is installed or available in your Python path.", file=sys.stderr)
    sys.exit(1)

# --- Global Variables ---
# Resolve the path of the currently running script
SCRIPT_PATH = str(pathlib.Path(__file__).resolve())
PYTHON_EXECUTABLE = sys.executable
log = logging.getLogger('fluxfce_cli')


# --- CLI Logging Setup ---
def setup_cli_logging(verbose: bool):
    """Configures logging for the CLI based on verbosity."""
    cli_log_level = logging.DEBUG if verbose else logging.INFO
    # Basic config first to ensure root logger has a handler if needed
    logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(name)s: %(message)s')

    # Configure our CLI logger specifically
    log.setLevel(cli_log_level)
    log.handlers.clear() # Remove default handlers from basicConfig if any attached here

    # Configure core library logging level directly
    core_log_level = logging.DEBUG if verbose else logging.WARNING
    logging.getLogger('fluxfce_core').setLevel(core_log_level)
    # Ensure the core logger also has a handler if basicConfig didn't cover it
    if not logging.getLogger('fluxfce_core').hasHandlers():
         core_handler = logging.StreamHandler(sys.stderr)
         core_formatter = logging.Formatter('%(levelname)s: %(name)s: %(message)s')
         core_handler.setFormatter(core_formatter)
         logging.getLogger('fluxfce_core').addHandler(core_handler)

    # Simpler console output for CLI INFO messages to stdout
    if cli_log_level <= logging.INFO:
        info_handler = logging.StreamHandler(sys.stdout)
        info_formatter = logging.Formatter('%(message)s') # Just the message
        info_handler.setFormatter(info_formatter)
        info_handler.setLevel(logging.INFO)
        # Filter out lower/higher levels from this stdout handler
        info_handler.addFilter(lambda record: record.levelno == logging.INFO)
        log.addHandler(info_handler)

    # Handler for CLI debug/warning/error to stderr
    error_handler = logging.StreamHandler(sys.stderr)
    error_formatter = logging.Formatter('%(levelname)s: %(message)s') # Level prefix for non-info
    error_handler.setFormatter(error_formatter)
    # Show DEBUG only if verbose, otherwise WARNING+
    error_handler.setLevel(logging.DEBUG if verbose else logging.WARNING)
    log.addHandler(error_handler)

    log.propagate = False # Prevent double logging

    log.debug("Verbose logging enabled.")


# --- Output Formatting ---
def print_status(status_data: dict):
    """Formats and prints the status dictionary."""
    print("--- fluxfce Status ---")

    # Config (Keep as before)
    print("\n[Configuration]")
    if status_data['config'].get('error'):
        print(f"  Error loading config: {status_data['config']['error']}")
    else:
        print(f"  Location:      {status_data['config'].get('latitude', 'N/A')}, {status_data['config'].get('longitude', 'N/A')}")
        print(f"  Timezone:      {status_data['config'].get('timezone', 'N/A')}")
        print(f"  Light Theme:   {status_data['config'].get('light_theme', 'N/A')}")
        print(f"  Dark Theme:    {status_data['config'].get('dark_theme', 'N/A')}")

    # State (Keep as before - or remove if state file removal step is done)
    # print("\n[State]")
    # if status_data['state'].get('error'):
    #     print(f"  Error reading state: {status_data['state']['error']}")
    # else:
    #     last_state = status_data['state'].get('last_auto_applied')
    #     print(f"  Last Auto-Applied: {last_state or 'Unknown'}")

    # Calculated Sun Times & Period (Keep as before)
    print("\n[Calculated Sun Times (Today)]")
    if status_data['sun_times'].get('error'):
         print(f"  Error: {status_data['sun_times']['error']}")
    elif status_data['sun_times'].get('sunrise') and status_data['sun_times'].get('sunset'):
        sunrise_dt = status_data['sun_times']['sunrise']
        sunset_dt = status_data['sun_times']['sunset']
        try:
            print(f"  Sunrise:       {sunrise_dt.isoformat(sep=' ', timespec='seconds')}")
            print(f"  Sunset:        {sunset_dt.isoformat(sep=' ', timespec='seconds')}")
        except Exception:
             print(f"  Sunrise:       {sunrise_dt}")
             print(f"  Sunset:        {sunset_dt}")
    else:
        print("  Could not be calculated (check config/location).")
    print(f"  Current Period:  {status_data.get('current_period', 'unknown').capitalize()}")

    # Schedule (Keep as before)
    print("\n[Scheduled Transitions ('at' jobs)]")
    if status_data['schedule'].get('error'):
         print(f"  Error checking schedule: {status_data['schedule']['error']}")
    else:
        jobs = status_data['schedule'].get('jobs', [])
        enabled = status_data['schedule'].get('enabled', False)
        if jobs:
             print(f"  Status:        Enabled ({len(jobs)} job(s) found)")
             for job in jobs:
                  job_id = job.get('id', 'N/A')
                  mode = job.get('mode', 'unknown').capitalize()
                  time_str = job.get('time_str', 'Unknown Time')
                  print(f"  - Job {job_id}: {mode} at {time_str}")
        elif enabled:
             print("  Status:        Enabled (No specific jobs found - state mismatch?)")
        else:
             print("  Status:        Disabled")
             print("  (Run 'fluxfce enable' to schedule transitions)")

    # Systemd (UPDATED TO INCLUDE RESUME SERVICE)
    print("\n[Systemd Units]")
    if status_data['systemd'].get('error'):
         print(f"  Error checking systemd status: {status_data['systemd']['error']}")
    else:
         # Use the distinct keys generated in the API layer
         timer_status = status_data['systemd'].get('scheduler_timer', 'Unknown')
         service_status = status_data['systemd'].get('scheduler_service', 'Unknown')
         login_status = status_data['systemd'].get('login_service', 'Unknown')
         resume_status = status_data['systemd'].get('resume_service', 'Unknown') # <-- Get resume status

         # Access constants directly via fluxfce_core thanks to __init__.py update
         print(f"  Scheduler Timer ({fluxfce_core.SCHEDULER_TIMER_NAME}): {timer_status}")
         print(f"  Scheduler Service ({fluxfce_core.SCHEDULER_SERVICE_NAME}): {service_status}")
         print(f"  Login Service ({fluxfce_core.LOGIN_SERVICE_NAME}): {login_status}")
         print(f"  Resume Service ({fluxfce_core.RESUME_SERVICE_NAME}): {resume_status}") # <-- Print resume status
         print("  (For detailed logs/status, use 'systemctl --user status ...' or 'journalctl --user -u ...')")

    print("-" * 25)

# --- Main Execution Logic ---
def main():
    parser = argparse.ArgumentParser(
        description="fluxfce (CLI): Manage XFCE appearance via sunrise/sunset timing.",
        formatter_class=argparse.RawTextHelpFormatter, # Keep formatting in help
        epilog="""
Examples:
  fluxfce install          # Interactive setup and enable
  fluxfce status           # Show current status and configuration
  fluxfce enable           # Enable automatic switching
  fluxfce disable          # Disable automatic switching
  fluxfce force-day        # Apply Day mode now and disable auto switching
  fluxfce force-night      # Apply Night mode now and disable auto switching
  fluxfce set-default --day # Save current desktop look as the new Day default
  fluxfce uninstall        # Remove systemd units and clear schedule (prompts for config removal)
"""
    )
    parser.add_argument('-v', '--verbose', action='store_true', help="Enable detailed logging output.")

    subparsers = parser.add_subparsers(dest='command', title='Commands', required=True)

    # Define Simplified Commands
    subparsers.add_parser('install', help='Install systemd units and enable automatic scheduling.')
    subparsers.add_parser('uninstall', help='Remove systemd units & clear schedule (prompts to remove config).')
    subparsers.add_parser('enable', help='Enable automatic scheduling (schedules transitions).')
    subparsers.add_parser('disable', help='Disable automatic scheduling (clears scheduled transitions).')
    subparsers.add_parser('status', help='Show config, calculated times, and schedule status.')
    subparsers.add_parser('force-day', help='Apply Day Mode settings now (disables automatic scheduling).')
    subparsers.add_parser('force-night', help='Apply Night Mode settings now (disables automatic scheduling).')

    parser_set_default = subparsers.add_parser('set-default', help='Save current desktop look as the new default for Day or Night mode.')
    parser_set_default.add_argument('--mode', choices=['day', 'night'], required=True, dest='default_mode', help='Specify whether to save as the Day or Night default.')

    # --- Internal Commands (Hidden) ---
    parser_internal = subparsers.add_parser('internal-apply', help=argparse.SUPPRESS)
    parser_internal.add_argument('--mode', choices=['day', 'night'], required=True, dest='internal_mode')

    subparsers.add_parser('schedule-jobs', help=argparse.SUPPRESS)
    subparsers.add_parser('run-login-check', help=argparse.SUPPRESS)

    args = parser.parse_args()

    # --- Setup & Dispatch ---
    setup_cli_logging(args.verbose)
    exit_code = 0 # Default to success

    try:
        log.debug(f"Running command: {args.command}")
        log.debug(f"Script path: {SCRIPT_PATH}")
        log.debug(f"Python executable: {PYTHON_EXECUTABLE}")

        if args.command == 'install':
            # --- Start FINAL FINAL Updated Install Block ---
            log.info("Starting installation process...")

            config_existed = fluxfce_core.CONFIG_FILE.exists()
            log.debug(f"Config file exists before install attempt: {config_existed}")

            # Load config (applies defaults in memory if file is new/missing keys)
            config = fluxfce_core.get_current_config() # Use API call
            config_needs_saving = False # Track if we need to save

            # --- Initial Setup Block (Only if config didn't exist) ---
            if not config_existed:
                log.info("Configuration file not found or is empty. Attempting setup.")

                # -- Timezone Handling --
                detected_tz = fluxfce_core.detect_system_timezone() # Use helper via core init
                default_tz = core_config.DEFAULT_CONFIG['Location']['TIMEZONE'] # Get default
                final_tz = default_tz # Start with default

                if detected_tz:
                    print(f"Detected system timezone: '{detected_tz}'")
                    if detected_tz != default_tz:
                         print(f"Using detected timezone for initial configuration.")
                         config.set('Location', 'TIMEZONE', detected_tz)
                         final_tz = detected_tz
                         config_needs_saving = True # Mark for saving
                    else:
                         print(f"Detected timezone matches default ('{default_tz}').")
                else:
                    print(f"Could not detect system timezone. Using default: '{default_tz}'")
                    print(f"You can change this later in {fluxfce_core.CONFIG_FILE}")

                # -- Coordinate Handling --
                print("\nPlease provide location coordinates for accurate sun times.")
                print("(Format: e.g., 43.65N, 79.38W - Press Enter to use defaults)")
                default_lat = core_config.DEFAULT_CONFIG['Location']['LATITUDE']
                default_lon = core_config.DEFAULT_CONFIG['Location']['LONGITUDE']
                chosen_lat = default_lat
                chosen_lon = default_lon
                coords_valid = False

                try:
                    # Prompt for Lat/Lon
                    lat_input = input(f"Enter Latitude [{default_lat}]: ").strip()
                    lon_input = input(f"Enter Longitude [{default_lon}]: ").strip()

                    # Use input if provided, otherwise stick with default
                    chosen_lat = lat_input if lat_input else default_lat
                    chosen_lon = lon_input if lon_input else default_lon

                    # Validate chosen values immediately
                    core_helpers.latlon_str_to_float(chosen_lat) # Raises ValidationError on failure
                    core_helpers.latlon_str_to_float(chosen_lon) # Raises ValidationError on failure
                    coords_valid = True # Mark as valid if no exception raised

                except (EOFError, KeyboardInterrupt):
                    print("\nInput skipped. Using default coordinates.")
                    # Keep default values, coords_valid remains False
                except core_exc.ValidationError as e:
                    print(f"\nWarning: Invalid coordinate input ({e}). Using default coordinates.")
                    # Keep default values, coords_valid remains False
                except Exception as e:
                    print(f"\nWarning: Unexpected error during coordinate input ({e}). Using default coordinates.")
                    log.exception("Coordinate input error")
                    # Keep default values, coords_valid remains False

                # Update config object *only if* validation passed and values differ from default
                if coords_valid and (chosen_lat != default_lat or chosen_lon != default_lon):
                    config.set('Location', 'LATITUDE', chosen_lat)
                    config.set('Location', 'LONGITUDE', chosen_lon)
                    print(f"Using coordinates: Latitude={chosen_lat}, Longitude={chosen_lon}")
                    config_needs_saving = True # Mark for saving
                elif coords_valid:
                    # User entered values identical to defaults, or just hit Enter
                    print(f"Using default coordinates: Latitude={default_lat}, Longitude={default_lon}")
                # Else: Warnings about invalid/skipped input already printed

                # -- Save Config --
                # Save config *if* timezone changed OR valid non-default coords were entered OR it was just created
                if config_needs_saving or not config_existed: # Always save if newly created
                    log.info("Saving initial/updated configuration file...")
                    fluxfce_core.save_configuration(config) # Use API call
            else:
                # Config existed, no initial setup needed
                log.info("Existing configuration file found.")

            # --- Proceed with Systemd and Scheduling ---
            log.info("Installing systemd units...")
            fluxfce_core.install_fluxfce(script_path=SCRIPT_PATH, python_executable=PYTHON_EXECUTABLE)
            log.info("Systemd units installed. Enabling scheduling...")
            fluxfce_core.enable_scheduling(python_exe_path=PYTHON_EXECUTABLE, script_exe_path=SCRIPT_PATH)

            # --- Final User Feedback Messages (Keep corrected version from previous step) ---
            print()
            print("-" * 45)
            print(" fluxfce installed and enabled successfully. ")
            print("-" * 45)
            print()

            # PATH Instructions
            user_bin_dir = pathlib.Path.home() / ".local" / "bin"
            print("IMPORTANT: The fluxfce code is now split into an executable script")
            print(f"({pathlib.Path(SCRIPT_PATH).name}) and a library directory ('fluxfce_core').")
            print("Simply moving the script will NOT work.")
            print("\nTo run 'fluxfce' easily from your terminal, you need to make the command")
            print("available in your system's $PATH.")

            print(f"\nRecommended Method (using a symbolic link):")
            print(f"  1. Ensure '{user_bin_dir}' exists and is in your PATH:")
            print(f"     $ mkdir -p \"{user_bin_dir}\"")
            print(f"     $ echo $PATH  # Check if the directory is listed")
            print(f"     # If not, add 'export PATH=\"{user_bin_dir}:$PATH\"' to your ~/.bashrc or ~/.zshrc")
            print(f"     # then run 'source ~/.bashrc' or restart your terminal.")
            print(f"  2. Make the main script executable:")
            print(f"     $ chmod +x \"{SCRIPT_PATH}\"")
            print(f"  3. Create a symbolic link in your PATH pointing to the script:")
            print(f"     $ ln -s \"{SCRIPT_PATH}\" \"{user_bin_dir / 'fluxfce'}\"")
            print(f"     (This keeps the code in '{pathlib.Path(SCRIPT_PATH).parent}' so imports work.)")

            print(f"\nAlternative (Proper Installation - Recommended for distribution):")
            print(f"  - Create packaging files (e.g., pyproject.toml).")
            print(f"  - Run 'pip install .' in the project directory ({pathlib.Path(SCRIPT_PATH).parent}).")
            print(f"  - This installs the 'fluxfce_core' library and places the 'fluxfce' command correctly.")

            # set-default Instructions
            print()
            print("Tip: Configure the Day/Night appearance by setting your preferred")
            print("     theme/background manually, then run:")
            print("     $ fluxfce set-default --mode day")
            print("     or")
            print("     $ fluxfce set-default --mode night")
            # --- End FINAL Updated Install Block ---

        # ... (rest of main function: uninstall, enable, disable, etc.) ...
        elif args.command == 'uninstall':
            log.info("Starting uninstallation (system components)...")
            fluxfce_core.uninstall_fluxfce()
            print("FluxFCE systemd units removed and schedule cleared.")
            config_dir_path = fluxfce_core.CONFIG_DIR
            if config_dir_path.exists():
                try:
                    confirm = input(f"\nDo you want to remove the configuration directory ({config_dir_path})? [y/N]: ").strip().lower()
                    if confirm == 'y':
                        log.warning(f"User confirmed removal of configuration directory: {config_dir_path}")
                        shutil.rmtree(config_dir_path)
                        print(f"Removed configuration directory: {config_dir_path}")
                    else:
                        print("Configuration directory kept.")
                except OSError as e:
                    print(f"\nError removing configuration directory {config_dir_path}: {e}", file=sys.stderr)
                    log.error(f"Failed to remove config directory {config_dir_path}: {e}")
                except EOFError:
                     print("\nSkipping config directory removal prompt (no input received).")
                     log.warning("Skipping config directory removal prompt due to EOFError.")
            else:
                log.debug(f"Configuration directory {config_dir_path} not found, skipping removal prompt.")
            print("\n--- Uninstallation Complete ---")

        elif args.command == 'enable':
            log.info("Enabling scheduling...")
            fluxfce_core.enable_scheduling(python_exe_path=PYTHON_EXECUTABLE, script_exe_path=SCRIPT_PATH)
            print("Automatic theme scheduling enabled.")

        elif args.command == 'disable':
            log.info("Disabling scheduling...")
            fluxfce_core.disable_scheduling()
            print("Automatic theme scheduling disabled ('at' jobs cleared).")

        elif args.command == 'status':
            log.info("Getting status...")
            status = fluxfce_core.get_status()
            print_status(status)

        elif args.command == 'force-day':
            log.info("Forcing Day mode...")
            fluxfce_core.apply_manual_mode('day')
            print("Day mode applied. Automatic scheduling disabled.")

        elif args.command == 'force-night':
            log.info("Forcing Night mode...")
            fluxfce_core.apply_manual_mode('night')
            print("Night mode applied. Automatic scheduling disabled.")

        elif args.command == 'set-default':
            mode = args.default_mode
            log.info(f"Setting current look as default for {mode} mode...")
            fluxfce_core.set_default_from_current(mode)
            print(f"Current desktop settings saved as default for {mode.capitalize()} mode.")
            print("(Run 'fluxfce enable' if needed to apply schedule changes).")

        # --- Internal Command Handling (Keep as before) ---
        elif args.command == 'internal-apply':
            mode = args.internal_mode
            log.info(f"CLI: Executing internal-apply for mode '{mode}'")
            success = fluxfce_core.handle_internal_apply(mode)
            exit_code = 0 if success else 1

        elif args.command == 'schedule-jobs':
            log.info("CLI: Executing schedule-jobs command")
            success = fluxfce_core.handle_schedule_jobs_command(
                python_exe_path=PYTHON_EXECUTABLE,
                script_exe_path=SCRIPT_PATH
            )
            exit_code = 0 if success else 1

        elif args.command == 'run-login-check':
            log.info("CLI: Executing run-login-check command")
            success = fluxfce_core.handle_run_login_check()
            exit_code = 0 if success else 1

        else:
            log.error(f"Unknown command: {args.command}")
            parser.print_help()
            exit_code = 1

    except core_exc.FluxFceError as e:
        log.error(f"{e}", exc_info=args.verbose)
        print(f"\nError: {e}", file=sys.stderr)
        exit_code = 1
    except Exception as e:
        log.exception(f"An unexpected error occurred: {e}")
        print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
        if args.verbose:
            print("\n--- Traceback ---", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            print("--- End Traceback ---", file=sys.stderr)
        exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()