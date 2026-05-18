# Receipt query cookbook

These examples run against `examples/receipts/` and demonstrate the main reason receipts are plain JSON: standard tools can answer audit questions without a proprietary database.

## PHI receipts with DuckDB

```bash
duckdb -c ".read examples/queries/find-phi-receipts.duckdb.sql"
```

Answers: which receipts touched `phi:*` classes, which model was involved, and which policy verdicts were recorded.

## Blocked receipts with jq

```bash
jq -s -f examples/queries/find-blocks-last-7d.jq examples/receipts/*.json
```

Answers: which receipts include an enforced block decision and why.

## Retention cleanup candidates

```bash
examples/queries/retention-prune-candidates.sh examples/receipts
```

Answers: which receipts are past `retention.retain_until`. The script is dry-run only; it prints candidates and does not delete files.

See also: `docs/RECEIPT_SCHEMA.md`.
