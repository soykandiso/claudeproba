# Design audit (DS1)

**Done 01.10.2026**, against `.claude/skills/design-system/SKILL.md` (the skill), at 375 / 768 / 1440.
This is the work list for DS2–DS9: every finding has an owner session, and the design phase is
finished when this file has no open finding (roadmap, "Phase acceptance").

Screenshots live in `docs/design/ds1/`, cropped to what the finding is about. The full-page captures
(41 of them, up to 29 000 px tall) were not committed. §4 says how to make them again.

---

## 1. What was audited

Every screen a person can reach on the real site. `/demo` is excluded: it gets replaced, not
redesigned (`base.html`).

| Screen | Route | Data it was looked at with |
|---|---|---|
| Placeholder home | `/` | none (P3 replaces it) |
| Intake | `/profil/` | empty, and the refused POST with five errors |
| What we understood | `/profil/pregled` | a ДОО, 62.01, Вевчани, 10–49, with a description containing an e-mail |
| Shortlist | `/povici/` | the five frozen calls (`seed_shortlist.py`): two open on 01.10.2026, one of them closing that day |
| Cited passage | `/povici/izvor/<criterion>` | the Skopje craftsmen call, condition 1 |
| Review queue | `/admin/` | `seed_review_queue.py` + two `seed_report.py` drafts |
| Call review | `/admin/stavka/1`, `/2`, `/3` | an AV call, an EU topic, an EU topic with failed quotes |
| Manual entry | `/admin/rachen-vnes` | empty |
| Report review | `/admin/izveshtaj/4`, `/5` | a clean draft and a blocked one («гарантирано») |
| Report PDF | `/admin/izveshtaj/4/pdf` | item 4 after approval, 11 pages |

**Checked on every screen, in the browser:** horizontal overflow, console errors, failed requests,
the computed font size of every text node, every colour in use, border radius, box shadow, italic,
`text-transform`, monospace, `lang`, `font-feature-settings`, which fonts actually loaded, tab
order with the focus style of each stop, the height of every control, inline `style`, and the
banned words, middle dots, arrows and non-`dd.mm.yyyy` dates in the rendered text. The shortlist was
also captured in greyscale. The font files were opened with fontTools.

## 2. What already holds

No need to re-check these until something changes them:

- **No horizontal scroll** on any screen at any of the three widths.
- **Console clean** on every live page. The two font-preload warnings on `/admin/stavka/2` and `/3`
  are F09.
- **Focus is visible on every tab stop** on `/profil`, `/povici`, `/admin`, `/admin/izveshtaj/5`:
  a 2px ink outline, never removed.
- `lang="mk"` on every page, `font-feature-settings: "locl"` on `body`; the loaded faces are only
  the vendored ones.
- **Every date reads `dd.mm.yyyy`.** No ISO or US date reaches the rendered text.
- **No shadows.** The only radius is 2px. No uppercase, no italic, no `·`, no `→`.
- **Each font file is ≤ 40 KB** (the largest is 23 KB). The Cyrillic subsets cover
  Ѓѓ Ќќ Љљ Њњ Џџ Ѕѕ Јј.
- Deadlines carry `--seal`. Under 14 days they say the days in words, and the closing day says
  «рокот истекува денес».
- `last_verified_at` is on every call of the shortlist and on every call page of the PDF.
- Banned words: none on the customer screens. The blocked report shows «гарантирано» to the
  reviewer, which is its job.

## 3. Findings

Severity: **A** breaks a rule the skill states as absolute, or a promise the brief makes to the
customer. **B** breaks a skill rule in a way a user would notice. **C** is a consistency or polish
issue.

### Foundation: tokens, type and fonts (DS2)

