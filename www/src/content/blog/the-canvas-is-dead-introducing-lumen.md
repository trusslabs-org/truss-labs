---
title: "LUMEN: a relational prototype for UI generation"
date: "2026-04-20"
description: "A speculative prototype I built to test whether you can describe UI by intent and relationships instead of pixel coordinates."
---

LUMEN is a speculative prototype I built to test one question: can you describe a UI by intent and relationships between pieces, and let the machine handle the pixel coordinates?

The tools I use daily (Figma, Sketch, Framer) are spatial. You move things by X/Y, tweak border radius, pick hex codes. That made sense when a human had to draw every screen. Now that a model can fill in the pixels, the bottleneck is somewhere else — describing what the interface *is for*, not where each element sits.

## The thesis

Most product design is assembly. You have a problem, you pick a solution shape, you build it from components that already exist. If you can express the requirements precisely enough, you don't need to draw the result. You curate from generated variations.

Concretely:

- Old way: drag a slider to change border radius from 4px to 8px.
- LUMEN way: tell the system "make this feel more organic," see five variations, pick one.

## How it works

LUMEN replaces coordinates with two concepts: *emphasis* (how important is this piece) and *gravity* (how does this piece relate to that one).

```json
{
  "elements": [
    { "id": "alert", "role": "status", "emphasis": "critical" },
    { "id": "logs", "role": "metadata", "emphasis": "low" }
  ],
  "gravity": [
    { "source": "alert", "target": "logs", "type": "ancillary", "force": 0.3 }
  ]
}
```

The engine takes that intent and projects it through a design language — a set of rules that turns the abstract graph into CSS.

## Multi-language projection

Because the intent is decoupled from the rendering, I can re-skin the same screen by swapping the projection layer. In the first run I projected the same intent through three lenses:

1. Brutalist — hard edges, heavy shadows.
2. Glass — translucency, blur.
3. Minimal — editorial, lots of whitespace.

Same input graph, three different outputs.

## What I'm unsure about

A few things I haven't figured out:

- Whether "gravity" is the right primitive, or whether it's just a fancy name for parent/child relationships.
- How LUMEN handles dense interfaces (dashboards, tables) where relationships aren't really the point.
- Whether the projection layer is just a styled component library with extra steps.

LUMEN is a sketch, not a product. I built it to see what falls out when you stop drawing and start describing. The thing I want to keep working on is the bridge between this kind of intent description and the audit/policy work in the rest of Truss Labs — there's a shared idea about structured artifacts being easier to govern than freeform output.

If you're working on something similar, I'm at ilteris@trusslabs.org.
