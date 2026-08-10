---
title: "The work item is the product"
description: "Enterprise AI adoption is the wrong unit. The useful middle is case-preparation AI: work arrives with evidence, policy context, recommended action, routing, and an audit trail."
date: "2026-08-10"
---

Varun's post on AI adoption being a myth names a problem I keep seeing from the infrastructure side: enterprise AI conversations still start with the wrong measurement.

Who has a seat? Who logged in this month? Who sent five prompts? Which team has the most token usage?

Those numbers are easy to count, but they are a weak proxy for the thing companies actually care about: did the work change?

If a team gets access to a chat assistant and the actual queue keeps moving at the same speed, the dashboard can still report adoption. If ten percent of the organization becomes excellent at AI and seventy percent never changes how they work, the dashboard can still report adoption. If a power user burns most of the tokens building sophisticated workflows while everyone else writes occasional emails, the dashboard can still report adoption.

That is not a moral failure. It is a measurement failure.

I do not want to restate his example. The interesting move is to extend the frame.

The better unit is the work item.

## The unit shift

The weak version of enterprise AI says:

> Here is a chat window. Ask it for help.

The slightly better version says:

> Here is an assistant connected to some of your tools.

The useful version says:

> The work item already arrives with the evidence, policy context, recommendation, routing, and receipt needed for a human to make the decision.

That is the difference between a tool and a prepared case.

Take an AI-governance review.

The weak version is a Slack message:

> Can we use this new model vendor for customer-support summaries?

The prepared-case version is a review packet:

> Proposed vendor: external model API. Data classes: customer messages, email addresses, support metadata. Policy hits: PII allowed only with redaction on output; payment data must be blocked from prompt boundary. Required controls: retention disabled, DPA on file, receipt logging enabled, human review for refunds. Recommended decision: allow for Tier 1 support summaries, block for billing disputes until payment-data classifier is deployed.

The AI did not become the compliance team. It prepared the judgment work.

The same pattern applies elsewhere:

- A security alert arrives with affected assets, prior login context, suspected attack path, recommended containment, and the policies that justify severity.
- A customer-support escalation arrives with product history, failed remediation attempts, refund policy, account value, and suggested response options.
- A deployment approval arrives with changed services, secrets touched, customer-data paths, rollback plan, test evidence, and risk flags.
- A contract review arrives with deviations from standard terms, business-owner impact, fallback language, and data-use implications.
- A vendor-risk review arrives with subprocessors, data residency, security attestations, missing documents, and required approvals.

This is the useful middle between two bad extremes.

It is not personal productivity: "summarize this ticket for me."

It is not autonomous fantasy: "run the finance department."

It is case-preparation AI. The work arrives already shaped for judgment.

## Beyond the barbell

The common enterprise pattern is a barbell.

On one end are small chat-window gains: rewrite this email, summarize this PDF, draft this job post. These are real, but they are disconnected from systems of record.

On the other end is the big-agent fantasy: let AI run the whole workflow. That is usually too broad, too risky, and too hard to audit.

The valuable middle is narrower and more operational:

> When X arrives, it already contains Y, Z, and a recommended next action.

Security alerts arrive with attack narrative, affected assets, and containment steps.

Contract redlines arrive with risk level, fallback language, and business-owner impact.

Support escalations arrive with customer history, likely cause, policy options, and suggested resolution.

Claims arrive with coverage mapping, missing evidence, and fraud indicators.

Finance anomalies arrive reconciled to source records and policy exceptions.

The user is still a human decision-maker. The AI is not pretending to be the department. It is preparing the case packet.

That is a much stronger definition of adoption than logins. A workflow has adopted AI when the work item itself changes shape.

## The control-plane problem

Prepared cases sound simple until you ask what the system has to touch.

An AI-governance review may need access to:

- vendor contracts
- data-processing terms
- security attestations
- product telemetry
- customer-data classifications
- retention settings
- model-boundary policy
- approval routing rules
- audit logs and receipts

That is where the real enterprise problem begins.

