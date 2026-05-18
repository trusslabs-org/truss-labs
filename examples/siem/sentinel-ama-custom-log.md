# Microsoft Sentinel via Azure Monitor Agent

For Sentinel, ship Truss receipts as a custom text log through Azure Monitor Agent (AMA), then parse JSON in KQL.

Microsoft's current custom log ingestion documentation is here:

- https://learn.microsoft.com/azure/azure-monitor/agents/data-collection-log-text
- https://learn.microsoft.com/azure/azure-monitor/logs/create-custom-table

## Shape

Receipt path:

```text
/var/truss/receipts/*/*.json
```

Recommended custom table name:

```text
TrussReceipt_CL
```

## Parsing sketch

After ingestion, keep the raw line and parse it at query time:

```kusto
TrussReceipt_CL
| extend receipt = parse_json(RawData)
| extend receipt_id = tostring(receipt.receipt_id)
| extend actor = tostring(receipt.actor.user_id)
| extend verdicts = receipt.policy_decisions
| project TimeGenerated, receipt_id, actor, verdicts, receipt
```

## Operational notes

AMA custom text logs are line-oriented. If your collector expects one event per line, either configure it to read each JSON file as a single event or roll receipts into JSONL before ingestion. Do not drop `evidence.receipt_hash`; that field is how an auditor verifies the receipt body later.
