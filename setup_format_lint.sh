setup_format_lint.sh

#!/usr/bin/env bash

# Script to initialize Python formatting (black) and linting (ruff) for the fluxfce project.

# Exit immediately if a command exits with a non-zero status.
set -e

# --- Configuration ---
PROJECT_ROOT_DIR=$(pwd) # Assumes script is run from the project root
PYTHON_FILES=(
    "fluxfce_cli.py"
    "fluxfce_dependency_setup.py" # Or your actual requirements checker script name
    "fluxfce_core/"
    # Add other Python files or directories if necessary
)
TARGET_PYTHON_VERSION="py39" # Matches fluxfce requirement

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

# --- Main Logic ---

# 1. Check for pip
if ! command -v pip &> /dev/null && ! command -v pip3 &> /dev/null; then
    print_warning "pip (or pip3) command not found. Please install pip."
    print_warning "For Debian/Ubuntu: sudo apt install python3-pip"
    exit 1
fi
PIP_CMD=$(command -v pip3 || command -v pip)

# 2. Install black and ruff
print_info "Installing/updating black and ruff using $PIP_CMD..."
$PIP_CMD install --user --upgrade black ruff # --user installs to user's site-packages

# Ensure tools installed with --user are in PATH (common issue)
# This is a simple check; a more robust solution might involve checking Python's sys.path
if ! command -v black &> /dev/null || ! command -v ruff &> /dev/null; then
    print_warning "black or ruff not found in PATH after installation."
    print_warning "This might be because ~/.local/bin is not in your PATH."
    print_warning "Please add it: export PATH=\"\$HOME/.local/bin:\$PATH\" (add to your ~/.bashrc or ~/.zshrc)"
    print_warning "Then, try running this script again in a new terminal."
    # Don't exit immediately, user might have them installed via other means (e.g. system package, pipx)
    # but it's good to warn. If they aren't found later, the script will fail.
fi


# 3. Create pyproject.toml for ruff (if it doesn't exist or is empty/minimal)
PYPROJECT_FILE="${PROJECT_ROOT_DIR}/pyproject.toml"
print_info "Checking for ${PYPROJECT_FILE}..."

# Basic check: if file exists and contains [tool.ruff], assume it's configured.
# A more sophisticated check could parse TOML, but this is often sufficient for a setup script.
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
    # Using cat with a HEREDOC to write the TOML content
    # Append mode (>>) in case other [tool.*] sections exist but not [tool.ruff]
    cat << EOF >> "$PYPROJECT_FILE"

[tool.ruff]
select = [
    "E",  # pycodestyle errors
    "F",  # Pyflakes
    "W",  # pycodestyle warnings
    "I",  # isort (import sorting)
    "UP", # pyupgrade (upgrade syntax to newer Python versions)
    "B",  # flake8-bugbear (potential bugs/design problems)
    "C90",# flake8-comprehensions (for more Pythonic comprehensions)
    "SIM",# flake8-simplify
    "TID",# flake8-tidy-imports
    # "PLC", "PLE", "PLR", "PLW", # Pylint conventions, errors, refactoring, warnings (can be noisy, add selectively)
    "RUF", # Ruff-specific rules
]
ignore = [
    "B008", # Do not perform function calls in argument defaults (sometimes intended)
    "E501", # Line too long (black will handle this, or ruff format) - can be useful to keep for ruff check if not using ruff format
]
line-length = 88
indent-width = 4
target-version = "${TARGET_PYTHON_VERSION}"
# If your project has a src directory:
# src = ["src"]
# exclude = [
#     ".git",
#     ".venv",
#     "__pycache__",
#     "build",
#     "dist",
#     "*.egg-info",
# ]

[tool.ruff.lint]
# Provide a fix for all supported rules.
fixable = ["ALL"]
unfixable = []

# Allow unused variables when underscore-prefixed.
dummy-variable-rgx = "^(_+|(_+[a-zA-Z0-9_]*[a-zA-Z0-9]+?))$"

[tool.ruff.lint.isort]
# Assuming fluxfce_core is your main first-party library
known-first-party = ["fluxfce_core", "fluxfce_dependency_setup"] # Add other top-level local modules

[tool.ruff.format]
# To make ruff's formatter behave like black (or close to it)
# Use this if you intend to use `ruff format .` as your primary formatter
# If you only use `black`, this section might not be strictly necessary
# unless ruff's linting phase needs to know about formatting choices.
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

# 4. Run black to format code
print_info "Running black to format Python files..."
if command -v black &> /dev/null; then
    black "${PYTHON_FILES[@]}"
    print_success "black formatting complete."
else
    print_warning "black command not found. Please ensure it's installed and in your PATH."
fi


# 5. Run ruff to check and autofix
print_info "Running ruff to check and autofix Python files..."
if command -v ruff &> /dev/null; then
    ruff check --fix --exit-non-zero-on-fix "${PYTHON_FILES[@]}" || true # Allow to continue even if some fixes remain after --exit-non-zero-on-fix
    print_info "Ruff autofix attempt complete."
    print_info "Running ruff check again to show remaining issues (if any)..."
    ruff check "${PYTHON_FILES[@]}" || print_warning "Ruff found issues. Please review the output above."
    print_success "Ruff check complete."
else
    print_warning "ruff command not found. Please ensure it's installed and in your PATH."
fi

# 6. (Optional) Run ruff format if you want ruff to be the primary formatter
# print_info "Running ruff to format Python files..."
# if command -v ruff &> /dev/null; then
#    ruff format "${PYTHON_FILES[@]}"
#    print_success "Ruff formatting complete."
# else
#    print_warning "ruff command not found."
# fi

print_info "---"
print_info "Formatting and linting script finished."
print_info "Review any changes made by black and ruff, and address any remaining ruff warnings."
print_info "You might want to commit the changes to pyproject.toml and the formatted/linted files."