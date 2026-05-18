import json
import sys
import argparse
import os
import signal

try:
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except (AttributeError, ValueError):
    pass

DEFAULT_PROJECT = "truss-labs"


def _project() -> str:
    return os.environ.get("TRUSS_PROJECT", DEFAULT_PROJECT)


def _traps_path() -> str:
    return os.path.expanduser(f"~/soul_registry/specs/{_project()}/traps.json")


def load_traps():
    path = _traps_path()
    if not os.path.exists(path):
        return []
    with open(path, 'r') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def save_traps(traps):
    path = _traps_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(traps, f, indent=2)


def add_trap(on_condition, action, limit=None, threshold=None):
    traps = load_traps()
    trap = {
        "id": f"TRAP-{len(traps) + 1}",
        "on": on_condition,
        "action": action,
        "limit": limit,
        "threshold": threshold,
        "status": "active"
    }
    traps.append(trap)
    save_traps(traps)
    print(f"Trap added: {trap['id']} (On: {on_condition} -> Action: {action})")


def list_traps():
    traps = load_traps()
    if not traps:
        print(f"No active traps for project '{_project()}'.")
        return
    print(f"--- ACTIVE TRUSS TRAPS ({_project()}) ---")
    for t in traps:
        print(f"[{t['id']}] On: {t['on']} | Action: {t['action']} | Status: {t['status']}")


def clear_traps():
    save_traps([])
    print(f"All traps cleared for project '{_project()}'.")


# Map trigger conditions to the audit flag they watch for on a trace node.
TRIGGER_FLAG_MAP = {
    "ON_ERROR": "FLAG_CRITICAL_FAILURE",
    "ON_RETRY": "FLAG_CIRCULAR_REASONING",
    "ON_CONFIDENCE_LOW": "FLAG_CONFIDENCE_LOW",
    "ON_STATE_DRIFT": "FLAG_STATE_DRIFT",
}


def _node_triggers_trap(node: dict, trap: dict) -> bool:
    if trap.get("status") != "active":
        return False
    flag = TRIGGER_FLAG_MAP.get(trap["on"])
    if not flag:
        return False
    return flag in node.get("audit_flags", [])


def run_traps():
    """Read trace JSONL from stdin, evaluate each node against active traps.

    Prints matches to stdout as JSON lines. Exits nonzero if any ACTION_HALT fires.
    """
    traps = [t for t in load_traps() if t.get("status") == "active"]
    if not traps:
        print(f"[truss-trap] no active traps for '{_project()}'; nothing to evaluate.",
              file=sys.stderr)
        return 0

    halted = False
    match_count = 0
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            node = json.loads(line)
        except json.JSONDecodeError:
            continue
        for trap in traps:
            if _node_triggers_trap(node, trap):
                match_count += 1
                event = {
                    "trap_id": trap["id"],
                    "on": trap["on"],
                    "action": trap["action"],
                    "node_id": node.get("node_id"),
                    "node_type": node.get("type"),
                    "node_name": node.get("name"),
                    "audit_flags": node.get("audit_flags", []),
                }
                sys.stdout.write(json.dumps(event) + "\n")
                sys.stdout.flush()
                if trap["action"] == "ACTION_HALT":
                    halted = True

    print(f"[truss-trap] evaluated against {len(traps)} trap(s); {match_count} match(es).",
          file=sys.stderr)
    return 1 if halted else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage Semantic Breakpoints (Traps).")
    subparsers = parser.add_subparsers(dest="command")

    add_parser = subparsers.add_parser("add", help="Add a new trap")
    add_parser.add_argument("--on", required=True,
                            choices=list(TRIGGER_FLAG_MAP.keys()),
                            help="Trigger condition")
    add_parser.add_argument("--action", required=True,
                            choices=["ACTION_HALT", "ACTION_SOCRATIC", "ACTION_BRANCH"],
                            help="Safety action")
    add_parser.add_argument("--limit", type=int, help="Limit for errors/retries")
    add_parser.add_argument("--threshold", type=float, help="Threshold for confidence/drift")

    subparsers.add_parser("list", help="List active traps")
    subparsers.add_parser("clear", help="Clear all traps")
    subparsers.add_parser("run", help="Evaluate traps against trace JSONL on stdin")

    args = parser.parse_args()

    if args.command == "add":
        add_trap(args.on, args.action, args.limit, args.threshold)
    elif args.command == "list":
        list_traps()
    elif args.command == "clear":
        clear_traps()
    elif args.command == "run":
        sys.exit(run_traps())
    else:
        parser.print_help()
