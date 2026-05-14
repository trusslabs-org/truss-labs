"""
soul_translate.py — convert ~/soul_registry/sessions/*/*/hooks.jsonl entries
into TWP-shaped JSONL nodes that compose with soul_query / soul_trap.

Bridges the schema gap noted in task 310: native hooks.jsonl is a hooks-event
log; the audit primitives (soul_query, soul_trap) want post-ingest TWP nodes
with node_id / type / audit_flags. This translator is the "option (b)" 5-line
primitive from that task's blocker — slightly more than 5 lines because audit-
flag detection has to do real work.

Usage:
    soul_translate [input] [output]
    cat hooks.jsonl | soul_translate | soul_query --json --flag FLAG_CRITICAL_FAILURE
"""
import argparse
import json
import os
import re
import signal
import sys
from collections import deque

try:
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except (AttributeError, ValueError):
    pass


CIRCULAR_WINDOW = 10
CIRCULAR_THRESHOLD = 3
OUTPUT_TRUNCATE = 8192

ERROR_RX = re.compile(r"\b(Error|Traceback|Exception|FAIL(?:ED|URE)?)\b", re.IGNORECASE)
NONZERO_EXIT_RX = re.compile(r"['\"]?(?:returncode|exit_code|exitCode)['\"]?\s*[:=]\s*([1-9]\d*)")


def _open_input(path):
    if path in (None, "-"):
        return sys.stdin, False
    if not os.path.exists(path):
        print(f"Error: {path} not found.", file=sys.stderr)
        sys.exit(2)
    return open(path, "r"), True


def _open_output(path):
    if path in (None, "-"):
        return sys.stdout, False
    return open(path, "w"), True


def _node_type(entry):
    event = entry.get("event")
    if event == "AfterTool":
        return "NODE_TOOL"
    if event in ("AfterModel", "AfterAgent"):
        return "NODE_LOGIC"
    return "NODE_LOGIC"


def _provenance(entry):
    op = (entry.get("op") or entry.get("operation") or "").upper()
    if op == "DECISION":
        return "PROV_INJECTED"
    return "PROV_NATURAL"


def _parse_outputs(content):
    """hooks.jsonl content is often a Python-repr stringified dict (e.g.
    "{'stdout': '...', 'returncode': 0}"). Try to recover structure; fall back
    to truncated string."""
    if not content:
        return {}
    text = str(content)[:OUTPUT_TRUNCATE]
    if text.startswith("{") and ("'" in text or '"' in text):
        # Best-effort: try JSON first (proper escaping), then ast.literal_eval
        try:
            return json.loads(text)
        except Exception:
            try:
                import ast
                v = ast.literal_eval(text)
                if isinstance(v, dict):
                    return v
            except Exception:
                pass
    return {"text": text}


def _detect_flags(entry, outputs, sliding_window):
    flags = []

    # FLAG_CRITICAL_FAILURE — error markers in content, or nonzero return code
    raw_content = str(entry.get("content", "") or "")
    if ERROR_RX.search(raw_content):
        flags.append("FLAG_CRITICAL_FAILURE")
    elif NONZERO_EXIT_RX.search(raw_content):
        flags.append("FLAG_CRITICAL_FAILURE")
    elif isinstance(outputs, dict):
        # Parsed dict path: explicit nonzero codes
        for key in ("returncode", "exit_code", "exitCode"):
            v = outputs.get(key)
            if isinstance(v, int) and v != 0:
                flags.append("FLAG_CRITICAL_FAILURE")
                break

    # FLAG_CIRCULAR_REASONING — same (op, target) ≥ N times in trailing window
    op = entry.get("operation") or entry.get("op")
    target = entry.get("target")
    if op and target and target != "none":
        repeats = sum(1 for o, t in sliding_window if o == op and t == target)
        if repeats + 1 >= CIRCULAR_THRESHOLD:  # +1 counts the current entry
            flags.append("FLAG_CIRCULAR_REASONING")

    # FLAG_CONFIDENCE_LOW (proxy) — heuristic placeholder intent left a trailing
    # space because the target was missing/unknown when the heuristic ran.
    sv = entry.get("strategic_vector") or {}
    intent = sv.get("intent")
    if isinstance(intent, str) and intent and intent.endswith(" "):
        flags.append("FLAG_CONFIDENCE_LOW")

    return flags


def translate(input_path, output_path):
    in_stream, close_in = _open_input(input_path)
    try:
        lines = in_stream.read().splitlines()
    finally:
        if close_in:
            in_stream.close()

    out_stream, close_out = _open_output(output_path)
    sliding = deque(maxlen=CIRCULAR_WINDOW)
    prev_id_by_session = {}
    seq_by_session = {}
    written = 0

    try:
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue
            if entry.get("event") == "SESSION_START":
                continue  # marker, not a real node

            session = entry.get("session_id", "unknown")
            seq_by_session[session] = seq_by_session.get(session, 0) + 1
            seq = seq_by_session[session]
            node_id = f"h{session[:8]}-{seq:05d}"
            parent_id = prev_id_by_session.get(session)

            outputs = _parse_outputs(entry.get("content"))
            flags = _detect_flags(entry, outputs, sliding)

            # Field-name fallback: standard hook entries use {timestamp,
            # operation}; /decision rows from soul_log_decision.py use
            # {ts, op}. Translator must accept both shapes.
            node = {
                "timestamp": entry.get("timestamp") or entry.get("ts"),
                "node_id": node_id,
                "parent_id": parent_id,
                "type": _node_type(entry),
                "name": (
                    entry.get("tool")
                    or (entry.get("operation") or entry.get("op") or "").lower()
                ),
                "inputs": {
                    "target": entry.get("target"),
                    "cwd": entry.get("cwd"),
                    "intent": entry.get("intent"),
                },
                "outputs": outputs,
                "provenance": _provenance(entry),
                "audit_flags": flags,
            }
            out_stream.write(json.dumps(node) + "\n")

            prev_id_by_session[session] = node_id
            op = entry.get("operation") or entry.get("op")
            target = entry.get("target")
            if op and target:
                sliding.append((op, target))
            written += 1
    finally:
        if close_out:
            out_stream.close()

    label = output_path if output_path not in (None, "-") else "stdout"
    print(f"Translated {written} hooks.jsonl entries to {label}", file=sys.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Translate hooks.jsonl event log into TWP-shaped trace nodes.")
    parser.add_argument("input", nargs="?", default="-",
                        help="Input hooks.jsonl path, or '-' / omitted for stdin")
    parser.add_argument("output", nargs="?", default="-",
                        help="Output TWP JSONL path, or '-' / omitted for stdout")
    args = parser.parse_args()
    translate(args.input, args.output)
