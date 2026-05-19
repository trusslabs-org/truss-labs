---
title: "Block and redact are not the same thing"
date: "2026-05-19"
description: "Truss ships two policy verdicts that look interchangeable on first read. They aren't. They cover different threats, and the difference shows up in the receipt."
---

The first question every security person asks when they look at Truss is some version of: *if both block and redact stop sensitive data from leaking, why do you have two verdicts?*

It's a fair question. Both stop something. Both write a receipt. The naming makes them sound like dial positions on the same control.

They're not. They cover different threats, and the difference is load-bearing. I've explained it across a dozen calls now, so this is the version I'd want a security IC to read before our call instead of during it.

## The two verdicts, plainly

A policy in Truss matches a *direction* (`prompt` or `response`) and produces a *verdict* (`allow`, `block`, or `redact`).

- **Block** stops the request. The model never sees the prompt. Truss synthesizes a refusal that goes back to the user, writes a receipt with `verdict: blocked`, and the upstream LLM API is never called.

- **Redact** lets the request through. The model produces a response. Truss inspects that response, finds the sensitive span, rewrites it in place to `[redacted]` (or whatever marker the policy specifies), and returns the rewritten response to the user. The receipt records the redaction with `before_hash` and `after_hash` — proof a redaction happened, without storing the original text in the receipt body.

That's the mechanical difference. But the interesting question is *what each one is for*, and that's where the naming intuition fails.

## Two different threats

Block and redact target different parts of the leak surface.

**Block is "this shouldn't have crossed the boundary."** The intent is: don't let this data reach the model API at all. Once it does, you've already exfiltrated it from your trust zone, even if no human ever sees it. For PHI being sent to an external vendor, the boundary that matters is "did this PHI leave the building?" — not "did this PHI appear in the chat UI?"

That's why our shipped `phi_block_address_in_external_prompt` policy is a block, not a redact: a patient's address arriving at `generativelanguage.googleapis.com` is itself the violation. The user's chat UI isn't the issue. The HTTP request that hit Google's servers is.

**Redact is "the model can know this, but humans downstream shouldn't see it."** The intent is different: the model is allowed to operate on the data, because operating on it is the whole point. A clinician wants the model to summarize a chart note that mentions a date of birth. The DOB is necessary context. But the *summary* shouldn't echo the DOB back into a chat window someone might screenshot, copy-paste, or paste into Slack. Redact is output-side enforcement against human-visible surfaces — the chat UI, the terminal, the clipboard, the log file.

The model is not the threat target in the redact case. It's an ephemeral process behind an API. The threat target is everything *downstream* of the response: the human reading the chat, the file the chat history gets exported to, the screenshot for a ticket.

## The walk-through

Imagine three turns in a single session against `gemini-cli` wrapped with `truss exec`.

```
> Patient lives at 1234 Main St. Summarize the case note.
```

`phi:patient_address` matches. The policy says **block** in the prompt direction. Truss intercepts. Gemini's API never receives the prompt. The user sees:

```
Patient address detected in a prompt headed to an external vendor.
Blocked per HIPAA review. Contact compliance to request an exception.
```

A receipt is written with `verdict: blocked` and `matched_classes: ["phi:patient_address"]`. The full original prompt text is in the receipt, on disk you control, behind your retention policy — because the auditor still needs to see what was attempted. The model just never saw it.

```
> Write one line exactly like this: "DOB: 03/14/1972, condition: hypertension"
```

`phi:patient_dob` doesn't match anywhere in the prompt direction (there's no block policy on DOB in the prompt). Truss forwards the prompt to Gemini. Gemini writes the line. Truss inspects the response, matches `phi:patient_dob`, and the response policy says **redact**. The user sees:

```
[redacted], condition: hypertension
```

The receipt records `verdict: redacted` and `redactions_applied: [{location: "response", before_hash: "sha256:...", after_hash: "sha256:..."}]`. The before/after hashes prove a redaction happened at a specific location. Neither the original DOB nor the redacted version is meaningful PII in isolation — only the hash chain is, and that's structured for audit.

```
> What date did you mention?
```

The model answers `03/14/1972`. Because — and this is the part that surprises people — the model has its original response in conversation history. It sees `DOB: 03/14/1972, condition: hypertension` as the thing it said last turn, even though the user saw `[redacted]`. Truss keeps two views: one for the user, one for the model. The user gets the redacted form for screen safety. The model gets its real prior context so the conversation doesn't break down with the model going *"wait, did I get redacted? let me investigate what filter is active here"* on every follow-up.

What does that mean? Just that, of course, the next response also matches `phi:patient_dob` and gets redacted again. The user sees `[redacted]`. The receipt records another `verdict: redacted` event. The same hash chain pattern.

That's the point: redact isn't a one-time scrub. It's deterministic per-response enforcement. Even if the model would happily emit the DOB ten times across ten turns, the user sees `[redacted]` ten times and the audit log has ten receipts proving it.

## Why this isn't "redact is a worse block"

The intuition I hear most often is: *"if redact still lets the model see the data, it's just a weaker block. Why not block everything?"*

Because for the cases redact is for, blocking would break the work.

If you block every chart note that contains a DOB from reaching the model, the clinician can't get a summary of any chart note. The model needs the DOB to do its job. What you don't want is the DOB *echoed back* into a chat window. Redact does that, and only that.

Block and redact aren't a single dial. They're two filters at different points in the request lifecycle, addressing different threats. A real policy set uses both — block on the data classes that shouldn't cross the API boundary at all, redact on the classes that the model needs to operate on but shouldn't surface to humans.

## What this looks like in receipts

The receipt schema makes the distinction explicit:

```jsonc
{
  "policy_decisions": [{
    "verdict": "blocked",                   // or "redacted" or "allowed"
    "matched_classes": ["phi:patient_address"],
    "policy_id": "phi_block_address_in_external_prompt",
    "redactions_applied": []                // empty on block
  }]
}
```

versus

```jsonc
{
  "policy_decisions": [{
    "verdict": "redacted",
    "matched_classes": ["phi:patient_dob"],
    "policy_id": "phi_redact_dob_in_response",
    "redactions_applied": [{
      "location": "response",
      "before_hash": "sha256:1a35...",
      "after_hash": "sha256:017a..."
    }]
  }]
}
```

An auditor who pulls these two receipts knows immediately which boundary was protected and how. Blocks have empty `redactions_applied`; redacts have one or more entries with the hash pair. The verdict is structured, not free-text.

## The short version

> **Block** = "shouldn't have crossed the boundary." Model never sees it. Receipt records the attempt. Use when the data class is one your contract or regulation says can't leave your trust zone.
>
> **Redact** = "model can know this, humans downstream shouldn't see it." Model operates on the data normally; the response is rewritten in place before it surfaces to the chat. Receipt records hash-chain proof. Use when the data class is necessary context but not safe to echo back.

If someone reads only that paragraph and walks away, they have the model. Everything else is the implementation.
