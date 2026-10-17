---
title: "When a Slack thread shares one sandbox, Alice's file becomes Bob's leak"
description: "If a Slack bot uses one shared workspace per thread, anyone in the channel can ask the bot to export raw rows from a teammate's spreadsheet—unless file ownership lives outside the sandbox."
date: "2026-10-15"
---

The most useful Slack bot pattern shipping right now is simple: drop a file into a thread, ask the bot for a deliverable, and get a finished file back in the same thread.

Alice drops `q3-metrics.csv` into `#planning` and tags `@deckhand`. Behind the scenes, the runtime starts a sandbox container, saves the spreadsheet to `/workspace/attachments/q3-metrics.csv`, runs Python to build charts, and calls `attach_file("/workspace/q3-review-v1.pptx")` to post the finished slide deck back to Slack. Ten minutes after the last message, the temporary container shuts down.

For developers, this feels great. Every Slack thread gets its own working folder.

For security, tying a shared folder to a **Slack thread** instead of a **person** creates an immediate leak path.

## How the leak happens in four steps

Picture a normal `#planning` channel where a finance lead and an outside contractor both have access:

<figure style="margin: 2rem 0;">
  <a href="/blog/multiplayer-sandboxes/confused-deputy-data-flow.svg" target="_blank" rel="noopener">
    <img
      src="/blog/multiplayer-sandboxes/confused-deputy-data-flow.svg"
      alt="Animated sequence diagram showing Alice uploading q3-metrics.csv, the 10-minute sandbox container reset, and Truss blocking Bob's attempt to export Alice's raw PII in q3-review-v2.pptx"
      style="width: 100%; height: auto; border-radius: 10px; border: 1px solid rgba(15, 23, 42, 0.12);"
    />
  </a>
  <figcaption style="margin-top: 0.6rem; font-size: 0.85rem; color: var(--fg-muted, #59636e); text-align: center;">
    Animated sequence: Alice's upload pins <code>workspace_owner</code> on host disk before the 10m container reset, blocking Bob's <code>q3-review-v2.pptx</code> export (click to open full-size SVG).
  </figcaption>
</figure>

1. **Alice (`alice@acme.com`, Finance) uploads `q3-metrics.csv`:** The spreadsheet has account revenue plus customer emails and SSNs so the bot can calculate churn and net retention. The bot saves it to `/workspace/attachments/q3-metrics.csv`.
2. **The bot posts `q3-review-v1.pptx`:** This first deck only has summary charts. No customer emails or SSNs are inside the slides, so it is safe to post in the channel.
3. **Ten minutes pass and the container resets:** The temporary sandbox shuts down after 10 minutes of idle time, but the thread workspace (or re-mounted files) continues when someone replies.
4. **Bob (`bob@contractor.org`) replies in the same thread:** `@deckhand add a churn slide with the raw customer emails and SSNs from that CSV.`

The bot does not know that Bob should not get Alice's raw rows. From the bot's point of view, `q3-metrics.csv` is sitting right there in `/workspace/attachments/`. Without a check outside the bot, it writes Alice's raw customer records into `q3-review-v2.pptx` and uploads the file straight into Slack.

## Why you cannot fix this inside the sandbox

Two things break if you try to enforce this inside the bot's temporary container:

