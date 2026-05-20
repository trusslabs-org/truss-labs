"""Truss MCP Resource Server — TWP v1.2 MVP prototype.

Spec: docs/research/TWP_ON_MCP_SPEC.md
Exposes the Truss Registry over the Model Context Protocol (stdio transport).
"""
import json
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Truss Labs Registry")

REGISTRY_ROOT = Path(os.environ.get("TRUSS_REGISTRY", os.path.expanduser("~/.truss/ledger")))
DEFAULT_PROJECT = "truss-labs"


def _project() -> str:
    return os.environ.get("TRUSS_PROJECT", DEFAULT_PROJECT)


def _log(msg: str) -> None:
    print(f"[truss-mcp] {msg}", file=sys.stderr, flush=True)


@mcp.resource("truss://registry/active")
def registry_active() -> str:
    """Snapshot of the active project's Truss Registry tasks."""
    project = _project()
    task_dir = REGISTRY_ROOT / "tasks" / project
    if not task_dir.exists():
        return json.dumps({"project": project, "tasks": [], "error": "task_dir_missing"})

    tasks = []
    for task_file in sorted(task_dir.glob("*.json")):
        try:
            with open(task_file) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            _log(f"skip malformed task {task_file.name}: {e}")
            continue
        tasks.append(data)
    return json.dumps({"project": project, "tasks": tasks}, indent=2)


@mcp.resource("truss://trace/dag")
def trace_dag_sessions() -> str:
    """Index of available trace sessions for the active project."""
    project = _project()
    trace_dir = REGISTRY_ROOT / "traces" / project
    if not trace_dir.exists():
        return json.dumps({"project": project, "sessions": []})

    sessions = []
    for host_dir in sorted(trace_dir.iterdir()):
        if not host_dir.is_dir():
            continue
        for session_dir in sorted(host_dir.iterdir()):
            if session_dir.is_dir():
                sessions.append({
                    "session_id": session_dir.name,
                    "host": host_dir.name,
                })
    return json.dumps({"project": project, "sessions": sessions}, indent=2)


@mcp.resource("truss://trace/dag/{session_id}")
def trace_dag_session(session_id: str) -> str:
    """Nodes and causal edges for a specific trace session."""
    project = _project()
    trace_dir = REGISTRY_ROOT / "traces" / project
    if not trace_dir.exists():
        return json.dumps({"session_id": session_id, "nodes": [], "edges": [], "error": "no_traces"})

    session_dir = None
    for host_dir in trace_dir.iterdir():
        candidate = host_dir / session_id
        if candidate.is_dir():
            session_dir = candidate
            break
    if session_dir is None:
        return json.dumps({"session_id": session_id, "nodes": [], "edges": [], "error": "session_not_found"})

    nodes = []
    for jsonl in sorted(session_dir.glob("*.jsonl")):
        try:
            with open(jsonl) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        node = json.loads(line)
                        if "provenance" not in node:
                            node["provenance"] = "PROV_NATURAL"
                        nodes.append(node)
                    except json.JSONDecodeError as e:
                        _log(f"skip malformed line in {jsonl.name}: {e}")
        except OSError as e:
            _log(f"cannot read {jsonl}: {e}")

    edges = []
    for n in nodes:
        parent = n.get("parent_id")
        node_id = n.get("node_id")
        if parent and node_id:
            edge_type = "CAUSAL_LINK"
            if n.get("provenance") == "PROV_INJECTED":
                edge_type = "INJECTION_LINK"
            elif n.get("provenance") == "PROV_SPECULATIVE":
                edge_type = "SPECULATIVE_BRANCH"
                
            edges.append({"from": parent, "to": node_id, "type": edge_type})
            
    return json.dumps({"session_id": session_id, "nodes": nodes, "edges": edges}, indent=2)


@mcp.tool()
def query_registry(query: str, project_key: str | None = None) -> str:
    """Substring-search task JSON in the registry."""
    pk = project_key or _project()
    task_dir = REGISTRY_ROOT / "tasks" / pk
    if not task_dir.exists():
        return json.dumps({"query": query, "results": [], "error": "task_dir_missing"})

    q = query.lower()
    results = []
    for task_file in task_dir.glob("*.json"):
        try:
            content = task_file.read_text()
        except OSError as e:
            _log(f"cannot read {task_file}: {e}")
            continue
        if q in content.lower():
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                data = {}
            results.append(data)
    return json.dumps({"query": query, "results": results}, indent=2)


_DEFERRED_NOTE = (
    "Truss platform integration (truss-lock, Socratic Block, COW registry) not yet "
    "implemented. This is a spec-aligned stub."
)


@mcp.tool()
def truss_pause(reason: str) -> str:
    """Yield control to the GUI, entering a Socratic Block. (Stub)"""
    return json.dumps({
        "status": "deferred",
        "tool": "truss_pause",
        "reason": reason,
        "note": _DEFERRED_NOTE,
    })


@mcp.tool()
def truss_inject_state(patch: list[dict]) -> str:
    """Modify short-term memory of the active project via JSONPatch. (Stub)"""
    return json.dumps({
        "status": "deferred",
        "tool": "truss_inject_state",
        "patch": patch,
        "note": _DEFERRED_NOTE,
    })


@mcp.tool()
def truss_spawn_branch(source_node_id: str, branch_intent: str) -> str:
    """COW-fork the registry from a source node. (Stub)"""
    return json.dumps({
        "status": "deferred",
        "tool": "truss_spawn_branch",
        "source_node_id": source_node_id,
        "branch_intent": branch_intent,
        "note": _DEFERRED_NOTE,
    })


def main() -> None:
    _log(f"starting Truss MCP Server; REGISTRY_ROOT={REGISTRY_ROOT}, TRUSS_PROJECT={_project()}")
    mcp.run()


if __name__ == "__main__":
    main()