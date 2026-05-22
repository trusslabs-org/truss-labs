# Sample receipts

These receipts are static examples for reviewers who want to inspect the audit artifact before running the proxy.

- `allowed.json` — benign prompt, synthetic allow decision.
- `blocked_phi_address.json` — prompt blocked before the LLM sees it; the attempted prompt is stored for audit review.
- `redacted_dob_response.json` — response redaction with before/after hashes in `policy_decisions[0].redactions_applied`.

Verify the hashes:

```bash
truss receipt verify examples/receipts
```

The verifier recomputes `evidence.receipt_hash` from the canonical JSON after setting that field to an empty string. These receipts are content-addressed, not cryptographically signed; `evidence.signature` is intentionally `null`.
