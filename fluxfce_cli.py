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
import subprocess # Added for running the dependency checker
# from datetime import datetime # Not directly used in this file now
from fluxfce_core import helpers as core_helpers
from fluxfce_core import config as core_config

# Import the refactored core library API and exceptions
try:
    import fluxfce_core
    from fluxfce_core import exceptions as core_exc
except ImportError as e:
    print(f"Error: Failed to import the fluxfce_core library: {e}", file=sys.stderr)
    print("Ensure fluxfce_core is installed or available in your Python path.", file=sys.stderr)
    sys.exit(1)

# --- Global Variables ---
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent # Directory of the current script
SCRIPT_PATH = str(pathlib.Path(__file__).resolve())
PYTHON_EXECUTABLE = sys.executable
DEPENDENCY_CHECKER_SCRIPT_NAME = "fluxfce_deps_check.py" # Name of your dependency checker script

log = logging.getLogger('fluxfce_cli')


# --- CLI Logging Setup ---
def setup_cli_logging(verbose: bool):
    """Configures logging for the CLI based on verbosity."""
    cli_log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(name)s: %(message)s')

    log.setLevel(cli_log_level)
    if log.hasHandlers(): # Clear existing handlers if any from basicConfig or re-runs
        log.handlers.clear()

    core_log_level = logging.DEBUG if verbose else logging.WARNING
    logging.getLogger('fluxfce_core').setLevel(core_log_level)
    if not logging.getLogger('fluxfce_core').hasHandlers():
         core_handler = logging.StreamHandler(sys.stderr)
         core_formatter = logging.Formatter('%(levelname)s: %(name)s: %(message)s')
         core_handler.setFormatter(core_formatter)
         logging.getLogger('fluxfce_core').addHandler(core_handler)
         logging.getLogger('fluxfce_core').propagate = False # Prevent core logs going to root

    if cli_log_level <= logging.INFO:
        info_handler = logging.StreamHandler(sys.stdout)
        info_formatter = logging.Formatter('%(message)s')
        info_handler.setFormatter(info_formatter)
        info_handler.setLevel(logging.INFO)
        info_handler.addFilter(lambda record: record.levelno == logging.INFO)
        log.addHandler(info_handler)

    error_handler = logging.StreamHandler(sys.stderr)
    error_formatter = logging.Formatter('%(levelname)s: %(message)s')
    error_handler.setFormatter(error_formatter)
    error_handler.setLevel(logging.DEBUG if verbose else logging.WARNING)
    log.addHandler(error_handler)

    log.propagate = False
    log.debug("Verbose logging enabled for fluxfce_cli.")


