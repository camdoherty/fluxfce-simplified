#!/usr/bin/env python3

import os
import shutil
import subprocess
import sys
from typing import Optional

MIN_PYTHON_VERSION = (3, 9)
DEPS_TO_CHECK = {
    # command_name: (package_name, friendly_name)
    "at": ("at", "'at' command scheduler"),
    "atq": ("at", "'atq' queue manager"),
    "atrm": ("at", "'atrm' job remover"),
    "xfconf-query": ("xfce4-utils", "XFCE Configuration tool ('xfconf-query')"),
    "systemctl": (
        "systemd",
        "Systemd control tool ('systemctl')",
    ),  # Should always be present
    "timedatectl": (
        "systemd",
        "Systemd time/date tool ('timedatectl')",
    ),  # Should always be present
    "xfdesktop": ("xfdesktop4", "XFCE Desktop manager ('xfdesktop')"),
    "xsct": ("xsct", "Screen Color Temperature tool ('xsct')"),
}

# For services, we check if they are active and enabled
SERVICES_TO_CHECK = {
    # service_name: (package_providing_service, friendly_name, enable_if_not_running)
    "atd": ("at", "'atd' scheduling service", True),
}

XFCE4_UTILS_FALLBACK = (
    "xfce4-session"  # If xfce4-utils isn't the direct package but part of a meta
)

# --- Helper Functions ---


def print_info(message: str):
    print(f"[INFO] {message}")


def print_warning(message: str):
    print(f"[WARN] {message}")


def print_error(message: str):
    print(f"[ERROR] {message}")


def print_success(message: str):
    print(f"[OK] {message}")


def run_command(
    command: list[str], check_exit_code: bool = True, capture_output: bool = False
) -> tuple[int, Optional[str], Optional[str]]:
    """Runs a system command."""
    try:
        process = subprocess.run(
            command,
            check=(
                check_exit_code if not capture_output else False
            ),  # check=True with capture needs careful handling
            capture_output=capture_output,
            text=True,
            env=os.environ.copy(),  # Ensure environment is passed
        )
        stdout = process.stdout.strip() if process.stdout else None
        stderr = process.stderr.strip() if process.stderr else None
        if capture_output and check_exit_code and process.returncode != 0:
            # Manually raise for captured output if check requested
            raise subprocess.CalledProcessError(
                process.returncode, command, output=stdout, stderr=stderr
            )
        return process.returncode, stdout, stderr
    except FileNotFoundError:
        print_error(
            f"Command not found: {command[0]}. This is unexpected for core system utilities."
        )
        return -1, None, None
    except subprocess.CalledProcessError as e:
        stderr_msg = f": {e.stderr}" if e.stderr else ""
        print_error(
            f"Command '{' '.join(e.cmd)}' failed with exit code {e.returncode}{stderr_msg}"
        )
        return e.returncode, e.stdout, e.stderr
    except Exception as e:
        print_error(
            f"An unexpected error occurred running command '{' '.join(command)}': {e}"
        )
        return -2, None, None


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
        except EOFError:  # Handle Ctrl+D
            print()  # Newline
            return (
                default_yes  # Or False, depending on desired non-interactive behavior
            )
        except KeyboardInterrupt:  # Handle Ctrl+C
            print("\nPrompt interrupted. Assuming 'no'.")
            return False


# --- Check Functions ---


def check_python_version() -> bool:
    """Checks if the current Python version meets the minimum requirement."""
    print_info(
        f"Checking Python version (minimum {MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]})..."
    )
    if sys.version_info >= MIN_PYTHON_VERSION:
        print_success(
            f"Python version {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} is sufficient."
        )
        return True
    else:
        print_error(
            f"Python version is {sys.version_info.major}.{sys.version_info.minor}. "
            f"FluxFCE requires Python {MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]} or newer."
        )
        return False


def check_command_installed(cmd_name: str, friendly_name: str) -> bool:
    """Checks if a command is installed and executable using shutil.which."""
    print_info(f"Checking for {friendly_name} ({cmd_name})...")
    path = shutil.which(cmd_name)
    if path:
        print_success(f"{friendly_name} found at: {path}")
        return True
    else:
        print_warning(f"{friendly_name} ({cmd_name}) NOT found in PATH.")
        return False


