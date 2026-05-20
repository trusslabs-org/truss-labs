import json
import sys
import argparse
import os
import signal

try:
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except (AttributeError, ValueError):
    pass


def load_nodes(source):
    """Yield parsed JSONL nodes from a file path or file-like object."""
    if hasattr(source, 'read'):
        stream = source
        close = False
    else:
        if not os.path.exists(source):
            print(f"Error: Trace file {source} not found.", file=sys.stderr)
            return
        stream = open(source, 'r')
        close = True
    try:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue
    finally:
        if close:
            stream.close()


def filter_nodes(nodes, node_type=None, flag=None, node_id=None):
    for node in nodes:
        if node_type and node.get('type') != node_type:
            continue
        if flag and flag not in node.get('audit_flags', []):
            continue
        if node_id and node.get('node_id') != node_id:
            continue
        yield node


def emit_json(results):
    for node in results:
        sys.stdout.write(json.dumps(node) + '\n')


def emit_pretty(results, node_index):
    results = list(results)
    if not results:
        print("No matching nodes found.")
        return
    print(f"--- TRUSS ANALYZE RESULTS ({len(results)} matches) ---")
    for r in results:
        print(f"\n[ NODE: {r['node_id']} | TYPE: {r['type']} ]")
        print(f"  Name: {r.get('name', '')}")
        print(f"  Timestamp: {r.get('timestamp', '')}")
        if r.get('audit_flags'):
            print(f"  Flags: {', '.join(r['audit_flags'])}")
        parent_id = r.get('parent_id')
        if parent_id and parent_id in node_index:
            p = node_index[parent_id]
            print(f"  Parent: {p['node_id']} ({p['type']})")
            print(f"    Parent Intent: {json.dumps(p.get('inputs', {}))[:100]}...")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Query a Truss Trace Log.")
    parser.add_argument("trace", nargs="?", default="-",
                        help="Path to a .jsonl trace file, or '-' / omitted to read stdin")
    parser.add_argument("--type", help="Filter by node type (e.g., NODE_LOGIC, NODE_TOOL)")
    parser.add_argument("--flag", help="Filter by audit flag (e.g., FLAG_CIRCULAR_REASONING)")
    parser.add_argument("--id", help="Find specific node by ID")
    parser.add_argument("--json", action="store_true",
                        help="Emit one JSON node per line to stdout (for pipes)")
    parser.add_argument("--pretty", action="store_true",
                        help="Human-readable output (default when --json is absent)")

    args = parser.parse_args()

    source = sys.stdin if args.trace == "-" else args.trace
    nodes = list(load_nodes(source))
    node_index = {n['node_id']: n for n in nodes if 'node_id' in n}
    results = filter_nodes(nodes, node_type=args.type, flag=args.flag, node_id=args.id)

    if args.json:
        emit_json(results)
    else:
        emit_pretty(results, node_index)