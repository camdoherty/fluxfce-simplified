#!/usr/bin/env bash

# Script to initialize Python formatting (black) and linting (ruff) for the lightfx project.

# Exit immediately if a command exits with a non-zero status.
set -e

# --- Configuration ---
PROJECT_ROOT_DIR=$(pwd) # Assumes script is run from the project root
PYTHON_FILES=(
    "lightfx_cli.py"
    "lightfx_deps_check.py" # Or your actual requirements checker script name
    "lightfx_core/"
)
TARGET_PYTHON_VERSION="py39"
VENV_NAME=".venv-lightfx-dev" # Name for the project-specific virtual environment

# --- Helper Functions ---
print_info() {
    echo "INFO: $1"
}

print_success() {
    echo "SUCCESS: $1"
}

print_warning() {
    echo "WARNING: $1"
}

print_error() {
    echo "ERROR: $1"
}

# --- Main Logic ---

INSTALL_METHOD=""

# Determine installation method for black & ruff
if command -v pipx &> /dev/null; then
    print_info "pipx found. Will use pipx to install black and ruff."
    INSTALL_METHOD="pipx"
else
    print_warning "pipx not found."
    if python3 -m venv --help &> /dev/null; then # Check if venv module is available
        print_info "Will attempt to use a project-specific Python virtual environment for black and ruff."
        INSTALL_METHOD="venv"
    else
        print_warning "Python's 'venv' module not found. This is unusual."
        print_info "Attempting to install black and ruff using 'apt' as a fallback."
        INSTALL_METHOD="apt"
    fi
fi


# 1. Install black and ruff
if [ "$INSTALL_METHOD" = "pipx" ]; then
    print_info "Installing/updating black and ruff using pipx..."
    pipx install black
    pipx install ruff
    pipx ensurepath # Ensures ~/.local/bin (where pipx shims are) is in PATH
    print_warning "If this is the first time running 'pipx ensurepath', you may need to open a new terminal or source your shell profile."
elif [ "$INSTALL_METHOD" = "venv" ]; then
    if [ ! -d "${PROJECT_ROOT_DIR}/${VENV_NAME}" ]; then
        print_info "Creating virtual environment at ${PROJECT_ROOT_DIR}/${VENV_NAME}..."
        python3 -m venv "${PROJECT_ROOT_DIR}/${VENV_NAME}"
        print_success "Virtual environment created."
    else
        print_info "Virtual environment ${PROJECT_ROOT_DIR}/${VENV_NAME} already exists."
    fi
    print_info "Activating virtual environment and installing/updating black and ruff..."
    # shellcheck disable=SC1091
    source "${PROJECT_ROOT_DIR}/${VENV_NAME}/bin/activate"
    pip install --upgrade black ruff
    # Note: When the script finishes, the venv will still be active in this script's subshell,
    # but not in the parent shell unless the user sources it manually.
    # For running black/ruff *within this script*, this is fine.
    # User would need to activate venv manually to run them later from terminal.
    print_info "To use these tools manually later, activate the venv: source ${VENV_NAME}/bin/activate"
elif [ "$INSTALL_METHOD" = "apt" ]; then
    print_info "Attempting to install python3-black and python3-ruff using apt..."
    print_warning "Note: Versions from apt may not be the latest available on PyPI."
    if sudo apt update && sudo apt install -y python3-black python3-ruff; then
        print_success "python3-black and python3-ruff installed via apt."
    else
        print_error "Failed to install tools via apt. Please install black and ruff manually."
        exit 1
    fi
else
    print_error "Could not determine an installation method for black and ruff. Please install them manually."
    exit 1
fi

print_success "black and ruff installation step complete."

# --- Rest of the script (pyproject.toml creation, running tools) remains the same ---

