#!/bin/bash
set -e
REPO_ROOT=$(pwd)
BUILD_DIR="tmp/truss-primitives"
TARGET_DIR="www/public/demo"
TARBALL="truss-primitives.tar.gz"
echo "Building $TARBALL..."
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
cp primitives/scripts/truss.py "$BUILD_DIR/truss"
chmod +x "$BUILD_DIR/truss"
cp primitives/scripts/truss_translate.py "$BUILD_DIR/"
cp primitives/scripts/truss_analyze.py "$BUILD_DIR/"
cp primitives/scripts/truss_trap.py "$BUILD_DIR/"
printf "{\"timestamp\": \"2026-05-18T10:00:00Z\", \"session_id\": \"demo-123\", \"event\": \"AfterTool\", \"operation\": \"ls\", \"target\": \"docs\", \"content\": \"file1.txt\"}
{\"timestamp\": \"2026-05-18T10:00:01\", \"session_id\": \"demo-123\", \"event\": \"AfterTool\", \"operation\": \"ls\", \"target\": \"docs\", \"content\": \"file1.txt\"}
{\"timestamp\": \"2026-05-18T10:00:02Z\", \"session_id\": \"demo-123\", \"event\": \"AfterTool\", \"operation\": \"ls\", \"target\": \"docs\", \"content\": \"file1.txt\"}
" > "$BUILD_DIR/hooks.jsonl"
cp LICENSE "$BUILD_DIR/"
printf "# Truss Primitives

This package contains the core CLI tools for the Truss Audit substrate.

## Usage

1. Add the current directory to your PATH or run directly:
   ./truss --help

2. Run the sample pipe:
   cat hooks.jsonl | ./truss translate | ./truss analyze --json --flag FLAG_CIRCULAR_REASONING | ./truss trap run

## Tools
- truss: The main entry point
- truss_translate.py: hooks.jsonl -> TWP nodes
- truss_analyze.py: Flag detection
- truss_trap.py: Runtime intervention

License: Apache 2.0
" > "$BUILD_DIR/README.md"
mkdir -p "$TARGET_DIR"
tar -czf "$TARGET_DIR/$TARBALL" -C tmp truss-primitives
echo "Success: $TARGET_DIR/$TARBALL created."
ls -lh "$TARGET_DIR/$TARBALL"