# --- Output Formatting ---
def print_status(status_data: dict):
    """Formats and prints the status dictionary."""
    # This function will now use `log.info` for most of its output
    # to be consistent with the CLI logging setup.
    # Direct `print` can be kept for very specific formatting if needed,
    # but `log.info` is generally preferred for application messages.

    log.info("--- fluxfce Status ---")

    log.info("\n[Configuration]")
    if status_data['config'].get('error'):
        log.info(f"  Error loading config: {status_data['config']['error']}")
    else:
        log.info(f"  Location:      {status_data['config'].get('latitude', 'N/A')}, {status_data['config'].get('longitude', 'N/A')}")
        log.info(f"  Timezone:      {status_data['config'].get('timezone', 'N/A')}")
        log.info(f"  Light Theme:   {status_data['config'].get('light_theme', 'N/A')}")
        log.info(f"  Dark Theme:    {status_data['config'].get('dark_theme', 'N/A')}")

    # State file logic is being removed, so this section will be removed.
    # log.info("\n[State]")
    # if status_data['state'].get('error'):
    #     log.info(f"  Error reading state: {status_data['state']['error']}")
    # else:
    #     last_state = status_data['state'].get('last_auto_applied')
    #     log.info(f"  Last Auto-Applied: {last_state or 'Unknown'}")

    log.info("\n[Calculated Sun Times (Today)]")
    if status_data['sun_times'].get('error'):
         log.info(f"  Error: {status_data['sun_times']['error']}")
    elif status_data['sun_times'].get('sunrise') and status_data['sun_times'].get('sunset'):
        sunrise_dt = status_data['sun_times']['sunrise']
        sunset_dt = status_data['sun_times']['sunset']
        try:
            log.info(f"  Sunrise:       {sunrise_dt.isoformat(sep=' ', timespec='seconds')}")
            log.info(f"  Sunset:        {sunset_dt.isoformat(sep=' ', timespec='seconds')}")
        except Exception: # Fallback if isoformat attributes are missing (e.g. raw string)
             log.info(f"  Sunrise:       {sunrise_dt}")
             log.info(f"  Sunset:        {sunset_dt}")
    else:
        log.info("  Could not be calculated (check config/location).")
    log.info(f"  Current Period:  {status_data.get('current_period', 'unknown').capitalize()}")

    log.info("\n[Scheduled Transitions ('at' jobs)]")
    if status_data['schedule'].get('error'):
         log.info(f"  Error checking schedule: {status_data['schedule']['error']}")
    else:
        jobs = status_data['schedule'].get('jobs', [])
        enabled = status_data['schedule'].get('enabled', False)
        if jobs:
             log.info(f"  Status:        Enabled ({len(jobs)} job(s) found)")
             for job in jobs:
                  job_id = job.get('id', 'N/A')
                  mode = job.get('mode', 'unknown').capitalize()
                  time_str = job.get('time_str', 'Unknown Time')
                  log.info(f"  - Job {job_id}: {mode} at {time_str}")
        elif enabled: # This case might indicate scheduler thinks it's on but no jobs found
             log.info("  Status:        Enabled (No specific fluxfce jobs found - state mismatch or just scheduled?)")
        else:
             log.info("  Status:        Disabled")
             log.info("  (Run 'fluxfce enable' to schedule transitions)")

    log.info("\n[Systemd Units]")
    if status_data['systemd'].get('error'):
         log.info(f"  Error checking systemd status: {status_data['systemd']['error']}")
    else:
         timer_status = status_data['systemd'].get('scheduler_timer', 'Unknown')
         service_status = status_data['systemd'].get('scheduler_service', 'Unknown')
         login_status = status_data['systemd'].get('login_service', 'Unknown')
         resume_status = status_data['systemd'].get('resume_service', 'Unknown')

         log.info(f"  Scheduler Timer ({fluxfce_core.SCHEDULER_TIMER_NAME}): {timer_status}")
         log.info(f"  Scheduler Service ({fluxfce_core.SCHEDULER_SERVICE_NAME}): {service_status}")
         log.info(f"  Login Service ({fluxfce_core.LOGIN_SERVICE_NAME}): {login_status}")
         log.info(f"  Resume Service ({fluxfce_core.RESUME_SERVICE_NAME}): {resume_status}")
         log.info("  (For detailed logs/status, use 'systemctl --user status ...' or 'journalctl --user -u ...')")

    log.info("-" * 25)

# --- User Interaction Helper (moved from requirements_check_install.py for CLI use) ---
def ask_yes_no_cli(prompt: str, default_yes: bool = False) -> bool:
    """Asks a yes/no question and returns True for yes, False for no. For CLI direct interaction."""
    suffix = "[Y/n]" if default_yes else "[y/N]"
    while True:
        try:
            # Use print for direct prompts, then flush to ensure visibility before input
            print(f"{prompt} {suffix}: ", end='', flush=True)
            response = input().strip().lower()
            if not response:
                return default_yes
            if response in ['y', 'yes']:
                return True
            if response in ['n', 'no']:
                return False
            print(f"[WARN] Invalid input. Please enter 'y' or 'n'.") # Use print for feedback to input
        except EOFError:
            print()
            return default_yes
        except KeyboardInterrupt:
            print("\nPrompt interrupted. Assuming 'no'.")
            return False

