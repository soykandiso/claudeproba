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

## The components (DL2, 02.10.2026)

- **Navigation** is glass and floats: a sticky bar at the top, and on a phone a capsule tab bar
  at the bottom where the thumb is, as in iOS 26. The current section sits on a solid lens, so
  its contrast is measured against `--surface`, not against whatever passes under the glass
  (axe caught the tinted pill at 4.46:1 in dark mode over a busy backdrop).
- **Buttons** are capsules in iOS's four styles and press in on a spring.
- **Calls are cards**; the verdict leads each card as a symbol drawn as SF Symbols are, painted
  in `currentColor` through a mask, so no colour is written outside `tokens.css`. Each verdict
  now carries a glyph as well as a shape (check, check, question, bar), which is stronger than
  the dossier's marks were.
- **Disclosures** turn a chevron; **settings-like rows** are inset grouped lists; a **segmented
  control** and a **sheet** exist for DL3 onwards.
- **Glass is fenced in by a test**: the templates may use it on the bars and a sheet only.

## The intake (DL3, 02.10.2026)

`/profil` reads like an iOS form: each section (Фирмата, Дејноста, Проектот) is an inset group
card with its title above; the headcount is a segmented control of its five bands (radios under
it, so the form still posts with no script, and «10–49» is held on one line by word joiners
around the dash); the purposes are a multi-select list; the one action spans the width on a
phone. `/profil/pregled` is a settings list: each answer a row, what it was read as on the right,
«Не е одговорено» where nothing was given, and the reason that costs nothing in the footer.
DS4's behaviour is untouched: the error summary links every field (the segmented control's
fieldset carries the field's id), errors sit between control and hint, the picker's loading
state is on the field.

## The shortlist and the passage (DL4, 02.10.2026)

`/povici` is a grouped page (`.wrap.grouped`): cards on the ground, sections apart by space, no
rules between them. The legend is an inset group, the four marks on one card, with what «Потребна
е проверка» does not mean as its footer. `/povici/izvor/<id>` opens with iOS's back button
(chevron, tint) to the call the reader left; the call's title as context, the condition as the
heading; the facts (institution, deadline, last check, retrieved, source, position) as an inset
group whose «Извор» row leads to the institution's page; the explanation of the mark as the
group's footer; then the stored text on a card of its own. The marked quote is still the one bold
element on the page: nothing else on it is green or underlined in the verified colour.
DS5's checks are unchanged: `#quote` and `#call-<id>`, last check and deadline on the passage,
the quote's own `lang`.

The stylesheet budget went from 14 to 15 KB gzipped here, as a recorded decision
(`tests/test_budget.py`): the language adds components the old one did not have. Every card now
shares one rule, so the next card costs a selector, not a block.

## The audit (DL7, 07.10.2026)

What was checked, and what it found:

- **axe, WCAG 2.0/2.1/2.2 A and AA**: every customer page (`/`, `/profil`, `/profil/pregled`,
  `/povici`, a passage), `/stil` and the seven demo pages in light and dark at 375, 768 and 1440,
  and the five operator screens in both themes at 375 after the changes below (at 768 and 1440 in
  DL6, before them; the only change there raises contrast): zero violations, no horizontal scroll.
- **Text on glass**: axe measures the bar against the page's ground, but glass shows what
  scrolls under it. Composited over the extremes (black in light, a white scan in dark, the
  tint), `--label-2` fell to 3.0:1. Text on glass is now `--label` (6.0:1 at worst); the current
  section is still told by its solid lens. A test computes it from the tokens.
- **Keyboard**: every stop on every page shows the tint ring (a queue row draws it on the row).
  Focus could scroll a control under the sticky bar or the phone's tab bar (WCAG 2.4.11):
  `html` now has `scroll-padding` for both.
- **Reduced motion and transparency**: every transition and animation cut to a frame; glass
  solid. Held by a test.
- **Glass**: only the bars, the tab bar and a sheet; at most two layers on any screen. The demo's
  bar had lost its material in DL2 (content showed through it) and was a third of a phone's
  height: it is glass now, and scrolls away below 768px.
- **Budget**: a first visit is 112-115 KB before the HTML (190 allowed; DS9 measured 132-167 with
  the old faces), about 1.2 s on Slow 4G, 2.8 s on Fast 3G, 0.4 s on 4G, computed from the gzipped
  bytes Caddy will send; text shows before Inter arrives (`font-display: swap`), and Apple
  devices fetch no font. Stylesheets 15 078 B gzipped of 15 360: the next component pays for
  itself.
- **The icon**: the citation seal, white on the tint (`static/favicon.svg`); `/favicon.ico`
  redirects to it.

Not run here, and the user's: a screen reader pass, Lighthouse, and the shortlist on a real
mid-range Android.

## The operator screens (DL6, 06.10.2026)

The admin is the same language, denser. The queue is a grouped page whose lists are inset cards
of rows: each row one tap target (the title's link stretched over it, `.rows__link`), iOS's
chevron on its right, the fill under it on hover and the tint ring on keyboard focus; titles are
the label colour, not underlined, because a row is not a link inside a sentence. An item or a
report review (`.grouped.grouped--cards`) makes each part a card; what was a card of its own
inside a part (a call's head, a notice) is recessed there in `--fill`, never lifted twice. Stored
text around a quote has rounded corners. The manual entry's fields sit on one card, as the
intake's do. DS7's behaviour is untouched: the decision bar under the problems, the reason beside
a disabled approval, removal a confirmed second step, the quote and the scanned page side by side
at 1200px.

## The report, on paper and on screen (DL5, 03.10.2026)

Paper is not glass. The PDF is a print rendering of the language: **one face, Inter** (400, 600,
700, the same woff2 files the site serves, merged per weight by `render.py` and each renamed for
its weight, since every static cut of Inter calls itself «Inter-Regular»), the weights doing what
Source Serif did for headings and quotes; the light theme's colours only; large titles drawn
tight; hairlines at 0.5pt; the quoted passage recessed in `--fill` with rounded corners and the
green bar straight on its left edge, the quote a step larger than the text. The four printed
verdict marks are unchanged (filled, hollow, dashed, struck: WeasyPrint has no masks, and the
pixel test reads them). `--font-print: "Inter"` names the face exactly, so no system font can
stand in; the embedded-font check refuses anything else.

The screen view (`/admin/izveshtaj/<id>/dokument`, later the customer's) is the same template
drawn as the site draws: the print scale takes the iOS text styles, each part a card on the
grouped ground, the verdicts the site's SF-style symbols, the source line with the citation
seal, and dark when the device is. On a phone a clause's number sits above it and the quote is
body size; from 768px the quote is title 3, as on the site. Before DL5 the screen view had
fallen back to the browser's serif: its print faces were no longer loaded on screen.

Fira Sans and Source Serif 4 are gone from the repository.

## Sources

- Apple, Human Interface Guidelines, Materials: Liquid Glass for the navigation layer, used
  sparingly, not in the content layer.
- "Liquid Glass on the Web: backdrop-filter Recipes and When Not to Use Them" (buildmvpfast,
  2026): blur 12-20px, saturate 140-200%, the 1px edge as an accessibility feature, at most 3-4
  glass layers, never animate the blur, Safari's `-webkit-` prefix and var() limitation.
- Anthropic's frontend-design skill: a compact token system, one or two families, boldness
  spent in one place, and a self-critique by screenshot before calling a screen done.
