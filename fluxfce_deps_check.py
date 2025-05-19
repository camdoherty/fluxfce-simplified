#!/usr/bin/env python3

import os
import shutil
import subprocess
import sys
from typing import Optional

MIN_PYTHON_VERSION = (3, 9)

# Updated list of command-line dependencies to check
DEPS_TO_CHECK = {
    # command_name: (package_name_suggestion_for_apt, friendly_name)
    "xfconf-query": ("xfce4-utils", "XFCE Configuration tool ('xfconf-query')"),
    "systemctl": ("systemd", "Systemd control tool ('systemctl')"),
    "timedatectl": ("systemd", "Systemd time/date tool ('timedatectl')"),
    "xfdesktop": ("xfdesktop4", "XFCE Desktop manager ('xfdesktop')"),
    "xsct": ("xsct", "Screen Color Temperature tool ('xsct')"),
}

# Fallback package suggestion if xfce4-utils isn't found directly (e.g., part of a meta-package)
XFCE4_UTILS_FALLBACK = "xfce4-session"


# --- Helper Functions ---

def print_info(message: str):
    print(f"[INFO] {message}")

def print_warning(message: str):
    print(f"[WARN] {message}")

def print_error(message: str):
    print(f"[ERROR] {message}")

def print_success(message: str):
    print(f"[OK]   {message}") # Added more space for alignment

def run_command(
    command: list[str], check_exit_code: bool = True, capture_output: bool = False
) -> tuple[int, Optional[str], Optional[str]]:
    """Runs a system command."""
    try:
        process = subprocess.run(
            command,
            check=check_exit_code and not capture_output, # Let CalledProcessError raise if not capturing
            capture_output=capture_output,
            text=True,
            env=os.environ.copy(),
        )
        stdout = process.stdout.strip() if process.stdout else None
        stderr = process.stderr.strip() if process.stderr else None
        
        if capture_output and check_exit_code and process.returncode != 0:
            # Manually raise for captured output if check_exit_code is True and run failed
            raise subprocess.CalledProcessError(
                process.returncode, command, output=stdout, stderr=stderr
            )
        return process.returncode, stdout, stderr
    except FileNotFoundError:
        # This specific error is often critical for expected commands
        print_error(f"Command not found: {command[0]}. Please ensure it is installed and in your PATH.")
        return -1, None, None # Indicate command not found
    except subprocess.CalledProcessError as e:
        stderr_msg = f": {e.stderr}" if e.stderr and e.stderr.strip() else ""
        print_error(
            f"Command '{' '.join(e.cmd)}' failed with exit code {e.returncode}{stderr_msg}"
        )
        return e.returncode, e.stdout, e.stderr
    except Exception as e:
        print_error(
            f"An unexpected error occurred running command '{' '.join(command)}': {e}"
        )
        return -2, None, None # Indicate other unexpected error

def ask_yes_no(prompt: str, default_yes: bool = False) -> bool:
    """Asks a yes/no question and returns True for yes, False for no."""
    suffix = "[Y/n]" if default_yes else "[y/N]"
    while True:
        try:
            response = input(f"{prompt} {suffix}: ").strip().lower()
            if not response:
                return default_yes
            if response in ["y", "yes"]:
                return True
            if response in ["n", "no"]:
                return False
            print_warning("Invalid input. Please enter 'y' or 'n'.")
        except EOFError:
            print()
            return default_yes
        except KeyboardInterrupt:
            print("\nPrompt interrupted. Assuming 'no'.")
            return False

# --- Check Functions ---

def check_python_version() -> bool:
    """Checks if the current Python version meets the minimum requirement."""
    print_info(f"Checking Python version (minimum {MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]})...")
    if sys.version_info >= MIN_PYTHON_VERSION:
        print_success(f"Python version {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} is sufficient.")
        return True
    else:
        print_error(
            f"Python version is {sys.version_info.major}.{sys.version_info.minor}. "
            f"FluxFCE requires Python {MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]} or newer."
        )
        return False

