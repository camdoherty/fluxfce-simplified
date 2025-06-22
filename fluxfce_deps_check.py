#!/usr/bin/env python3

import os
import shutil
import sys

MIN_PYTHON_VERSION = (3, 9)

# --- Helper Functions (copied for script self-containment) ---
def print_info(message: str): print(f"[INFO] {message}")
def print_warning(message: str): print(f"[WARN] {message}")
def print_error(message: str): print(f"[ERROR] {message}")
def print_success(message: str): print(f"[OK]   {message}")

def get_desktop_environment() -> str:
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
    if "XFCE" in desktop: return "XFCE"
    if "CINNAMON" in desktop: return "CINNAMON"
    return "UNKNOWN"

# --- DE-specific Dependencies ---
DEPS_COMMON = {
    "systemctl": ("systemd", "Systemd control tool ('systemctl')"),
    "timedatectl": ("systemd", "Systemd time/date tool ('timedatectl')"),
    "xsct": ("xsct", "Screen Color Temperature tool ('xsct')"),
}
DEPS_XFCE = {
    "xfconf-query": ("xfce4-utils", "XFCE Configuration tool ('xfconf-query')"),
    "xfdesktop": ("xfdesktop4", "XFCE Desktop manager ('xfdesktop')"),
    "xrandr": ("x11-xserver-utils", "Xrandr display tool"),
}
DEPS_CINNAMON = {
    "gsettings": ("libglib2.0-bin", "GSettings configuration tool ('gsettings')"),
    "gdbus": ("libglib2.0-bin", "GDBus command-line tool"),
}

# --- Main Logic ---

def check_command_installed(cmd_name: str, friendly_name: str) -> bool:
    """Checks if a command is installed and executable using shutil.which."""
    print_info(f"Checking for {friendly_name} ('{cmd_name}')...")
    path = shutil.which(cmd_name)
    if path:
        print_success(f"{friendly_name} found at: {path}")
        return True
    else:
        print_error(f"{friendly_name} ('{cmd_name}') NOT found in PATH.")
        return False

def main():
    print_info("FluxFCE Universal Dependency Checker")
    print_info("=" * 60)

    current_de = get_desktop_environment()
    print_info(f"Detected Desktop Environment: {current_de}")

    if current_de == "UNKNOWN":
        print_error("Could not determine Desktop Environment (XFCE or Cinnamon).")
        print_error("Cannot verify all dependencies. Please ensure required tools are installed manually.")
        sys.exit(1)

    # 1. Check Python Version
    print_info(f"\nChecking Python version (minimum {MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]})...")
    if sys.version_info < MIN_PYTHON_VERSION:
        print_error(f"Python version is too old. FluxFCE requires Python {MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]}+.")
        sys.exit(1)
    print_success(f"Python version {sys.version_info.major}.{sys.version_info.minor} is sufficient.")

    # 2. Determine and check dependencies
    deps_to_check = DEPS_COMMON.copy()
    if current_de == "XFCE":
        deps_to_check.update(DEPS_XFCE)
    elif current_de == "CINNAMON":
        deps_to_check.update(DEPS_CINNAMON)

    print_info(f"\n--- Checking for required commands for {current_de} ---")
    all_ok = True
    for cmd, (_, friendly) in deps_to_check.items():
        if not check_command_installed(cmd, friendly):
            all_ok = False

    # 3. Final result
    print_info("-" * 60)
    if all_ok:
        print_success("All checked dependencies appear to be OK!")
        sys.exit(0)
    else:
        print_error("One or more critical dependencies are missing.")
        print_error("Please review the output above and install them manually before proceeding.")
        sys.exit(1)

if __name__ == "__main__":
    main()