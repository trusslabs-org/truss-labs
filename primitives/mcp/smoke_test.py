"""Smoke test for the Truss MCP server.

Spawns truss_server.py over stdio, asserts the expected resources and tools
are exposed, and that truss://registry/active returns parseable JSON.

Exits 0 on success. Prints a single-line diagnosis on failure.
"""
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED_RESOURCES = {"truss://registry/active", "truss://trace/dag"}
EXPECTED_TOOLS = {"query_registry", "truss_pause", "truss_inject_state", "truss_spawn_branch"}


async def run() -> int:
    server_path = Path(__file__).parent / "truss_server.py"
    params = StdioServerParameters(command=sys.executable, args=[str(server_path)])

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            resources = await session.list_resources()
            resource_uris = {str(r.uri) for r in resources.resources}

            tools = await session.list_tools()
            tool_names = {t.name for t in tools.tools}

            missing_resources = EXPECTED_RESOURCES - resource_uris
            if missing_resources:
                print(f"FAIL: missing resources {sorted(missing_resources)}; got {sorted(resource_uris)}")
                return 1

            if tool_names != EXPECTED_TOOLS:
                print(f"FAIL: tools mismatch; got {sorted(tool_names)}, expected {sorted(EXPECTED_TOOLS)}")
                return 1

            active = await session.read_resource("truss://registry/active")
            if not active.contents:
                print("FAIL: truss://registry/active returned no contents")
                return 1
            try:
                parsed = json.loads(active.contents[0].text)
            except (AttributeError, json.JSONDecodeError) as e:
                print(f"FAIL: truss://registry/active not parseable JSON: {e}")
                return 1
            if "tasks" not in parsed:
                print(f"FAIL: truss://registry/active missing 'tasks' key: {parsed}")
                return 1

            print(
                f"OK: resources={sorted(resource_uris)}, "
                f"tools={sorted(tool_names)}, "
                f"tasks={len(parsed['tasks'])}"
            )
            return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
