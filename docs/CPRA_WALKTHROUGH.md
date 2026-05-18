# CPRA Walkthrough: AI Activity Receipts

This is a hypothetical operations walkthrough, not legal advice. The California Public Records Act generally gives access to public records unless an exemption applies; agency counsel should review scope, exemptions, and redactions before any production. See the California Secretary of State PRA page: https://www.sos.ca.gov/administration/public-records-act-requests

## Scenario

A request arrives at a California county:

> Please provide records of AI assistant activity that touched patient record `record:11248` during the last six months.

Truss receipts are JSON files on disk. The response workflow is ordinary records work: locate candidate records, review them, redact where required, and preserve the integrity check.

## 1. Find Candidate Receipts

If the receipt includes `context_references[].resource_id`, start with `grep`:

```bash
grep -rl '"resource_id":"record:11248"' /var/truss/receipts/ > /tmp/cpra-candidates.txt
```

For the sample receipts in this repo, find all receipts touching PHI:

```bash
jq -s '.[] | select(any(.data_classes_touched[]?; .class | startswith("phi:"))) |
  {receipt_id, timestamp, verdict: [.policy_decisions[].verdict], prompt: .prompt.text}' \
  examples/receipts/*.json
```

## 2. Check Retention

Each receipt carries its retention metadata:

```bash
jq '{receipt_id, retain_until: .retention.retain_until, legal_hold: .retention.legal_hold}' \
  examples/receipts/*.json
```

If `retain_until` has passed and the file was lawfully deleted before the request arrived, the record may no longer exist. If `legal_hold` is true, deletion should be suspended.

## 3. Build The Review Packet

For each candidate receipt, the useful fields are:

- `receipt_id`, `timestamp`, and `schema_version`
- `actor`, `tool`, and `policy_decisions`
- `data_classes_touched`
- `prompt.text` and `response.text`, subject to counsel-approved redaction
- `evidence.receipt_hash`
- `retention`

Fields likely needing review before release include prompt/response text, user identifiers, endpoint names, and any PHI/PII. The receipt format makes those fields explicit; it does not decide disclosure.

## 4. Verify Integrity

Before producing or relying on a receipt, recompute its hash:

```bash
truss verify examples/receipts/blocked_phi_address.json
```

The verifier zeros `evidence.receipt_hash`, canonicalizes the JSON, computes SHA-256, and compares it to the stored value. This is tamper-detection, not cryptographic signing; `evidence.signature` is currently `null`.

## Known Gap

This receipt format has not yet been tested in an actual CPRA response. Treat this as an evaluation workflow for security, IT, and counsel to review before formal use.
