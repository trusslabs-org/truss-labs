---
title: "The work item is the product"
description: "Varun's AI adoption critique points to the real enterprise unit: not seats, prompts, or tokens, but prepared work items with evidence, policy, routing, and receipts."
date: "2026-08-10"
---

[Varun's post on AI adoption](https://x.com/i/status/2085806422072418632) makes a point that feels obvious once someone says it plainly: enterprise AI adoption dashboards are measuring the wrong thing.

Seats are not adoption. Logins are not adoption. Prompt counts are not adoption. Token spend is not adoption.

Those are activity metrics. They tell us whether a tool exists, whether someone touched it, and whether money is being burned. They do not tell us whether the work changed.

That is the part we want to extend.

Varun's frame is roughly: most companies get a barbell. A small group becomes very good at AI, a middle group uses it shallowly, and a large group barely changes. We think that is right for broad chatbot rollouts. But the more interesting lesson is not just "train the top slice and automate for everyone else."

The deeper lesson is that the unit of AI adoption should move from the user to the work item.

## The Shape Of The Shift

Here is the graph we keep coming back to:

```text
Operational value
^
|                                      Big autonomous agent fantasy
|                                      "Let AI run the department"
|                                      High ambition, low trust
|
|                    Prepared work items
|                    "The case arrives with evidence,
|                     policy, recommendation, route, receipt"
|                    High leverage, human judgment preserved
|
|     Chat productivity
|     "Summarize this, draft that"
|     Useful, but detached from the queue
|
+----------------------------------------------------------------> Workflow integration
      personal tool              operational layer              governed system
```

Most of the enterprise AI conversation swings between the bottom-left and the top-right.

The bottom-left is real but limited: chat as a personal productivity layer.

The top-right is exciting but usually too vague: autonomous agents running entire business functions.

We think the middle is where a lot of durable value will show up first. Not "everyone becomes a prompt expert." Not "the agent replaces the department." Instead:

> The work item arrives prepared for judgment.

That sounds small. It is not small.

## What We Mean By Prepared

A prepared work item is not a summary pasted into a chat window.

It is an operational object that has been enriched before it reaches the human:

```text
Raw event
  -> classification
  -> evidence packet
  -> policy / contract / history mapping
  -> recommended next action
  -> route to the right human
  -> durable receipt
  -> human judgment
```

The AI does not need to pretend to be the owner of the decision. The useful move is earlier than that. It turns messy intake into a case packet.

That is the difference between:

> "Here is a tool. Ask it for help."

and:

> "Here is the work. It already contains the context needed to decide."

## Better Examples Than Chat

The easiest way to see this is through queues.

Every serious business already has queues: support queues, security queues, approval queues, compliance queues, procurement queues, legal queues, data-access queues, deployment queues.

The question is whether AI stays outside those queues as a side chat window, or whether the queue item itself becomes smarter.

### AI Vendor Review

Weak version:

> Can we use this model vendor for support summaries?

Prepared version:

> Proposed vendor: external model API. Data classes: support messages, customer email addresses, account metadata. Policy mapping: PII allowed only with output redaction; payment data blocked from prompt boundary. Evidence: DPA on file, retention controls documented, SOC 2 report current. Missing: billing-dispute workflow review. Recommended decision: allow for Tier 1 support summaries, block for billing disputes until payment-data classifier is deployed. Route: security and legal.

That is not just a summary. It is a review object.

### Security Alert

Weak version:

> Suspicious login detected.

Prepared version:

> New login from unfamiliar ASN followed by OAuth token creation. Prior session from New York occurred 18 minutes earlier. User received a phishing email with matching sender infrastructure. Affected assets: mailbox, CRM token, docs access. Recommended severity: high. Suggested containment: revoke sessions, disable OAuth token, inspect forwarding rules, preserve receipt. Route: security on-call.

The analyst still decides. But the case arrives with a story, not a blinking light.

### Support Escalation

Weak version:

> Customer is upset about a failed workflow.

Prepared version:

> Enterprise customer escalation. Failure began after workspace migration. Three support attempts repeated the same cache reset. Product logs show permission mismatch on inherited group. Contract tier allows priority engineering review. Recommended action: acknowledge failed prior remediation, route to platform team, offer temporary admin override, and attach incident to renewal risk.

The AI is not "doing support." It is compressing the hunt.

### Deployment Approval

Weak version:

> Approve deploy?

Prepared version:

> Release touches auth middleware, billing webhook parser, and customer-export job. Secrets: none changed. Data paths: customer email and billing account metadata. Tests: unit pass, integration pass, no migration rollback tested. Policy flags: billing path requires second approver. Recommended action: approve auth change, hold billing parser until rollback is tested. Route: engineering manager plus payments owner.

This is where AI becomes useful to governance. It prepares the review, but it does not erase accountability.

### Contract Redline

Weak version:

> Summarize this contract.

Prepared version:

> Top deviations from standard terms: uncapped liability, customer-data use for model training, 90-day payment terms, termination notice extended to 120 days. Highest risk: data-use clause conflicts with customer commitments. Suggested fallback language attached. Route: legal plus data-governance owner.

That is not a document summary. It is a negotiation packet.

### Data Access Request

Weak version:

> Analyst requests production data access.

Prepared version:

> Request scope: customer event logs for churn analysis. Data classes: user IDs, emails, workspace IDs, billing plan, usage events. Policy: direct email access not needed; pseudonymized export allowed for analytics workspace. Prior similar request approved with 30-day expiry. Recommended decision: approve pseudonymized dataset, deny raw production access, require expiry and receipt. Route: data steward.

This is the Truss-shaped version of AI adoption: the system helps decide what can cross a boundary.

## Why This Connects To Truss

Truss Labs is not trying to be the support platform, the contract tool, the SIEM, or the procurement system.

We care about the layer underneath prepared work:

- What crossed the model boundary?
- Which data classes appeared?
- Which policy saw them?
- Was the request allowed, blocked, redacted, or alerted?
- What session state existed before the decision?
- What changed after the decision?
- Which receipt proves it later?

Prepared work items are only trustworthy if the preparation is inspectable.

Otherwise we have a familiar failure mode: an AI system gives a confident recommendation, everyone moves faster for a while, and then nobody can answer the basic governance questions.

What did the model see?

Was it allowed to see that?

Which evidence did it use?

Which policy version did it apply?

Did the human accept, edit, or reject the recommendation?

Where is the receipt?

That is the control-plane problem.

## The Receipt Is The Product Boundary

If an agent prepares an AI vendor review, the record should look less like a chat transcript and more like an operational receipt:

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
    "controls": [
      "output_redaction",
      "receipt_logging",
      "payment_data_prompt_block"
    ],
    "route_to": "security_and_legal",
    "confidence": "medium"
  }
}
```

That record is not decorative logging. It is the structural difference between "we used AI" and "we can govern the work AI touched."

This is why we think receipts, policy memory, and model-boundary control are not side features. They are the infrastructure that lets the prepared-work-item pattern become real.

## A Better Adoption Dashboard

If we measure AI by user activity, we get tool theater.

If we measure AI by work-item shape, the dashboard gets much more useful:

- What percentage of security alerts arrive with evidence packets?
- What percentage of vendor reviews include data-classification and policy mapping?
- What percentage of support escalations arrive with prior attempts and likely owner?
- How often do humans accept, edit, or reject the recommendation?
- Which policy exceptions recur?
- Which workflows are blocked by missing evidence?
- Which model calls produced auditable receipts?
- Where did cycle time improve without increasing unmanaged risk?

That is a better board conversation than "monthly active AI users went up."

We would rather report:

> Forty-two percent of vendor reviews now arrive as prepared cases with data classification, policy mapping, recommended controls, approval route, and review receipt.

than:

> Eighty-eight percent of employees used AI this month.

The first one says the work changed.

## The Work Item Is The Product

The next wave of enterprise AI will not be won by asking every employee to become a prompt expert.

Some people will become power users. We should support them. They are where reusable internal tools, playbooks, evals, and workflow ideas come from.

But most employees do not want a better chat box. They want the work to arrive in a state where judgment is easier.

That is the practical promise of case-preparation AI:

```text
raw work item in
prepared case out
human judgment preserved
audit trail intact
```

Varun's post is useful because it punctures the shallow adoption story. Our extension is that the enterprise unit should not be the user at all. It should be the work item.

And once the work item becomes the product, the control plane matters.

That is where Truss Labs lives: policy, memory, boundary control, and receipts for the systems that prepare judgment work.

AI disclosure: This post was drafted with assistance from Codex.