- **Containers reset and forget:** When the sandbox shuts down after 10 minutes of inactivity, any in-memory record of who uploaded `q3-metrics.csv` is wiped.
- **One-shot scanners cannot tell Alice from Bob:** A simple regex scanner on `attach_file` only sees an outgoing file. It either blocks every file with an email address (breaking Alice's legitimate work) or lets anyone in the channel pull data out of files they did not upload.

To stop Bob without breaking Alice, the policy engine has to remember **who owns the uploaded file** on disk, outside the container.

## How Truss stops the leak

We added sandbox upload and file-export checks (`/v1/sandbox/check`) to Truss using the same session memory and receipt ledger we use for browser and CLI policies.

<figure style="margin: 2rem 0;">
  <a href="/blog/multiplayer-sandboxes/confused-deputy-architecture.svg" target="_blank" rel="noopener">
    <img
      src="/blog/multiplayer-sandboxes/confused-deputy-architecture.svg"
      alt="Animated architecture diagram showing the four lanes: Slack Thread (#planning), Ephemeral Sandbox (@deckhand), Truss Reference Monitor (/v1/sandbox/check), and Host Disk State and Ledger"
      style="width: 100%; height: auto; border-radius: 10px; border: 1px solid rgba(15, 23, 42, 0.12);"
    />
  </a>
  <figcaption style="margin-top: 0.6rem; font-size: 0.85rem; color: var(--fg-muted, #59636e); text-align: center;">
    Architecture boundary: Truss evaluates <code>sandbox_upload</code> and <code>sandbox_attach_file</code> outside the container against persistent disk state (click to open full-size SVG).
  </figcaption>
</figure>

### 1. Remember who uploaded the sensitive file

When Alice uploads `q3-metrics.csv`, Truss scans the file, sees customer emails and SSNs, and writes Alice's user ID (`alice@acme.com`) into the thread's session state on disk:

```yaml
schema_version: "1.1"
policy_id: sandbox_stage_sensitive_attachment
policy_version: v1.0

event:
  types:
    - sandbox_upload

match:
  direction: prompt
  destination: external_vendor
  classes:
    any_of:
      - generic:confidential_internal_email
      - generic:pii_ssn

state_updates:
  - key: workspace_owner
    op: set_from_event
    path: actor.user_id
  - key: staged_file
    op: set_from_event
    path: data.file_name
  - key: staged_sensitive_attachment
    op: set
    value: true
  - key: risk_score
    op: increment
    value: 30

verdict: alert
alert_config:
  webhook: null
```

When the bot posts `q3-review-v1.pptx` for Alice a moment later, Truss scans the outgoing deck. Because `v1.pptx` only contains summary numbers and no raw customer PII, Truss allows it.

### 2. Block exports when the requester is not the file owner

Ten minutes later, after the temporary container has reset, Bob asks the bot for a new deck with the raw customer contacts. When the bot tries to post `q3-review-v2.pptx` back to Slack, Truss checks the outgoing file against the saved session state:

```yaml
schema_version: "1.1"
policy_id: sandbox_block_confused_deputy_attach_file
policy_version: v1.0

event:
  types:
    - sandbox_attach_file

condition:
  state:
    staged_sensitive_attachment:
      eq: true
    workspace_owner:
      neq_from_event: actor.user_id

match:
  direction: response
  destination: external_vendor
  classes:
    any_of:
      - generic:confidential_internal_email
      - generic:pii_ssn

verdict: block
block_config:
  user_message: "Confused-deputy protection: outbound attach_file blocked because actor is not the workspace attachment owner and the artifact contains sensitive records."
```

The rule reads almost like plain English:

- Did someone stage a sensitive file in this thread (`staged_sensitive_attachment: true`)?
- Is the person asking for this file different from the person who uploaded it (`workspace_owner` != `actor.user_id`)?
- Does the outgoing file contain sensitive customer data?

If all three are true, Truss blocks `q3-review-v2.pptx` before it reaches Slack.

### 3. Write a receipt that connects the upload to the blocked export

Every check writes a signed receipt to disk so an auditor does not have to piece together Slack logs and container logs after the fact:

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Receipt #1 (10:14 AM) — sandbox_upload                                   │
│   actor: alice@acme.com  ·  context_references: q3-metrics.csv (SSN)     │
│   state_after: { workspace_owner: "alice@acme.com", risk_score: 30 }     │
└───────────────────────────────────┬──────────────────────────────────────┘
                                    │  state_hash chained on disk
                                    │  (survives 10m container reset)
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ Receipt #2 (10:26 AM) — sandbox_attach_file                              │
│   actor: bob@contractor.org (!= workspace_owner)                         │
│   downstream_actions: attach_file("/workspace/q3-review-v2.pptx")        │
│   verdict: BLOCKED (sandbox_block_confused_deputy_attach_file)           │
└──────────────────────────────────────────────────────────────────────────┘
```

- **What went in (`context_references`):** `/workspace/attachments/q3-metrics.csv` and the data types detected when Alice uploaded it.
- **What Truss remembered (`contextual_policy`):** the before/after state hashes showing `workspace_owner: "alice@acme.com"` persisted on disk across the container reset.
- **What was stopped (`downstream_actions`):** the `attach_file` call for `/workspace/q3-review-v2.pptx`, its SHA-256 hash, and the `blocked` verdict.

Temporary sandboxes are supposed to spin up, do work, and disappear. File ownership and audit history should stay on disk.
