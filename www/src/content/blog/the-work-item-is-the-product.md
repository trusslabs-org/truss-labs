---
title: "The work item is the product"
description: "Enterprise AI adoption is the wrong unit. The useful middle is case-preparation AI: work arrives with evidence, policy context, recommended action, routing, and an audit trail."
date: "2026-08-10"
---

Most enterprise AI conversations still start with the wrong measurement.

Who has a seat? Who logged in this month? Who sent five prompts? Which team has the most token usage?

Those numbers are easy to count, but they are a weak proxy for the thing companies actually care about: did the work change?

If a finance team gets access to a chat assistant and invoice throughput stays flat, the dashboard can still report adoption. If ten percent of the organization becomes excellent at AI and seventy percent never changes how they work, the dashboard can still report adoption. If a power user burns ninety percent of the tokens building sophisticated workflows while everyone else writes occasional emails, the dashboard can still report adoption.

That is not a moral failure. It is a measurement failure.

The better unit is the work item.

## The example that matters

Consider an invoice exception.

The weak version of AI says:

> Invoice #48291 failed validation.

The slightly better version says:

> This may be a price variance.

The useful version says:

> Likely price variance: invoice line 3 bills $18.40/unit against a PO-approved $16.75/unit. The July 12 contract addendum supports $16.75. A similar variance was approved once for expedited freight, but this invoice has no freight note. Recommended action: route to the procurement owner for approval or vendor correction.

That is the difference between an alert and a prepared case.

The AI did not replace the accounts-payable analyst. It did the work before the work:

- detected the exception
- classified the likely issue
- pulled evidence from the PO, contract, receipt, and prior approvals
- mapped the evidence to policy or precedent
- recommended the next action
- routed the case to the right human
- preserved enough context for later review

This is the useful middle between two bad extremes.

It is not personal productivity: "summarize this invoice for me."

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

The invoice example may need access to:

- the invoice
- the purchase order
- contract terms
- receiving records
- vendor master data
- prior exceptions
- approval policy
- employee routing rules
- audit logs

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

Truss is not trying to be the AP workflow product, the security alert product, or the claims-processing product.

The Truss layer is lower than that.

It asks:

- What crossed the model boundary?
- Which policy saw it?
- Was the request allowed, blocked, redacted, or alerted?
- What session state existed before the decision?
- What state changed after the decision?
- Which receipt proves the path later?

That matters because case-preparation AI needs more than good prompts. It needs receipts.

If an agent prepares an invoice exception, the enterprise should be able to inspect a durable record:

```json
{
  "workflow": "accounts_payable_exception",
  "work_item": "invoice_48291",
  "event": "case_prepared",
  "model_boundary": {
    "vendor": "external_model",
    "direction": "prompt",
    "verdict": "allowed"
  },
  "evidence": [
    "invoice.line_items[3]",
    "purchase_order.price_terms",
    "contract.addendum.2026-07-12",
    "prior_exception.approved_variance"
  ],
  "policy": {
    "policy_id": "ap_price_variance_review",
    "policy_version": "v1.3"
  },
  "recommendation": {
    "reason_code": "price_variance",
    "route_to": "procurement_owner",
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

"Forty-two percent of invoice exceptions now arrive as prepared cases with reason code, source evidence, recommended route, and review receipt."

That is adoption you can manage.

## The work item is the product

The next wave of enterprise AI will not be won by asking every employee to become a prompt expert.

Some people will. They should be trained, given publishing surfaces, and rewarded for turning their workflows into reusable tools.

But most employees do not want a better chat box. They want the work to arrive in a state where judgment is easier.

That is the practical promise of case-preparation AI:

Raw work item in. Prepared case out. Human judgment preserved. Audit trail intact.

Truss Labs exists for the hard part underneath that sentence: the policy, memory, boundary control, and receipt layer that lets prepared cases become trustworthy infrastructure instead of another pile of clever text.

AI disclosure: This post was drafted with assistance from Codex.
