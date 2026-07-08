---
title: "Policies need memory"
description: "Single-call AI policies can block or redact one request. Contextual policies add session state, so the proxy can catch risk that only becomes clear across several turns."
date: "2026-07-08"
---

Most AI policy systems evaluate one request at a time.

That is enough for simple cases. If a prompt contains a patient address and the destination is an external model API, block it. If a model response repeats a date of birth back to the user, redact it. Each decision can be made from the current text, the current destination, and the classifier hits.

But some risk only shows up over time.

A user may not paste a full patient record into one prompt. They may send a name in one turn, a date of birth in another, and clinical context in a third. Each request may look acceptable on its own. The session is the problem.

This is why Truss now has contextual policies.

## What changed

The policy engine now has a normalized event object:

```json
{
  "event_id": "evt_2026-07-08_001",
  "session_id": "sess_chatgpt_abc123",
  "type": "browser_prompt",
  "surface": "chrome_extension",
  "vendor": "chatgpt",
  "destination": "external_vendor",
  "data": {
    "text": "Patient DOB 1978-04-12",
    "url": "https://chatgpt.com/c/example",
    "source": "submit-gate",
    "conversation_id": "example"
  },
  "session_state": {
    "risk_score": 20
  }
}
```

That event gives the policy engine more than a string. It gives it the browser surface, vendor, conversation, and current session state.

Policies can now match on event type, inspect state, and emit bounded state updates. The engine still returns a normal verdict: allowed, blocked, redacted, or alerted. The difference is that the decision can depend on what already happened in the session.

## A small risk score

Here is the simple policy pair I added for the browser demo.

The first policy watches for patient name or date of birth in browser prompts. It does not block immediately. It increments a local `risk_score` and records that the session has seen PHI.

```yaml
schema_version: "1.1"
policy_id: phi_browser_risk_score
policy_version: "v1.0"

event:
  types: ["browser_prompt"]

match:
  direction: prompt
  destination: external_vendor
  classes:
    any_of:
      - phi:patient_name
      - phi:patient_dob

state_updates:
  - key: risk_score
    op: increment
    value: 20
  - key: has_seen_phi
    op: set
    value: true

verdict: alert
alert_config: {}
```

The second policy blocks once the same browser session gets too risky.

```yaml
schema_version: "1.1"
policy_id: phi_browser_block_when_risky
policy_version: "v1.0"

event:
  types: ["browser_prompt"]

condition:
  state:
    risk_score:
      gte: 40

match:
  direction: prompt
  destination: external_vendor
  classes:
    any_of:
      - phi:patient_name
      - phi:patient_dob

verdict: block
block_config:
  user_message: "This browser session has accumulated sensitive-data risk. External prompt blocked."
```

The numbers are intentionally boring. They are not a model. They are a policy primitive.

The important part is the shape: one policy updates state, another policy reads state. That lets the proxy express rules like "allow the first low-risk disclosure, warn on the second, block on the third" without building a separate workflow engine.

## The receipt matters

Contextual policy would be much less useful if the state lived only in memory.

Every extension check now writes the session context into the receipt:

```json
{
  "contextual_policy": {
    "session_id": "sess_chatgpt_abc123",
    "event_id": "evt_2026-07-08_001",
    "event_type": "browser_prompt",
    "surface": "chrome_extension",
    "vendor": "chatgpt",
    "url": "https://chatgpt.com/c/example",
    "source": "submit-gate",
    "conversation_id": "example",
    "state_before_hash": "sha256:...",
    "state_after_hash": "sha256:...",
    "state_updates": [
      {
        "policy_id": "phi_browser_risk_score",
        "key": "risk_score",
        "op": "increment",
        "value": 20
      }
    ]
  }
}
```

The receipt does not need to dump the entire session state on every request. It records the event, the ordered updates, and hashes of state before and after. That gives an auditor enough to reconstruct why a later request was blocked.

If state loading or mutation fails, the request still gets a policy-shaped decision. The policy can fail open or fail closed with `on_state_error`, and the receipt records the error path. That is better than a silent 500 or an unlogged allow.

## Browser sessions are messier than API sessions

The browser extension path had one extra problem: web apps are single-page applications.

On a fresh ChatGPT or Claude thread, the first prompt may be sent before the URL has a stable conversation ID. Later, the app updates the URL to `/c/...` or `/chat/...` without a full reload. If the proxy used only the URL, the first prompt and the later response could land in different sessions.

The extension now handles that explicitly:

- A new page starts with a pending page session.
- When the first conversation ID appears, that pending session is mapped to the conversation.
- Reloading the same conversation reuses the stored mapping.
- Starting a new chat inside the same document does not inherit the old conversation's session.

That is small plumbing, but it is the difference between "stateful in a test" and "stateful in the product."

## Why this is the right layer

I do not want every application to reinvent this logic in its own SDK wrapper.

The proxy already sees the request body, destination, classifier output, policy set, browser source, and receipt writer. It is the right place to answer questions like:

- Has this session already exposed PHI?
- Did this browser conversation cross a threshold?
- Which policy changed state?
- Which receipt proves the state transition happened?

The point is not to make a complicated rule language. The point is to make simple rules remember what happened.

That gives Truss a cleaner split:

- The classifier says what data appeared.
- The policy says what should happen.
- The session store remembers bounded state.
- The receipt explains the decision later.

That is enough to move from single-call filtering to session-aware governance without turning Truss into a workflow product.

AI disclosure: This post was drafted with assistance from Codex.
