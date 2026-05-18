# SIEM forwarding examples

Truss receipts are JSON files. You do not need a proprietary connector to ship them into a SIEM; point the forwarder you already operate at the receipts directory.

## Which example to use

- `splunk-uf-inputs.conf` — use when the host already runs Splunk Universal Forwarder.
- `rsyslog-imfile.conf` — use for Linux-native forwarding to a syslog collector or relay.
- `sentinel-ama-custom-log.md` — use for Microsoft Sentinel / Azure Monitor Agent environments.

## File-per-receipt trade-off

The demo writes one JSON file per receipt under a date directory, for example:

```text
/var/truss/receipts/2026-05-15/rcp_2026-05-15T12-52-11_3c5972.json
```

That is easy to audit with `find`, `grep`, `jq`, and filesystem retention jobs. At very high volume, a downstream collector may prefer JSONL batches or Parquet. That is a transport decision; the receipt schema stays the same.

## Suggested fields

Index or parse at least:

- `receipt_id`
- `timestamp`
- `actor.user_id`
- `tool.tool_id`
- `tool.model_id`
- `policy_decisions[].verdict`
- `policy_decisions[].policy_id`
- `data_classes_touched[].class`
- `evidence.receipt_hash`
