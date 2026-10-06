---
name: design-system
description: Visual language, tokens and UI rules for this project. Use whenever building or editing any UI, component, page or style.
---

# Design direction

**An iOS app, on the web** (DL1, 02.10.2026; the why is `docs/design-language.md`). This product
tells a small business whether it can apply for public money, and proves it. It should feel like
the phone in their hand: large bold titles, inset grouped lists on a soft ground, one blue for
everything you can press, navigation floating on frosted glass, dark mode following the phone.
Familiar is the point.

The memorable element is still **the cited passage**: every claim carries a quoted passage, a
source and a date, and that is where visual boldness goes. Everything around it stays calm.

## Never

- **Glass in the content layer.** Glass (`.glass`) is for the floating navigation layer only:
  the navigation bar, the phone's tab bar, a floating primary action, a sheet. Never under a call,
  a condition, a quote, a form or the report. At most a few glass layers per screen; never animate
  the blur. (Apple's HIG: "use sparingly", "not in the content layer".)
- Text on glass that must be read for a decision.
- Purple/blue gradients as decoration, emoji in UI, rainbow accents. One tint, used for action.
- The AI-default palettes: cream with terracotta, near-black with acid green. Also: uniform
  rounded SaaS cards with gradient decoration and drop shadows on everything.
- All-caps tracked-out eyebrow labels. Meta strings joined with middle dots (`A · B · C`).
  `WORD — fragment` constructions. `→` appended to link or button text.
- Monospace as decoration. **Only** for identifiers a user copies or compares: reference codes,
  ЕМБС/ЕДБ, invoice numbers, character spans.
- Italic. Neither Inter nor SF has Macedonian italic forms; emphasis is weight.

# Tokens

Defined once in `app/web/static/css/tokens.css`, light in `:root` and dark in the block after it.
No colour value in components, ever. `/stil` renders every token in both themes
(`?tema=svetla`, `?tema=temna`); look there before adding one.

## Type

    --font-text / --font-display: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", …

Apple devices render their own SF and download nothing; everyone else gets **Inter**, self-hosted
as subsetted woff2 (`ops/dev/cut_fonts.py`), **never from a font CDN** (no visitor IP to a US
processor, `docs/architecture.md` §8). Weights: 400 text, 600 headlines and controls, 700 large
titles. Paper names its face exactly, `--font-print: "Inter"`, the same files merged per weight
by `app/reports/render.py` (DL5).

The iOS text styles: **caption 12** (identifiers only), **footnote 13** (labels), **subhead 15**
(secondary sentences; nothing a reader must read is smaller), **body 17**, **title3 20**, **title2
22**, **title1 28**, **large 34**, **display 48** (the landing hero only). Large type draws tighter
(`--tracking-title`). Measure ≤ 68ch.

### Cyrillic correctness is a design requirement, not a preference

- Every page sets `lang="mk"`, and type sets `font-feature-settings: "locl"`.
- Check every font subset covers **Ѓѓ Ќќ Љљ Њњ Џџ Ѕѕ Јј** before shipping it (a test does).
- No italic, no synthesised bold or oblique (`font-synthesis: none`).

## Color

Light / dark, iOS's system colours deepened where iOS's own fail WCAG for small web text:

    --bg               #F2F2F7 / #000000   page ground (grouped background)
    --surface          #FFFFFF / #1C1C1E   content: lists, cards, fields
    --fill             #EFEFF4 / #2C2C2E   recessed: a quoted passage, a disabled control
    --label            #1D1D1F / #F5F5F7   primary text
    --label-2          #56565C / #AEAEB2   secondary sentences
    --label-3          #636368 / #98989D   labels, helper text
    --separator        #C6C6C8 / #38383A   dividers only, never a control's only edge
    --separator-strong #8A8A8E / #7C7C80   the edge that defines a control (≥ 3:1)
    --tint             #0A5BD3 / #4D9BFF   action and selection: links, buttons, focus
    --tint-strong      #0A5BD3 / #1E6FE6   the filled button's ground (white on it ≥ 4.5:1)
    --deadline         #C8341A / #FF7A66   deadlines ONLY: a clock is running
    --verified         #1F7A3A / #3DCC6E   the citation mark ONLY

Every pair is measured from the values in both themes (`app/web/style.pairs`, on `/stil`, and a
test). Trust that over this list. `--deadline` never marks an error or a required field;
`--verified` marks that a statement is backed by a citation. Errors are weight and a heavy rule,
not red.

## Shape, depth, material, motion

Spacing: 4px base, only **4 / 8 / 12 / 16 / 24 / 32 / 48 / 64 / 96**.
Radius: **8 / 12 / 20 / 28 and pill**; concentric (an inner radius is the outer minus the padding).
Depth: `--shadow-1` lifts a surface off the ground; `--shadow-2` is under glass. Nothing else.
Glass: `.glass` (solid → frosted where supported → solid under `prefers-reduced-transparency`),
with its 1px edge kept for forced-colours mode.
Motion: `--ease-out`, `--ease-spring`, `--dur-1` 160ms, `--dur-2` 280ms; it answers an action and
stops under `prefers-reduced-motion`.

# Rules

## The verdict system

Four verdicts, and `needs_verification` is the **default and most common** result. A red/amber/green
traffic light would therefore render the normal case as a failure. Encode verdicts by **mark and
rule weight first, hue second**, so they survive both colour-blindness and a cheap phone screen:

| Verdict | Symbol (screen, `--sym-*`) | Paper (WeasyPrint has no masks) |
|---|---|---|
| Eligible | filled disc with a check cut out | filled disc |
| Likely eligible | whole ring with a check | hollow ring |
| Needs verification | broken ring with a question — **neutral, never a warning colour** | dashed ring |
| Not eligible | ring struck through, muted | ring struck through |

The symbol alone must tell the verdict (legends, the admin and the PDF show it without its
label or card). Check on `/stil?siv=1` in both themes.

## Components

Draw from `app/web/templates/_components.html`, never by copying markup: verdict, deadline, date,
amount, excerpt, submit, empty, error summary, **segmented**, **group** (DL2). A new variant is a
parameter there and a row on `/stil`, in both themes.

- **Navigation bar**: `site-header glass glass--bar`, sticky. On phones its sections move to the
  **tab bar**, a floating glass capsule at the bottom (`has-tab-bar` on `body`). The current
  section sits on a solid lens (`--surface`), so its tint never depends on what is under the glass.
- **Buttons**: capsules in iOS's four styles. `.btn` filled (the one action a screen is for),
  `--quiet` tinted (the others), `--gray` (the neutral way out), `--plain` (an action that reads
  as a link). `--destructive` stays an underlined text button, apart from «Зачувај» (F34).
- **Cards**: a call is a `.call` card on the grouped ground. Lists of settings-like rows are
  `c.group(...)`: inset hairlines, a footnote header, an explanation under it. Every card is one
  recipe, the `.surface` rule in `site.css`: add a new card's class to that selector rather than
  writing the background, radius and shadow again. A page of cards is `.wrap.grouped`: its
  sections are spaced, not ruled (DL4); with `.grouped--cards` each section is itself a card,
  and a card inside it is recessed in `--fill`, never lifted twice (DL6).
- **Rows**: `ul.rows` is an inset grouped list. A row that leads somewhere puts `.rows__link` on
  its title: the link covers the row and the chevron is drawn. One link per row.
- **Back**: `a.back` is iOS's back button, a drawn chevron and the way back in the tint. It
  returns to the place the reader left (`#call-<id>`), not the top of the list.
- **Disclosure**: iOS's chevron, turning on a spring. **Segmented control**: radio inputs under
  `c.segmented(...)`, so it posts without script. **Sheet**: `dialog.sheet.glass`.
- **The cited excerpt** stays the bold element: a recessed rounded block, the quote larger, a
  green bar and the citation seal (`--sym-cite`). Our own text is `own=true`, never green.
- A passed deadline is `--label`, not `--deadline`. Submit buttons get their busy state from
  `app/web/static/js/submit.js` (`data-busy` says what is happening).
- **Glass appears only where `tests/test_components.py` lists it** (the bars, a sheet). Adding it
  anywhere else fails that test on purpose.

## Every screen showing a call

- States `last_verified_at` in `dd.mm.yyyy`. No exceptions — this is a promise in the brief, §12.
- Every eligibility statement is clickable through to its cited passage. No citation, no claim.
- Deadlines carry `--deadline`. Under 14 days also says how many days remain, in words; a passed
  deadline is `--label`, no clock is running.

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

Target a mid-range Android on mobile data. Fonts subsetted, no webfont over 40KB, no preload (Apple
devices would fetch Inter for nothing). Glass blur costs frames: keep it to the navigation layer.
Everything before the HTML ≤ 190 KB, stylesheets ≤ 15 KB gzipped (`tests/test_budget.py`; raised
once, from 14, at DL4).
No JavaScript beyond HTMX unless it earns its place. The shortlist renders in under 3s on the VPS.

## Before saying done

Verify in the browser at **375 / 768 / 1440, in light and in dark**. Check: no horizontal scroll at
375, focus visible on every control, Cyrillic renders with correct letterforms, the verdict
treatments are distinguishable in greyscale, no glass in the content layer, and axe reports zero
WCAG 2.1 AA violations in both themes.
