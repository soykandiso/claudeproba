# Legal notes: reusing official publications

Roadmap P3 s43 (07.10.2026), answering `architecture.md` §9.7: may the platform show, and the
public archive (s41–42) publish, the text of the calls it reads?

**This is a reading of the statutes by Claude, not legal advice.** It quotes the law it relies
on so a lawyer can check it in minutes. The decisions marked *yours* are the user's. Before
anything beyond the rules below (full texts, mirrored documents), a Macedonian lawyer should
confirm §2.

## 1. What the law says

**Закон за авторското право и сродните права**, «Службен весник на Република Македонија»
бр. 115/10, 140/10, 51/11, 147/13, 154/15 и 27/16, read in the unofficial consolidated text
published by ЗАМП ([PDF](https://zamp.mk/wp-content/uploads/2024/09/%D0%97%D0%90%D0%9A%D0%9E%D0%9D-%D0%97%D0%90-%D0%90%D0%92%D0%A2%D0%9E%D0%A0%D0%A1%D0%9A%D0%9E%D0%A2%D0%9E-%D0%9F%D0%A0%D0%90%D0%92%D0%9E-%D0%98-%D0%A1%D0%A0%D0%9E%D0%94%D0%9D%D0%98%D0%A2%D0%95-%D0%9F%D0%A0%D0%90%D0%92%D0%90_1.pdf)).
Amendments after 27/16, if any, were not found; a lawyer should confirm.

- **Article 16, not works.** «Како авторско дело, во смисла на овој закон, не се сметаат: […]
  2) службените текстови од политичка, законодавна, административна и судска природа и нивните
  службени преводи; 3) дневните и други вести кои имаат карактер на обични - медиумски
  информации, едноставни факти и податоци […]». A public call issued by a ministry, an agency
  or a municipality in the exercise of its public function reads as an official text of an
  administrative nature; deadlines, amounts and eligibility as facts are data in any case.
- **Article 52(7), quotation.** Free use without payment covers «користење делови на авторски
  дела (цитати), во научни истражувања, за настава, критика, полемика или преглед, во обем и до
  степен потребен за конкретната намена и под услов да се наведе името на авторот и изворот».
  It is not limited to non-commercial use. A short quote beside the statement it supports, with
  the source, is a quotation for review even where a text *is* protected.
- **Articles 118–122, the database maker's right** (15 years, Art. 128). The maker of a database
  with substantial investment controls extraction and reuse of the whole or of substantial parts,
  and (Art. 120(1)3) of **insubstantial parts used repeatedly and systematically** against normal
  use or unreasonably harming the maker's interests. This is the one provision a crawler meets
  head on: a listing page of calls may be such a database, whatever the status of each call.

**The European Commission** ([legal notice](https://commission.europa.eu/legal-notice_en)):
unless otherwise indicated, EU-owned content is licensed **CC BY 4.0**, under Commission Decision
2011/833/EU on the reuse of Commission documents: reuse is allowed with credit and with changes
indicated; third-party works, identifiable private individuals, logos and other industrial
property are excluded.

**Watch:** the Ministry of Digital Transformation has a draft Law on Open Data and Reuse of
Public Sector Data (transposing Directive 2019/1024) in public consultation; commentary on it
says some reuse would need the holder's permission. It was a draft when this was written. If it
is adopted, read it before the archive's first public page.

## 2. What that means, source by source

| Source | Who writes the call | Basis for showing its words |
|---|---|---|
| АВРСМ (`av`), Министерство за економија (`economy`), Град Скопје (`skopje`) | a public body | Art. 16(2): the call is an official administrative text; Art. 52(7) as a second basis for quotes |
| ИПАРД (`ipard`) | the paying agency, a public body | as above. The footer's «сите права задржани» covers the site's own content (design, photos, news); it does not make an official text protected |
| EU Funding & Tenders Portal (`eu-portal`) | the Commission | CC BY 4.0: credit beside every quote (**built**, §4); our summaries and translations are "changes" and say so |
| Manual entry (`manual`) | anyone: a donor, an embassy, a UN agency, an NGO | **not** an official text of a Macedonian body: Art. 52(7) only. Quotes stay short and sourced, nothing more |
| ФИТР (`fitr`, inactive) | a public fund | as the public bodies, when it is reachable |

## 3. Rules for everything public (the shortlist, the passages, the archive of s41–42)

1. **What we write is ours**: summaries, structured facts (title, institution, deadline, amounts,
   who may apply), verdicts and reasons. Facts are not works (Art. 16(3)).
2. **Their words appear only as quotes**: verbatim, short, each beside the statement it supports,
   with the source and the date we read it. This is already invariant 2; it is also what Art.
   52(7) asks for, so a quote stands even where Art. 16(2) would not.
3. **No mirrors.** No full text of a call and no hosted copy of a PDF or attachment on a public
   page: link to the original. Art. 16(2) probably allows more for the public bodies, but not for
   manual entries, and a mirror is duplicate content to a search engine as well.
4. **The passage window stays a window**: the quote with up to 600 characters either side
   (`CONTEXT` in `app/web/shortlist/__init__.py`), and the link to the whole document.
5. **A licence's credit is shown beside the quote** (`credit_mk` in `config/sources.yaml`).
6. **No logos, no photos, no scanned page images** in public. The page images beside OCR'd quotes
   are an operator's tool and stay in the admin.
7. **People are not republished.** A call's contact person (name, phone, e-mail) is the
   institution's business, not the archive's: archive pages name the institution only. A
   passage window can still contain a contact line today; **s41 must scrub persons from any
   text window shown publicly**. The gateway's `Scrubber` (`app/ai/scrub.py`) already finds
   e-mail addresses and Macedonian phone numbers; a person's name has no shape it can match, so the
   archive's contact line is dropped by position (the contact block of a call), not by pattern.
8. **The listings are not copied.** The archive is built from each call's own documents, never by
   reproducing a source's listing page; the crawler stays at ~0.2 req/s with an identifying
   User-Agent (CLAUDE.md). This keeps Art. 120(1)3 out of reach: one call's facts from its own
   document, at the pace of a careful reader.
9. **On request, down.** If an institution asks for its text to be removed, it is removed and the
   request recorded in `decisions.md`. That needs a public contact address, which waits on D2.

## 4. What changed in the code (07.10.2026)

- `config/sources.yaml`: `eu-portal` has its terms (`terms_url`, `terms_note`) and a credit,
  «© Европска унија, CC BY 4.0» linking to the licence. `SourceEntry` gained `credit_mk` and
  `credit_url`; they are configuration, read by the web layer and never stored.
- `app/matching/shortlist.py`: a verified citation carries its source's credit; the excerpt
  component shows it as a `rel="license"` link (shortlist, landing); the passage page lists it
  as «Лиценца».
- `app/ai/scrub.mask_contacts`: e-mail addresses and phone numbers in the text shown around a quote
  on the passage page are masked (rule 7); the quote is never touched (P3 s41–42).

## 5. Yours to decide

*The conservative default of each is in code since 07.10.2026: `decisions.md` D12.*

- **Full texts, ever?** Rule 3 says no. If the archive should one day carry whole calls from the
  public bodies (Art. 16(2)), have a lawyer confirm that a јавен повик is a «службен текст од
  административна природа» first. The SEO case is against it anyway (`architecture.md` §9.7).
- **Manual entries in the archive at all?** Their text is somebody's copyright. Facts and short
  quotes are fine (rule 2); leaving them out of the public archive entirely is the simpler
  position.
- **The open data law**: whether it has passed, before the archive's first public page.