# 2. Create pyproject.toml for ruff
PYPROJECT_FILE="${PROJECT_ROOT_DIR}/pyproject.toml"
print_info "Checking for ${PYPROJECT_FILE}..."
# ... (pyproject.toml creation logic as before) ...
# (Ensure you paste the full pyproject.toml creation logic here from the previous script version)
CREATE_RUFF_CONFIG=true
if [ -f "$PYPROJECT_FILE" ]; then
    if grep -q "\[tool.ruff\]" "$PYPROJECT_FILE"; then
        print_info "Found existing [tool.ruff] configuration in ${PYPROJECT_FILE}. Skipping creation."
        CREATE_RUFF_CONFIG=false
    else
        print_info "${PYPROJECT_FILE} exists but no [tool.ruff] section found. Will append."
    fi
fi

if [ "$CREATE_RUFF_CONFIG" = true ]; then
    print_info "Creating/updating ${PYPROJECT_FILE} with ruff configuration..."
    cat << EOF >> "$PYPROJECT_FILE"

[tool.ruff]
select = [
    "E", "F", "W", "I", "UP", "B", "C90", "SIM", "TID", "RUF",
]
ignore = ["B008", "E501"]
line-length = 88
indent-width = 4
target-version = "${TARGET_PYTHON_VERSION}"

[tool.ruff.lint]
fixable = ["ALL"]
unfixable = []
dummy-variable-rgx = "^(_+|(_+[a-zA-Z0-9_]*[a-zA-Z0-9]+?))$"

[tool.ruff.lint.isort]
known-first-party = ["lightfx_core", "lightfx_dependency_setup"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
skip-magic-trailing-comma = false
line-ending = "auto"
docstring-code-format = true
docstring-code-line-length = "dynamic"
EOF
    print_success "${PYPROJECT_FILE} created/updated with ruff configuration."
else
    print_info "Please ensure your existing [tool.ruff] configuration in ${PYPROJECT_FILE} is appropriate."
fi

# 3. Run black to format code
print_info "Running black to format Python files..."
if [ "$INSTALL_METHOD" = "venv" ]; then
    # shellcheck disable=SC1091
    source "${PROJECT_ROOT_DIR}/${VENV_NAME}/bin/activate" # Ensure venv is active
fi
if command -v black &> /dev/null; then
    black "${PYTHON_FILES[@]}"
    print_success "black formatting complete."
else
    print_warning "black command not found. Please ensure it's installed and in your PATH."
    print_warning "If using a virtual environment, make sure it's activated."
fi


# 4. Run ruff to check and autofix
print_info "Running ruff to check and autofix Python files..."
if [ "$INSTALL_METHOD" = "venv" ]; then
    # shellcheck disable=SC1091
    source "${PROJECT_ROOT_DIR}/${VENV_NAME}/bin/activate" # Ensure venv is active
fi
if command -v ruff &> /dev/null; then
    ruff check --fix --exit-non-zero-on-fix "${PYTHON_FILES[@]}" || true
    print_info "Ruff autofix attempt complete."
    print_info "Running ruff check again to show remaining issues (if any)..."
    ruff check "${PYTHON_FILES[@]}" || print_warning "Ruff found issues. Please review the output above."
    print_success "Ruff check complete."
else
    print_warning "ruff command not found. Please ensure it's installed and in your PATH."
    print_warning "If using a virtual environment, make sure it's activated."
fi

# Deactivate venv if we sourced it (optional, as script subshell will exit anyway)
if [ "$INSTALL_METHOD" = "venv" ] && command -v deactivate &> /dev/null ; then
    # Check if 'deactivate' function exists (specific to some venv activators)
    print_info "Deactivating virtual environment (within script scope)."
    deactivate || true # Squelch error if deactivate isn't a function/alias somehow
fi


print_info "---"
print_info "Formatting and linting script finished."
# ... (rest of the final messages) ...
print_info "Review any changes made by black and ruff, and address any remaining ruff warnings."
print_info "You might want to commit the changes to pyproject.toml and the formatted/linted files."
if [ "$INSTALL_METHOD" = "venv" ]; then
    print_info "To run black/ruff manually later, activate the virtual environment: source ${PROJECT_ROOT_DIR}/${VENV_NAME}/bin/activate"
fi