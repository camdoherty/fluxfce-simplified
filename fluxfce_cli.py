#!/usr/bin/env python3

"""
fluxfce (CLI) - Simplified XFCE Theming Tool

Command-line interface for managing automatic XFCE theme/background/screen
switching based on sunrise/sunset times using the fluxfce_core library.
"""

import argparse
import logging
import shutil
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
except ImportError as e:
    print(f"Error: Failed to import the fluxfce_core library: {e}", file=sys.stderr)
    print("Ensure fluxfce_core is installed or available in your Python path.", file=sys.stderr)
    sys.exit(1)

# --- Obsolete Global Variables Removed ---

log = logging.getLogger("fluxfce_cli")

# --- ANSI Color Codes for Terminal Output ---
IS_TTY = sys.stdout.isatty()

class AnsiColors:
    GREEN = "\033[92m" if IS_TTY else ""
    RED = "\033[91m" if IS_TTY else ""
    YELLOW = "\033[93m" if IS_TTY else ""
    RESET = "\033[0m" if IS_TTY else ""

# --- CLI Logging Setup (Unchanged) ---
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


# --- Output Formatting (Unchanged) ---
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
    else:
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

# --- User Interaction Helper (Unchanged) ---
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
            print("[WARN] Invalid input. Please enter 'y' or 'n'.")
        except (EOFError, KeyboardInterrupt):
            print("\nPrompt interrupted. Assuming 'no'.")
            return False

# --- Main Execution Logic ---
def main():
    """Parses command-line arguments and dispatches to appropriate command handlers."""
    parser = argparse.ArgumentParser(
        description="fluxfce (CLI): Manage XFCE appearance via sunrise/sunset timing.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
Examples:
  fluxfce install                 # Run first-time setup for user configuration files.
  fluxfce status -v               # Show detailed status, including profiles and services.
  fluxfce day                     # Apply Day mode now without disabling auto switching.
  fluxfce enable                  # Enable automatic scheduling.
  fluxfce set-default --mode day  # Save current desktop look as the new Day default.
  fluxfce uninstall               # Disable timers and remove user configuration.
""",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable detailed logging output.")
    subparsers = parser.add_subparsers(dest="command", title="Commands", required=True)

    # --- UPDATED HELP TEXT ---
    subparsers.add_parser("install", help="Run first-time setup for user configuration files.")
    uninstall_parser = subparsers.add_parser(
        "uninstall", help="Disable timers and remove user configuration (use 'apt purge' to remove the app)."
    )
    uninstall_parser.add_argument(
        "--keep-config",
        action="store_true",
        help="Only disable timers, do not remove user configuration files.",
    )
    # --- END UPDATED HELP TEXT ---

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
    subparsers.add_parser("run-resume-check", help=argparse.SUPPRESS)

    args = parser.parse_args()
    setup_cli_logging(args.verbose)
    exit_code = 0

    try:
        log.debug(f"Running command: {args.command}")

        if args.command == "install":
            log.info("--- fluxfce First-Time User Setup ---")
            log.info("This command will create default configuration files in your home directory.")
            try:
                core_config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                log.info(f"Configuration directory ensured at: {core_config.CONFIG_DIR}")
            except OSError as e:
                log.error(f"Failed to create config directory: {e}")
                sys.exit(1)

            if not core_config.CONFIG_FILE.exists():
                log.info(f"Configuration file not found. Creating default at: {core_config.CONFIG_FILE}")
                try:
                    config_obj = fluxfce_core.get_current_config()
                    fluxfce_core.save_configuration(config_obj)
                    log.info("Default 'config.ini' created successfully.")
                except core_exc.FluxFceError as e:
                    log.error(f"Failed to create default configuration: {e}")
                    sys.exit(1)
            else:
                log.info("Existing configuration file found. Skipping creation.")

            log.info("\nChecking for default background profiles...")
            try:
                fluxfce_core.install_default_background_profiles()
                log.info("Default background profiles are installed.")
            except core_exc.FluxFceError as e:
                log.error(f"Failed to install default background profiles: {e}")

            log.info("\n--- Setup Complete ---")
            log.info("To activate automatic theming, run: fluxfce enable")
            log.info("Customize your look and save it with: fluxfce set-default --mode day|night")

        elif args.command == "uninstall":
            log.warning("To fully remove the application, use your system's package manager (e.g., 'sudo apt purge fluxfce').")
            log.warning("This command only disables timers and offers to remove your personal configuration.")

            log.info("Disabling scheduling and clearing dynamic timers...")
            fluxfce_core.disable_scheduling()
            log.info("FluxFCE scheduling disabled.")

            if not args.keep_config:
                log.info("Removing user configuration files...")
                if core_config.CONFIG_DIR.exists():
                    if ask_yes_no_cli(f"Do you want to REMOVE the configuration directory {core_config.CONFIG_DIR} and all its contents?", default_yes=False):
                        try:
                            shutil.rmtree(core_config.CONFIG_DIR)
                            log.info(f"Removed configuration directory: {core_config.CONFIG_DIR}")
                        except OSError as e:
                            log.error(f"Error removing config directory {core_config.CONFIG_DIR}: {e}")
                    else:
                        log.info(f"User configuration directory {core_config.CONFIG_DIR} kept.")
                else:
                    log.info(f"User configuration directory {core_config.CONFIG_DIR} not found, nothing to remove.")
            else:
                log.info("User configuration files will be kept.")
            log.info("Uninstall process complete.")

        elif args.command == "day":
            log.info("Applying Day mode (scheduling will remain active)...")
            fluxfce_core.apply_temporary_mode("day")

        elif args.command == "night":
            log.info("Applying Night mode (scheduling will remain active)...")
            fluxfce_core.apply_temporary_mode("night")

        elif args.command == "enable":
            log.info("Enabling scheduling via systemd timers...")
            if not core_config.CONFIG_FILE.exists():
                log.error(f"Config file {core_config.CONFIG_FILE} not found. Run 'fluxfce install' first.")
                exit_code = 1
            else:
                # --- SIMPLIFIED CALL ---
                fluxfce_core.enable_scheduling()
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
            fluxfce_core.set_default_from_current(mode)
            log.info(f"Current desktop settings saved as default for {mode.capitalize()} mode.")

        elif args.command == "internal-apply":
            success = fluxfce_core.handle_internal_apply(args.internal_mode)
            exit_code = 0 if success else 1
        
        elif args.command == "schedule-dynamic-transitions":
            # --- SIMPLIFIED CALL ---
            success = fluxfce_core.handle_schedule_dynamic_transitions_command()
            exit_code = 0 if success else 1

        elif args.command == "run-login-check":
            success = fluxfce_core.handle_run_login_check()
            exit_code = 0 if success else 1

        elif args.command == "run-resume-check":
            success = fluxfce_core.handle_run_resume_check()
            exit_code = 0 if success else 1
        else:
            log.error(f"Unknown command: {args.command}")
            parser.print_help(sys.stderr)
            exit_code = 1

    except core_exc.FluxFceError as e:
        log.error(f"FluxFCE Error: {e}", exc_info=args.verbose)
        exit_code = 1
    except Exception as e_main:
        log.error(f"An unexpected error occurred in CLI: {e_main}", exc_info=True)
        exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()