| # | Sev | Screen | Finding | Fix |
|---|---|---|---|---|
| F01 | C | `/` | The placeholder has its own `<style>` with eight hex values, so it would fail DS2's "no hex outside `tokens.css`" check. | Make it extend `base.html`, or delete it once P3's landing exists. The DS2 check must not exempt it silently. |
| F02 | B | `/povici`, `/profil/pregled` | Inline `style` in templates: `padding-block: 24px` and `padding-top: 32px` (`shortlist/index.html`), `padding-top: 24px` (`intake/review.html`), and `style="--gap: 4px"` (`shortlist/_macros.html`). That last one does nothing: `.stack` never reads `--gap`, so the title and the institution sit 16px apart instead of 4px. | Add `--gap` to `.stack` (`margin-top: var(--gap, var(--s-16))`) and move the paddings into classes. Make the DS2 check also fail on `style=` in `app/web/templates/` outside `demo/`. |
| F03 | B | all | `site.css` uses raw values outside the spacing scale: verdict and step markers at 12/14px, rules at 3px, offsets at 5/6/20/22px, and column widths at 1.5/2.5/7.5/8.5/11rem. The skill's 4px scale has no token for a marker or a rule weight, so these had nowhere to come from. | Add `--mark` (12px), `--rule-w` (1px) and `--rule-w-strong` (3px) to `tokens.css`, and replace each raw value with a token or the nearest scale step. |
| F05 | B | all | The Fira Sans Cyrillic subsets keep no language systems at all (no `locl`, no MKD), while Source Serif keeps `cyrl/MKD`. Upright Fira is the same in Russian and Macedonian, so nothing renders wrong **today**, and no italic face is shipped. But an `<em>`, `<i>` or `<cite>` would get a synthesised oblique of the Russian forms. | Set `font-synthesis: none` on `body` now. When DS2 re-cuts the subsets, keep the `locl` lookups (`pyftsubset --layout-features+=locl --layout-scripts+=cyrl`). Do not ship italic until a native reader signs it off (DS2 acceptance). |
| F06 | B | `/povici`, `/profil`, admin | **14px is used for body content.** It is used for the reason under every condition (`.small.soft`), the hints, the excerpt source line, the verdict labels and the nav. The skill says body never goes below 16, and 12 is for identifiers. 14 is in the scale but has no stated job. | Define the job: 14 for labels (`dt`, the verdict label, the source line), never for a sentence the user must read. The condition's reason and the hints go to 16 `--ink-soft`. |
| F07 | C | PDF | `report.css` sizes text in points (8, 8.5, 10.5, 12, 14, 22pt), so the scale has a second, undeclared copy. | A print scale in `tokens.css` (`--print-*`), used only by `report.css`. Owned by **DS6**. |
| F27 | C | `/profil`, `/profil/pregled` | `.privacy-note` and `.form` are capped at 40rem, not `--measure`. At 14px that is about 90 characters to a line. | Use `max-width: var(--measure)` throughout. Everything that reads as prose gets the measure. |

### Components and states (DS3)

| # | Sev | Screen | Finding | Fix |
|---|---|---|---|---|
| F10 | **A** | `/povici` legend, PDF legend, report review | **"Likely eligible" and "Needs verification" have the same mark**, a hollow circle. They differ only in ink vs ink-soft. In greyscale ([f10](design/ds1/f10-legend-greyscale-375.png)) the legend tells them apart by a shade of grey. On the call itself the left rule does differ (solid vs dashed), but the legend, the verdict label in the admin and the PDF show the mark alone. | Put the rule into the mark, so it survives wherever it is used alone. Eligible: filled disc. Likely: hollow disc. Needs verification: **dashed** hollow disc (`border-style: dashed`, 2px). Not eligible: a struck mark (disc with a horizontal bar through it). Re-check in greyscale on `/stil`. |
| F11 | B | `/povici` | The not-eligible treatment was never seen with real data: no profile against the five frozen calls produced an excluded call that day. | `/stil` (DS2) renders all four verdicts on a call. DS5 checks the excluded section with a profile that triggers it (a `tp` against AV). |
| F12 | B | `/profil/pregled` | `--verified` used outside a citation, in two places. The scrubbed-description preview is an `.excerpt` with the green rule ([f12](design/ds1/f12-verified-on-scrub-375.png)), but it is our own text, not a quote. The activity picker's «Прочитано како» is also green. The skill gives `--verified` one job: the citation mark. | Add an `.excerpt--own` variant with an `--ink-soft` rule. `.chosen` goes to ink, weight 500. |
| F04 | C | `/povici`, admin | The +/− in front of every `<summary>` is set in `--font-id` (monospace) for alignment, which is monospace as decoration. | Draw the marker with the body face at a fixed width, or as a 12px CSS cross. |
| F25 | B | `/profil`, all admin forms | **Submit buttons have no loading state.** `.btn[aria-busy]` is styled, but nothing ever sets it. On a slow phone «Зачувај го профилот» gives no sign it was pressed, and a second tap submits again. | Set `aria-busy` and `disabled` on the submitter. The admin does not load HTMX, and the intake form is a plain POST. So either `hx-boost` plus `hx-disabled-elt` on the forms, or our first JavaScript: one file, under 20 lines, documented in `base.html`. It earns its place: a double submit of «Прифати и објави» is the risk. DS3 picks one. |
| F26 | C | `/profil` | Checkboxes and their labels have no hover state, and no active state (only the native one). | `.choice:hover` gives an `--ink` border to the box (via `accent-color` plus an outline on the input). |
| F31 | C | `/povici` vs admin | The same past deadline reads «рокот помина» (`format.days_left`) on the customer side and «рокот измина» in the admin (`admin/__init__.py:172`). | One function: the admin imports `format.days_left`. |

