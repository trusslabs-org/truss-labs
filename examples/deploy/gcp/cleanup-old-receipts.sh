#!/usr/bin/env bash
# Delete demo receipts older than TRUSS_RECEIPT_RETENTION_DAYS (default 7).
#
# Driven by examples/deploy/gcp/systemd/truss-receipt-cleanup.timer (daily).
# The receipts themselves are written with retention_days=7 by the demo, so
# this just enforces the same number at the storage layer.

set -euo pipefail

RECEIPTS_DIR="${TRUSS_RECEIPTS_DIR:-/var/truss/receipts}"
RETENTION_DAYS="${TRUSS_RECEIPT_RETENTION_DAYS:-7}"

if [[ ! -d "$RECEIPTS_DIR" ]]; then
  echo "receipts dir does not exist: $RECEIPTS_DIR" >&2
  exit 0
fi

# Files
find "$RECEIPTS_DIR" -type f -name '*.json' -mtime "+$RETENTION_DAYS" -delete

# Per-day directories that became empty
find "$RECEIPTS_DIR" -mindepth 1 -type d -empty -delete
