# Receipt JSON Schema

**Version:** 1.1
**Status:** Reference for the public audit-proxy demo and the `primitives/audit` codebase.
**Source of truth in code:** [`primitives/audit/schema.py`](../primitives/audit/schema.py)

Every model call routed through the Truss audit-proxy produces one JSON receipt on disk. This document describes the schema those receipts conform to. The same `RECEIPT_JSON_SCHEMA` constant in `schema.py` is enforced at write time — invalid receipts never land on disk.

---

## Design principles

1. **One file per receipt.** The filesystem is the index of last resort; `grep` and `jq` must work without extra infrastructure.
2. **JSON, not binary.** Plain text survives vendor failure, model deprecation, and multi-year retention. Diff-able and version-controllable.
3. **Self-contained per receipt.** Anything an auditor needs to interpret a single AI interaction is in that one file. No cross-file joins required for basic forensics.
4. **Customer-neutral data-class taxonomy.** Don't hardcode PHI. Sensitive-data classes are configurable per customer via namespace prefixes (`phi:*`, `pci:*`, `cji:*`, etc.).
5. **Hash everything that's text.** SHA-256 of prompt, response, downstream content. **Not for tamper-prevention** (that's signatures, which are post-pilot work) **but for tamper-detection**: an auditor can recompute and verify.
6. **Include retention metadata.** A receipt knows when it can be deleted. Compliance is a property of the file, not of the system reading it.
7. **Include policy-decision metadata.** Every receipt records which policy rules evaluated against the interaction and what the verdict was (allowed / blocked / redacted / alerted). Control is part of the audit trail, not separate from it.
8. **Atomic writes.** The writer uses temp file + `os.replace` so partial receipts are never visible to readers.

---

## Example receipt

```json
{
  "schema_version": "1.1",
  "receipt_id": "rcp_2026-05-15T14-32-08_a3f8c7",
  "timestamp": "2026-05-15T14:32:08.421Z",

  "external_trace_uri": null,

  "actor": {
    "user_id": "alice@acme.example",
    "user_role": "analyst",
    "department": "operations",
    "auth_method": "saml_sso"
  },

  "tool": {
    "tool_id": "internal_chat_assistant",
    "tool_version": "v2.4.1",
    "model_id": "gemini-2.5-flash",
    "model_vendor": "google",
    "endpoint": "generativelanguage.googleapis.com/v1beta"
  },

  "prompt": {
    "text": "Summarize the key changes in this quarter's IT operations report.",
    "text_hash": "sha256:abc123...",
    "text_length_chars": 64,
    "context_references": []
  },

  "response": {
    "text": "Three notable changes this quarter: ...",
    "text_hash": "sha256:def456...",
    "text_length_chars": 287,
    "tokens_used": 78,
    "latency_ms": 1240
  },

  "data_classes_touched": [],

  "downstream_actions": [],

  "policy_decisions": [
    {
      "policy_id": "default_allow",
      "policy_version": "v1.0",
      "policy_set_version": "a3f8c7b29e10",
      "evaluated_at": "2026-05-15T14:32:08.380Z",
      "verdict": "allowed",
      "enforcement_mode": "enforced",
      "matched_classes": [],
      "would_have_blocked": null,
      "redactions_applied": [],
      "error_reason": null,
      "alert_id": null
    }
  ],

  "evidence": {
    "receipt_hash": "sha256:fullreceiptexcludingthisfield...",
    "captured_by": "truss-audit-pipeline-v0.1",
    "capture_method": "http_proxy_intercept",
    "signature": null
  },

  "retention": {
    "retain_until": "2033-05-15",
    "retention_policy": "default_seven_year",
    "deletable_after": "2033-05-15T00:00:00Z",
    "legal_hold": false
  }
}
```

---

## Field reference

### Top-level

| Field | Type | Required | Notes |
|---|---|---|---|
| `schema_version` | string | yes | Constant `"1.1"` for this version. |
| `receipt_id` | string | yes | Pattern: `rcp_<ISO-timestamp>_<6-hex>`. |
| `timestamp` | ISO-8601 string | yes | UTC. |
| `external_trace_uri` | string \| null | no | Optional bridge to an external trace system (OpenTelemetry, vendor-specific). The receipt is fully interpretable without it. |
| `actor` | object | yes | Who made the call (see below). |
| `tool` | object | yes | What made the call. |
| `prompt` | object | yes | What was sent to the model. |
| `response` | object | yes | What came back. |
| `data_classes_touched` | array | yes | Classifier output: which sensitive-data classes appeared and where. |
| `downstream_actions` | array | yes | Side effects that followed (file writes, API calls, etc.). |
| `policy_decisions` | array | yes | Per-policy verdicts that ran against this interaction. |
| `evidence` | object | yes | Hash + capture metadata for integrity verification. |
| `retention` | object | yes | Retention/legal-hold metadata for lifecycle management. |

### `actor`
- `user_id` (required), `user_role`, `department`, `auth_method`.

### `tool`
- `tool_id` (required), `model_id` (required), `tool_version`, `model_vendor`, `endpoint`.

### `prompt`
- `text` (required) — the prompt as sent to the model.
- `text_hash` (required) — `sha256:<64-hex>` of the prompt text.
- `text_length_chars` (required).
- `context_references` (array) — structured pointers to the data the agent retrieved (e.g., a record ID it pulled before composing the prompt).

