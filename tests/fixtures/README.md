# Source fixtures

Real responses captured during P1 session 6 reconnaissance (`docs/sources.md` §6), used as parser
fixtures and frozen snapshots. **Do not edit these files** — a fixture that no longer matches what
the source served is worse than none. Re-capture instead and update this manifest.

Retrieved 13.09.2026 unless marked otherwise. Hashes are SHA-256 of the file as committed.

| File | Source | Note | SHA-256 |
|---|---|---|---|
| `av/listing-oglasi-aktivni-merki.html` | https://av.gov.mk/oglasi-za-aktivni-merki.nspx | retrieved 12.09.2026 | `f64578cf1df62dd9…` |
| `av/measure-724-business-mk.json` | POST …/GetActiveEmploymentMeasureDescriptionForBusinessMk {detailId:724} |  | `4ccc2516427d1efb…` |
| `av/measure-819-business-mk.json` | POST …/GetActiveEmploymentMeasureDescriptionForBusinessMk {detailId:819} |  | `45a17932825bf46a…` |
| `av/measure-820-business-mk.json` | POST …/GetActiveEmploymentMeasureDescriptionForBusinessMk {detailId:820} |  | `e260b5604c09ec4d…` |
| `av/measures-list.json` | POST https://av.gov.mk/services/ServiceJobAnnouncements.asmx/GetActiveEmploymentMeasures | full archive, 328 items | `e8f9c2537ac47f65…` |
| `economy/call-1.html` | https://www.economy.gov.mk/mk-MK/javni-objavi/javni-oglasi/javen-povik-za-nadomesti-standardi-od-oblasta-na-dokumenti-… (open, deadline 15.09.2026) |  | `fa1e22c1291c471a…` |
| `economy/call-2.html` | https://www.economy.gov.mk/mk-MK/javni-objavi/javni-oglasi/javen-povik-za-zajaknuvanje-na-sorbotkata-… (open, deadline 15.09.2026) |  | `d0419993e1d2f3f2…` |
| `economy/call-3-javen-povik.docx` | https://portal.mdt.gov.mk/post-body-files/javen-povik-za-finansiska-poddrska-na-mikro-mali-i-sredni-pretprijatija-i-zanaetcii-file-tw5n.docx | main call document is DOCX | `85f0155d8d4cab25…` |
| `economy/call-3.html` | https://www.economy.gov.mk/mk-MK/javni-objavi/javni-oglasi/javen-povik-za-finansiska-poddrska-na-mikro-mali-i-sredni-pretprijatija-i-zanaetcii (closed 30.06.2026) |  | `fd9b9232ffaf0f00…` |
| `economy/listing-javni-oglasi-empty.html` | https://www.economy.gov.mk/mk-MK/javni-objavi/javni-oglasi | retrieved 16.09.2026: "Во моментот нема активни јавни огласи" | `d639c7759baf06e0…` |
| `economy/listing-javni-oglasi.html` | https://www.economy.gov.mk/mk-MK/javni-objavi/javni-oglasi | retrieved 12.09.2026 | `852b4aadcf5263ee…` |
| `economy/listing-zavrseni.html` | https://www.economy.gov.mk/mk-MK/javni-objavi/zavrseni-javni-oglasi | retrieved 12.09.2026 | `0248f8160ab29962…` |
| `eu_portal/search-open-sme.json` | POST https://api.tech.ec.europa.eu/search-api/prod/rest/search?apiKey=SEDIA&text=SME (open+forthcoming; trimmed to 5 results) |  | `a7efddd1aa9922eb…` |
| `eu_portal/search-scope-horizon-eic.json` | POST https://api.tech.ec.europa.eu/search-api/prod/rest/search?apiKey=SEDIA&text=***&pageSize=100&pageNumber=1 with `search_request(SCOPE[1], 1)` from `app/ingestion/sources/eu_portal.py` | retrieved 16.09.2026; 23 of 31 "Open"/"Forthcoming" topics have 2023 deadlines | `581f7fadd89f4ab9…` |
| `eu_portal/topic-digital-2026-skills-10-edtech.json` | https://ec.europa.eu/info/funding-tenders/opportunities/data/topicDetails/digital-2026-skills-10-edtech.json |  | `ebb67dc9b50c3694…` |
| `eu_portal/topic-horizon-cl6-2026-01-circbio-07.json` | https://ec.europa.eu/info/funding-tenders/opportunities/data/topicDetails/horizon-cl6-2026-01-circbio-07.json |  | `0ce656d2b820e573…` |
| `eu_portal/topic-smp-cosme-2024-cluster-01.json` | https://ec.europa.eu/info/funding-tenders/opportunities/data/topicDetails/smp-cosme-2024-cluster-01.json |  | `0d970537e3439558…` |
| `ipardpa/call-32-javen-povik-01-2025-kratka.pdf` | https://www.ipardpa.gov.mk/Upload/Documents/Јавен Повик 01_2025 Кратка верзија.pdf | Word export, no text layer | `6832f8f36eac8ab4…` |
| `ipardpa/call-32.html` | https://www.ipardpa.gov.mk/mk/Home/IpardPovici/32 |  | `d8312e5458f4a1f4…` |
| `ipardpa/call-33.html` | https://www.ipardpa.gov.mk/mk/Home/IpardPovici/33 |  | `3a07ee14721f14d3…` |
| `ipardpa/call-34-najava-03-2025.pdf` | https://www.ipardpa.gov.mk/Upload/Documents/ПРЕТХОДНА НАЈАВА 03-2025.pdf | has text layer | `c950d07d3c19076d…` |
| `ipardpa/call-34.html` | https://www.ipardpa.gov.mk/mk/Home/IpardPovici/34 |  | `d068569051912a22…` |
| `ipardpa/listing-ipard-2021-2027.html` | https://www.ipardpa.gov.mk/mk/Home/Ipard/5 |  | `258a3be98fd88777…` |
| `ipardpa/listing-ipard-povici.html` | https://www.ipardpa.gov.mk/mk/Home/JavniPovici/1 | retrieved 12.09.2026 | `a09ae608fc70c746…` |
| `skopje/call-12094.pdf` | https://skopje.gov.mk/media/12094/javen-povik.pdf | scanned, no text layer | `ee9981aaf7683150…` |
| `skopje/call-12134.pdf` | https://skopje.gov.mk/media/12134/јавен-повик-за-млади-за-2026-мкд.pdf | scanned, no text layer | `00241e5067576608…` |
| `skopje/call-12149.ocr.json` | Tesseract 5.3.4 `mkd`, 300 dpi, over `skopje/call-12149.pdf` | **recorded 16.09.2026, not a source response**: replayed by `RecordedOcr` in tests, because OCR output varies between Tesseract versions | `926aceee5a51d288…` |
| `skopje/call-12149.pdf` | https://skopje.gov.mk/media/12149/јавен-повик-субвенции-на-занаети.pdf | scanned, no text layer | `60df3a26f79d9ca7…` |
| `skopje/listing-javni-povici.html` | https://skopje.gov.mk (Јавни повици) | retrieved 12.09.2026 | `cc0b271ce65da2c3…` |

## Not committed (too large), recorded for re-capture

| Document | Source | Size | SHA-256 |
|---|---|---|---|
| Economy call 1, main PDF (no text layer) | https://portal.mdt.gov.mk/post-body-files/javen-povik-za-nadomesti-standardi-…-file-cnm3.pdf | 2,5 MB | `8f3b5e21135a085584f1afe1e5673154f3a8c22a86e870d8191cb27c4ab2c0e8` |
| Economy call 2, main PDF (no text layer) | https://portal.mdt.gov.mk/post-body-files/javen-povik-za-zajaknuvanje-na-sorbotkata-…-file-yqir.pdf | 2,0 MB | `386d51806d730946c714c210ef8aa16691bedcdc16f96e92f45af1c6098aa942` |
| IPARD call 01/2025, long version (no text layer) | https://www.ipardpa.gov.mk/Upload/Documents/Јавен Повик 01_2025 Долга верзија.pdf | 5,2 MB | `461051a3c096ec2d20a94a8e63428c46d629fd870eb25eb08312bc1de05c3b2f` |

No FITR fixtures: the host did not respond (`docs/sources.md` §6.1).
