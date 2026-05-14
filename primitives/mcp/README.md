# Truss MCP Resource Server

MVP prototype of the Truss-on-MCP server. Spec: [`docs/research/TWP_ON_MCP_SPEC.md`](../../docs/research/TWP_ON_MCP_SPEC.md).

## Run

```bash
pip install mcp>=1.2
python primitives/mcp/truss_server.py
```

Env vars:
- `SOUL_REGISTRY` — registry root (default `~/soul_registry`)
- `SOUL_PROJECT` — active project key (default `ilteris-company`)

## Smoke test

```bash
python primitives/mcp/smoke_test.py
```

Exits 0 on success, prints a one-line diagnosis otherwise.

## MCP Inspector

```bash
npx @modelcontextprotocol/inspector python primitives/mcp/truss_server.py
```

## Surface

### MVP (implemented)

| Kind | Name | Notes |
|------|------|-------|
| Resource | `truss://registry/active` | Task snapshot for the active project |
| Resource | `truss://trace/dag` | Index of trace sessions for the active project |
| Resource | `truss://trace/dag/{session_id}` | Nodes + causal edges for one session |
| Tool | `query_registry(query, project_key?)` | Substring-search task JSON |

### Spec-aligned stubs (return `{"status": "deferred"}`)

| Tool | Spec ref |
|------|----------|
| `truss_pause(reason)` | §4.1 |
| `truss_inject_state(variables)` | §4.2 |
| `truss_spawn_branch(source_node_id, branch_intent)` | §4.3 |

### Deferred (not in this prototype)

- Real `truss_pause` / `truss_inject_state` — needs `soul-lock` + Socratic Block state machine.
- Real `truss_spawn_branch` — needs COW branch storage in the registry.
- WebSocket transport (stdio only for now).
- Subscribe/streaming on `truss://registry/active` (snapshot only).
- Branch GC on `soul finalize`.
