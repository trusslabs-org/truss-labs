# Truss Design Principles

Truss should feel like infrastructure, not a marketing site wrapped around a demo. The product promise is model-boundary governance: inspect what crosses the boundary, enforce a policy, and leave receipts that an operator can verify. The visual system should make that promise legible before the user reads a paragraph.

## Brand Voice To Visual Language

Truss speaks in the voice of an audit tool: exact, calm, operational, and accountable. It should avoid spectacle because the buyer is evaluating whether this system can sit between sensitive work and third-party models without becoming another liability.

The visual language follows that posture:

- Dense, scan-friendly surfaces over oversized editorial sections.
- Monospace typography where the object is operational state, policy, receipt data, or command output.
- Dark default surfaces to signal terminal-native infrastructure work.
- Coral accent for warmth and direction without turning the interface into a warning system.
- Small-radius panels, explicit borders, and visible dividers where state needs boundaries.
- Status colors reserved for verdicts and operational outcomes, not decoration.

The homepage, sandbox, standalone demo, extension popup, and future artifacts should all look like parts of one system: a quiet control plane for AI traffic.

## Token Model

The canonical token source is `www/src/styles/tokens.css`. It uses a two-layer taxonomy:

- `--ref-*` tokens are raw values: palette colors, outline values, and font families.
- `--sys-*` tokens are semantic product roles: background, surface, text, accent, status, and form states.

Surfaces should consume `--sys-*` tokens. New raw values should only be added to `--ref-*` when the current palette cannot express a real product need. This keeps implementation details out of page-level styling and makes future theme changes possible without rewriting components.

Examples:

- Use `--sys-color-text-dim` for captions, metadata, helper text, and quiet explanatory copy.
- Use `--sys-color-surface` for panels and tool regions.
- Use `--sys-color-outline` or `--sys-color-outline-strong` for separators, inputs, and focusable boundaries.
- Use `--sys-color-status-allowed`, `--sys-color-status-redacted`, and `--sys-color-status-blocked` only when displaying policy outcomes.

## Why Monospace

Truss is anchored in receipts, policies, ledgers, command output, and traffic metadata. Monospace typography makes those objects feel inspectable. It also matches the buyer's operational context: security engineers, platform teams, and technical founders who already trust terminal-native tools.

This does not mean every layout should look like a raw terminal. It means the system should preserve the audit aesthetic: aligned values, readable hashes, compact state labels, and code-adjacent controls.

## Why Dark And Coral

The default dark theme communicates seriousness and reduces the gap between the website, CLI demos, popup ledger, and local developer workflows. It also keeps screenshots and screencasts visually coherent when they include terminals, browsers, and receipt data.

Coral is the primary brand accent because it adds warmth to a serious surface without using the common enterprise-blue palette. It should identify links, active states, key boundaries, and primary actions. It should not dominate the page.

The paper-light theme is reserved for documentation and long-form reading. It is an opt-in content mode, not a second brand.

## What The System Rules Out

Truss should not use visual patterns that imply a generic AI product or a speculative future-state pitch. Avoid:

- Marketing gradients as primary structure.
- Stock illustrations, decorative blobs, and abstract AI imagery.
- Lottie-style flourish where a state transition or receipt would be clearer.
- Large rounded cards nested inside other cards.
- One-off colors or per-surface themes that bypass the token file.
- Status colors used as brand decoration.
- Copy that explains the UI instead of exposing the operational object itself.

When in doubt, show the artifact: the prompt boundary, policy rule, verdict, receipt path, hash, or ledger event. Truss earns trust by making the control surface visible.
