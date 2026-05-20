#!/usr/bin/env bash
# Smoke test: prove hooks.jsonl → trace translate → trace analyze → trap run
# composes end-to-end as a real Unix pipe under Truss.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_FIXTURE="$(mktemp -t hooks_fix.XXXXXX.jsonl)"
TRAP_EVENTS="$(mktemp -t truss_trap_events.XXXXXX.jsonl)"
trap 'rm -f "$HOOKS_FIXTURE" "$TRAP_EVENTS"' EXIT

# Isolate trap config — don't touch the real registry.
export TRUSS_PROJECT="truss-labs-translate-test-$$"

# Fixture: native hooks.jsonl shape with a SESSION_START marker, an error,
# and a 3x retry on the same target.
cat > "$HOOKS_FIXTURE" <<'JSONL'
{"event":"SESSION_START","timestamp":"2026-05-03T10:00:00","session_id":"abc12345","pid":1,"ppid":1}
{"timestamp":"2026-05-03T10:00:01","event":"AfterTool","operation":"BASH","session_id":"abc12345","cwd":"/x","tool":"Bash","target":"ls /tmp","content":"{'stdout': 'foo', 'returncode': 0}"}
{"timestamp":"2026-05-03T10:00:02","event":"AfterTool","operation":"BASH","session_id":"abc12345","cwd":"/x","tool":"Bash","target":"cat /missing","content":"{'stderr': 'cat: /missing: No such file', 'returncode': 1}"}
{"timestamp":"2026-05-03T10:00:03","event":"AfterTool","operation":"READ","session_id":"abc12345","cwd":"/x","tool":"Read","target":"/etc/hosts","content":"{'type': 'text'}"}
{"timestamp":"2026-05-03T10:00:04","event":"AfterTool","operation":"READ","session_id":"abc12345","cwd":"/x","tool":"Read","target":"/etc/hosts","content":"{'type': 'text'}"}
{"timestamp":"2026-05-03T10:00:05","event":"AfterTool","operation":"READ","session_id":"abc12345","cwd":"/x","tool":"Read","target":"/etc/hosts","content":"{'type': 'text'}"}
JSONL

# Configure ON_RETRY trap that halts. Use the new CLI structure.
python3 "$SCRIPT_DIR/truss.py" trap clear > /dev/null
python3 "$SCRIPT_DIR/truss.py" trap add --on ON_RETRY --action ACTION_HALT > /dev/null

# Pipe under test: hooks.jsonl → translate → query (filter circular) → trap.
set +e
cat "$HOOKS_FIXTURE" \
  | python3 "$SCRIPT_DIR/truss.py" trace translate \
  | python3 "$SCRIPT_DIR/truss.py" trace analyze --json --flag FLAG_CIRCULAR_REASONING \
  | python3 "$SCRIPT_DIR/truss.py" trap run \
  > "$TRAP_EVENTS"
PIPE_EXIT=$?
set -e

# Cleanup.
python3 "$SCRIPT_DIR/truss.py" trap clear > /dev/null
rm -rf "$HOME/.truss/ledger/specs/$TRUSS_PROJECT" 2>/dev/null || true

# Assertions.
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
# Spot-check that translation produced a TWP-shaped node id (h<sid>-NNNNN).
if ! grep -qE '"node_id": "h[a-f0-9]+-[0-9]+"' "$TRAP_EVENTS"; then
  echo "FAIL: trap event did not reference TWP-shaped node_id" >&2
  cat "$TRAP_EVENTS" >&2
  exit 1
fi

echo "PASS: hooks.jsonl → translate → query → trap composes. Trap event:"
cat "$TRAP_EVENTS"