### `response`
- `text` (required), `text_hash` (required), `text_length_chars` (required).
- `tokens_used`, `latency_ms` (nullable).

### `data_classes_touched[]`
Each entry: `class` (string, namespace-prefixed: `"phi:patient_name"`, `"pii:ssn"`, etc.), `instances` (int), `in_prompt` (bool), `in_response` (bool).

### `downstream_actions[]`
Each entry: `action_id`, `type`, `target_path`, `target_size_bytes`, `content_hash`, `diff_from_response`, `timestamp`.

### `policy_decisions[]`
One entry per policy that evaluated this interaction. Per `POLICY_ENGINE_SPEC v0.2`:
- `policy_id`, `policy_version` — nullable for synthetic "no rule matched" entries.
- `policy_set_version` — always present.
- `evaluated_at` — ISO-8601 timestamp.
- `verdict` — closed enum: `allowed | blocked | redacted | alerted`.
- `enforcement_mode` — closed enum: `enforced | audit_only | error`.
- `matched_classes[]` — which data classes triggered the rule.
- `would_have_blocked` — nullable bool. Only meaningful when `enforcement_mode != enforced`.
- `redactions_applied[]` — each entry: `location` (`"prompt"` | `"response"`), `before_hash`, `after_hash`.
- `error_reason` — closed enum, null unless `enforcement_mode == error`: `classifier_timeout | classifier_exception | taxonomy_load_error | policy_eval_exception`.
- `alert_id` — null unless `verdict == alerted`. When present: `{id, delivery_status: "pending"|"delivered"|"failed", delivered_at: ISO-8601 | null}`.

### `evidence`
- `receipt_hash` — SHA-256 over the canonicalized JSON body, computed with this field zeroed. An auditor reproduces the hash by:
  1. Loading the receipt JSON
  2. Setting `evidence.receipt_hash = ""`
  3. Re-serializing with `sort_keys=True, separators=(',', ':')`
  4. SHA-256 of the UTF-8 bytes
- `captured_by` — identifier of the writer (e.g., `"truss-audit-pipeline-v0.1"`).
- `capture_method` — e.g., `"http_proxy_intercept"`.
- `signature` — **nullable**. Reserved for future cryptographic signing. **Not currently populated.** See "What this schema does NOT yet handle" below.

### `retention`
- `retain_until` (date), `retention_policy` (string identifier), `deletable_after` (datetime), `legal_hold` (bool).

---

## Querying receipts

### SQLite / DuckDB
DuckDB and SQLite-with-json can read the receipts directory directly. No vendor index, no proprietary format.

```sql
SELECT receipt_id, prompt.text, data_classes_touched, tool.model_id, timestamp
FROM read_json_auto('receipts/**/*.json')
WHERE EXISTS (
  SELECT 1 FROM unnest(data_classes_touched) AS dc(c)
  WHERE c.class LIKE 'phi:%'
)
AND timestamp > '2026-05-01';
```

### grep
```bash
grep -lr '"resource_id":"record:11248"' receipts/ | xargs jq -s '.'
```

Returns every receipt mentioning record 11248 across prompt context, response, or downstream actions. Single grep, no infrastructure.

### Retention prune
```bash
find receipts/ -name '*.json' -newer some-marker | \
  xargs jq -r 'select(.retention.retain_until < (now | strftime("%Y-%m-%d"))) | .receipt_id'
```

The `retention.retain_until` field on every receipt makes the retention policy a property of the file. A garbage-collection job can run `find` against `retain_until < today` and prune. An auditor can verify retention compliance by sampling files.

---

## What this schema does NOT yet handle

Honest gaps. None block evaluation; all are documented for transparency.

- **Cryptographic signatures.** `evidence.signature` is `null` in v1.1. The receipt is content-addressed via `evidence.receipt_hash` (SHA-256), which gives **tamper-detection** (auditor recomputes and verifies). True **tamper-prevention** via signing requires a key-management story — HSM, per-customer key, etc. Post-pilot work.
- **Multi-modal AI** (image inputs, voice, video). Schema is text-first. Multi-modal classifiers can be wired later; the receipt structure supports it.
- **Streaming responses.** Captured as a complete response, not a stream.
- **Multi-agent / multi-step workflows.** A receipt is one prompt → one response → downstream actions. Composite workflows (agent-A-calls-agent-B) currently produce one receipt per model call, not a unified workflow record. The optional `external_trace_uri` field is the bridge for orgs running a separate workflow tracer.
- **Raw-prompt redaction at the receipt layer.** When a prompt is blocked, the receipt currently stores `prompt.text` raw. This is by design — auditors need to see what was attempted — but it means **retention policy, not field-level redaction, is what protects sensitive content in the audit log over time.** A future option to store hash-only on block is on the roadmap.

---

## Schema evolution

Every receipt carries `schema_version`. Migrations rewrite old receipts to a new schema in place, preserving the original under `<receipt_id>.v<old>.json` for evidence integrity. The promise is **backward-readability via migrations**, not forward-compatibility.

---

## See also

- [`primitives/audit/schema.py`](../primitives/audit/schema.py) — code source of truth (TypedDicts + JSON Schema)
- [`primitives/audit/receipt_writer.py`](../primitives/audit/receipt_writer.py) — atomic writer with schema validation
- [`primitives/audit/tests/test_receipt_writer.py`](../primitives/audit/tests/test_receipt_writer.py) — examples of construction
- [`SECURITY.md`](../SECURITY.md) — vulnerability disclosure
