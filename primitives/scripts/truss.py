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
import shlex
import shutil
from pathlib import Path

VERSION = "0.3.0"

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
    # Always ensure directories exist 
    bootstrap_ledger()
    
    packages = packages or []
    
    # 1. Check if we are already running inside our private venv
    if str(sys.executable) == str(VENV_PYTHON):
        # We are inside. Check if specific packages are missing and install if so.
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
        # Update pip immediately
        subprocess.check_call([str(VENV_PYTHON), "-m", "pip", "install", "--upgrade", "pip", "setuptools"])

    # 3. Always ensure basic dependencies are in the venv before we re-exec
    base_deps = ["fastapi", "uvicorn", "httpx", "pyyaml", "pydantic"]
    
    # Re-exec into the venv
    print(f"🛡️ Truss: Entering isolated environment...")
    
    # We pass the current script path and all arguments
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
    # 1. Double check uvicorn is actually there
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

    # If args is a Namespace (from argparse), handle it, else it's a list from manual main()
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
        
        # MANDATORY: Add primitives dir to PYTHONPATH so uvicorn can find the factory
        # Resolve symlinks so an install at ~/.local/bin/truss finds the real source tree
        script_dir = Path(__file__).resolve().parent
        
        # Search for the folder that SHOULD contain 'primitives' folder
        # Case A: Source checkout - repo_root/primitives/scripts/truss.py
        # Case B: Installed - ~/.truss/primitives/truss and ~/.truss/primitives/primitives/
        
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
            # Last ditch effort
            proxy_env["PYTHONPATH"] = f"{script_dir}:{script_dir.parent}:{proxy_env.get('PYTHONPATH', '')}"

        # Wire proxy env vars (mirrors examples/run_demo.sh). Defaults point at the
        # in-repo example policies + shipped phi taxonomy so `truss exec` works out of the box.
        if found_root:
            default_policies = found_root / "examples" / "policies"
            default_taxonomy = found_root / "primitives" / "audit" / "taxonomies" / "phi.yaml"
            if policy:
                proxy_env["TRUSS_POLICIES_DIR"] = str(Path(policy).expanduser().absolute())
            else:
                proxy_env.setdefault("TRUSS_POLICIES_DIR", str(default_policies))
            proxy_env.setdefault("TRUSS_TAXONOMIES", str(default_taxonomy))
        proxy_env.setdefault("TRUSS_RECEIPTS_DIR", str(DEFAULT_RECEIPTS_DIR))
        # Truss never holds upstream LLM creds on these surfaces — the client
        # (gemini-cli, claude) forwards its own x-goog-api-key / x-api-key in
        # the request headers, and truss relays them upstream.


        # Ensure log dir exists
        TRUSS_DIR.mkdir(parents=True, exist_ok=True)
        # Start uvicorn in the background, redirecting logs to proxy.log
        log_file = open(PROXY_LOG, "a", buffering=1) # line buffered
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
        
        # Wait for proxy to start
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

    # 2. Prepare Environment
    env = os.environ.copy()
    proxy_url = f"http://localhost:{port}"

    # Reverse-proxy path for clients that honor a base-URL env var.
    # - @google/genai (gemini-cli) honors GOOGLE_GEMINI_BASE_URL
    # - claude (Anthropic CLI) honors ANTHROPIC_BASE_URL
    # We deliberately do NOT set HTTPS_PROXY: gemini-cli routes every fetch
    # through it without honoring NO_PROXY, causing the SDK to try to
    # CONNECT-tunnel through truss to reach truss itself.
    env["GOOGLE_GEMINI_BASE_URL"] = proxy_url
    env["ANTHROPIC_BASE_URL"] = proxy_url
    
    # Inject paths for local agent discovery
    local_bin = str(Path("~/.local/bin").expanduser())
    truss_bin = str(TRUSS_DIR / "bin")
    current_path = env.get("PATH", "")
    new_path = f"{local_bin}:{truss_bin}:{current_path}"
    env["PATH"] = new_path
    
    # Resolve the executable path manually to ensure it's found
    executable = shutil.which(command[0], path=new_path)
    
    print(f"🛡️ Truss Governance Active (Policy: {policy or 'default'})")
    
    # 3. Run the command
    try:
        if executable:
            # Command found as a file - run normally
            command[0] = executable
            print(f"🛡️ Executing binary: {' '.join(command)}")
            result = subprocess.run(command, env=env)
        else:
            # Command not found as file - likely a shell function. 
            # We wrap it in zsh -i -l -c to allow it to be found.
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

