#!/usr/bin/env bash
# Smoke test: prove soul_query | soul_trap composes as a real Unix pipe.
#
# Task: 311 (unblocks Artifact 3 / task 310).
#
# This test exercises the pipe mechanically against a fixture shaped like a
# post-ingest TWP trace (node_id / type / audit_flags). The current
# ~/truss/traces/ directory holds hooks-event JSONL, which has a
# different shape — a translator from hooks.jsonl → TWP node shape is a
# separate concern (soul_ingest is currently LangChain-only).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURE="$(mktemp -t soul_trace.XXXXXX.jsonl)"
TRAP_EVENTS="$(mktemp -t soul_trap_events.XXXXXX.jsonl)"
trap 'rm -f "$FIXTURE" "$TRAP_EVENTS"' EXIT

# Isolate the trap config so we don't touch the real registry.
export SOUL_PROJECT="truss-labs-test-$$"

cat > "$FIXTURE" <<'JSONL'
{"timestamp":"2026-04-18T12:00:00Z","node_id":"n1","parent_id":null,"type":"NODE_LOGIC","name":"plan","inputs":{"goal":"demo"},"outputs":{},"provenance":"PROV_NATURAL","audit_flags":[]}
{"timestamp":"2026-04-18T12:00:01Z","node_id":"n2","parent_id":"n1","type":"NODE_TOOL","name":"grep","inputs":{"q":"x"},"outputs":{},"provenance":"PROV_NATURAL","audit_flags":["FLAG_CIRCULAR_REASONING"]}
{"timestamp":"2026-04-18T12:00:02Z","node_id":"n3","parent_id":"n1","type":"NODE_TOOL","name":"http","inputs":{"url":"y"},"outputs":{},"provenance":"PROV_NATURAL","audit_flags":["FLAG_CRITICAL_FAILURE"]}
JSONL

# Configure a trap that halts on retry loops.
python3 "$SCRIPT_DIR/soul_trap.py" clear > /dev/null
python3 "$SCRIPT_DIR/soul_trap.py" add --on ON_RETRY --action ACTION_HALT > /dev/null

# The pipe under test: trace JSONL → query filter → trap evaluation.
set +e
cat "$FIXTURE" \
  | python3 "$SCRIPT_DIR/soul_query.py" --json --flag FLAG_CIRCULAR_REASONING \
  | python3 "$SCRIPT_DIR/soul_trap.py" run \
  > "$TRAP_EVENTS"
PIPE_EXIT=$?
set -e

# Cleanup isolated trap config.
python3 "$SCRIPT_DIR/soul_trap.py" clear > /dev/null
rm -rf "$HOME/truss/specs/$SOUL_PROJECT" 2>/dev/null || true

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

echo "PASS: soul_query | soul_trap composes. Trap event:"
cat "$TRAP_EVENTS"
