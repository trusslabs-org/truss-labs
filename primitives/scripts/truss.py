#!/usr/bin/env python3
"""
truss — The high-level CLI for the Truss Audit substrate.
"""

import argparse
import sys
import json
import hashlib
import signal
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
        print(f"Error: Receipts directory not found at {path}")
        sys.exit(1)
    receipts = list(path.glob("**/*.json"))
    print(f"Scanned {path}")
    print(f"Found {len(receipts)} receipts.")

def cmd_verify(args):
    path = Path(args.path).expanduser()
    receipts = list(path.glob("**/*.json"))
    print(f"Verifying {len(receipts)} receipts...")
    failures = 0
    for r_path in receipts:
        try:
            with open(r_path, 'r') as f:
                receipt = json.load(f)
            stored_hash = receipt["evidence"]["receipt_hash"]
            receipt["evidence"]["receipt_hash"] = ""
            canonical = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            recomputed = _sha256_hash(canonical)
            if stored_hash != recomputed:
                print(f"FAIL: {r_path.name}")
                failures += 1
        except Exception:
            failures += 1
    if failures == 0: print("PASS: All receipts verified.")
    else: sys.exit(1)

def cmd_query(args):
    if not duckdb: sys.exit(1)
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
    if not duckdb: sys.exit(1)
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
