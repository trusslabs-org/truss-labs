# Truss Labs

Truss is an audit and policy layer that sits in front of LLM and agent APIs. Every call gets a YAML policy applied (allow / block / redact), and a hash-verifiable JSON receipt is written to disk. The pitch: DLP-style visibility for AI activity on sensitive data, on infrastructure you control.

**Live demo:** [demo.trusslabs.org](https://demo.trusslabs.org)
**Site:** [trusslabs.org](https://trusslabs.org)

## What's in this repo

```
primitives/     Audit-proxy (FastAPI), policy engine, classifier, receipt writer
                + Unix-style CLIs that compose with pipes (soul_query, soul_trap, soul_translate)
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

## Verify sample receipts

```bash
truss verify examples/receipts
```

The verifier recomputes each receipt hash by zeroing `evidence.receipt_hash`, canonicalizing the JSON, and comparing it to the stored SHA-256.

## Run the primitives against a real trace

```bash
# Translate a session's hooks.jsonl into TWP-shaped nodes, find every retry loop:
cat ~/.local/share/some-session/hooks.jsonl \
  | python3 primitives/scripts/soul_translate.py \
  | python3 primitives/scripts/soul_query.py --json --flag FLAG_CIRCULAR_REASONING \
  | python3 primitives/scripts/soul_trap.py run
```

A live recording: [trusslabs.org/demo/](https://trusslabs.org/) (asciinema embed under the "Show me" section).

## Deploy

The live demo at `demo.trusslabs.org` runs on a GCP VM behind a Cloudflare Tunnel. Full provisioning steps in [`examples/deploy/gcp/README.md`](examples/deploy/gcp/README.md). The VM has zero inbound ports open; traffic flows out through `cloudflared`.

## License

Apache 2.0 — see [LICENSE](LICENSE).