def main():
    # MANDATORY: Bootstrap directories before anything else
    bootstrap_ledger()

    # If no arguments, print header and help
    if len(sys.argv) == 1:
        print(f"🛡️ Truss Audit Substrate (v{VERSION})")
        print("--------------------------------")
        parser = argparse.ArgumentParser(prog="truss")
        parser.add_argument("--version", action="version", version=f"truss {VERSION}")
        subparsers = parser.add_subparsers(dest="command", required=True)
        subparsers.add_parser("install", help="Install truss CLI and bootstrap ledger")
        subparsers.add_parser("exec", help="Run a command under Truss governance")
        subparsers.add_parser("index", help="Index receipts")
        subparsers.add_parser("verify", help="Verify receipt hashes")
        subparsers.add_parser("query", help="Query receipts using SQL")
        subparsers.add_parser("report", help="Generate audit report")
        subparsers.add_parser("translate", help="Translate logs to TWP nodes")
        subparsers.add_parser("analyze", help="Analyze trace nodes")
        subparsers.add_parser("trap", help="Manage audit traps")
        parser.print_help()
        return

    # If first arg is 'exec', bootstrap and re-exec
    if len(sys.argv) > 1 and sys.argv[1] == "exec":
        ensure_bootstrap()
        cmd_exec(sys.argv[2:])
        return

    parser = argparse.ArgumentParser(prog="truss")
    parser.add_argument("--version", action="version", version=f"truss {VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_install = subparsers.add_parser("install", help="Install truss CLI to ~/.local/bin and bootstrap ledger")

    p_index = subparsers.add_parser("index", help="Index receipts")
    p_index.add_argument("path", type=str, default=str(DEFAULT_RECEIPTS_DIR), nargs="?")

    p_verify = subparsers.add_parser("verify", help="Verify receipt hashes")
    p_verify.add_argument("path", type=str, default=str(DEFAULT_RECEIPTS_DIR), nargs="?")
    p_verify.add_argument("--allow-empty", action="store_true")

    p_query = subparsers.add_parser("query", help="Query receipts using SQL (DuckDB)")
    p_query.add_argument("sql")
    p_query.add_argument("--path", type=str, default=str(DEFAULT_RECEIPTS_DIR))

    p_report = subparsers.add_parser("report", help="Generate audit report")
    p_report.add_argument("--path", type=str, default=str(DEFAULT_RECEIPTS_DIR))

    p_translate = subparsers.add_parser("translate", help="Translate hooks.jsonl to TWP nodes")
    p_translate.add_argument("input", nargs="?", default="-")
    p_translate.add_argument("output", nargs="?", default="-")

    p_analyze = subparsers.add_parser("analyze", help="Analyze trace nodes for flags")
    p_analyze.add_argument("trace", nargs="?", default="-")
    p_analyze.add_argument("--type")
    p_analyze.add_argument("--flag")
    p_analyze.add_argument("--id")
    p_analyze.add_argument("--json", action="store_true")

    p_trap = subparsers.add_parser("trap", help="Manage and run audit traps")
    p_trap.add_argument("trap_command", choices=["add", "clear", "list", "run"])
    p_trap.add_argument("--on")
    p_trap.add_argument("--action")
    p_trap.add_argument("--project")

    # Documentation only
    p_exec = subparsers.add_parser("exec", help="Run a command under Truss governance")
    p_exec.add_argument("--policy", help="Path to policy YAML file")
    p_exec.add_argument("--port", type=int, help="Proxy port (default 8000)")
    p_exec.add_argument("command_to_run", nargs=argparse.REMAINDER, help="Command to run")

    args = parser.parse_args()

    # Ensure full bootstrap (venv check) for standard commands too
    if args.command != "install":
        ensure_bootstrap()

    if args.command == "install": cmd_install(args)
    elif args.command == "index": cmd_index(args)
    elif args.command == "verify": cmd_verify(args)
    elif args.command == "query": cmd_query(args)
    elif args.command == "report": cmd_report(args)
    elif args.command == "translate": cmd_translate(args)
    elif args.command == "analyze": cmd_analyze(args)
    elif args.command == "trap": cmd_trap(args)
    elif args.command == "exec":
        cmd_exec(args)

if __name__ == "__main__":
    # Ensure local primitives are importable (resolve symlinks for ~/.local/bin/truss)
    here = Path(__file__).resolve()
    repo_root = here.parent.parent.parent
    sys.path.append(str(repo_root))
    sys.path.append(str(here.parent))
    
    main()