def check_command_installed(cmd_name: str, friendly_name: str) -> bool:
    """Checks if a command is installed and executable using shutil.which."""
    print_info(f"Checking for {friendly_name} ('{cmd_name}')...")
    path = shutil.which(cmd_name)
    if path:
        print_success(f"{friendly_name} found at: {path}")
        return True
    else:
        print_warning(f"{friendly_name} ('{cmd_name}') NOT found in PATH.")
        return False

# --- Installation Functions ---

def print_manual_xsct_instructions():
    """Prints manual installation instructions for xsct."""
    print_warning("-" * 60)
    print_warning("Manual Installation for 'xsct' might be required.")
    print_warning("If 'sudo apt install xsct' failed or was skipped, you might need to build it from source:")
    print_info("  1. Install build dependencies (example for Debian/Ubuntu):")
    print_info("     sudo apt update")
    print_info("     sudo apt install build-essential libx11-dev libxrandr-dev git")
    print_info("  2. Clone the xsct repository:")
    print_info("     git clone https://github.com/faf0/xsct.git")
    print_info("  3. Compile and install:")
    print_info("     cd xsct")
    print_info("     sudo make install  # Installs to /usr/local/bin by default")
    print_info("     # OR, for user-local install (ensure ~/.local/bin is in PATH):")
    print_info("     # mkdir -p ~/.local/bin && make PREFIX=~/.local install")
    print_warning("-" * 60)

def install_package(
    pkg_name_suggestion: str, cmd_name_being_checked: str, friendly_name: str
) -> bool:
    """
    Attempts to install a package using apt.
    Handles xsct special case for manual instructions.
    Handles xfce4-utils fallback.
    """
    install_prompt = (
        f"Attempt to install '{friendly_name}' (package suggestion: {pkg_name_suggestion}) "
        f"using 'sudo apt install {pkg_name_suggestion}'?"
    )
    if not ask_yes_no(install_prompt, default_yes=True): # Default to yes for convenience
        print_info(f"Skipping installation of {friendly_name}.")
        if cmd_name_being_checked == "xsct":
            print_manual_xsct_instructions()
        return False

    print_info(f"Attempting to install {pkg_name_suggestion}...")
    
    # Offer to run apt update first
    if ask_yes_no("Run 'sudo apt update' first to refresh package lists?", default_yes=True):
        print_info("Running 'sudo apt update'...")
        ret_update, _, _ = run_command(["sudo", "apt", "update"])
        if ret_update != 0:
            print_warning("Failed to run 'sudo apt update'. Package lists may be outdated. Continuing install attempt...")
    else:
        print_info("Skipping 'apt update'.")

    ret_install, _, _ = run_command(["sudo", "apt", "install", "-y", pkg_name_suggestion])
    
    if ret_install == 0:
        print_success(f"Successfully installed package '{pkg_name_suggestion}' for {friendly_name}.")
        # Verify the command is now available
        if shutil.which(cmd_name_being_checked):
            print_success(f"Command '{cmd_name_being_checked}' is now available.")
            return True
        else:
            print_warning(f"Package '{pkg_name_suggestion}' installed, but command '{cmd_name_being_checked}' still not found. This is unexpected.")
            return False # Command still not found
    else:
        print_error(f"Failed to install package '{pkg_name_suggestion}' for {friendly_name}.")
        if cmd_name_being_checked == "xsct":
            print_info("The package 'xsct' might not be available in your system's default repositories or installation failed.")
            print_manual_xsct_instructions()
        elif cmd_name_being_checked == "xfconf-query" and pkg_name_suggestion == "xfce4-utils":
            print_info(f"Trying fallback package '{XFCE4_UTILS_FALLBACK}' for XFCE utilities.")
            # Recursive call for the fallback package.
            return install_package(XFCE4_UTILS_FALLBACK, cmd_name_being_checked, friendly_name)
        return False

