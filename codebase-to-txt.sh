#!/bin/bash

# Output file
OUTPUT_FILE="codebase.txt"
# Directory to search (current directory)
SEARCH_DIR="."
# Separator string
SEPARATOR="##############"

# Clear the output file if it exists
> "$OUTPUT_FILE"

# Find relevant files, excluding __pycache__ and .git
find "$SEARCH_DIR" \( -path "$SEARCH_DIR/__pycache__" -o -path "$SEARCH_DIR/.git" \) -prune -o \
\( -name "*.py" -o -name "*.md" \) -print | sort | while IFS= read -r FILE; do
    echo "$SEPARATOR" >> "$OUTPUT_FILE"
    echo "$FILE" >> "$OUTPUT_FILE" # Print relative path
    echo "" >> "$OUTPUT_FILE" # Blank line
    cat "$FILE" >> "$OUTPUT_FILE"
    echo "" >> "$OUTPUT_FILE" # Blank line after content
done

# Add a final separator
echo "$SEPARATOR" >> "$OUTPUT_FILE"

echo "Codebase concatenated into $OUTPUT_FILE"