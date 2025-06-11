#!/usr/bin/env bash
set -euo pipefail

# Generate date string in YYYY-MM-DD format
DATE=$(date +%Y-%m-%d)
# Define output file name
OUTPUT="codebase-$DATE.txt"

# Initialize (or truncate) the output file
> "$OUTPUT"

# Find all .py, .md, and .toml files (explicit extensions) and sort them
find . -type f \( -name '*.py' -o -name '*.md' -o -name '*.toml' \) | sort | while IFS= read -r file; do
  # Remove leading './' for a clean relative path
  relpath="${file#./}"

  # Append separator, path, and file content to the output
  {
    echo
    echo '##############'
    echo "$relpath"
    echo
    cat "$file"
    echo
  } >> "$OUTPUT"
done

# Inform the user
echo "All matching files have been concatenated into $OUTPUT"
