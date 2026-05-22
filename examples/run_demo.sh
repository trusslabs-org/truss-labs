#!/usr/bin/env bash
# Boot the Truss Audit proxy with the shipped example policies + phi taxonomy.
# Real Gemini upstream if GEMINI_API_KEY is in ~/.gemini/.env (or env), else stub.
#
# Usage: ./examples/run_demo.sh [host:port]
#   default host:port = 127.0.0.1:8000
#
# Open examples/demo.html in a browser after this is up.

set -euo pipefail

HOSTPORT="${1:-127.0.0.1:8000}"
HOST="${HOSTPORT%:*}"
PORT="${HOSTPORT##*:}"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -f "${HOME}/.gemini/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${HOME}/.gemini/.env"
  set +a
fi

export TRUSS_POLICIES_DIR="${REPO_ROOT}/examples/policies"
export TRUSS_RECEIPTS_DIR="${TRUSS_RECEIPTS_DIR:-${HOME}/.truss/ledger/receipts}"
export TRUSS_TAXONOMIES="${REPO_ROOT}/primitives/audit/taxonomies/phi.yaml"

cd "${REPO_ROOT}"
echo "policies:    ${TRUSS_POLICIES_DIR}"
echo "receipts:    ${TRUSS_RECEIPTS_DIR}"
echo "taxonomies:  ${TRUSS_TAXONOMIES}"
echo "model:       ${GEMINI_MODEL_ID:-gemini-3-flash-preview}  ($([ -n "${GEMINI_API_KEY:-}" ] && echo real || echo stub))"
echo "listening:   http://${HOST}:${PORT}"
echo

# Prefer Homebrew Python as it contains dependencies
PYTHON_BIN="/opt/homebrew/bin/python3"
if [[ ! -f "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

exec "$PYTHON_BIN" -m uvicorn primitives.audit.proxy:create_app_from_env \
  --factory --host "${HOST}" --port "${PORT}"
