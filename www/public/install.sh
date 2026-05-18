#!/bin/bash
# Truss Audit Substrate Installer
set -e

echo "🛡️ Initializing Truss installation..."

TRUSS_HOME="$HOME/.truss"
BIN_DIR="$TRUSS_HOME/bin"
PRIMITIVES_DIR="$TRUSS_HOME/primitives"
VERSION="0.2.0"
TARBALL_URL="https://trusslabs.org/demo/truss-primitives-v$VERSION.tar.gz"

# 1. Create directory structure
mkdir -p "$BIN_DIR"
mkdir -p "$PRIMITIVES_DIR"
mkdir -p "$TRUSS_HOME/ledger/receipts"
mkdir -p "$TRUSS_HOME/ledger/tasks"
mkdir -p "$TRUSS_HOME/ledger/sessions"

# 2. Download and extract
echo "🛡️ Downloading Truss v$VERSION..."
curl -sSL "$TARBALL_URL" -o "/tmp/truss.tar.gz"

echo "🛡️ Extracting primitives..."
tar -xzf "/tmp/truss.tar.gz" -C "$PRIMITIVES_DIR" --strip-components=1

# 3. Setup binary
chmod +x "$PRIMITIVES_DIR/truss"
ln -sf "$PRIMITIVES_DIR/truss" "$BIN_DIR/truss"

# 4. Final instructions
echo "------------------------------------------------"
echo "🛡️ Truss CLI installed successfully!"
echo ""
echo "To use 'truss', add it to your PATH:"
echo "  export PATH="\$PATH:$BIN_DIR""
echo ""
echo "Try it out: truss --help"
echo "------------------------------------------------"
