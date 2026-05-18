#!/usr/bin/env bash
# Artifact 3 — Unix-native composition receipt (proves Belief 3)
#
# Belief (verbatim, trusslabs.org):
#   "Agent tooling should be Unix-native: small CLI primitives that
#    compose, not a locked platform."
#
# One-liner:
#   truss analyze | truss trap — a Unix sentence, not a SaaS workflow.
#
# Clarity test:
#   Two cold reviewers watch the recording and articulate, unprompted:
#   "this composes with my existing shell tools, not a locked platform."
#
# Task: 310
# Target length: ~15 seconds.
#
# ------------------------------------------------------------------------
# HOW TO RECORD
# ------------------------------------------------------------------------
#
# This script is SELF-RUNNING. The on-camera input is ONE command:
#
#     ./demo/artifact_3_unix_pipe.sh
#
# Live-typing a long pipe under tmux paste is too fragile (newlines get
# injected mid-pipe and zsh splits on them). The runner below prints fake
# prompts and runs each command so the recording is deterministic.
#
# Steps:
#
# 1. From repo root, in your own terminal (NOT through Claude's `!`):
#      cd ~/Code/truss-labs
#      export TRUSS_PROJECT=truss-labs-310-demo
#      asciinema rec demo/artifact_3_unix_pipe.cast
#
# 2. Inside the recording shell, run:
#      ./demo/artifact_3_unix_pipe.sh
#
# 3. When it finishes (~13s), Ctrl-D to stop recording.
#
# 4. Preview:
#      asciinema play demo/artifact_3_unix_pipe.cast
#
# 5. Re-record until it lands. Don't edit the .cast file.
#
# ------------------------------------------------------------------------
# WHAT MAKES THIS VISCERALLY USEFUL
# ------------------------------------------------------------------------
#
# The pipe runs against a real session's hooks.jsonl from this very
# laptop's registry — a session where the agent actually got stuck
# retrying the same Edit. TRAP-1 fires on each retry node. No fixtures,
# no fake data: same shell vocabulary you already use, applied to your
# agent's behavior.
#
# ------------------------------------------------------------------------
# PRE-FLIGHT (done off camera, idempotent — safe to run again)
# ------------------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

export TRUSS_PROJECT="${TRUSS_PROJECT:-truss-labs-310-demo}"
python3 primitives/scripts/truss_trap.py clear > /dev/null
python3 primitives/scripts/truss_trap.py add --on ON_RETRY --action ACTION_HALT > /dev/null

SESSION="$HOME/truss/sessions/truss-labs/11810484-c02b-4497-9032-38dce49851d2"

# ------------------------------------------------------------------------
# ON-CAMERA SEQUENCE
# ------------------------------------------------------------------------

# Fake-prompt + typing helpers. Prints a prompt, "types" the command at a
# readable cadence, then runs it.
PROMPT=$'\033[36m~/Code/truss-labs\033[0m \033[32m$\033[0m '
TYPE_DELAY=0.012  # per-character; ~15ms feels human, not robotic

type_cmd() {
  local cmd="$1"
  printf '%s' "$PROMPT"
  for ((i=0; i<${#cmd}; i++)); do
    printf '%s' "${cmd:i:1}"
    sleep "$TYPE_DELAY"
  done
  printf '\n'
}

run_step() {
  local cmd="$1"
  type_cmd "$cmd"
  eval "$cmd"
  sleep 0.6
}

# [0:00] An agent session — every tool call, on disk, one event per line.
run_step "wc -l $SESSION/hooks.jsonl"

# [0:04] Three primitives. One pipe. Find every retry loop.
run_step "cat $SESSION/hooks.jsonl | python3 primitives/scripts/truss_translate.py | python3 primitives/scripts/truss_analyze.py --json --flag FLAG_CIRCULAR_REASONING 2>/dev/null | python3 primitives/scripts/truss_trap.py run 2>/dev/null | head -3"

# [0:13] Final prompt — leave a clean trailing line so the cast ends well.
printf '%s\n' "$PROMPT"
