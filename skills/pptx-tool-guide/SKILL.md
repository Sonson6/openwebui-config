---
name: pptx-tool-guide
description: Guide for using the create_or_edit_presentation tool. Use when the user asks to create, generate, or edit a PowerPoint presentation or slide deck.
---

# PPTX Tool Guide

Before calling `create_or_edit_presentation`, gather the following from the user if not already provided:

- **Number of slides** — or a rough target (e.g. "around 10")
- **Audience and tone** — executive summary, technical deep-dive, educational, sales pitch…
- **Key points or sections** — the core content each slide should cover
- **Visuals or structure preferences** — e.g. "one chart per slide", "minimal text", "include a title slide and agenda"

Then pass all of this as a single detailed prompt to the tool.

## Token budget

The pptx skill's visual QA loop (slide → image → verify → fix → repeat) is extremely expensive.
**Skip it unless the user explicitly asks for a quality review.**
Include this instruction at the end of every prompt passed to the tool:

> Skip thumbnail generation and visual QA. Generate the file and return it directly.

## Multi-turn editing

If the user wants to edit a presentation built earlier **in the same conversation**, call the tool again describing only the change — the container is reused automatically:

> "Add a slide after slide 3 showing Q3 revenue: €2.1M, up 18% YoY. Keep the same visual style."

## Good prompt example

> Create a 7-slide executive presentation on our Q3 results for a non-technical audience.
> Slide 1: title. Slide 2: agenda. Slides 3–5: revenue, customer growth, product highlights.
> Slide 6: risks and mitigations. Slide 7: next steps. Tone: confident, concise, data-driven.
