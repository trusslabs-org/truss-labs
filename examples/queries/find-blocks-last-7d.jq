[
  .[]
  | . as $receipt
  | [
      .policy_decisions[]
      | select(.verdict == "blocked" and .enforcement_mode == "enforced")
    ] as $blocks
  | select($blocks | length > 0)
  | {
      receipt_id: $receipt.receipt_id,
      timestamp: $receipt.timestamp,
      actor: $receipt.actor.user_id,
      prompt: $receipt.prompt.text,
      blocks: [
        $blocks[]
        | {
            policy_id,
            matched_classes
          }
      ]
    }
]
