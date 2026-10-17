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

<figure style="margin: 2rem 0; border: 1px solid var(--sys-color-border); border-radius: 6px; background: #111214; padding: 1.25rem; overflow-x: auto;">
  <div style="font-size: 0.72rem; color: var(--sys-color-text-dim); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 0.85rem;">Figure 1 — Without Truss: Shared Slack thread sandbox leaks Alice's CSV to Bob</div>
  <svg viewBox="0 0 760 280" width="100%" style="min-width: 580px; display: block; font-family: 'JetBrains Mono', monospace;">
    <!-- Swimlane backgrounds -->
    <rect x="10" y="10" width="740" height="68" rx="5" fill="#18191c" stroke="#2a2d32" />
    <rect x="10" y="92" width="740" height="86" rx="5" fill="#18191c" stroke="#2a2d32" />
    <rect x="10" y="192" width="740" height="76" rx="5" fill="#18191c" stroke="#2a2d32" />

    <!-- Swimlane labels -->
    <text x="24" y="38" fill="#e0e0e0" font-size="11" font-weight="700">1. Slack Thread</text>
    <text x="24" y="54" fill="#888888" font-size="9.5">#planning</text>

    <text x="24" y="126" fill="#e0e0e0" font-size="11" font-weight="700">2. Bot Container</text>
    <text x="24" y="142" fill="#888888" font-size="9.5">10m idle TTL</text>

    <text x="24" y="224" fill="#e0e0e0" font-size="11" font-weight="700">3. Shared Disk</text>
    <text x="24" y="240" fill="#888888" font-size="9.5">/workspace</text>

    <!-- Beat 1: Alice uploads -->
    <rect x="148" y="20" width="136" height="48" rx="4" fill="#122738" stroke="#1d9bd1" />
    <text x="158" y="39" fill="#60a5fa" font-size="10" font-weight="700">Step 1 · Alice</text>
    <text x="158" y="54" fill="#d1d5db" font-size="9">Uploads q3-metrics.csv</text>

    <line x1="216" y1="68" x2="216" y2="202" stroke="#1d9bd1" stroke-width="1.5" stroke-dasharray="3,2" />
    <rect x="148" y="202" width="136" height="54" rx="4" fill="#1c2128" stroke="#3b82f6" />
    <text x="158" y="222" fill="#93c5fd" font-size="9.5" font-weight="700">q3-metrics.csv</text>
    <text x="158" y="236" fill="#9ca3af" font-size="8.5">Emails + SSNs on disk</text>
    <text x="158" y="248" fill="#f87171" font-size="8.5">No owner tag saved</text>

    <!-- Beat 2: Summary v1.pptx -->
    <rect x="300" y="106" width="132" height="56" rx="4" fill="#14291e" stroke="#4ade80" />
    <text x="310" y="126" fill="#4ade80" font-size="10" font-weight="700">Step 2 · Bot</text>
    <text x="310" y="140" fill="#d1d5db" font-size="9">Builds summary charts</text>
    <text x="310" y="153" fill="#86efac" font-size="8.5">v1.pptx (Safe, no PII)</text>
    <line x1="366" y1="106" x2="366" y2="68" stroke="#4ade80" stroke-width="1.5" />

    <!-- Beat 3: 10m TTL Reset -->
    <rect x="448" y="106" width="124" height="56" rx="4" fill="#2b2111" stroke="#fbbf24" stroke-dasharray="4,2" />
    <text x="458" y="126" fill="#fbbf24" font-size="10" font-weight="700">Step 3 · 10m Idle</text>
    <text x="458" y="140" fill="#fde68a" font-size="9">Container resets</text>
    <text x="458" y="153" fill="#d1d5db" font-size="8.5">RAM wiped; disk stays</text>

    <!-- Persistent line across disk -->
    <line x1="284" y1="229" x2="588" y2="229" stroke="#6b7280" stroke-width="1.5" stroke-dasharray="4,4" />

    <!-- Beat 4: Bob exfiltrates -->
    <rect x="588" y="20" width="150" height="48" rx="4" fill="#311520" stroke="#f87171" />
    <text x="598" y="39" fill="#f87171" font-size="10" font-weight="700">Step 4 · Bob</text>
    <text x="598" y="54" fill="#fecaca" font-size="9">"Add raw emails &amp; SSNs"</text>

    <rect x="588" y="106" width="150" height="56" rx="4" fill="#3b1219" stroke="#ef4444" />
    <text x="598" y="126" fill="#f87171" font-size="10" font-weight="700">⚠️ LEAK: v2.pptx</text>
    <text x="598" y="140" fill="#fecaca" font-size="9">Bot reads Alice's CSV</text>
    <text x="598" y="153" fill="#fca5a5" font-size="8.5">&amp; posts PII to Slack</text>

    <line x1="663" y1="202" x2="663" y2="162" stroke="#ef4444" stroke-width="1.5" />
    <line x1="663" y1="106" x2="663" y2="68" stroke="#ef4444" stroke-width="1.5" />
    <rect x="588" y="202" width="150" height="54" rx="4" fill="#1c2128" stroke="#ef4444" />
    <text x="598" y="224" fill="#fca5a5" font-size="9.5" font-weight="700">Reads q3-metrics.csv</text>
    <text x="598" y="240" fill="#9ca3af" font-size="8.5">Bot cannot tell Bob != Alice</text>
  </svg>
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

