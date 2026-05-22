#!/bin/bash
set -e
REPO_ROOT=$(pwd)
BUILD_DIR="tmp/truss-primitives"
TARGET_DIR="www/public/demo"
VERSION="0.3.2"
TARBALL="truss-primitives-v$VERSION.tar.gz"

echo "Building $TARBALL..."
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/primitives"

# Create root entry point as 'truss'. Keep it as a tiny wrapper so module-local
# paths such as primitives/scripts/truss_trap.py resolve correctly.
cat > "$BUILD_DIR/truss" <<'PY'
#!/usr/bin/env python3
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "primitives" / "scripts"))

from primitives.scripts.truss import main

if __name__ == "__main__":
    main()
PY
chmod +x "$BUILD_DIR/truss"

# Copy the entire primitives tree (including scripts and audit)
cp -r primitives/* "$BUILD_DIR/primitives/"
mkdir -p "$BUILD_DIR/examples"
cp -r examples/policies "$BUILD_DIR/examples/"
cp -r examples/receipts "$BUILD_DIR/examples/"

# Ensure __init__.py exists in the primitives folder for namespace/module resolution
touch "$BUILD_DIR/primitives/__init__.py"

# Create fixtures/hooks for demo
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
   ./truss trap add --on ON_RETRY --action ACTION_HALT
   cat hooks.jsonl | ./truss trace translate | ./truss trace analyze --json --flag FLAG_CIRCULAR_REASONING | ./truss trap run

3. Verify the sample receipts:
   ./truss receipt verify examples/receipts

License: Apache 2.0
" > "$BUILD_DIR/README.md"

mkdir -p "$TARGET_DIR"
tar -czf "$TARGET_DIR/$TARBALL" -C tmp truss-primitives
# Also keep the generic name
cp "$TARGET_DIR/$TARBALL" "$TARGET_DIR/truss-primitives.tar.gz"

echo "Success: $TARGET_DIR/$TARBALL created."
ls -lh "$TARGET_DIR/$TARBALL"