def check_service_status(service_name: str, friendly_name: str) -> tuple[bool, bool]:
    """
    Checks if a systemd service is active and enabled.
    Returns: (is_active, is_enabled)
    """
    print_info(f"Checking status of {friendly_name} ({service_name})...")
    is_active = False
    is_enabled = False

    # Check active
    ret_active, _, _ = run_command(
        ["systemctl", "is-active", "--quiet", service_name], check_exit_code=False
    )
    if ret_active == 0:
        is_active = True
        print_success(f"{friendly_name} is active.")
    else:
        print_warning(f"{friendly_name} is NOT active.")

    # Check enabled
    ret_enabled, _, _ = run_command(
        ["systemctl", "is-enabled", "--quiet", service_name], check_exit_code=False
    )
    if ret_enabled == 0:
        is_enabled = True
        print_success(f"{friendly_name} is enabled.")
    else:
        # A return code of 1 for is-enabled means "disabled". Other codes are errors.
        # We're primarily interested if it's *not* enabled (or errored).
        print_warning(f"{friendly_name} is NOT enabled (or status check failed).")

    return is_active, is_enabled


# --- Installation Functions ---


def install_package(
    pkg_name: str, friendly_name: str, is_xsct_fallback: bool = False
) -> bool:
    """Attempts to install a package using apt."""
    install_prompt = f"Attempt to install {friendly_name} (package: {pkg_name}) using 'sudo apt install {pkg_name}'?"
    if not ask_yes_no(install_prompt):
        print_info(f"Skipping installation of {friendly_name}.")
        if (
            pkg_name == "xsct" and not is_xsct_fallback
        ):  # Only show manual for initial xsct attempt
            print_manual_xsct_instructions()
        return False

    print_info(f"Attempting to install {pkg_name}...")
    # Ensure APT cache is updated before trying to install a specific package
    # This is good practice if the script might be run on a system not recently updated
    # However, for a simple checker, we might assume user runs `apt update` separately.
    # For robustness, let's offer to update.
    if ask_yes_no(
        "Run 'sudo apt update' first to refresh package lists?", default_yes=True
    ):
        ret_update, _, _ = run_command(["sudo", "apt", "update"])
        if ret_update != 0:
            print_error("Failed to run 'sudo apt update'. Please try manually.")
            # Don't necessarily stop, apt install might still work if lists are recent enough
    else:
        print_info("Skipping 'apt update'.")

    ret_install, _, _ = run_command(
        ["sudo", "apt", "install", "-y", pkg_name]
    )  # -y for non-interactive install after user agrees
    if ret_install == 0:
        print_success(f"Successfully installed {friendly_name} (package: {pkg_name}).")
        return True
    else:
        print_error(f"Failed to install {friendly_name} (package: {pkg_name}).")
        if (
            pkg_name == "xsct" and not is_xsct_fallback
        ):  # Offer manual instructions if 'apt install xsct' fails
            print_info(
                "The package 'xsct' might not be available in your current repositories or the installation failed."
            )
            print_manual_xsct_instructions()
        elif (
            pkg_name == "xfce4-utils" and not is_xsct_fallback
        ):  # Try fallback for xfconf-query
            print_info(
                f"Trying fallback package '{XFCE4_UTILS_FALLBACK}' for XFCE utilities."
            )
            return install_package(
                XFCE4_UTILS_FALLBACK, friendly_name, is_xsct_fallback=True
            )  # a bit of recursion
        return False


def enable_service(service_name: str, friendly_name: str) -> bool:
    """Attempts to enable and start a systemd service."""
    if not ask_yes_no(
        f"Attempt to enable and start {friendly_name} (service: {service_name}) using 'sudo systemctl enable --now {service_name}'?"
    ):
        print_info(f"Skipping enabling of {friendly_name}.")
        return False

    print_info(f"Attempting to enable and start {service_name}...")
    ret_enable, _, _ = run_command(
        ["sudo", "systemctl", "enable", "--now", service_name]
    )
    if ret_enable == 0:
        print_success(f"Successfully enabled and started {friendly_name}.")
        return True
    else:
        print_error(f"Failed to enable/start {friendly_name}.")
        return False


def print_manual_xsct_instructions():
    print_warning("-" * 60)
    print_warning("Manual Installation for 'xsct' is likely required.")
    print_warning(
        "If 'sudo apt install xsct' failed or was skipped, please follow these general steps:"
    )
    print_info("  1. Install build dependencies:")
    print_info("     sudo apt update")
    print_info("     sudo apt install build-essential libx11-dev libxrandr-dev git")
    print_info("  2. Clone the xsct repository:")
    print_info("     git clone https://github.com/faf0/xsct.git")
    print_info("  3. Compile and install:")
    print_info("     cd xsct")
    print_info("     sudo make install  # Installs to /usr/local/bin by default")
    print_info(
        "     # OR, to install to ~/.local/bin (preferred if you don't want to use sudo):"
    )
    print_info("     # mkdir -p ~/.local/bin && make PREFIX=~/.local install")
    print_info("     # (Ensure ~/.local/bin is in your PATH if you choose this option)")
    print_warning("-" * 60)


