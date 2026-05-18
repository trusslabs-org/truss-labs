#!/usr/bin/env bash
# Artifact 1 — State-on-disk receipt (proves Belief 1)
#
# Belief (verbatim, trusslabs.org):
#   "State belongs on disk, not in a vendor's database."
#
# One-liner:
#   Your agent's memory is at ~/.truss/ledger/. Back it up with cp -r.
#   Walk away from any vendor tomorrow.
#
# Clarity test:
#   Two cold reviewers watch the recording and articulate, unprompted:
#   "my agent's memory lives on my disk, not someone else's cloud."
#
# Task: 309
# Target length: 55-65 seconds.
#
# ------------------------------------------------------------------------
# HOW TO RECORD
# ------------------------------------------------------------------------
#
# 1. Install asciinema if needed:
#      brew install asciinema
#
# 2. Start the recording:
#      asciinema rec demo/artifact_1_state_on_disk.cast
#
# 3. Type the commands below live. Do NOT execute this file.
#    Pace: slow enough to be readable, fast enough to land under 65s total.
#
# 4. Ctrl-D to stop. Preview:
#      asciinema play demo/artifact_1_state_on_disk.cast
#
# 5. Re-record until it lands. Don't edit the .cast file.
#
# ------------------------------------------------------------------------
# PRIVACY NOTE
# ------------------------------------------------------------------------
#
# This script is scoped to truss-labs/ on purpose. The ~/.truss/ledger/tasks/
# directory at the top level contains other project names (client work,
# personal projects) that may be private. Do NOT run `ls tasks/` unscoped
# during recording without reviewing what's there first.
#
# ------------------------------------------------------------------------
# THE SEQUENCE
# ------------------------------------------------------------------------

# [0:00] "The agent's memory lives on my disk. Here's the directory."
cd ~/truss
pwd

# [0:07] "Organized by project."
ls -d tasks/truss-labs traces/truss-labs

# [0:14] "Tasks are just JSON files."
ls tasks/truss-labs/

# [0:23] "Cat any of them like a text file."
head -20 tasks/truss-labs/309.json

# [0:37] "Traces live here too — one directory per session."
ls traces/truss-labs/MacBookPro/

# [0:45] "Each trace is JSONL — one event per line, plain text."
cat traces/truss-labs/MacBookPro/*/hooks.jsonl | head -2

# [0:52] "Grep across tasks the same way you'd grep any directory."
grep -h '"belief":' tasks/truss-labs/*.json | head -3

# [0:58] "That's the whole thing. cp -r takes it anywhere."
du -sh tasks/truss-labs/ traces/truss-labs/
