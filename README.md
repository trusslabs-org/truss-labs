# Truss Labs

Truss is an audit and policy layer that sits in front of LLM and agent APIs. Every call gets a YAML policy applied (allow / block / redact), and a hash-verifiable JSON receipt is written to disk. The pitch: DLP-style visibility for AI activity on sensitive data, on infrastructure you control.

**Live sandbox:** [trusslabs.org/sandbox](https://trusslabs.org/sandbox)
**Site:** [trusslabs.org](https://trusslabs.org)

## What's in this repo

```
primitives/     Audit-proxy (FastAPI), policy engine, classifier, receipt writer
                + Unified 'truss' CLI for receipt verification and trace analysis
www/            trusslabs.org (Astro static site)
examples/       Sample policies, a local demo page, a GCP deploy runbook
demo/           Asciinema casts of the primitives running against real session traces
fixtures/       Sample traces for testing the primitives
docs/           Specs and design docs
```

## Run the audit-proxy locally

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

Policies live in `examples/policies/`. The demo loads the shipped PHI block and response-redaction rules, plus a synthetic allow decision when no rule matches.

## The Truss CLI

The `truss` CLI is the Swiss Army knife for auditing AI agents.

### Verify sample receipts

```bash
truss receipt verify examples/receipts
```

The verifier recomputes each receipt hash by zeroing `evidence.receipt_hash`, canonicalizing the JSON, and comparing it to the stored SHA-256.

### Run the primitives against a real trace

Translate a session's hooks.jsonl into traceable nodes, find every retry loop, and halt if a trap is set:

```bash
cat ~/.local/share/some-session/hooks.jsonl \
  | truss trace translate \
  | truss trace analyze --json --flag FLAG_CIRCULAR_REASONING \
  | truss trap run
```

A live recording: [trusslabs.org/demo/](https://trusslabs.org/) (asciinema embed under the "Show me" section).

## Sandbox

The interactive sandbox runs 100% client-side at [trusslabs.org/sandbox](https://trusslabs.org/sandbox).

If you want to deploy the older server-side proxy architecture, the legacy GCP VM provisioning runbook is located in [`examples/deploy/gcp/README.md`](examples/deploy/gcp/README.md).

## License

Apache 2.0 — see [LICENSE](LICENSE).
