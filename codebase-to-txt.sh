#!/usr/bin/env bash
set -euo pipefail

# Generate date string in YYYY-MM-DD format
DATE=$(date +%Y-%m-%d)
# Define output file name
OUTPUT="codebase-$DATE.txt"

# Initialize (or truncate) the output file
> "$OUTPUT"

# Find all .py, .md, and .toml files, ignoring specified files/dirs
INCLUDED_FILES=$(find . \
  -type d \( -name backup -o -name todo \) -prune -false \
  -o -type f \( -name '*.py' -o -name '*.md' -o -name '*.toml' \) \
  ! -name '*.log' \
  ! -name 'prompt*' \
  ! -name 'codebase*' \
  | sort)

# Print included files to terminal
echo "Files included in $OUTPUT:"
echo "$INCLUDED_FILES"
echo

# Concatenate files into the output, separated cleanly
while IFS= read -r file; do
  relpath="${file#./}"
  {
    echo
    echo '##############'
    echo "$relpath"
    echo
    cat "$file"
    echo
  } >> "$OUTPUT"
done <<< "$INCLUDED_FILES"

echo
echo "All matching files have been concatenated into $OUTPUT"
