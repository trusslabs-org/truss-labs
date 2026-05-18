# Truss Primitives

This package contains the core CLI tools for the Truss Audit substrate.

## Usage

1. Add the current directory to your PATH or run directly:
   ./truss --help

2. Run the sample pipe:
   cat hooks.jsonl | ./truss translate | ./truss analyze --json --flag FLAG_CIRCULAR_REASONING | ./truss trap run

## Tools
- truss: The main entry point
- truss_translate.py: hooks.jsonl -> TWP nodes
- truss_analyze.py: Flag detection
- truss_trap.py: Runtime intervention

License: Apache 2.0
