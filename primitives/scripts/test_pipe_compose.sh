#!/usr/bin/env bash
# Smoke test: prove trace analyze | trap run composes as a real Unix pipe under Truss.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURE="$(mktemp -t truss_trace.XXXXXX.jsonl)"
TRAP_EVENTS="$(mktemp -t truss_trap_events.XXXXXX.jsonl)"
trap 'rm -f "$FIXTURE" "$TRAP_EVENTS"' EXIT

# Isolate the trap config so we don't touch the real registry.
export TRUSS_PROJECT="truss-labs-test-$$"

cat > "$FIXTURE" <<'JSONL'
{"timestamp":"2026-04-18T12:00:00Z","node_id":"n1","parent_id":null,"type":"NODE_LOGIC","name":"plan","inputs":{"goal":"demo"},"outputs":{},"provenance":"PROV_NATURAL","audit_flags":[]}
{"timestamp":"2026-04-18T12:00:01Z","node_id":"n2","parent_id":"n1","type":"NODE_TOOL","name":"grep","inputs":{"q":"x"},"outputs":{},"provenance":"PROV_NATURAL","audit_flags":["FLAG_CIRCULAR_REASONING"]}
{"timestamp":"2026-04-18T12:00:02Z","node_id":"n3","parent_id":"n1","type":"NODE_TOOL","name":"http","inputs":{"url":"y"},"outputs":{},"provenance":"PROV_NATURAL","audit_flags":["FLAG_CRITICAL_FAILURE"]}
JSONL

# Configure a trap that halts on retry loops.
python3 "$SCRIPT_DIR/truss.py" trap clear > /dev/null
python3 "$SCRIPT_DIR/truss.py" trap add --on ON_RETRY --action ACTION_HALT > /dev/null

# The pipe under test: trace JSONL → query filter → trap evaluation.
set +e
cat "$FIXTURE" \
  | python3 "$SCRIPT_DIR/truss.py" trace analyze --json --flag FLAG_CIRCULAR_REASONING \
  | python3 "$SCRIPT_DIR/truss.py" trap run \
  > "$TRAP_EVENTS"
PIPE_EXIT=$?
set -e

# Cleanup isolated trap config.
python3 "$SCRIPT_DIR/truss.py" trap clear > /dev/null
rm -rf "$HOME/.truss/ledger/specs/$TRUSS_PROJECT" 2>/dev/null || true

# Assert: pipe produced output, and halt trap fired (exit 1).
if [ ! -s "$TRAP_EVENTS" ]; then
  echo "FAIL: pipe produced no trap events" >&2
  exit 1
fi
if [ "$PIPE_EXIT" -ne 1 ]; then
  echo "FAIL: expected exit 1 (ACTION_HALT), got $PIPE_EXIT" >&2
  exit 1
fi
if ! grep -q '"TRAP-1"' "$TRAP_EVENTS"; then
  echo "FAIL: TRAP-1 did not fire. Events:" >&2
  cat "$TRAP_EVENTS" >&2
  exit 1
fi

echo "PASS: trace analyze | trap run composes. Trap event:"
cat "$TRAP_EVENTS"
