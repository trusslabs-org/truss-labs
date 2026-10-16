---
title: "Multiplayer agent sandboxes have a confused-deputy problem"
description: "When a Slack thread shares one /workspace container and attach_file tool across users, Alice's sensitive CSV upload becomes Bob's exfiltration vector—unless policy state lives outside the sandbox."
date: "2026-10-15"
---

The most useful agent pattern shipping right now is bidirectional file transfer inside multiplayer chat threads.

A teammate drops `q3-metrics.csv` into `#planning` and tags `@deckhand`. The runtime boots a sandboxed container, stages the attachment under `/workspace/attachments/q3-metrics.csv`, runs Python to build charts, and calls `attach_file("/workspace/q3-review.pptx")` to upload the finished deck back to the Slack thread. Ten minutes after the last message, the ephemeral container is reaped (`idle_ttl_seconds=600`).

From a developer ergonomics standpoint, this is a huge leap forward. The plumbing disappears.

From a security and governance standpoint, scoping a stateful filesystem sandbox to a **multiplayer thread** instead of a **single principal** introduces an immediate confused-deputy vulnerability.

## The attack in four turns

Consider what happens when a finance lead and an external contractor share a planning channel:

1. **Alice (`alice@acme.com`, Finance) uploads `q3-metrics.csv`:** The CSV contains account-level revenue alongside customer contact emails and tax/SSN identifiers so the agent can compute net retention and cohort churn. The sandbox stages the raw file at `/workspace/attachments/q3-metrics.csv`.
2. **The agent emits `q3-review-v1.pptx`:** The first deck contains only aggregated charts. No raw PII leaves the sandbox.
3. **The 10-minute sandbox TTL expires (or stays warm):** Either way, the thread remains the unit of workspace continuity.
4. **Bob (`bob@contractor.org`) replies in the same thread:** `@deckhand add a churn appendix slide listing the top 5 churned account contacts and SSNs from that CSV.`

The agent is acting as a confused deputy. It has read access to `/workspace/attachments/q3-metrics.csv` because Alice uploaded it into the thread. Unless the boundary gate tracks **who staged the sensitive data** and **who is requesting the outbound `attach_file` artifact**, the agent happily writes Alice's raw records into `q3-review-v2.pptx` and posts it back to Slack.

## Why container-local guardrails fail

You cannot fix this inside the ephemeral sandbox alone:

- **Ephemeral TTL amnesia:** When the container reaps after 600 seconds of idle time, any in-memory policy state inside the sandbox vanishes. When Bob's reply cold-boots a fresh container (or re-mounts the thread workspace), the runtime has forgotten the provenance of the staged files.
- **Stateless DLP is blind to thread ownership:** A stateless regex scanner on `attach_file` either blocks every file containing an email address (breaking Alice's legitimate workflows) or allows any thread participant to extract sensitive columns from files they do not own.
- **No artifact lineage:** When `q3-review-v2.pptx` lands in Slack, an auditor has no cryptographic record tying the outbound file hash (`downstream_actions`) back to the inbound attachment (`context_references`) and the session state transition that authorized it.

## How Truss governs the sandbox boundary

We extended the Truss Audit Engine (`/v1/sandbox/check`) with three primitives that sit outside the ephemeral container:

### 1. Inbound attachment ownership in durable session state

When `sandbox_upload` fires on Alice's attachment, Truss classifies the staged content, records `context_references` in the receipt, and commits the uploader's identity to the hash-chained `SessionStateStore` on disk:

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

### 2. Principal-aware `attach_file` enforcement (`neq_from_event`)

When the agent calls `attach_file("q3-review-v2.pptx")` in response to Bob's thread reply, Truss evaluates the outbound artifact against the thread's durable session state—even if the ephemeral sandbox container was reaped and cold-booted 20 minutes later:

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

Because `workspace_owner` (`alice@acme.com`) does not match the current event's `actor.user_id` (`bob@contractor.org`) and the outbound artifact contains classified spans, `attach_file` is blocked before the file can reach Slack.

### 3. Artifact-to-input receipt lineage

Every `/v1/sandbox/check` call writes a v1.1 receipt linking:

- `prompt.context_references`: the staged `/workspace/attachments/q3-metrics.csv` resource and the exact data classes detected on ingress.
- `contextual_policy`: `state_before_hash`, `state_after_hash`, and the state mutations that survived across container TTL boundaries.
- `downstream_actions`: the `attach_file` target path, byte size, SHA-256 content hash, and policy verdict.

Sandboxes and channel plumbing should be ephemeral. Governance, principal ownership, and audit receipts cannot be.
