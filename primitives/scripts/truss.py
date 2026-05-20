#!/usr/bin/env python3
"""
truss — The high-level, noun-first CLI for the Truss Audit substrate.
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
import shlex
import shutil
from pathlib import Path

VERSION = "0.3.1"

# Try to set SIGPIPE to default to handle broken pipes gracefully (Unix only)
try:
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except (AttributeError, ValueError):
    pass

TRUSS_DIR = Path("~/.truss").expanduser()
LEDGER_DIR = TRUSS_DIR / "ledger"
DEFAULT_RECEIPTS_DIR = LEDGER_DIR / "receipts"
VENV_DIR = TRUSS_DIR / "venv"
VENV_PYTHON = VENV_DIR / "bin" / "python3"
DEFAULT_PROXY_PORT = 8000
PROXY_LOG = TRUSS_DIR / "proxy.log"

def _sha256_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()

def bootstrap_ledger():
    """Ensures ledger directory structure exists."""
    TRUSS_DIR.mkdir(parents=True, exist_ok=True)
    # Always ensure log file exists so tail doesn't fail
    if not PROXY_LOG.exists():
        PROXY_LOG.touch()
    
    subdirs = ["receipts", "tasks", "sessions", "teams", "specs"]
    for sd in subdirs:
        (LEDGER_DIR / sd).mkdir(parents=True, exist_ok=True)

def ensure_bootstrap(packages=None):
    """
    Ensures we are running in the private Truss venv and dependencies are installed.
    """
    bootstrap_ledger()
    packages = packages or []
    
    # 1. Check if we are already running inside our private venv
    if str(sys.executable) == str(VENV_PYTHON):
        missing = []
        for pkg in packages:
            import_name = pkg.split(":")[0] if ":" in pkg else pkg
            try:
                importlib.import_module(import_name)
            except ImportError:
                missing.append(pkg.split(":")[1] if ":" in pkg else pkg)
        
        if missing:
            print(f"🛡️ Truss: Adding dependencies to venv ({', '.join(missing)})...")
            subprocess.check_call([str(VENV_PYTHON), "-m", "pip", "install"] + missing)
        return

    # 2. Not in venv. Does it exist?
    if not VENV_PYTHON.exists():
        print(f"🛡️ Truss: Initializing private environment at {VENV_DIR}...")
        TRUSS_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)])
        subprocess.check_call([str(VENV_PYTHON), "-m", "pip", "install", "--upgrade", "pip", "setuptools"])

    # 3. Always ensure basic dependencies are in the venv before we re-exec
    base_deps = ["fastapi", "uvicorn", "httpx", "pyyaml", "pydantic"]
    
    print(f"🛡️ Truss: Entering isolated environment...")
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), __file__] + sys.argv[1:])

# --- System Commands ---

def cmd_install(args):
    """
    Installs the truss CLI to ~/.local/bin and bootstraps the ledger.
    """
    print(f"🛡️ Bootstrapping Truss Ledger at {LEDGER_DIR}...")
    bootstrap_ledger()
    
    bin_dir = Path("~/.local/bin").expanduser()
    bin_dir.mkdir(parents=True, exist_ok=True)
    dest = bin_dir / "truss"
    
    src = Path(__file__).absolute()
    
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    
    os.symlink(src, dest)
    dest.chmod(0o755)
    
    print(f"🛡️ Truss CLI installed to {dest}")
    print(f"🛡️ Make sure {bin_dir} is in your PATH.")
    print(f"   Run: export PATH=\"$PATH:{bin_dir}\"")

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
    ensure_bootstrap(["duckdb"])
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
    ensure_bootstrap(["duckdb"])
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

# --- Pipe Commands ---

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
    cmd = [sys.executable, str(script_path), args.verb]
    if hasattr(args, 'on') and args.on: cmd.extend(["--on", args.on])
    if hasattr(args, 'action') and args.action: cmd.extend(["--action", args.action])
    if hasattr(args, 'limit') and args.limit: cmd.extend(["--limit", str(args.limit)])
    if hasattr(args, 'threshold') and args.threshold: cmd.extend(["--threshold", str(args.threshold)])
    
    # Propagate the project target environment cleanly
    env = os.environ.copy()
    if hasattr(args, 'project') and args.project:
        env["TRUSS_PROJECT"] = args.project
        
    res = subprocess.run(cmd, env=env)
    sys.exit(res.returncode)

# --- The Proxy Commands ---

def is_port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def cmd_kill(args):
    """
    Stop any Truss Audit Proxy bound to the port.
    """
    port = args.port or DEFAULT_PROXY_PORT
    if not is_port_open(port):
        print(f"🛡️ No Truss Audit Proxy running on port {port}.")
        return
    try:
        out = subprocess.check_output(["lsof", "-ti", f":{port}"], text=True).strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"Error: could not locate process on port {port}: {e}", file=sys.stderr)
        sys.exit(1)
    pids = [int(p) for p in out.splitlines() if p.strip()]
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"🛡️ Sent SIGTERM to pid {pid}")
        except ProcessLookupError:
            pass
    # Give it a moment to exit cleanly, then SIGKILL stragglers
    for _ in range(15):
        if not is_port_open(port):
            break
        time.sleep(0.1)
    if is_port_open(port):
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
                print(f"🛡️ Force-killed pid {pid}")
            except ProcessLookupError:
                pass
        time.sleep(0.2)
    if is_port_open(port):
        print(f"Warning: port {port} still bound after kill attempt", file=sys.stderr)
        sys.exit(1)
    print(f"🛡️ Truss Audit Proxy stopped (port {port}).")

def cmd_proxy_status(args):
    port = args.port or DEFAULT_PROXY_PORT
    is_active = is_port_open(port)
    print(f"🛡️ Truss Audit Proxy Status (Port {port})")
    print("------------------------------------------------")
    print(f"Status:      {'🟢 ACTIVE' if is_active else '🔴 INACTIVE'}")
    
    pids = []
    if is_active:
        try:
            out = subprocess.check_output(["lsof", "-ti", f":{port}"], text=True).strip()
            pids = [int(p) for p in out.splitlines() if p.strip()]
        except Exception:
            pass
    
    if pids:
        print(f"PID(s):      {', '.join(str(p) for p in pids)}")
    
    print(f"Log path:    {PROXY_LOG}")
    print(f"Ledger path: {LEDGER_DIR}")
    
    if PROXY_LOG.exists():
        print("\n--- Last 10 Proxy Logs ---")
        try:
            with open(PROXY_LOG, "r") as lf:
                lines = lf.readlines()
                for line in lines[-10:]:
                    print(line, end="")
        except Exception as e:
            print(f"Could not read logs: {e}")

def cmd_exec(args):
    try:
        import uvicorn
        import google.genai  # noqa: F401
    except ImportError:
        print("🛡️ Truss: Missing proxy components. Bootstrapping...")
        subprocess.check_call([str(VENV_PYTHON), "-m", "pip", "install", "uvicorn", "fastapi", "httpx", "pyyaml", "pydantic", "google-genai"])

    # Parse manual options
    policy = None
    port = DEFAULT_PROXY_PORT
    command = []

    if hasattr(args, 'command_to_run'):
        policy = args.policy
        port = args.port or DEFAULT_PROXY_PORT
        command = args.command_to_run
    else:
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
                command = args[i:]
                break
    
    if not command:
        print("Error: No command provided to exec.")
        sys.exit(1)

    proxy_proc = None
    if not is_port_open(port):
        print(f"🛡️ Starting Truss Audit Proxy on port {port}...")
        proxy_env = os.environ.copy()
        if policy:
            proxy_env["TRUSS_POLICY_PATH"] = str(Path(policy).absolute())
        
        script_dir = Path(__file__).resolve().parent
        
        found_root = None
        if (script_dir / "primitives" / "audit").exists():
            found_root = script_dir
        elif (script_dir.parent / "primitives" / "audit").exists():
            found_root = script_dir.parent
        elif (script_dir.parent.parent / "primitives" / "audit").exists():
            found_root = script_dir.parent.parent
        
        if found_root:
            proxy_env["PYTHONPATH"] = f"{found_root}:{proxy_env.get('PYTHONPATH', '')}"
        else:
            proxy_env["PYTHONPATH"] = f"{script_dir}:{script_dir.parent}:{proxy_env.get('PYTHONPATH', '')}"

        if found_root:
            default_policies = found_root / "examples" / "policies"
            default_taxonomy = found_root / "primitives" / "audit" / "taxonomies" / "phi.yaml"
            if policy:
                proxy_env["TRUSS_POLICIES_DIR"] = str(Path(policy).expanduser().absolute())
            else:
                proxy_env.setdefault("TRUSS_POLICIES_DIR", str(default_policies))
            proxy_env.setdefault("TRUSS_TAXONOMIES", str(default_taxonomy))
        proxy_env.setdefault("TRUSS_RECEIPTS_DIR", str(DEFAULT_RECEIPTS_DIR))

        TRUSS_DIR.mkdir(parents=True, exist_ok=True)
        log_file = open(PROXY_LOG, "a", buffering=1)
        log_file.write(f"\n--- Truss Proxy Start v{VERSION} ---\n")
        log_file.write(f"CWD: {os.getcwd()}\n")
        log_file.write(f"PYTHONPATH: {proxy_env.get('PYTHONPATH')}\n")
        log_file.write(f"SCRIPT_DIR: {script_dir}\n")
        
        proxy_proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "primitives.audit.proxy:create_app_from_env", "--port", str(port), "--factory"],
            env=proxy_env,
            stdout=log_file,
            stderr=log_file
        )
        
        retries = 30
        while not is_port_open(port) and retries > 0:
            time.sleep(0.2)
            retries -= 1
        
        if retries == 0:
            print(f"Error: Truss Audit Proxy failed to start. Check {PROXY_LOG}", file=sys.stderr)
            if proxy_proc: proxy_proc.terminate()
            sys.exit(1)
        print("🛡️ Truss Audit Proxy ready.")
    else:
        print(f"🛡️ Using existing Truss Audit Proxy on port {port}.")

    env = os.environ.copy()
    proxy_url = f"http://localhost:{port}"

    env["GOOGLE_GEMINI_BASE_URL"] = proxy_url
    env["ANTHROPIC_BASE_URL"] = proxy_url
    
    local_bin = str(Path("~/.local/bin").expanduser())
    truss_bin = str(TRUSS_DIR / "bin")
    current_path = env.get("PATH", "")
    new_path = f"{local_bin}:{truss_bin}:{current_path}"
    env["PATH"] = new_path
    
    executable = shutil.which(command[0], path=new_path)
    
    print(f"🛡️ Truss Governance Active (Policy: {policy or 'default'})")
    
    try:
        if executable:
            command[0] = executable
            print(f"🛡️ Executing binary: {' '.join(command)}")
            result = subprocess.run(command, env=env)
        else:
            shell_cmd = f"export GOOGLE_GEMINI_BASE_URL={proxy_url} ANTHROPIC_BASE_URL={proxy_url}; "
            shell_cmd += " ".join(shlex.quote(c) for c in command)

            print(f"🛡️ Executing shell command: {shell_cmd}")
            result = subprocess.run(["zsh", "-i", "-l", "-c", shell_cmd], env=env)
            
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

# --- Alias redirection ---

def handle_legacy_aliases():
    """
    Transparently maps legacy top-level verbs to the new noun-first structure.
    Rewrites sys.argv in place and prints a deprecation warning to stderr.
    """
    alias_map = {
        "index": ["receipt", "list"],
        "verify": ["receipt", "verify"],
        "query": ["receipt", "query"],
        "report": ["receipt", "report"],
        "translate": ["trace", "translate"],
        "analyze": ["trace", "analyze"],
        "kill": ["proxy", "stop"],
    }
    
    if len(sys.argv) > 1:
        verb = sys.argv[1]
        
        if verb == "exec":
            print("⚠️  Deprecation Warning: 'truss exec' is deprecated. Use 'truss proxy exec' instead.", file=sys.stderr)
            sys.argv[1:2] = ["proxy", "exec"]
            return
            
        if verb == "trap" and len(sys.argv) > 2:
            # Trap remains, but let's map subcommands if legacy format was used
            return
            
        if verb in alias_map:
            target = alias_map[verb]
            print(f"⚠️  Deprecation Warning: 'truss {verb}' is deprecated. Use 'truss {' '.join(target)}' instead.", file=sys.stderr)
            sys.argv[1:2] = target

def main():
    bootstrap_ledger()
    handle_legacy_aliases()

    # If first arg is 'proxy exec', bootstrap and re-exec
    if len(sys.argv) > 2 and sys.argv[1] == "proxy" and sys.argv[2] == "exec":
        ensure_bootstrap()
        cmd_exec(sys.argv[3:])
        return

    # Special short circuit for install / proxy stop to avoid heavy startup
    if len(sys.argv) > 1 and sys.argv[1] == "install":
        cmd_install(None)
        return
    if len(sys.argv) > 2 and sys.argv[1] == "proxy" and sys.argv[2] == "stop":
        class DummyArgs: port = DEFAULT_PROXY_PORT
        cmd_kill(DummyArgs())
        return

    # Help output on bare execution
    if len(sys.argv) == 1:
        print(f"🛡️ Truss Audit Substrate (v{VERSION})")
        print("--------------------------------")
        parser = argparse.ArgumentParser(prog="truss")
        parser.add_argument("--version", action="version", version=f"truss {VERSION}")
        subparsers = parser.add_subparsers(dest="noun", required=True)
        subparsers.add_parser("install", help="Install truss CLI and bootstrap ledger")
        subparsers.add_parser("receipt", help="Query and verify receipts")
        subparsers.add_parser("trace", help="Parse and analyze session traces")
        subparsers.add_parser("trap", help="Manage security traps")
        subparsers.add_parser("proxy", help="Manage proxy daemon")
        parser.print_help()
        return

    parser = argparse.ArgumentParser(prog="truss", description="🛡️ Truss Audit Substrate")
    parser.add_argument("--version", action="version", version=f"truss {VERSION}")
    subparsers = parser.add_subparsers(dest="noun", required=True)

    # --- 1. Global / Bootstrapping Nouns/Verbs ---
    p_install = subparsers.add_parser("install", help="Install truss CLI and bootstrap ledger")

    # --- 2. Receipt Subparser ---
    p_receipt = subparsers.add_parser("receipt", help="Manage and query local audit receipts")
    receipt_sub = p_receipt.add_subparsers(dest="verb", required=True)

    p_receipt_list = receipt_sub.add_parser("list", help="Scan and index local receipts")
    p_receipt_list.add_argument("path", type=str, default=str(DEFAULT_RECEIPTS_DIR), nargs="?")

    p_receipt_verify = receipt_sub.add_parser("verify", help="Validate cryptographic integrity of receipts")
    p_receipt_verify.add_argument("path", type=str, default=str(DEFAULT_RECEIPTS_DIR), nargs="?")
    p_receipt_verify.add_argument("--allow-empty", action="store_true", help="Allow successful verification of empty directories")

    p_receipt_query = receipt_sub.add_parser("query", help="Query local receipts using SQL (DuckDB)")
    p_receipt_query.add_argument("sql", help="SQL query to execute (refers to 'receipts' table)")
    p_receipt_query.add_argument("--path", type=str, default=str(DEFAULT_RECEIPTS_DIR), help="Path to receipts folder")

    p_receipt_report = receipt_sub.add_parser("report", help="Generate automated activity report")
    p_receipt_report.add_argument("--path", type=str, default=str(DEFAULT_RECEIPTS_DIR), help="Path to receipts folder")

    # --- 3. Trace Subparser ---
    p_trace = subparsers.add_parser("trace", help="Parse and analyze session traces")
    trace_sub = p_trace.add_subparsers(dest="verb", required=True)

    p_trace_translate = trace_sub.add_parser("translate", help="Translate raw session hooks.jsonl into TWP nodes")
    p_trace_translate.add_argument("input", nargs="?", default="-", help="Input file (default: stdin)")
    p_trace_translate.add_argument("output", nargs="?", default="-", help="Output file (default: stdout)")

    p_trace_analyze = trace_sub.add_parser("analyze", help="Analyze translated trace nodes for retry loops and patterns")
    p_trace_analyze.add_argument("trace", nargs="?", default="-", help="Input trace file (default: stdin)")
    p_trace_analyze.add_argument("--type", help="Filter by node type")
    p_trace_analyze.add_argument("--flag", help="Filter by specific audit flag")
    p_trace_analyze.add_argument("--id", help="Filter by specific node ID")
    p_trace_analyze.add_argument("--json", action="store_true", help="Emit JSON instead of pretty output")

    # --- 4. Trap Subparser ---
    p_trap = subparsers.add_parser("trap", help="Manage security, alignment, and audit traps")
    trap_sub = p_trap.add_subparsers(dest="verb", required=True)

    p_trap_add = trap_sub.add_parser("add", help="Add a new audit trap")
    p_trap_add.add_argument("--on", required=True, choices=["ON_ERROR", "ON_RETRY", "ON_CONFIDENCE_LOW", "ON_STATE_DRIFT"], help="Trigger condition")
    p_trap_add.add_argument("--action", required=True, choices=["ACTION_HALT", "ACTION_SOCRATIC", "ACTION_BRANCH"], help="Safety action to fire")
    p_trap_add.add_argument("--limit", type=int, help="Limit constraint for the trap")
    p_trap_add.add_argument("--threshold", type=float, help="Numeric threshold for condition")
    p_trap_add.add_argument("--project", help="Override project target (default: TRUSS_PROJECT environment var)")

    p_trap_list = trap_sub.add_parser("list", help="List active traps")
    p_trap_list.add_argument("--project", help="Override project target")

    p_trap_clear = trap_sub.add_parser("clear", help="Clear all traps")
    p_trap_clear.add_argument("--project", help="Override project target")

    p_trap_run = trap_sub.add_parser("run", help="Run the trap engine on translated trace nodes from stdin")
    p_trap_run.add_argument("--project", help="Override project target")

    # --- 5. Proxy Subparser ---
    p_proxy = subparsers.add_parser("proxy", help="Manage the local Truss Audit Proxy daemon")
    proxy_sub = p_proxy.add_subparsers(dest="verb", required=True)

    p_proxy_exec = proxy_sub.add_parser("exec", help="Execute a command under local Truss governance")
    p_proxy_exec.add_argument("--policy", help="Path to policy YAML file/directory")
    p_proxy_exec.add_argument("--port", type=int, default=DEFAULT_PROXY_PORT, help="Proxy port to bind/connect")
    p_proxy_exec.add_argument("command_to_run", nargs=argparse.REMAINDER, help="The command and its arguments to run")

    p_proxy_stop = proxy_sub.add_parser("stop", help="Stop any active Truss Audit Proxy daemon")
    p_proxy_stop.add_argument("--port", type=int, default=DEFAULT_PROXY_PORT, help="Target proxy port to stop")

    p_proxy_status = proxy_sub.add_parser("status", help="Display current status and logs of the local proxy daemon")
    p_proxy_status.add_argument("--port", type=int, default=DEFAULT_PROXY_PORT, help="Proxy port to probe")

    args = parser.parse_args()

    ensure_bootstrap()

    if args.noun == "install": cmd_install(args)
    elif args.noun == "receipt":
        if args.verb == "list": cmd_index(args)
        elif args.verb == "verify": cmd_verify(args)
        elif args.verb == "query": cmd_query(args)
        elif args.verb == "report": cmd_report(args)
    elif args.noun == "trace":
        if args.verb == "translate": cmd_translate(args)
        elif args.verb == "analyze": cmd_analyze(args)
    elif args.noun == "trap":
        cmd_trap(args)
    elif args.noun == "proxy":
        if args.verb == "exec": cmd_exec(args)
        elif args.verb == "stop": cmd_kill(args)
        elif args.noun == "proxy" and args.verb == "status": cmd_proxy_status(args)

if __name__ == "__main__":
    here = Path(__file__).resolve()
    repo_root = here.parent.parent.parent
    sys.path.append(str(repo_root))
    sys.path.append(str(here.parent))
    
    main()