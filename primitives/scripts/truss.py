#!/usr/bin/env python3
"""
truss — The high-level CLI for the Truss Audit substrate.
"""

import hashlib
import argparse
import json
import signal
import sys
import os
import subprocess
import time
import socket
import importlib
from pathlib import Path

# Try to set SIGPIPE to default to handle broken pipes gracefully (Unix only)
try:
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except (AttributeError, ValueError):
    pass

DEFAULT_RECEIPTS_DIR = Path("~/.truss/ledger/receipts").expanduser()
DEFAULT_PROXY_PORT = 8000

def _sha256_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()

def ensure_dependencies(packages):
    """
    Surgically install missing dependencies via pip.
    """
    missing = []
    for pkg in packages:
        # Map import name to pip package name if different
        install_name = pkg
        import_name = pkg
        if ":" in pkg:
            import_name, install_name = pkg.split(":")
        
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing.append(install_name)
    
    if not missing:
        return

    print(f"🛡️ Truss: Missing dependencies found ({', '.join(missing)})")
    print(f"🛡️ Bootstrapping environment...")
    
    try:
        # Check if we are in a venv
        is_venv = sys.prefix != sys.base_prefix
        pip_cmd = [sys.executable, "-m", "pip", "install"]
        if not is_venv:
            print("⚠️ Warning: Not running in a virtual environment. Installation might require permissions.")
        
        subprocess.check_call(pip_cmd + missing)
        print(f"🛡️ Bootstrapping complete. Continuing...\n")
    except Exception as e:
        print(f"❌ Error: Failed to install dependencies: {e}", file=sys.stderr)
        print(f"Please install manually: pip install {' '.join(missing)}", file=sys.stderr)
        sys.exit(1)

# --- Receipt Commands ---

def cmd_index(args):
    path = Path(args.path).expanduser()
    if not path.exists():
        print(f"Error: receipts directory not found at {path}")
        sys.exit(1)
    receipts = list(path.glob("**/*.json"))
    print(f"Scanned {path}")
    print(f"Found {len(receipts)} receipts.")

def cmd_verify(args):
    path = Path(args.path).expanduser()
    if not path.exists():
        print(f"Error: receipts path not found: {path}", file=sys.stderr)
        sys.exit(1)
    if path.is_file():
        receipts = [path]
    else:
        receipts = sorted(path.glob("**/*.json"))
    if not receipts and not args.allow_empty:
        print(f"Error: no receipt JSON files found under {path}", file=sys.stderr)
        sys.exit(1)

    print(f"Verifying {len(receipts)} receipt(s) under {path}...")
    failures = 0
    for r_path in receipts:
        try:
            with open(r_path, "r", encoding="utf-8") as f:
                receipt = json.load(f)
            stored_hash = receipt["evidence"]["receipt_hash"]
            receipt["evidence"]["receipt_hash"] = ""
            canonical = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            recomputed = _sha256_hash(canonical)
            if stored_hash != recomputed:
                print(f"FAIL: {r_path} hash mismatch")
                print(f"  stored:     {stored_hash}")
                print(f"  recomputed: {recomputed}")
                failures += 1
            else:
                print(f"OK:   {r_path}")
        except Exception as e:
            print(f"FAIL: {r_path} ({e})")
            failures += 1
    if failures == 0:
        print(f"PASS: verified {len(receipts)} receipt(s).")
    else:
        print(f"FAIL: {failures} of {len(receipts)} receipt(s) failed verification.")
        sys.exit(1)

def cmd_query(args):
    ensure_dependencies(["duckdb"])
    import duckdb
    path = Path(args.path).expanduser()
    json_pattern = str(path / "**" / "*.json")
    try:
        sql = args.sql.replace("receipts", f"read_json_auto('{json_pattern}')")
        rel = duckdb.query(sql)
        if rel: print(rel.df().to_string(index=False))
    except Exception as e:
        print(e)
        sys.exit(1)

