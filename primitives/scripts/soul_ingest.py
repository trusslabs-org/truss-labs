import json
import sys
import os
import argparse
import signal

try:
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except (AttributeError, ValueError):
    pass


def _open_input(path):
    if path in (None, "-"):
        return sys.stdin, False
    if not os.path.exists(path):
        print(f"Error: {path} not found.", file=sys.stderr)
        sys.exit(2)
    return open(path, 'r'), True


def _open_output(path):
    if path in (None, "-"):
        return sys.stdout, False
    return open(path, 'w'), True


def ingest_langchain(input_path, output_path):
    in_stream, close_in = _open_input(input_path)
    try:
        data = json.load(in_stream)
    finally:
        if close_in:
            in_stream.close()

    hooks = []
    tool_inputs = set()

    for run in data:
        node_type = "NODE_LOGIC"
        if run['run_type'] == 'tool':
            node_type = "NODE_TOOL"
        elif run['run_type'] == 'chain':
            node_type = "CLUSTER"

        audit_flags = []
        if node_type == "NODE_TOOL":
            tool_input_str = json.dumps(run['inputs'])
            if tool_input_str in tool_inputs:
                audit_flags.append("FLAG_CIRCULAR_REASONING")
            tool_inputs.add(tool_input_str)

        if run.get('error'):
            audit_flags.append("FLAG_CRITICAL_FAILURE")

        hook = {
            "timestamp": run['start_time'],
            "node_id": run['run_id'],
            "parent_id": run['parent_run_id'],
            "type": node_type,
            "name": run['name'],
            "inputs": run['inputs'],
            "outputs": run['outputs'],
            "provenance": "PROV_EXTERNAL_LANGCHAIN",
            "audit_flags": audit_flags
        }
        hooks.append(hook)

    out_stream, close_out = _open_output(output_path)
    try:
        for hook in hooks:
            out_stream.write(json.dumps(hook) + '\n')
    finally:
        if close_out:
            out_stream.close()

    label = output_path if output_path not in (None, "-") else "stdout"
    print(f"Ingested {len(hooks)} nodes to {label}", file=sys.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Convert a LangChain run JSON dump into JSONL trace nodes.")
    parser.add_argument("input", nargs="?", default="-",
                        help="Input JSON path, or '-' / omitted for stdin")
    parser.add_argument("output", nargs="?", default="-",
                        help="Output JSONL path, or '-' / omitted for stdout")
    args = parser.parse_args()
    ingest_langchain(args.input, args.output)