# --- Main Logic ---


def main():
    print_info("FluxFCE Dependency Checker for Debian/Ubuntu-based systems")
    print_info("=" * 60)

    if os.geteuid() == 0:
        print_warning(
            "This script is not designed to be run as root, though it will invoke 'sudo' for installations."
        )
        if not ask_yes_no("Continue anyway?", default_yes=False):
            sys.exit(1)

    all_deps_ok = True
    missing_packages_to_install: dict[str, str] = {}  # pkg_name: friendly_name
    services_to_manage: list[tuple[str, str, bool]] = (
        []
    )  # service_name, friendly_name, needs_enable

    # 1. Check Python Version
    if not check_python_version():
        all_deps_ok = False
        print_error("Please upgrade Python before proceeding with FluxFCE.")
        # For a real installer, this might be a hard stop. For a checker, we can continue reporting.

    # 2. Check Commands
    for cmd, (pkg, friendly) in DEPS_TO_CHECK.items():
        if not check_command_installed(cmd, friendly):
            all_deps_ok = False
            # Prioritize xsct due to potential for direct apt install vs manual
            if cmd == "xsct":
                # Add to front of install list if apt install is possible
                if (
                    "xsct" not in missing_packages_to_install
                ):  # Avoid duplicates if listed by another tool check
                    missing_packages_to_install = {
                        "xsct": friendly,
                        **missing_packages_to_install,
                    }
            elif pkg not in missing_packages_to_install:
                missing_packages_to_install[pkg] = friendly

    # 3. Check Services
    for service, (pkg, friendly, enable_flag) in SERVICES_TO_CHECK.items():
        active, enabled = check_service_status(service, friendly)
        if not active or (enable_flag and not enabled):
            all_deps_ok = False
            if (
                pkg not in missing_packages_to_install
            ):  # If service is down, package might be missing
                missing_packages_to_install[pkg] = f"Package for {friendly}"
            if enable_flag and (
                not active or not enabled
            ):  # Only add to enable list if it needs enabling
                services_to_manage.append((service, friendly, True))

    print_info("-" * 60)
    if all_deps_ok:
        print_success("All checked dependencies and services appear to be OK!")
        print_info(
            "Note: 'systemd' and 'python3' core presence is assumed by this script if command checks pass."
        )
        sys.exit(0)
    else:
        print_warning("Some dependencies or services require attention.")

    # 4. Attempt to Install/Enable Missing Items
    if missing_packages_to_install:
        print_info("\n--- Attempting to install missing packages ---")
        # Install xsct first if it's in the list, then others
        if "xsct" in missing_packages_to_install:
            friendly_name = missing_packages_to_install.pop("xsct")
            install_package("xsct", friendly_name)
            # After attempting xsct, re-check to see if it's now available
            if not check_command_installed("xsct", DEPS_TO_CHECK["xsct"][1]):
                # If still not found (e.g., user skipped, apt failed, and no manual install yet)
                # The manual instructions were printed by install_package on failure.
                pass

        for pkg, friendly in missing_packages_to_install.items():
            install_package(pkg, friendly)
    else:
        print_info("No missing packages to install (or user skipped previous prompts).")

    if services_to_manage:
        print_info("\n--- Attempting to manage services ---")
        for service, friendly, needs_enable in services_to_manage:
            if (
                needs_enable
            ):  # At this point, only services needing enabling should be here
                # Re-check status before attempting to enable, in case installing package fixed it
                active, enabled = check_service_status(service, friendly)
                if not active or not enabled:
                    enable_service(service, friendly)
    else:
        print_info(
            "No services requiring management (or user skipped previous prompts)."
        )

    print_info("-" * 60)
    print_warning("Dependency check finished. Please review the output above.")
    print_info("It's recommended to re-run this script after making changes to verify.")
    print_info(
        "If 'xsct' installation failed via apt, ensure you follow the manual steps if needed."
    )
    sys.exit(1 if not all_deps_ok else 0)


if __name__ == "__main__":
    # Basic check for running on a non-APT system (very simplistic)
    if not shutil.which("apt"):
        print_error(
            "This script is intended for APT-based systems (Debian, Ubuntu, Mint)."
        )
        print_error("Dependency checking logic for 'apt' will not work.")
        # sys.exit(1) # Or let it run and fail on apt commands

    main()
