---
name: design-system
description: Visual language, tokens and UI rules for this project. Use whenever building or editing any UI, component, page or style.
---

# Design direction

**The dossier, not the dashboard.** This product's job is to tell a company whether it can apply for
public money, and to prove it. Every claim carries a quoted passage, a source and a date. The
vernacular to draw from is the official document — Службен весник, numbered clauses, marginal
citations, stamped dates — not the SaaS product page.

Aesthetic: archival paper and iron-gall ink. Quiet, dense with information, generous with reading
space. Left-aligned throughout. The memorable element is **the cited passage itself**, set as a
recessed excerpt with its source line visible. Everything around it stays disciplined and plain.

Spend boldness there and nowhere else.

## Never

- Purple/blue gradients, glassmorphism, emoji in UI, Inter as the display face.
- Centred hero plus three feature cards. No card kit at all — content is separated by hairlines and
  space, never boxed into identical rounded rectangles.
- The AI-default palette: warm cream near `#F4F1EA`, clay accent near `#D97757`, acid green on
  near-black. Also banned: tinted near-black (`#0B0B0B`, `#111`) standing in for black.
- All-caps tracked-out eyebrow labels above headings. Meta strings joined with middle dots
  (`A · B · C`). `WORD — fragment` constructions. `→` appended to link or button text.
- Monospace as decoration. It is permitted **only** for identifiers a user copies or compares:
  reference codes, ЕМБС/ЕДБ, invoice numbers, character spans.
- Multi-column newspaper text. Hairlines and zero radius come from the token system below, but the
  layout stays single-column and readable.

# Tokens

Defined once in `app/web/static/css/tokens.css`. No hex values in components, ever.

## Type

    --font-display: "Source Serif 4", Georgia, serif;
    --font-body:    "Fira Sans", "Segoe UI", system-ui, sans-serif;

Both are self-hosted as subsetted woff2 — **never loaded from the Google Fonts CDN**, which would
leak every visitor's IP to a US processor and contradict the data-protection posture in
`docs/architecture.md` §8.

Chosen for this project specifically, not as house style: Source Serif 4 has genuinely designed
Cyrillic with Macedonian locale forms; Fira Sans was drawn for small screens on cheap Android
hardware, which is exactly the device the brief targets. They contrast clearly rather than harmonise.

Scale: **12 / 14 / 16 / 20 / 28 / 40 / 64**. 12 is for identifiers only. Body never below 16 —
Cyrillic needs the x-height on a phone.

Measure: **≤ 68ch**. Macedonian runs wider than English; give serif text extra line-height (1.65)
over sans (1.5).

### Cyrillic correctness is a design requirement, not a preference

- Every page sets `lang="mk"`, and type sets `font-feature-settings: "locl"`. Macedonian italic
  **бгдпт** take different forms from Russian; without `locl` they render wrong to a native reader.
- **Verify any italic Macedonian visually before shipping it.** If a face lacks the Macedonian
  locale forms, do not use italic at all — reach for weight or the recessed-excerpt treatment
  instead. Wrong letterforms read as sloppiness in exactly the market this product must be trusted in.
- Check every font subset covers **Ѓѓ Ќќ Љљ Њњ Џџ Ss Јј** before shipping it.

## Color

    --paper       #F7F6F3   page ground — cool, greyed, deliberately not cream
    --paper-sunk  #EDEBE6   recessed ground for quoted source passages
    --ink         #22201B   primary text — iron-gall, visibly warm at display sizes
    --ink-soft    #625D54   secondary text, ≥4.5:1 on paper
    --rule        #C9C4B8   hairlines and dividers — decorative separation only
    --rule-strong #8F887A   borders that DEFINE a control (inputs, selects, buttons)
    --seal        #A8321E   deadlines ONLY
    --verified    #35635A   the citation mark ONLY

Measured against `--paper`: ink 15.1:1 · ink-soft 6.1:1 · seal 6.2:1 · verified 6.3:1 ·
rule-strong 3.3:1. All pass. `--rule` is 1.6:1, which is fine for a divider and **not** fine as the
only boundary of a form control — with shadows banned, a 1px border is doing that job alone, so
controls take `--rule-strong` (WCAG 1.4.11 wants 3:1 for non-text contrast). Re-measure if you
change any value.

`--seal` means *a clock is running*. It never marks an error, a required field, or anything
decorative. `--verified` marks that a statement is backed by a citation. Two single-purpose colours;
give them no other jobs.

v1 is light-only. Tokens are structured so a dark theme is a value swap, but do not invent one
without being asked.

## Space, radius, depth

Spacing: 4px base, only **4 / 8 / 12 / 16 / 24 / 32 / 48 / 64 / 96**.
Radius: **0 and 2px only.** Shadows: **none** — separation comes from 1px borders and space.

# Rules

## The verdict system

Four verdicts, and `needs_verification` is the **default and most common** result. A red/amber/green
traffic light would therefore render the normal case as a failure. Encode verdicts by **mark and
rule weight first, hue second**, so they survive both colour-blindness and a cheap phone screen:

| Verdict | Treatment |
|---|---|
| Eligible | solid rule, filled marker |
| Likely eligible | solid rule, hollow marker |
| Needs verification | dashed rule, hollow marker — **neutral, never a warning colour** |
| Not eligible | muted ink, struck rule |

## Every screen showing a call

- States `last_verified_at` in `dd.mm.yyyy`. No exceptions — this is a promise in the brief, §12.
- Every eligibility statement is clickable through to its cited passage. No citation, no claim.
- Deadlines carry `--seal`. Under 14 days also says how many days remain, in words.

## Interaction

- Every interactive element needs **hover, focus-visible, active, disabled and loading**. Focus is
  visible and never removed.
- Motion answers a user action only — opening, expanding, confirming. No scattered scroll reveals,
  no entrance animations on sections. Respect `prefers-reduced-motion`.
- HTMX swaps show a loading state on the element that was actioned, not a page-level spinner.

## Copy

- Sentence case. Active voice. A button names what happens: "Побарај извештај", not "Испрати".
- Use the vocabulary of the actual calls — јавен повик, барател, прифатливи трошоци — not invented
  product jargon. Users match our words against the official document in front of them.
- **Banned from all output**: гарантирано, "guaranteed", "approved", "you will receive". Enforced by
  lint; assume the lint is right.
- Dates `dd.mm.yyyy`. Currency МКД and EUR. Never USD, never `mm/dd`.
- Empty states say what to do next. Errors say what happened and how to fix it, and never apologise.
- No dark patterns in the upgrade path. The free shortlist shows the full top 10 with reasons —
  never blurred, never truncated to manufacture pressure.

## Performance budget

Target a mid-range Android on mobile data. Fonts subsetted and preloaded; no webfont over 40KB.
No JavaScript beyond HTMX unless it earns its place. The shortlist renders in under 3s on the VPS.

## Before saying done

Verify with the chrome-devtools MCP at **375 / 768 / 1440**. Check: no horizontal scroll at 375,
focus visible on every control, Cyrillic renders with correct letterforms, and the verdict treatments
are distinguishable in greyscale.