def cmd_report(args):
    ensure_dependencies(["duckdb"])
    import duckdb
    path = Path(args.path).expanduser()
    json_pattern = str(path / "**" / "*.json")
    print(f"--- Truss Audit Weekly Activity Report ---")
    try:
        # 1. Volume
        print("\n[ Volume by Day ]")
        print(duckdb.query(f"SELECT timestamp[1:10] as day, count(*) FROM read_json_auto('{json_pattern}') GROUP BY 1 ORDER BY 1 DESC").df().to_string(index=False))
        
        # 2. Data Classes
        print("\n[ Sensitive Data Classes Touched ]")
        print(duckdb.query(f"SELECT d.class, count(*) FROM (SELECT UNNEST(data_classes_touched) as d FROM read_json_auto('{json_pattern}')) GROUP BY 1 ORDER BY 2 DESC").df().to_string(index=False))

        # 3. Policy Verdicts
        print("\n[ Policy Enforcement Summary ]")
        print(duckdb.query(f"SELECT p.verdict, count(*) FROM (SELECT UNNEST(policy_decisions) as p FROM read_json_auto('{json_pattern}')) GROUP BY 1 ORDER BY 2 DESC").df().to_string(index=False))
    except Exception as e:
        print(f"Report Error: {e}")

# --- Pipe Commands (imported/wrapped from truss_*.py) ---

def cmd_translate(args):
    try:
        from truss_translate import translate
    except ImportError:
        from .truss_translate import translate
    translate(args.input, args.output)

def cmd_analyze(args):
    try:
        from truss_analyze import load_nodes, filter_nodes, emit_json, emit_pretty
    except ImportError:
        from .truss_analyze import load_nodes, filter_nodes, emit_json, emit_pretty
        
    source = sys.stdin if args.trace == "-" else args.trace
    nodes = list(load_nodes(source))
    node_index = {n['node_id']: n for n in nodes if 'node_id' in n}
    results = filter_nodes(nodes, node_type=args.type, flag=args.flag, node_id=args.id)

    if args.json:
        emit_json(results)
    else:
        emit_pretty(results, node_index)

def cmd_trap(args):
    script_path = Path(__file__).parent / "truss_trap.py"
    cmd = [sys.executable, str(script_path), args.trap_command]
    if args.on: cmd.extend(["--on", args.on])
    if args.action: cmd.extend(["--action", args.action])
    if args.project: cmd.extend(["--project", args.project])
    
    subprocess.run(cmd)

# --- The Demo Wrapper ---

def is_port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def cmd_exec(args):
    """
    truss exec [options] -- command args...
    """
    # 1. Parse manual options since argparse.REMAINDER is finicky
    policy = None
    port = DEFAULT_PROXY_PORT
    command = []

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--policy" and i + 1 < len(args):
            policy = args[i+1]
            i += 2
        elif arg == "--port" and i + 1 < len(args):
            port = int(args[i+1])
            i += 2
        elif arg == "--":
            command = args[i+1:]
            break
        else:
            # First non-option is the start of the command if no --
            command = args[i:]
            break
    
    if not command:
        print("Error: No command provided to exec.")
        sys.exit(1)

    # Surgical Dependency Check
    ensure_dependencies(["fastapi", "uvicorn", "httpx", "yaml:pyyaml", "pydantic"])

    proxy_proc = None
    if not is_port_open(port):
        print(f"🛡️ Starting Truss Audit Proxy on port {port}...")
        proxy_env = os.environ.copy()
        if policy:
            proxy_env["TRUSS_POLICY_PATH"] = str(Path(policy).absolute())
        
        # Start uvicorn in the background
        proxy_proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "primitives.audit.proxy:create_app_from_env", "--port", str(port), "--factory"],
            env=proxy_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        # Wait for proxy to start
        retries = 30
        while not is_port_open(port) and retries > 0:
            time.sleep(0.2)
            retries -= 1
        
        if retries == 0:
            print("Error: Truss Audit Proxy failed to start.", file=sys.stderr)
            if proxy_proc: proxy_proc.terminate()
            sys.exit(1)
        print("🛡️ Truss Audit Proxy ready.")
    else:
        print(f"🛡️ Using existing Truss Audit Proxy on port {port}.")

    print(f"🛡️ Truss Governance Active (Policy: {policy or 'default'})")
    print(f"🛡️ Executing: {' '.join(command)}")
    
    # 2. Prepare Environment
    env = os.environ.copy()
    proxy_url = f"http://localhost:{port}"
    env["HTTP_PROXY"] = proxy_url
    env["HTTPS_PROXY"] = proxy_url
    env["http_proxy"] = proxy_url
    env["https_proxy"] = proxy_url
    
    # 3. Run the command
    try:
        result = subprocess.run(command, env=env)
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Truss Error: {e}", file=sys.stderr)
    finally:
        if proxy_proc:
            print("\n🛡️ Stopping Truss Audit Proxy...")
            proxy_proc.terminate()
            proxy_proc.wait()
            print("🛡️ Truss Audit Proxy stopped.")

