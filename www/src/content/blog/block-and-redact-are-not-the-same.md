---
title: "Block and redact are not the same thing"
description: "Most LLM security tools conflate blocking and redacting. In a multi-turn agent session, confusing the two breaks both model reasoning and the legal audit trail."
date: "2026-05-15"
---

Most security products that sit in front of AI models have one big button: *redact*. 

If they see a Social Security number, a credit card, or a date of birth, they replace it with `[REDACTED_SSN]` or some other neutral placeholder in the prompt, send it to the model, and hope the model doesn't notice.

If you are building a simple search box, that works. If you are building a multi-turn agent, **it breaks everything.** 

Here's why blocking and redacting are structurally different, and why confusing the two ruins both model reasoning and the legal audit trail.

## The mechanical difference

*   **Block** is binary. The call is aborted before it reaches the model. The model receives nothing; the user gets a local refusal.
*   **Redact** is inline. The data is altered before it's displayed or sent. The model operates on one version, while a downstream human or log gets a different version.

That's the mechanical difference. But the interesting question is *what each one is for*, and that's where the naming intuition fails.

## Two different threats

Block and redact target different parts of the leak surface.

**Block is "this shouldn't have crossed the boundary."** The intent is: don't let this data reach the model API at all. Once it does, you've already exfiltrated it from your trust zone, even if no human ever sees it. For PHI being sent to an external vendor, the boundary that matters is "did this PHI leave the building?" — not "did this PHI appear in the chat UI?"

That's why our shipped `phi_block_address_in_external_prompt` policy is a block, not a redact: a patient's address arriving at `generativelanguage.googleapis.com` is itself the violation. The user's chat UI isn't the issue. The HTTP request that hit Google's servers is.

**Redact is "the model can know this, but humans downstream shouldn't see it."** The intent is different: the model is allowed to operate on the data, because operating on it is the whole point. A clinician wants the model to summarize a chart note that mentions a date of birth. The DOB is necessary context. But the *summary* shouldn't echo the DOB back into a chat window someone might screenshot, copy-paste, or paste into Slack. Redact is output-side enforcement against human-visible surfaces — the chat UI, the terminal, the clipboard, the log file.

The model is not the threat target in the redact case. It's an ephemeral process behind an API. The threat target is everything *downstream* of the response: the human reading the chat, the file the chat history gets exported to, the screenshot for a ticket.

## The walk-through

Imagine three turns in a single session against `gemini-cli` wrapped with `truss proxy exec`.

```
> Patient lives at 1234 Main St. Summarize the case note.
```

`phi:patient_address` matches. The policy says **block** in the prompt direction. Truss intercepts. Gemini's API never receives the prompt. The user sees:

```
Patient address detected in a prompt headed to an external vendor.
Blocked per HIPAA review. Contact compliance to request an exception.
```

A receipt is written with `verdict: blocked` and `matched_classes: ["phi:patient_address"]`. The full original prompt text is in the receipt, on disk you control, behind your retention policy — because the auditor still needs to see what was attempted. The model just never saw it.

Now, a separate turn:

```
> Patient has a DOB of 04/12/1978. Please write their summary.
```

The prompt doesn't match the address block. The prompt flows upstream. Gemini processes it, reasons over it, and returns:

```
SUMMARY: Patient is a 48-year-old male born April 12, 1978.
```

Truss intercepts the *response*. `phi:patient_dob` matches. The policy says **redact** in the response direction. Truss rewrites the response text:

```
SUMMARY: Patient is a 48-year-old male born [REDACTED_DOB].
```

This is what the user sees in their terminal or chat window. The DOB was processed by the model, but it is not exfiltrated onto the human-visible screen.

## The multi-turn swap problem

This is where standard redaction proxies break. 

On the very next turn, the user's CLI (or SDK) sends the *entire session history* back to the model, including the model's own prior response:

```
> Yes, and does that born [REDACTED_DOB] match the intake chart?
```

If you send that literal text back to Gemini, **Gemini's reasoning breaks.** It looks at `born [REDACTED_DOB]` and has no idea what DOB the user is talking about, even though it originally wrote it. The model gets confused, starts hallucinating, or asks the user to re-provide the date.

To solve this, Truss runs a stateful **swap table**. 

Every time Truss redacts a response, it stores a temporary local hash of the redacted value pointing to the original:

`sha256:5ef2...09e` → `April 12, 1978`

On the next turn, before forwarding the prompt history to the provider, Truss walks the prior assistant turns in the request body and swaps the original value *back* into the prompt. 

The upstream model sees an unbroken, coherent view of its own outputs:

```
> Yes, and does that born April 12, 1978 match the intake chart?
```

While the user's local terminal and logs remain completely clean:

```
> Yes, and does that born [REDACTED_DOB] match the intake chart?
```

## Alignment over mechanics

This is why Truss is a separate governance substrate and not just a regex filter in your SDK. 

To govern agents, the proxy must understand the protocol (Gemini/Claude API structures) and hold state across turns to protect the model's reasoning while guaranteeing the security boundary.

When you conflate blocking and redacting, you either leak data to the model's server unnecessarily, or you break the agent's ability to reason over long sessions. You need to do both, and you need to know exactly which one you are doing.
