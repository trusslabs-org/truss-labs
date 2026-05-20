"""TWP v1.2 cross-check smoke test.

Tests the five v1.2-specific gaps NOT covered by smoke_test.py:
  1. Provenance defaulting — nodes without a provenance field get PROV_NATURAL.
  2. Edge type classification — CAUSAL_LINK / INJECTION_LINK / SPECULATIVE_BRANCH.
  3. Deferred-stub contract — truss_pause / truss_inject_state / truss_spawn_branch.
  4. query_registry substring search — returns a matching task.
  5. Session-not-found error path — bogus session_id → well-formed JSON error.

Spawns truss_server.py with a temporary registry so the real registry is
untouched. Exits 0 only if all five checks pass.
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_PATH = Path(__file__).parent / "truss_server.py"
PROJECT = "test-project"
HOST = "testhost"
SESSION_ID = "2026-01-01T000000_aabbccdd"

# ---------------------------------------------------------------------------
# Fixture JSONL — four nodes covering all provenance variants + a missing field
# ---------------------------------------------------------------------------
TRACE_LINES = [
    # n0: root node, no parent, has explicit PROV_NATURAL
    json.dumps({"node_id": "n0", "text": "root", "provenance": "PROV_NATURAL"}),
    # n1: child of n0, PROV_NATURAL (explicit) → expect CAUSAL_LINK
    json.dumps({"node_id": "n1", "parent_id": "n0", "text": "natural child", "provenance": "PROV_NATURAL"}),
    # n2: child of n1, PROV_INJECTED → expect INJECTION_LINK
    json.dumps({"node_id": "n2", "parent_id": "n1", "text": "injected child", "provenance": "PROV_INJECTED"}),
    # n3: child of n2, PROV_SPECULATIVE → expect SPECULATIVE_BRANCH
    json.dumps({"node_id": "n3", "parent_id": "n2", "text": "speculative child", "provenance": "PROV_SPECULATIVE"}),
    # n4: child of n3, NO provenance field → should default to PROV_NATURAL → CAUSAL_LINK
    json.dumps({"node_id": "n4", "parent_id": "n3", "text": "no-prov child"}),
]

TASK_FIXTURE = {
    "id": "101",
    "title": "Design causal graph indexer",
    "status": "in_progress",
    "description": "Build a searchable index of causal_graph nodes for fast lookup.",
}


def build_registry(tmpdir: Path) -> None:
    """Populate a minimal registry under tmpdir."""
    # Task file
    task_dir = tmpdir / "tasks" / PROJECT
    task_dir.mkdir(parents=True)
    (task_dir / "101.json").write_text(json.dumps(TASK_FIXTURE, indent=2))

    # Trace JSONL
    session_dir = tmpdir / "traces" / PROJECT / HOST / SESSION_ID
    session_dir.mkdir(parents=True)
    (session_dir / "trace.jsonl").write_text("\n".join(TRACE_LINES) + "\n")


def result_line(check: str, passed: bool, detail: str = "") -> str:
    status = "PASS" if passed else "FAIL"
    return f"  [{status}] {check}" + (f" — {detail}" if detail else "")


async def run(tmpdir: Path) -> int:
    env = {
        **os.environ,
        "TRUSS_REGISTRY": str(tmpdir),
        "TRUSS_PROJECT": PROJECT,
    }
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER_PATH)],
        env=env,
    )

    results: list[tuple[str, bool, str]] = []

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # ------------------------------------------------------------------
            # Read the trace DAG once; used by checks 1 and 2.
            # ------------------------------------------------------------------
            dag_resp = await session.read_resource(f"truss://trace/dag/{SESSION_ID}")
            dag = json.loads(dag_resp.contents[0].text)
            nodes_by_id = {n["node_id"]: n for n in dag.get("nodes", [])}
            edges_by_to = {e["to"]: e for e in dag.get("edges", [])}

            # ------------------------------------------------------------------
            # Check 1: Provenance defaulting
            # ------------------------------------------------------------------
            n4 = nodes_by_id.get("n4", {})
            prov = n4.get("provenance")
            ok1 = prov == "PROV_NATURAL"
            results.append(("1. Provenance default (n4 missing → PROV_NATURAL)", ok1,
                            f"got provenance={prov!r}"))

            # ------------------------------------------------------------------
            # Check 2a: CAUSAL_LINK for PROV_NATURAL parent→child (n1)
            # ------------------------------------------------------------------
            e1 = edges_by_to.get("n1", {})
            ok2a = e1.get("type") == "CAUSAL_LINK"
            results.append(("2a. Edge n0→n1 (PROV_NATURAL) → CAUSAL_LINK", ok2a,
                            f"got type={e1.get('type')!r}"))

            # ------------------------------------------------------------------
            # Check 2b: INJECTION_LINK for PROV_INJECTED (n2)
            # ------------------------------------------------------------------
            e2 = edges_by_to.get("n2", {})
            ok2b = e2.get("type") == "INJECTION_LINK"
            results.append(("2b. Edge n1→n2 (PROV_INJECTED) → INJECTION_LINK", ok2b,
                            f"got type={e2.get('type')!r}"))

            # ------------------------------------------------------------------
            # Check 2c: SPECULATIVE_BRANCH for PROV_SPECULATIVE (n3)
            # ------------------------------------------------------------------
            e3 = edges_by_to.get("n3", {})
            ok2c = e3.get("type") == "SPECULATIVE_BRANCH"
            results.append(("2c. Edge n2→n3 (PROV_SPECULATIVE) → SPECULATIVE_BRANCH", ok2c,
                            f"got type={e3.get('type')!r}"))

            # ------------------------------------------------------------------
            # Check 2d: PROV_NATURAL default also produces CAUSAL_LINK (n4)
            # ------------------------------------------------------------------
            e4 = edges_by_to.get("n4", {})
            ok2d = e4.get("type") == "CAUSAL_LINK"
            results.append(("2d. Edge n3→n4 (no prov→default) → CAUSAL_LINK", ok2d,
                            f"got type={e4.get('type')!r}"))

            # ------------------------------------------------------------------
            # Check 3a: truss_pause deferred-stub contract
            # ------------------------------------------------------------------
            pause_resp = await session.call_tool("truss_pause", {"reason": "smoke test pause"})
            pause_body = json.loads(pause_resp.content[0].text)
            ok3a = (
                pause_body.get("status") == "deferred"
                and pause_body.get("tool") == "truss_pause"
                and pause_body.get("reason") == "smoke test pause"
            )
            results.append(("3a. truss_pause deferred-stub contract", ok3a,
                            f"got {pause_body}"))

            # ------------------------------------------------------------------
            # Check 3b: truss_inject_state deferred-stub contract
            # ------------------------------------------------------------------
            patch_val = [{"op": "replace", "path": "/status", "value": "done"}]
            inject_resp = await session.call_tool("truss_inject_state", {"patch": patch_val})
            inject_body = json.loads(inject_resp.content[0].text)
            ok3b = (
                inject_body.get("status") == "deferred"
                and inject_body.get("tool") == "truss_inject_state"
                and inject_body.get("patch") == patch_val
            )
            results.append(("3b. truss_inject_state deferred-stub contract", ok3b,
                            f"got {inject_body}"))

            # ------------------------------------------------------------------
            # Check 3c: truss_spawn_branch deferred-stub contract
            # ------------------------------------------------------------------
            spawn_resp = await session.call_tool("truss_spawn_branch", {
                "source_node_id": "n1",
                "branch_intent": "test branch",
            })
            spawn_body = json.loads(spawn_resp.content[0].text)
            ok3c = (
                spawn_body.get("status") == "deferred"
                and spawn_body.get("tool") == "truss_spawn_branch"
                and spawn_body.get("source_node_id") == "n1"
                and spawn_body.get("branch_intent") == "test branch"
            )
            results.append(("3c. truss_spawn_branch deferred-stub contract", ok3c,
                            f"got {spawn_body}"))

            # ------------------------------------------------------------------
            # Check 4: query_registry substring search
            # ------------------------------------------------------------------
            qr_resp = await session.call_tool("query_registry", {"query": "causal_graph"})
            qr_body = json.loads(qr_resp.content[0].text)
            matched = qr_body.get("results", [])
            ok4 = len(matched) >= 1 and any(r.get("id") == "101" for r in matched)
            results.append(("4. query_registry substring search returns task 101", ok4,
                            f"got {len(matched)} result(s)"))

            # ------------------------------------------------------------------
            # Check 5: Session-not-found error path
            # ------------------------------------------------------------------
            bogus_resp = await session.read_resource("truss://trace/dag/does_not_exist_xyz")
            bogus_body = json.loads(bogus_resp.contents[0].text)
            ok5 = (
                isinstance(bogus_body, dict)
                and bogus_body.get("error") == "session_not_found"
            )
            results.append(("5. Session-not-found returns well-formed error JSON", ok5,
                            f"got {bogus_body}"))

    # --------------------------------------------------------------------------
    # Print results
    # --------------------------------------------------------------------------
    print("\nTWP v1.2 smoke test results:")
    all_pass = True
    for name, passed, detail in results:
        print(result_line(name, passed, detail))
        if not passed:
            all_pass = False

    print()
    if all_pass:
        print("ALL CHECKS PASSED")
        return 0
    else:
        failed = sum(1 for _, p, _ in results if not p)
        print(f"{failed}/{len(results)} CHECKS FAILED")
        return 1


def main() -> None:
    tmpdir = Path(tempfile.mkdtemp(prefix="truss_v12_smoke_"))
    try:
        build_registry(tmpdir)
        code = asyncio.run(run(tmpdir))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    sys.exit(code)


if __name__ == "__main__":
    main()