### Intake (DS4)

| # | Sev | Screen | Finding | Fix |
|---|---|---|---|---|
| F21 | B | `/profil` refused | The error summary reads «5 полиња треба да се поправи», which is singular agreement with a plural subject ([f21](design/ds1/f21-error-summary-375.png)). It also does not link to the fields. | «… треба да се поправат». The summary lists each field as a link to its `id`, and receives focus (it already has `tabindex="-1"`). |
| F22 | C | `/profil` refused | The error sits **below the hint**. At 375 a three-line hint separates the control from what is wrong with it ([f22](design/ds1/f22-error-under-hint-375.png)). | Order: label, control, error, hint. Keep `aria-describedby` as it is (error first). |
| F23 | B | `/profil/pregled`, admin report, PDF | Company age is said in months: «93–105 месеци, основана 2018» ([f23](design/ds1/f23-review-rows-375.png)), and «81–93 месеци» in the report. Nobody thinks of their company in months. | Say it in years: «7–8 години». Months only where a call states a limit in months, and then beside it. One formatter in `format.py`, used by all three. Shared with **DS6**. |
| F24 | C | `/profil/pregled` | «Намена: опрема и машини» is lower case. The form shows the same words capitalised. | Capitalise in the review rows the way `_macros.checkboxes` does. |
| F19 | C | `/profil/pregled`, passage | Neither nav item is marked current on `/profil/pregled` (it belongs to «Профил») or on a passage page (it belongs to «Повици»). | Match by blueprint (`request.blueprint`), not by endpoint. |

### Shortlist and passage (DS5)

| # | Sev | Screen | Finding | Fix |
|---|---|---|---|---|
| F13 | **A** | passage | **The passage page shows a call but not its `last_verified_at`**, nor its deadline ([f13](design/ds1/f13-passage-375.png)). The skill: "every screen showing a call states `last_verified_at` … No exceptions". | Add «Последна проверка» and «Рок за пријава» (with `ui.deadline`) to the facts. |
| F14 | B | shortlist → passage | The link to a passage has no `#quote`. At 375 the marked text starts about 1 350px down, below two screens of preamble. «Назад кон повиците» returns to the top of the list, not to the call the reader came from. | Link to `…#quote`. Give each `li.call` an `id` and send it back as `…/povici/#call-<id>`. |
| F15 | B | passage | The page's `h1` is the call title, five lines on a phone. The condition, which is why the reader is here, is a 16px paragraph under it. | The condition is the heading, and the call title becomes the context line above it. This is the page DS5's acceptance tests ("why a call is needs verification and where that comes from"). |
| F16 | B | `/povici` | Every excerpt caption ends with the snapshot and character span («5 1332–1436»). That is an identifier no customer compares, and at 375 the caption runs to four lines ([f16](design/ds1/f16-excerpt-caption-375.png)). | Keep the span on the passage page, where it explains the mark. The shortlist caption is source and date, plus the link. |
| F17 | B | `/povici` | On the call closing today, «Зошто е на ова место» says «До рокот остануваат 0 дена, кратко за подготовка» ([f17](design/ds1/f17-zero-days-375.png)). It uses digits, and it contradicts the deadline above it, which says «рокот истекува денес» ([f17b](design/ds1/f17-deadline-today-375.png)). | `stage2._days_left` uses `format.days_left` for under 14 days. This changes the reason text only, not the score, so no weights version moves. |
| F18 | B | `/povici`, passage, PDF | English quotes and titles from EU calls carry no `lang`. A screen reader reads «Financial and operational capacity» with the Macedonian voice, inside Macedonian quotation marks ([f18](design/ds1/f18-english-quote-375.png)). | Put `lang` on the `blockquote` and the title from the snapshot's language. Use the matching marks for that language: “…” for `en`. |

### The report, on screen and on paper (DS6)

| # | Sev | Screen | Finding | Fix |
|---|---|---|---|---|
| F28 | B | PDF p.1 | In the legend, the verdict label wraps into the description column: «Можете да аплицирате / повикот» ([f28](design/ds1/f28-pdf-legend.png)). | A two-column grid with the label column sized to its content (`grid-template-columns: max-content 1fr`), or a definition list stacked label over text. |
| F29 | **A** | PDF, report review | **A deadline that has passed is shown as a plain date.** Item 4 lists a call with «Рок за пријава 21.08.2026» on a report issued 01.10.2026, with nothing saying it has closed ([f29](design/ds1/f29-pdf-deadline-passed.png)). The dev seed put a closed call into the run: stage 1 excludes them (`stage1.py:68`). But the PDF is rendered at approval, which can be days after the run, so a call can close in between. Neither the PDF nor `/admin/izveshtaj` says the days left in words either. | Both surfaces use `ui.deadline` / `days_left`, against the **issue date**. `compose.blockers()` gains a blocker: "a call's deadline has passed since the run". The reviewer drops it or closes the report. |
| F30 | C | `/povici`, admin, PDF | One date, three labels: «Последна проверка» (shortlist, admin), «Состојба на» (PDF). | «Последна проверка» everywhere. |