<figure style="margin: 2rem 0; border: 1px solid var(--sys-color-border); border-radius: 6px; background: #111214; padding: 1.25rem; overflow-x: auto;">
  <div style="font-size: 0.72rem; color: var(--sys-color-text-dim); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 0.85rem;">Figure 2 — With Truss: File ownership lives on disk outside the sandbox</div>
  <svg viewBox="0 0 760 250" width="100%" style="min-width: 580px; display: block; font-family: 'JetBrains Mono', monospace;">
    <!-- Top box: Ephemeral Sandbox -->
    <rect x="16" y="16" width="440" height="92" rx="6" fill="#18191c" stroke="#35373b" />
    <text x="30" y="38" fill="#e0e0e0" font-size="11" font-weight="700">Ephemeral Slack Bot Sandbox (10m TTL)</text>
    <text x="30" y="56" fill="#9ca3af" font-size="9.5">1. Alice uploads q3-metrics.csv  ──► POST /v1/sandbox/check</text>
    <text x="30" y="74" fill="#9ca3af" font-size="9.5">2. Alice builds v1.pptx (no PII) ──► POST /v1/sandbox/check</text>
    <text x="30" y="92" fill="#fca5a5" font-size="9.5">4. Bob asks for raw PII (v2.pptx)──► POST /v1/sandbox/check</text>

    <!-- Bottom box: Truss Control Plane -->
    <rect x="16" y="136" width="440" height="98" rx="6" fill="#171311" stroke="#ff9966" />
    <text x="30" y="158" fill="#ff9966" font-size="11" font-weight="700">Truss Ledger on Disk (~/.truss/ledger/sessions/)</text>
    <text x="30" y="178" fill="#e5e7eb" font-size="9.5">workspace_owner: "alice@acme.com"   (persists across 10m reset)</text>
    <text x="30" y="196" fill="#e5e7eb" font-size="9.5">staged_file:     "q3-metrics.csv"   (SSN + customer email)</text>
    <text x="30" y="214" fill="#9ca3af" font-size="9">Rule: if outgoing file has PII &amp;&amp; actor != workspace_owner ──► BLOCK</text>

    <!-- Arrows between sandbox and Truss -->
    <line x1="236" y1="108" x2="236" y2="136" stroke="#ff9966" stroke-width="2" />

    <!-- Right Verdict Cards -->
    <rect x="484" y="18" width="260" height="88" rx="6" fill="#12261a" stroke="#4ade80" />
    <text x="500" y="42" fill="#4ade80" font-size="11" font-weight="700">✅ Alice's v1.pptx: ALLOWED</text>
    <text x="500" y="62" fill="#d1d5db" font-size="9.5">Summary charts only (no raw PII)</text>
    <text x="500" y="80" fill="#86efac" font-size="9">Posted to #planning + receipt saved</text>

    <rect x="484" y="136" width="260" height="98" rx="6" fill="#321419" stroke="#f87171" />
    <text x="500" y="160" fill="#f87171" font-size="11" font-weight="700">🛑 Bob's v2.pptx: BLOCKED</text>
    <text x="500" y="180" fill="#fecaca" font-size="9.5">bob@contractor.org != alice@acme.com</text>
    <text x="500" y="198" fill="#fca5a5" font-size="9">Contains Alice's raw customer SSNs</text>
    <text x="500" y="216" fill="#e5e7eb" font-size="8.5">Signed block receipt written to disk</text>

    <line x1="456" y1="62" x2="484" y2="62" stroke="#4ade80" stroke-width="2" />
    <line x1="456" y1="185" x2="484" y2="185" stroke="#f87171" stroke-width="2" />
  </svg>
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
