# Security Policy

## Reporting a vulnerability

If you find a security issue in the Truss audit-proxy, the policy engine, the classifier, the receipt writer, or any of the primitives, please report it privately rather than opening a public issue.

**Contact:** ilteris@trusslabs.org

Include:
- A description of the issue and where in the code it lives (file path + line if possible)
- Steps to reproduce, or a proof-of-concept
- The impact you believe it has (e.g., bypass of policy enforcement, receipt tampering, information disclosure)
- Whether you'd like to be credited in the fix

You can encrypt the report against the maintainer's public key on request.

## What to expect

- Acknowledgement within 72 hours of receipt
- A first assessment within one week
- Coordinated disclosure: I'll work with you on a timeline before any public write-up

This is a single-maintainer project today. Response times are best-effort, not contractual. I'll be honest about scope and capacity in my reply.

## Scope

In scope:
- `primitives/audit/` — the audit-proxy, policy engine, classifier, receipt writer
- `primitives/scripts/` — the CLI primitives
- The `examples/policies/` reference policies (insofar as a misleading example could cause downstream misconfiguration)
- Deployment guidance in `examples/deploy/`

Out of scope:
- The `www/` static site (report site issues to the host directly)
- Third-party model providers (Gemini, Anthropic, OpenAI) — report those upstream
- Asciinema demo recordings

## Known limitations

These are documented gaps, not vulnerabilities. They are tracked in the public repo and the roadmap.

- **Receipt signing.** `evidence.signature` is currently nullable and not populated. Receipts are content-addressed via `evidence.receipt_hash` (SHA-256 over canonical JSON), which provides tamper-*detection* but not tamper-*prevention*. Cryptographic signing with a key-management story (HSM, per-customer key) is post-pilot work. See [`docs/RECEIPT_SCHEMA.md`](docs/RECEIPT_SCHEMA.md).
- **Prompt text on block.** When a policy blocks a request, the receipt currently stores `prompt.text` raw. This is intentional — auditors need to see what was attempted — but means retention policy, not field-level redaction at the receipt layer, is what protects sensitive content in the audit log over time.
- **Single-maintainer project.** No 24/7 on-call. Response is best-effort.

## License

This project is Apache 2.0. See [LICENSE](LICENSE).