### Operator screens (DS7)

| # | Sev | Screen | Finding | Fix |
|---|---|---|---|---|
| F08 | B | all admin | The admin wordmark is «Грантови.мк» ([f08](design/ds1/f08-admin-wordmark-375.png)), which decides D2 (name and domain). The customer shell is descriptive on purpose. | «Грантови и субвенции», as `base.html`, until D2 is decided. |
| F09 | C | all admin | No skip link; `main` has no `tabindex="-1"`. On `/admin/stavka/2` and `/3` at 375, both preloaded fonts log «preloaded but not used within a few seconds». | Take the skip link from `base.html`. Read the preload warning in DS9's performance pass: drop a preload if the font is not needed above the fold. |
| F32 | B | `/admin` | The queue shows pipeline strings in English: «new call from av: approve before publishing», «extract_call: 7 of 8 quotes not found verbatim in the documents» ([f32](design/ds1/f32-queue-english-1440.png)). | Map each `reason` code to a Macedonian sentence in `app/review/`. Keep the raw string for the log, not the screen. |
| F33 | B | `/admin/izveshtaj/<id>` | **The decision is at the end of a 23 000px page** (1440; 29 000 at 375), behind more than 60 tab stops. When approval is refused, the disabled button says nothing beside it: the reason is the problem list at the top, 17 000px away ([f33](design/ds1/f33-decision-at-end-1440.png)). | Put a short decision bar under the problem list: the count, «Оди на одлуката», and the disabled state with its reason. Repeat the reason beside the button. Skip links per call. This is DS7's 45-minute acceptance. |
| F34 | B | report review, call review | «Отстрани ја изјавата» and «Отстрани го условот» look exactly like «Зачувај…», directly below it, with no confirmation ([f34](design/ds1/f34-remove-like-save-1440.png)). | A destructive variant: text button, underlined, separated by `--s-32`. Ask for confirmation with a second step (a `<details>` holding the real submit), not with `confirm()`. |
| F35 | C | report review | A hint ends «(P2 s34)», an internal session number shown on screen. | Say what happens: «Причината станува случај за евалуација». |
| F36 | C | report and call review at 1440 | The page is a 640px column with 800px of paper beside it, while the reviewer scrolls between a quote and its scanned page. | At ≥ 1200px, show the quote and its facsimile or context side by side. Prose keeps the measure. |

### Accessibility and performance (DS9)

| # | Sev | Screen | Finding | Fix |
|---|---|---|---|---|
| F37 | B | `/povici`, passage, header | Some touch targets are under 44px. «Види го во текстот на повикот» is an inline 14px link about 21px tall, ten times on a page. The nav links are 37px, and so is the source link on the passage page. | Inline links stay inline for reading but get `padding-block: var(--s-8)`. Nav links get `min-height: 44px`. |

### Owners at a glance

| Session | Findings |
|---|---|
| DS2 | F01, F02, F03, F05, F06, F27 |
| DS3 | F04, F10, F11 (`/stil`), F12, F25, F26, F31 |
| DS4 | F19, F21, F22, F23, F24 |
| DS5 | F11 (live check), F13, F14, F15, F16, F17, F18 |
| DS6 | F07, F23 (report and PDF half), F28, F29, F30 |
| DS7 | F08, F09, F32, F33, F34, F35, F36 |
| DS9 | F37 |

Three are **A**: F10, F13 and F29. F13 and F29 break a promise to the customer (a date on every
call; a deadline you can trust), so they could be taken out of order, ahead of the sessions that
own them. F10 belongs with the rest of DS3's component set.

## 4. Repeating the audit

The browser can't use the chrome-devtools MCP here (there is no X server). Use the CDP script in
`handoff.md` §7, extended with the probes listed in §1 above. A finding is closed when its
screenshot, taken again, no longer shows it. The finding then moves to §2 with the date.

In a cloud session without Docker (01.10.2026), the stack ran natively, as in `handoff.md` §5. In
short: system Postgres 16 with `postgresql-16-pgvector`, a `grants` superuser, `alembic upgrade
head`, the three seed scripts, `flask run --port 8080`. Chromium is started as `nobody`, which
keeps its sandbox; root would need `--no-sandbox`.