If an AI system prepares judgment work, it is no longer just a text generator. It is now participating in a governed workflow. It needs to know what it was allowed to read, what evidence it used, which policy version it applied, which recommendation it produced, who received the case, and what the human did afterward.

Without that control plane, case-preparation AI becomes another opaque automation layer.

The failure mode is not only "the model was wrong." The failure modes are more structural:

- the model used evidence it should not have accessed
- the recommendation was based on stale policy
- the routing decision cannot be explained
- sensitive data appeared in a downstream surface
- the human changed the outcome but the system lost the correction
- the audit trail shows the final decision but not the reasoning path

This is where Truss Labs connects directly to the workflow story.

## What Truss cares about

Truss is not trying to be the support workflow product, the security alert product, or the vendor-risk product.

The Truss layer is lower than that.

It asks:

- What crossed the model boundary?
- Which policy saw it?
- Was the request allowed, blocked, redacted, or alerted?
- What session state existed before the decision?
- What state changed after the decision?
- Which receipt proves the path later?

That matters because case-preparation AI needs more than good prompts. It needs receipts.

If an agent prepares an AI-governance review, the enterprise should be able to inspect a durable record:

```json
{
  "workflow": "ai_vendor_review",
  "work_item": "vendor_review_1042",
  "event": "case_prepared",
  "model_boundary": {
    "vendor": "external_model",
    "direction": "prompt",
    "verdict": "allowed_with_controls"
  },
  "evidence": [
    "vendor.dpa",
    "security.soc2_report",
    "data_map.support_messages",
    "policy.customer_pii_external_model"
  ],
  "policy": {
    "policy_id": "external_model_customer_data",
    "policy_version": "v2.1"
  },
  "recommendation": {
    "decision": "allow_tier_1_support_summaries",
    "controls": ["output_redaction", "receipt_logging", "payment_data_prompt_block"],
    "route_to": "security_and_legal",
    "confidence": "medium"
  }
}
```

That record is not a decorative log. It is the structural difference between an AI feature and a governed system.

## Why chat cannot hold this

A chat window can produce the same paragraph once.

It cannot reliably own the workflow.

The prepared case needs state. It needs identity. It needs policy memory. It needs source links. It needs permission boundaries. It needs a receipt that survives the current browser tab and can be inspected by someone who was not present for the conversation.

This is why I keep coming back to the same architecture:

- the classifier says what data appeared
- the policy engine decides what can happen
- the session store remembers bounded context
- the receipt writer records the decision path
- the workflow system receives a prepared case, not a raw model response

That is the division of labor.

The model can draft, compare, classify, and recommend. The control plane decides what the model is allowed to see, what the user is allowed to receive, and what proof exists afterward.

## Adoption should be measured at the queue

If we measure AI by tool usage, we get tool theater.

If we measure AI by workflow shape, the questions get better:

- What percentage of exceptions arrive pre-classified?
- What percentage of cases include linked evidence?
- How often does the human accept, edit, or reject the recommendation?
- How much review burden moved from search to judgment?
- Which policy exceptions recur?
- Which automations are blocked by missing evidence?
- Which model calls produced auditable receipts?

That is a board-level metric because it maps directly to operations.

Not "eighty-eight percent of employees used AI."

"Forty-two percent of vendor reviews now arrive as prepared cases with data classification, policy mapping, recommended controls, approval route, and review receipt."

That is adoption you can manage.

## The work item is the product

The next wave of enterprise AI will not be won by asking every employee to become a prompt expert.

Some people will. They should be trained, given publishing surfaces, and rewarded for turning their workflows into reusable tools.

But most employees do not want a better chat box. They want the work to arrive in a state where judgment is easier.

That is the practical promise of case-preparation AI:

Raw work item in. Prepared case out. Human judgment preserved. Audit trail intact.

Truss Labs exists for the hard part underneath that sentence: the policy, memory, boundary control, and receipt layer that lets prepared cases become trustworthy infrastructure instead of another pile of clever text.

AI disclosure: This post was drafted with assistance from Codex.
