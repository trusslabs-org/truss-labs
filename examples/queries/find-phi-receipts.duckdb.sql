WITH receipts AS (
  SELECT *
  FROM read_json_auto('examples/receipts/*.json')
),
phi AS (
  SELECT
    receipt_id,
    timestamp,
    prompt.text AS prompt_text,
    tool.model_id AS model_id,
    unnest(data_classes_touched) AS data_class,
    policy_decisions
  FROM receipts
)
SELECT
  receipt_id,
  timestamp,
  model_id,
  data_class.class AS class,
  list_transform(policy_decisions, p -> p.verdict) AS verdicts,
  prompt_text
FROM phi
WHERE starts_with(data_class.class, 'phi:')
ORDER BY timestamp;
