#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-examples/receipts}"
TODAY="$(date -u +%Y-%m-%d)"

find "$ROOT" -name '*.json' -print0 |
  xargs -0 jq -r --arg today "$TODAY" '
    select(.retention.legal_hold != true)
    | select(.retention.retain_until < $today)
    | [.receipt_id, .retention.retain_until, input_filename] | @tsv
  '
