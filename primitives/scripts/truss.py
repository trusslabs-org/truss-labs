#!/usr/bin/env python3
"""
truss — The high-level CLI for the Truss Audit substrate.
"""

import hashlib
import argparse
import json
import signal
import sys
from pathlib import Path

try:
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except (AttributeError, ValueError):
    pass

try:
    import duckdb
except ImportError:
    duckdb = None

DEFAULT_RECEIPTS_DIR = Path("~/.truss/receipts").expanduser()

def _sha256_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()

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
    if not duckdb:
        print("Error: duckdb is required for query. Install with: pip install duckdb", file=sys.stderr)
        sys.exit(1)
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
    if not duckdb:
        print("Error: duckdb is required for report. Install with: pip install duckdb", file=sys.stderr)
        sys.exit(1)
    path = Path(args.path).expanduser()
    json_pattern = str(path / "**" / "*.json")
    print(f"--- Truss Audit Weekly Activity Report ---")
    try:
        # 1. Volume
        print("\n[ Volume by Day ]")
        print(duckdb.query(f"SELECT timestamp[1:10] as day, count(*) FROM read_json_auto('{json_pattern}') GROUP BY 1 ORDER BY 1 DESC").df().to_string(index=False))
        
        # 2. Data Classes - use the struct field directly
        print("\n[ Sensitive Data Classes Touched ]")
        print(duckdb.query(f"SELECT d.class, count(*) FROM (SELECT UNNEST(data_classes_touched) as d FROM read_json_auto('{json_pattern}')) GROUP BY 1 ORDER BY 2 DESC").df().to_string(index=False))

        # 3. Policy Verdicts
        print("\n[ Policy Enforcement Summary ]")
        print(duckdb.query(f"SELECT p.verdict, count(*) FROM (SELECT UNNEST(policy_decisions) as p FROM read_json_auto('{json_pattern}')) GROUP BY 1 ORDER BY 2 DESC").df().to_string(index=False))
    except Exception as e:
        print(f"Report Error: {e}")

def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    p_index = subparsers.add_parser("index")
    p_index.add_argument("path", type=str, default=str(DEFAULT_RECEIPTS_DIR), nargs="?")
    p_verify = subparsers.add_parser("verify")
    p_verify.add_argument("path", type=str, default=str(DEFAULT_RECEIPTS_DIR), nargs="?")
    p_verify.add_argument("--allow-empty", action="store_true")
    p_query = subparsers.add_parser("query")
    p_query.add_argument("sql")
    p_query.add_argument("--path", type=str, default=str(DEFAULT_RECEIPTS_DIR))
    p_report = subparsers.add_parser("report")
    p_report.add_argument("--path", type=str, default=str(DEFAULT_RECEIPTS_DIR))
    args = parser.parse_args()
    if args.command == "index": cmd_index(args)
    elif args.command == "verify": cmd_verify(args)
    elif args.command == "query": cmd_query(args)
    elif args.command == "report": cmd_report(args)

if __name__ == "__main__": main()
