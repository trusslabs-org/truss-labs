#!/usr/bin/env bash
# Idempotent bootstrap for the Truss audit-proxy demo on a fresh Ubuntu 24.04 VM.
#
# Run this AS ROOT on the VM, after the operator has staged:
#   - /tmp/truss.tar.gz       — tarball of the truss-labs working tree
#   - /tmp/truss-env-staging  — file containing GEMINI_API_KEY=... (mode 0600)
#
# Layout produced:
#   /opt/truss/truss-labs/      code
#   /opt/truss/venv/            python venv
#   /var/truss/receipts/        receipt destination
#   /etc/truss/env              env file (mode 0600, owned by root:truss)
#   /etc/systemd/system/truss-audit-proxy.service
#
# Idempotent: rerunnable. Refreshes code, dependencies, and env without
# breaking existing receipts.

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "must run as root (use sudo)" >&2
  exit 1
fi

CODE_TARBALL="${1:-/tmp/truss.tar.gz}"
ENV_STAGING="${2:-/tmp/truss-env-staging}"

[[ -f "$CODE_TARBALL" ]] || { echo "missing $CODE_TARBALL" >&2; exit 1; }
[[ -f "$ENV_STAGING" ]] || { echo "missing $ENV_STAGING" >&2; exit 1; }

TRUSS_USER="truss"
CODE_DIR="/opt/truss/truss-labs"
VENV_DIR="/opt/truss/venv"
RECEIPTS_DIR="/var/truss/receipts"
ENV_FILE="/etc/truss/env"

echo "==> Installing system dependencies"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip ca-certificates curl

echo "==> Creating system user '$TRUSS_USER'"
if ! id -u "$TRUSS_USER" >/dev/null 2>&1; then
  useradd --system --home-dir /var/truss --create-home --shell /usr/sbin/nologin "$TRUSS_USER"
fi

echo "==> Preparing directories"
mkdir -p /opt/truss "$RECEIPTS_DIR" /etc/truss
chown -R "$TRUSS_USER:$TRUSS_USER" /var/truss

echo "==> Unpacking code"
mkdir -p "$CODE_DIR"
tar -xzf "$CODE_TARBALL" -C "$CODE_DIR"
chown -R root:root "$CODE_DIR"  # code is read-only to the truss user

echo "==> Setting up Python venv"
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet \
  "fastapi>=0.115" "uvicorn[standard]>=0.30" "pydantic>=2.10" \
  "pyyaml>=6.0" "jsonschema>=4.26" "google-genai>=1.0"
chown -R root:root "$VENV_DIR"

echo "==> Installing env file"
install -m 600 -o root -g "$TRUSS_USER" "$ENV_STAGING" "$ENV_FILE"
rm -f "$ENV_STAGING"

echo "==> Installing systemd units"
install -m 644 "$CODE_DIR/examples/deploy/gcp/systemd/truss-audit-proxy.service" \
  /etc/systemd/system/truss-audit-proxy.service
install -m 644 "$CODE_DIR/examples/deploy/gcp/systemd/truss-receipt-cleanup.service" \
  /etc/systemd/system/truss-receipt-cleanup.service
install -m 644 "$CODE_DIR/examples/deploy/gcp/systemd/truss-receipt-cleanup.timer" \
  /etc/systemd/system/truss-receipt-cleanup.timer
systemctl daemon-reload
systemctl enable truss-audit-proxy.service
systemctl restart truss-audit-proxy.service
systemctl enable --now truss-receipt-cleanup.timer

echo "==> Health check"
for i in {1..15}; do
  if curl -fsS http://127.0.0.1:8000/healthz >/dev/null 2>&1; then
    curl -s http://127.0.0.1:8000/healthz
    echo
    echo "==> Provision complete."
    exit 0
  fi
  sleep 1
done

echo "Proxy did not become healthy in 15s — check 'journalctl -u truss-audit-proxy -n 100'" >&2
exit 1