# --- Main Execution Logic ---
def main():
    parser = argparse.ArgumentParser(
        description="fluxfce (CLI): Manage XFCE appearance via sunrise/sunset timing.",
        formatter_class=argparse.RawTextHelpFormatter,
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

    subparsers.add_parser('install', help='Install systemd units and enable automatic scheduling.')
    subparsers.add_parser('uninstall', help='Remove systemd units & clear schedule (prompts to remove config).')
    subparsers.add_parser('enable', help='Enable automatic scheduling (schedules transitions).')
    subparsers.add_parser('disable', help='Disable automatic scheduling (clears scheduled transitions).')
    subparsers.add_parser('status', help='Show config, calculated times, and schedule status.')
    subparsers.add_parser('force-day', help='Apply Day Mode settings now (disables automatic scheduling).')
    subparsers.add_parser('force-night', help='Apply Night Mode settings now (disables automatic scheduling).')
    parser_set_default = subparsers.add_parser('set-default', help='Save current desktop look as the new default for Day or Night mode.')
    parser_set_default.add_argument('--mode', choices=['day', 'night'], required=True, dest='default_mode', help='Specify whether to save as the Day or Night default.')
    parser_internal = subparsers.add_parser('internal-apply', help=argparse.SUPPRESS)
    parser_internal.add_argument('--mode', choices=['day', 'night'], required=True, dest='internal_mode')
    subparsers.add_parser('schedule-jobs', help=argparse.SUPPRESS)
    subparsers.add_parser('run-login-check', help=argparse.SUPPRESS)

    args = parser.parse_args()
    setup_cli_logging(args.verbose)
    exit_code = 0

    try:
        log.debug(f"Running command: {args.command}")
        log.debug(f"Script path: {SCRIPT_PATH}")
        log.debug(f"Python executable: {PYTHON_EXECUTABLE}")

        if args.command == 'install':
            # --- Step 1: System Dependency Check ---
            log.info("--- Step 1: Checking system dependencies ---")
            dependency_checker_script = SCRIPT_DIR / DEPENDENCY_CHECKER_SCRIPT_NAME
            if not dependency_checker_script.exists():
                log.error(f"Dependency checker script '{DEPENDENCY_CHECKER_SCRIPT_NAME}' not found in {SCRIPT_DIR}")
                log.error("Please ensure it's present alongside fluxfce_cli.py. Aborting installation.")
                sys.exit(1)

            log.info(f"Executing dependency checker: {dependency_checker_script}...")
            # The dependency checker script will handle its own interactive output.
            # We let its stdout/stderr go directly to the console.
            process = subprocess.run(
                [PYTHON_EXECUTABLE, str(dependency_checker_script)],
                check=False, # We check the return code manually
                capture_output=False, # Let it print directly
            )
            if process.returncode != 0:
                log.error(f"Dependency check/setup script failed or reported unresolved critical issues (exit code: {process.returncode}).")
                log.error("Please review its output above. Aborting fluxfce installation.")
                sys.exit(1)
            log.info("System dependency check passed or issues were addressed.")
            log.info("--- Dependency check complete ---")

            # --- Step 2: FluxFCE Application Configuration (Interactive Setup) ---
            log.info("\n--- Step 2: Configuring FluxFCE application settings ---")
            config_existed_before_setup = fluxfce_core.CONFIG_FILE.exists()
            # Load config (applies defaults in memory if file is new/missing keys, but doesn't save)
            config = fluxfce_core.get_current_config()
            config_needs_saving_after_interactive_setup = False

            # Trigger interactive setup if config file didn't exist,
            # OR if it exists but key settings like lat/lon are missing/default
            # (This makes it more robust if a user creates an empty config or deletes values)
            run_interactive_setup = False
            if not config_existed_before_setup:
                run_interactive_setup = True
                log.info("Configuration file not found. Starting interactive setup.")
            else:
                # Check if essential location settings are default or missing
                loc_section = 'Location'
                current_lat = config.get(loc_section, 'LATITUDE', fallback=None)
                current_lon = config.get(loc_section, 'LONGITUDE', fallback=None)
                # current_tz = config.get(loc_section, 'TIMEZONE', fallback=None) # TZ auto-detection is good
                if (current_lat == core_config.DEFAULT_CONFIG[loc_section]['LATITUDE'] and \
                    current_lon == core_config.DEFAULT_CONFIG[loc_section]['LONGITUDE']) or \
                    not current_lat or not current_lon:
                    log.info("Existing configuration found, but location seems to be default or missing.")
                    if ask_yes_no_cli("Do you want to run interactive setup for location and timezone?", default_yes=True):
                        run_interactive_setup = True
                    else:
                        log.info("Skipping interactive setup. Using current/default config values.")
                else:
                    log.info(f"Existing configuration found at {fluxfce_core.CONFIG_FILE}. Using it.")


            if run_interactive_setup:
                # -- Timezone Handling --
                # Use print for direct prompts, as this is an interactive section.
                detected_tz = fluxfce_core.detect_system_timezone()
                default_tz = core_config.DEFAULT_CONFIG['Location']['TIMEZONE']
                final_tz = config.get('Location', 'TIMEZONE', fallback=default_tz) # Start with current or default

                if detected_tz:
                    print(f"\nDetected system timezone: '{detected_tz}'")
                    if detected_tz != final_tz:
                        if ask_yes_no_cli(f"Use detected timezone '{detected_tz}' (current is '{final_tz}')?", default_yes=True):
                            final_tz = detected_tz
                    else:
                        print(f"Detected timezone matches current/default ('{final_tz}').")
                else:
                    print(f"\nCould not detect system timezone. Current is '{final_tz}'.")
                    if final_tz == default_tz:
                         print(f"Consider setting it manually if '{default_tz}' is incorrect.")
                
                # Update config object if changed
                if config.get('Location', 'TIMEZONE') != final_tz:
                    config.set('Location', 'TIMEZONE', final_tz)
                    config_needs_saving_after_interactive_setup = True
                print(f"Using timezone: {final_tz}")
                if final_tz == default_tz and not detected_tz:
                     print(f"(You can change this later in {fluxfce_core.CONFIG_FILE})")


                # -- Coordinate Handling --
                print("\nPlease provide location coordinates for accurate sun times.")
                print("(Format: e.g., 43.65N, 79.38W - Press Enter to use defaults from config or internal defaults)")
                
                # Get current or internal defaults to display in prompt
                prompt_default_lat = config.get('Location', 'LATITUDE', fallback=core_config.DEFAULT_CONFIG['Location']['LATITUDE'])
                prompt_default_lon = config.get('Location', 'LONGITUDE', fallback=core_config.DEFAULT_CONFIG['Location']['LONGITUDE'])
                
                chosen_lat = prompt_default_lat
                chosen_lon = prompt_default_lon
                coords_changed = False

                try:
                    lat_input = input(f"Enter Latitude [{prompt_default_lat}]: ").strip()
                    lon_input = input(f"Enter Longitude [{prompt_default_lon}]: ").strip()

                    temp_lat = lat_input if lat_input else prompt_default_lat
                    temp_lon = lon_input if lon_input else prompt_default_lon

                    # Validate chosen values immediately
                    core_helpers.latlon_str_to_float(temp_lat) # Raises ValidationError on failure
                    core_helpers.latlon_str_to_float(temp_lon) # Raises ValidationError on failure
                    
                    # If validation passed, assign
                    chosen_lat = temp_lat
                    chosen_lon = temp_lon
                    
                    if chosen_lat != config.get('Location', 'LATITUDE') or \
                       chosen_lon != config.get('Location', 'LONGITUDE'):
                        coords_changed = True

                except (EOFError, KeyboardInterrupt):
                    print("\nInput skipped. Using previous/default coordinates.")
                except core_exc.ValidationError as e:
                    print(f"\nWarning: Invalid coordinate input ({e}). Using previous/default coordinates.")
                except Exception as e: # Catch any other unexpected error during input
                    print(f"\nWarning: Unexpected error during coordinate input ({e}). Using previous/default coordinates.")
                    log.exception("Coordinate input error during interactive setup")
                
                if coords_changed:
                    config.set('Location', 'LATITUDE', chosen_lat)
                    config.set('Location', 'LONGITUDE', chosen_lon)
                    print(f"Using coordinates: Latitude={chosen_lat}, Longitude={chosen_lon}")
                    config_needs_saving_after_interactive_setup = True
                else:
                    print(f"Using coordinates: Latitude={chosen_lat}, Longitude={chosen_lon} (no changes made).")

                # -- Save Config --
                if config_needs_saving_after_interactive_setup or not config_existed_before_setup:
                    log.info("Saving initial/updated FluxFCE configuration...")
                    fluxfce_core.save_configuration(config)
            # else: # config_existed_before_setup was true and user skipped interactive
            #     log.info(f"Using existing configuration from {fluxfce_core.CONFIG_FILE}")
            log.info("--- FluxFCE application configuration complete ---")

            # --- Step 3: Install Systemd Units ---
            log.info("\n--- Step 3: Installing systemd units ---")
            fluxfce_core.install_fluxfce(script_path=SCRIPT_PATH, python_executable=PYTHON_EXECUTABLE)
            log.info("Systemd units installed.")

            # --- Step 4: Enable Scheduling ---
            log.info("\n--- Step 4: Enabling automatic scheduling ---")
            fluxfce_core.enable_scheduling(python_exe_path=PYTHON_EXECUTABLE, script_exe_path=SCRIPT_PATH)
            log.info("Automatic theme scheduling enabled.")

            # --- Step 5: Final User Feedback ---
            log.info("\n" + "-" * 45)
            log.info(" fluxfce installed and enabled successfully. ")
            log.info("-" * 45 + "\n")

            user_bin_dir = pathlib.Path.home() / ".local" / "bin"
            log.info("IMPORTANT: To run 'fluxfce' easily from your terminal, ensure")
            log.info(f"the script ({pathlib.Path(SCRIPT_PATH).name}) or a symlink to it is in your PATH.")
            log.info(f"\nRecommended Method (if script is not yet in PATH via pip install or similar):")
            log.info(f"  1. Ensure '{user_bin_dir}' exists and is in your PATH:")
            log.info(f"     $ mkdir -p \"{user_bin_dir}\"")
            log.info(f"     $ echo $PATH  # Check if directory is listed")
            log.info(f"     # If not, add 'export PATH=\"{user_bin_dir}:$PATH\"' to your ~/.bashrc or ~/.zshrc")
            log.info(f"     # Then run 'source ~/.bashrc' or restart your terminal.")
            log.info(f"  2. Make the main script executable (if not already):")
            log.info(f"     $ chmod +x \"{SCRIPT_PATH}\"")
            log.info(f"  3. Create a symbolic link in '{user_bin_dir}':")
            log.info(f"     $ ln -s -f \"{SCRIPT_PATH}\" \"{user_bin_dir / 'fluxfce'}\"") # -f to overwrite if exists
            log.info(f"     (This allows 'fluxfce_core' to be found by the script.)")

            log.info(f"\nAlternative (Proper Python Package Installation - Recommended for broader distribution):")
            log.info(f"  - If you cloned the repository, navigate to its root directory.")
            log.info(f"  - Create packaging files (e.g., pyproject.toml).")
            log.info(f"  - Run 'pip install .'. This typically installs the 'fluxfce' command correctly.")

            log.info("\nTip: Configure Day/Night appearance by setting your preferred")
            log.info("     theme/background manually, then run:")
            log.info("     $ fluxfce set-default --mode day")
            log.info("     or")
            log.info("     $ fluxfce set-default --mode night")
            log.info("\nInstallation complete. Check 'fluxfce status' to see the current setup.")

        elif args.command == 'uninstall':
            log.info("Starting uninstallation (system components)...")
            fluxfce_core.uninstall_fluxfce() # This handles systemd units and schedule
            log.info("FluxFCE systemd units removed and schedule cleared.")
            
            config_dir_path = fluxfce_core.CONFIG_DIR # Assuming CONFIG_DIR is accessible
            if config_dir_path.exists():
                log.warning(f"\nConfiguration directory found at: {config_dir_path}")
                if ask_yes_no_cli(f"Do you want to REMOVE this configuration directory?", default_yes=False):
                    try:
                        shutil.rmtree(config_dir_path)
                        log.info(f"Removed configuration directory: {config_dir_path}")
                    except OSError as e:
                        log.error(f"Error removing configuration directory {config_dir_path}: {e}")
                else:
                    log.info("Configuration directory kept.")
            else:
                log.debug(f"Configuration directory {config_dir_path} not found, nothing to remove there.")
            log.info("\n--- Uninstallation Complete ---")

        elif args.command == 'enable':
            log.info("Enabling scheduling...")
            # It might be good to run a quick dependency check here too, or ensure config is valid
            # For now, directly enabling as per original logic.
            if not fluxfce_core.CONFIG_FILE.exists():
                log.error(f"Configuration file {fluxfce_core.CONFIG_FILE} not found.")
                log.error("Please run 'fluxfce install' first or ensure your config is in place.")
                exit_code = 1
            else:
                fluxfce_core.enable_scheduling(python_exe_path=PYTHON_EXECUTABLE, script_exe_path=SCRIPT_PATH)
                log.info("Automatic theme scheduling enabled.")
                log.info("Run 'fluxfce status' to see scheduled jobs.")

        elif args.command == 'disable':
            log.info("Disabling scheduling...")
            fluxfce_core.disable_scheduling()
            log.info("Automatic theme scheduling disabled ('at' jobs cleared).")

        elif args.command == 'status':
            # log.info("Getting status...") # print_status already prints a header
            status = fluxfce_core.get_status()
            print_status(status) # Uses log.info now

        elif args.command == 'force-day':
            log.info("Forcing Day mode...")
            fluxfce_core.apply_manual_mode('day') # This also disables scheduling
            log.info("Day mode applied. Automatic scheduling disabled.")

        elif args.command == 'force-night':
            log.info("Forcing Night mode...")
            fluxfce_core.apply_manual_mode('night') # This also disables scheduling
            log.info("Night mode applied. Automatic scheduling disabled.")

        elif args.command == 'set-default':
            mode = args.default_mode
            log.info(f"Setting current look as default for {mode} mode...")
            fluxfce_core.set_default_from_current(mode)
            log.info(f"Current desktop settings saved as default for {mode.capitalize()} mode.")
            log.info("(Run 'fluxfce enable' if you want to (re)activate scheduling with new defaults).")

        elif args.command == 'internal-apply':
            mode = args.internal_mode
            # This command is run by 'at' jobs, keep logging minimal or ensure it goes to journal
            # The core library's handle_internal_apply should do its own logging.
            # log.info(f"CLI: Executing internal-apply for mode '{mode}'") # Already logged by core
            success = fluxfce_core.handle_internal_apply(mode)
            exit_code = 0 if success else 1

        elif args.command == 'schedule-jobs':
            # log.info("CLI: Executing schedule-jobs command") # Already logged by core
            success = fluxfce_core.handle_schedule_jobs_command(
                python_exe_path=PYTHON_EXECUTABLE,
                script_exe_path=SCRIPT_PATH
            )
            exit_code = 0 if success else 1

        elif args.command == 'run-login-check':
            # log.info("CLI: Executing run-login-check command") # Already logged by core
            success = fluxfce_core.handle_run_login_check()
            exit_code = 0 if success else 1
        else:
            # This case should not be reached due to `required=True` for subparsers
            log.error(f"Unknown command: {args.command}")
            parser.print_help(sys.stderr) # Print help to stderr for errors
            exit_code = 1

    except core_exc.FluxFceError as e:
        log.error(f"FluxFCE Error: {e}", exc_info=args.verbose) # Provide traceback if verbose
        # print(f"\nError: {e}", file=sys.stderr) # Log.error already prints to stderr
        exit_code = 1
    except Exception: # Catchall for unexpected errors
        log.error("An unexpected error occurred:", exc_info=True) # Always provide traceback for unexpected
        # print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
        # if args.verbose:
        #     print("\n--- Traceback ---", file=sys.stderr)
        #     traceback.print_exc(file=sys.stderr)
        #     print("--- End Traceback ---", file=sys.stderr)
        exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()