# --- Main Logic ---
def main():
    print_info("FluxFCE Dependency Checker for Debian/Ubuntu-based systems")
    print_info("(Focuses on command-line tools needed by FluxFCE core)")
    print_info("=" * 60)

    if not shutil.which("apt"):
        print_warning("This script's package installation suggestions use 'apt'.")
        print_warning("If you are on a non-APT system, you'll need to install dependencies manually.")
        # Continue with checks, but installation attempts might not be relevant.

    if os.geteuid() == 0:
        print_warning(
            "This script is not designed to be run as root, though it will invoke 'sudo' "
            "for package installations if you permit."
        )
        if not ask_yes_no("Continue anyway?", default_yes=False):
            sys.exit(1)

    all_deps_ok_initially = True
    missing_commands_to_resolve: dict[str, tuple[str, str]] = {} # cmd_name: (pkg_suggestion, friendly_name)

    # 1. Check Python Version
    if not check_python_version():
        all_deps_ok_initially = False
        # This is a critical failure for FluxFCE itself.
        print_error("Please upgrade Python before proceeding with FluxFCE installation.")
        # Exiting early if Python version is insufficient, as fluxfce_cli.py won't run.
        # sys.exit(1) # Or choose to report all other missing deps first. Let's report all.

    # 2. Check Commands
    print_info("\n--- Checking for required command-line tools ---")
    for cmd, (pkg_suggestion, friendly) in DEPS_TO_CHECK.items():
        if not check_command_installed(cmd, friendly):
            all_deps_ok_initially = False
            if cmd not in missing_commands_to_resolve: # Avoid duplicates if somehow listed twice
                missing_commands_to_resolve[cmd] = (pkg_suggestion, friendly)
    
    print_info("-" * 60)
    if all_deps_ok_initially:
        print_success("All checked dependencies appear to be OK!")
        print_info("Note: Core system utilities (like 'python3', 'mkdir', 'ln') are assumed to be present.")
        sys.exit(0)
    else:
        print_warning("Some dependencies require attention.")

    # 3. Attempt to Install Missing Items
    if missing_commands_to_resolve:
        print_info("\n--- Attempting to resolve missing dependencies ---")
        # Prioritize xsct for special handling/messaging if apt install fails
        if "xsct" in missing_commands_to_resolve:
            pkg_sugg, friendly_name = missing_commands_to_resolve.pop("xsct")
            install_package(pkg_sugg, "xsct", friendly_name)
            # Re-check xsct specifically, as its installation can be manual
            if check_command_installed("xsct", DEPS_TO_CHECK["xsct"][1]):
                 print_success("'xsct' is now available.")
            else:
                 print_warning("'xsct' still appears to be unavailable after installation attempt.")
                 # Manual instructions were already printed by install_package on failure.

        # Attempt to install other missing packages
        for cmd_name, (pkg_sugg, friendly_name) in missing_commands_to_resolve.items():
            # Check again in case a previous install provided this command (e.g., meta-package)
            if not shutil.which(cmd_name):
                install_package(pkg_sugg, cmd_name, friendly_name)
    else:
        print_info("No missing command-line tools to attempt to install (or user skipped previous prompts).")

    print_info("-" * 60)
    # Final verification
    print_info("Re-verifying all dependencies after installation attempts...")
    final_all_ok = True
    if not check_python_version(): # Re-check Python version
        final_all_ok = False

    for cmd, (_, friendly) in DEPS_TO_CHECK.items():
        if not check_command_installed(cmd, friendly):
            final_all_ok = False
            if cmd == "xsct":
                print_warning(f"'{cmd}' ({friendly}) is still missing. Manual installation might be required (see instructions above if printed).")
            else:
                print_warning(f"'{cmd}' ({friendly}) is still missing. Please install it manually.")


    print_info("-" * 60)
    if final_all_ok:
        print_success("All critical dependencies appear to be satisfied now!")
        sys.exit(0)
    else:
        print_error("One or more critical dependencies are still missing after installation attempts.")
        print_error("Please review the output above and install them manually.")
        sys.exit(1)

if __name__ == "__main__":
    main()