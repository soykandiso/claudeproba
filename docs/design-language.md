# Design language (DL1, 02.10.2026)

The second visual direction of this product, after DS1–DS9's "dossier". Asked for by the user
on 02.10.2026: *a radical design improvement, font, colours, UI, elements, everything; inspired
by Apple iOS design, glass.* The user then chose **Inter**, **Apple-faithful glass**, **light and
dark following the phone** and a **deep-blue tint**. This file is the why; the rules are
`.claude/skills/design-system/SKILL.md`, the values `app/web/static/css/tokens.css`, and every
value is rendered on `/stil` (`?tema=svetla`, `?tema=temna`).

## What it is

**An iOS app, on the web, for people deciding whether to apply for public money.** The
familiar grammar of the phone in their hand: large bold titles, grouped lists on a soft ground,
one blue for everything you can press, controls that float above the content on frosted glass,
and a dark mode that follows the phone. Familiar is the point. A small-business owner in
Strumica should feel they already know how to use it.

Three ideas from Apple's Human Interface Guidelines carry it:

- **Content leads.** The page is content on solid surfaces. Navigation and controls float above
  it and recede. Nothing that must be read sits on glass.
- **Concentric, rounded shape.** Radii from 8 to 28 and pills, one family of curves, never a
  sharp corner next to a soft one.
- **Responsive, quiet motion.** Movement answers a touch, with Apple's own curves, and stops
  when the reader asks for less motion.

## What does not change

The language is new; the product's promises are not. Every one of these survives into every
DL session and is tested:

- The five invariants (CLAUDE.md). **No citation, no claim** still makes the cited passage the
  one element that gets visual boldness.
- **A verdict is told apart without colour**: its mark alone says which of the four it is,
  in greyscale, in both themes (DS3's F10, the pixel test for paper).
- Macedonian first, correct Cyrillic (every face draws Ѓѓ Ќќ Љљ Њњ Џџ Ѕѕ Јј), `dd.mm.yyyy`,
  МКД and EUR, the banned words.
- One source of values (`tokens.css`), no inline style, every size from a token.
- **Zero WCAG 2.1 AA violations**, 44px targets, a visible focus, in both themes.
- The budget: a first visit under 190 KB before the HTML (`tests/test_budget.py`).

## Decisions, with their reasons

**Type: Inter, behind SF.** SF Pro is licensed for Apple platforms only; it may not be served
from a website. The stack asks for `-apple-system` first, so iPhones and Macs render in their
own SF and download nothing; everyone else gets Inter, the free face nearest to SF, with full
Macedonian Cyrillic. Inter is cut as static instances at the optical size each weight is used
at, as SF Text and SF Display are: 400 at 14 for reading, 600 at 20 for headlines and controls,
700 at 28 for large titles (`ops/dev/cut_fonts.py`; 7 KB per Cyrillic file). The scale is iOS's
text styles: body 17, subhead 15, footnote 13, caption 12, title 20/22/28, large 34, display 48,
with SF Display's tight tracking at large sizes. **No italic**: neither Inter nor SF has
Macedonian italic forms, so emphasis is weight, as on iOS. That retires DS2's open italic
sign-off.

**Colour: iOS's system palette, made accessible.** Grounds and labels follow iOS
(`systemGroupedBackground` #F2F2F7, white surfaces, true black in dark). Where iOS's own
colours fail WCAG for small text on the web (its secondary label, `systemBlue` on white), they
are deepened: the tint is #0A5BD3 (6.1:1 on white), the secondary label #56565C. Dark mode has
its own lighter tint for text (#4D9BFF) and a deeper one under white button text (#1E6FE6).
Every pair is measured in both themes on `/stil` and in a test (34 pairs, all pass). The
single-purpose colours keep their jobs: `--deadline` means a clock is running, `--verified`
marks a citation.

**Glass: the floating layer only.** Apple's guidance is explicit: Liquid Glass belongs to the
navigation layer, sparingly, never in the content layer. On the web it is `backdrop-filter`,
which costs real frames on a cheap Android and has no fixed contrast ratio. So glass is for the
navigation bar, the phone's tab bar, a floating primary action and a sheet. Content (calls,
conditions, quotes, forms, the report) sits on solid surfaces. The material degrades in three
steps: solid by default, frosted where `backdrop-filter` is supported, and solid again under
`prefers-reduced-transparency`. Its 1px edge is kept because forced-colours mode removes
everything else. Never more than a few glass layers on a screen, and never an animated blur.

**Shape and depth.** Radii 8, 12, 20 and 28, and pills. Two soft shadows: one to lift a
surface off the ground, one under glass. The dossier's hairline-only rule is gone; separators
inside a grouped list are iOS's inset hairlines.

**Motion.** `--ease-out` and `--ease-spring` (Apple's), 160 and 280 ms. It answers an action.
Everything collapses to 1 ms under `prefers-reduced-motion`.

## What the PDF does

Paper is not glass. Until DL5 the PDF keeps the faces it merges and checks (Fira Sans and
Source Serif 4, `--font-print-*`) and takes the light theme's colours only. DL5 makes it a print
rendering of the new language.

## Sources

- Apple, Human Interface Guidelines, Materials: Liquid Glass for the navigation layer, used
  sparingly, not in the content layer.
- "Liquid Glass on the Web: backdrop-filter Recipes and When Not to Use Them" (buildmvpfast,
  2026): blur 12-20px, saturate 140-200%, the 1px edge as an accessibility feature, at most 3-4
  glass layers, never animate the blur, Safari's `-webkit-` prefix and var() limitation.
- Anthropic's frontend-design skill: a compact token system, one or two families, boldness
  spent in one place, and a self-critique by screenshot before calling a screen done.
