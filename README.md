# Truss Labs

Truss is an open-source governance and receipt layer for teams using public AI tools and shared agent workspaces. Every prompt or file transfer is checked against local YAML policies (`allow`, `redact`, or `block`), stateful session memory is persisted on disk, and a hash-verifiable JSON receipt is written for audit review.

- **Site & Interactive Slack Leak Demo:** [trusslabs.org](https://trusslabs.org)
- **Blog / Lab Notes:** [trusslabs.org/blog](https://trusslabs.org/blog)
- **Live Audit Proxy Sandbox:** [demo.trusslabs.org](https://demo.trusslabs.org)

## What's in this repo

```
extension/      Chrome MV3 extension intercepting ChatGPT, Claude, and Gemini prompts in the browser
primitives/     Audit-proxy (FastAPI), stateful YAML policy engine, classifier, receipt writer
                + Unified 'truss' CLI for proxy wrapping, receipt verification, and trace analysis
examples/       Sample YAML policies (browser PHI, shared Slack sandbox Alice-vs-Bob), local demo UI, GCP runbook
www/            trusslabs.org (Astro static site & blog)
demo/           Asciinema casts of the primitives running against real session traces
docs/           Receipt schema, deployment architectures, and release checklist
```

## Three enforcement surfaces, one policy engine

1. **Browser-edge protection (`extension/` + `/v1/extension/check`):** Hooks ChatGPT, Claude, and Gemini inside the browser tab and fails closed if the local proxy is unreachable.
2. **Shared Slack & sandbox protection (`/v1/sandbox/check`):** Tracks who uploaded sensitive files (`workspace_owner`) on disk across 10-minute sandbox container resets so another user in the same Slack thread cannot ask the bot to export raw rows from a teammate's spreadsheet. See [`sandbox_stage_sensitive_attachment.yaml`](examples/policies/sandbox_stage_sensitive_attachment.yaml) and [`sandbox_block_confused_deputy_attach_file.yaml`](examples/policies/sandbox_block_confused_deputy_attach_file.yaml).
3. **CLI process proxy (`truss proxy start` / `truss proxy exec`):** Wraps local agents and command-line tools with the same YAML policies and tamper-evident receipt ledger.

## Run the audit-proxy and interactive demo locally

```bash
# 1. Install deps in a venv
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# 2. Optional: set a Gemini key. Without one, the demo uses a deterministic stub.
export GEMINI_API_KEY=...

# 3. Start the proxy + demo page on localhost:8000
./examples/run_demo.sh

# 4. Open http://localhost:8000
```

Policies live in `examples/policies/`. The local demo includes both the **Shared Slack Thread Leak Test (Alice vs. Bob)** and the single-turn PHI prompt/response checks.

## The Truss CLI

### Verify sample receipts

```bash
truss receipt verify examples/receipts
```

The verifier recomputes each receipt hash by zeroing `evidence.receipt_hash`, canonicalizing the JSON, and comparing it to the stored SHA-256.

### Run the trace primitives against a session log

Translate a session's `hooks.jsonl` into traceable nodes, find retry loops, and halt if a trap is set:

```bash
cat ~/.local/share/some-session/hooks.jsonl \
  | truss trace translate \
  | truss trace analyze --json --flag FLAG_CIRCULAR_REASONING \
  | truss trap run
```

## Deploy

- **Static site (`trusslabs.org`):** Built from `www/` and deployed to Cloudflare Pages (`see www/DEPLOY.md`).
- **Live demo (`demo.trusslabs.org`):** Runs on a GCP VM behind an outbound Cloudflare Tunnel (`see examples/deploy/gcp/README.md`).

## License

Apache 2.0 — see [LICENSE](LICENSE).