def main():
    # If first arg is 'exec', handle it manually to avoid argparse subparser issues with REMAINDER
    if len(sys.argv) > 1 and sys.argv[1] == "exec":
        cmd_exec(sys.argv[2:])
        return

    parser = argparse.ArgumentParser(prog="truss")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_index = subparsers.add_parser("index", help="Index receipts")
    p_index.add_argument("path", type=str, default=str(DEFAULT_RECEIPTS_DIR), nargs="?")

    p_verify = subparsers.add_parser("verify", help="Verify receipt hashes")
    p_verify.add_argument("path", type=str, default=str(DEFAULT_RECEIPTS_DIR), nargs="?")
    p_verify.add_argument("--allow-empty", action="store_true")

    p_query = subparsers.add_parser("query", help="Query receipts using SQL (DuckDB)")
    p_query.add_argument("sql", help="SQL query. Use 'receipts' as the table name.")
    p_query.add_argument("--path", type=str, default=str(DEFAULT_RECEIPTS_DIR))

    p_report = subparsers.add_parser("report", help="Generate audit report")
    p_report.add_argument("--path", type=str, default=str(DEFAULT_RECEIPTS_DIR))

    p_translate = subparsers.add_parser("translate", help="Translate hooks.jsonl to TWP nodes")
    p_translate.add_argument("input", nargs="?", default="-")
    p_translate.add_argument("output", nargs="?", default="-")

    p_analyze = subparsers.add_parser("analyze", help="Analyze trace nodes for flags")
    p_analyze.add_argument("trace", nargs="?", default="-")
    p_analyze.add_argument("--type", help="Filter by node type")
    p_analyze.add_argument("--flag", help="Filter by audit flag")
    p_analyze.add_argument("--id", help="Filter by node ID")
    p_analyze.add_argument("--json", action="store_true", help="Emit JSONL")

    p_trap = subparsers.add_parser("trap", help="Manage and run audit traps")
    p_trap.add_argument("trap_command", choices=["add", "clear", "list", "run"])
    p_trap.add_argument("--on", help="Trap condition (e.g. ON_RETRY)")
    p_trap.add_argument("--action", help="Trap action (e.g. ACTION_HALT)")
    p_trap.add_argument("--project", help="Project name")

    args = parser.parse_args()

    if args.command == "index": cmd_index(args)
    elif args.command == "verify": cmd_verify(args)
    elif args.command == "query": cmd_query(args)
    elif args.command == "report": cmd_report(args)
    elif args.command == "translate": cmd_translate(args)
    elif args.command == "analyze": cmd_analyze(args)
    elif args.command == "trap": cmd_trap(args)

if __name__ == "__main__":
    sys.path.append(str(Path(__file__).parent))
    main()
