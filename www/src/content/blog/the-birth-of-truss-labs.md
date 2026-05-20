---
title: "The birth of Truss Labs"
description: "Notes on incorporating, picking a C-Corp, and why I'm working on the infrastructure under agents instead of another agent product."
date: "2026-04-17"
---

Yesterday I filed the paperwork for **Truss Labs Inc.** in New York. This is a note on what I'm actually working on and why I structured it this way, written mostly for myself and anyone following along.

## What I'm building

Short version: the plumbing under AI agents, not the agents themselves.

Current agent products mostly run inside a linear chat box. The model reasons, calls a tool, gets a response, and moves on. If it drifts or loops, you usually can't tell until after the fact, and you can't intervene mid-run without restarting. The logs — when they exist — aren't structured enough to replay or diff against.

I don't think the fix is a bigger model. The fix is better scaffolding: durable state, structured traces you can query, and a UI that lets a human steer a run while it's happening.

That's the scope of Truss Labs for the next year or so.

## Why a NY C-Corp, and why now

I picked a New York C-Corp for clean legal separation and because it's the default structure if there's any chance of raising later. It's not the cheapest to maintain and it's not the most tax-efficient for a pre-revenue solo founder — but it's the least friction if the project starts mattering to other people.

I also incorporated *before* writing much public code, which is probably earlier than strictly necessary. The reason is specific: I wanted the IP ownership clean from day one, so there's no ambiguity between "side project I did before forming the company" and "work that belongs to the company."

- Email: ilteris@trusslabs.org
- Cloud: Google Workspace, own-domain DNS

No outside capital. Runway is personal for the first couple of years.

## What's actually built so far

Honestly, not much that's public yet. What exists internally:

1. **Truss Kernel** — a local shell harness that keeps agent state (sessions, tasks, traces) on disk in a format I can query with ordinary tools. Not a framework; more like a filesystem convention plus a few CLIs.
2. **TWP (Truss Wire Protocol)** — a thin layer on top of Anthropic's [Model Context Protocol](https://modelcontextprotocol.io/) that adds branching and checkpointing. This is the piece I'm least sure about and most likely to rewrite.
3. **Primitives** — `truss trace analyze`, `truss trap`, `truss ingest`. Small CLI tools. `truss trap` halts a run when confidence drops below a threshold; `truss trace analyze` reads traces; `truss ingest` loads context.

The Trace-Tree UI — a way to see a run as a tree you can branch and inspect — is sketched but not built.

## What'm unsure about

A few things I don't have good answers to yet:

- Whether TWP should exist at all, or whether MCP plus conventions is enough.
- Whether the Truss Kernel should be a library, a daemon, or stay as a shell harness.
- Who the first real users are. Right now it's just me.

I'd rather write about those openly than pretend the roadmap is settled.

## Building in public

I'll post here as things move. If you're working on similar problems — agent state, trace tooling, or anything in the interface layer above MCP — I'm reachable at ilteris@trusslabs.org.
