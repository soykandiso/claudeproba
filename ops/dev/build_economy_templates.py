# ruff: noqa: E501 -- the Ministry's URLs and its own words, kept whole so they can be searched.
"""Template set 2 (roadmap P5 s62): the Ministry of Economy and Labour's 2026 forms.

    PYTHONPATH=. uv run python ops/dev/build_economy_templates.py [--forms var/forms/economy]

Three calls of 2026, each with the same three forms, downloaded 16.10.2026 (with the user's
leave) from the attachments on portal.mdt.gov.mk, the .doc ones converted with Word:

- msp-2026: «Финансиска поддршка на микро, мали и средни претпријатија и занаетчии»;
- socijalni-praktiki-2026: «Надоместување на трошоци за стандарди и извештаи за општествено
  прифатливи практики» (Барање – ОО 2026);
- univerziteti-2026: «Соработка помеѓу преработувачката индустрија и универзитетите».

Every application form lists the attachments it wants, with their conditions (how old, in
original, notarised); the manifests repeat them in the form's words as notes, so the checklist
says what the Ministry said. The calls are closed; a new call of the same programme usually
reuses the form, and `build` refuses a changed file (its hash), which is when to look again.
"""

import argparse
import datetime as dt
from functools import partial
from pathlib import Path

from app.documents.forms import FormSpec, build

PORTAL = "https://portal.mdt.gov.mk/post-body-files/"
RETRIEVED = dt.date(2026, 10, 16)
NOTE = (
    "Барањето со прилозите се доставува до Министерството за економија и труд, како што е "
    "наведено во повикот. Проверете ја последната верзија на повикот пред да поднесете."
)
SIGNATURE_OO = "Mесто и дата"  # the form's own caption begins with a Latin M

Form = partial(FormSpec, programme="economy", retrieved=RETRIEVED, package_note_mk=NOTE)


def asked(key: str, note: str | None = None) -> dict:
    return {"key": key, "note_mk": note} if note else {"key": key}


TWO_MONTHS = "Според барањето: не постара од 2 (два) месеци."
NOTARY = "Според барањето: двете изјави од пакетот, во оригинал и заверени на нотар."
FEES = "Според барањето: 250,00 и 50,00 денари административна такса; сметките се во барањето."

STATE_AID = dict(
    cells=[
        ("Назив на деловниот субјект", "applicant_name"),
        ("Седиште и адреса", "applicant_address"),
        ("Матичен број", "applicant_embs"),
    ],
    appended=[("Даночен број", "applicant_edb")],
    signature_after="(Vendi dhe data)",
    by_hand_mk=(
        "Табелата за примената државна помош од мало значење по години и вкупниот износ, "
        "името на одговорното лице во изјавите А) и Б), местото и датумот"
    ),
    attachments=[asked("notarska_zaverka", NOTARY)],
)
# The two ОО calls' state-aid declaration (horizontal aid) has no table for the subject:
# only the person's name, the aid by year and the signature, all the applicant's.
STATE_AID_OO = dict(
    signature_after="(Vendi dhe data)",
    by_hand_mk=(
        "Табелата за примената хоризонтална државна помош по години и вкупниот износ, "
        "името на одговорното лице во изјавите А) и Б), местото и датумот"
    ),
    attachments=[asked("notarska_zaverka", NOTARY)],
)
DECLARATION = dict(
    lines=[("(име и презиме", "responsible_person"), ("(назив на претпријатие", "applicant_name")],
    by_hand_mk="Адресата на седиштето (улица и место) во изјавата",
    attachments=[asked("notarska_zaverka", NOTARY)],
)
OO_CELLS = [
    ("Полн назив на  деловниот субјект", "applicant_name"),
    ("Седиште и адреса", "applicant_address"),
    ("Контакт лице и мобилен телефон", "contact_person"),
    ("Е-маил адреса", "contact_email"),
    ("Веб страница на деловниот субјект", "website"),
    ("Одговорно лице", "responsible_person"),
    ("Матичен број на деловниот субјект", "applicant_embs"),
    ("Даночен број на деловниот субјект", "applicant_edb"),
    ("Жиро  сметка", "bank_account"),
    ("Банка депонент", "bank_name"),
    ("Број на вработени", "employees_exact"),
    ("Приоритетна дејност", "applicant_activity"),
]

FORMS = [
    # -- «Финансиска поддршка на ММСП и занаетчии», 2026
    Form(
        slug="msp-2026/barane",
        title_mk="Барање за финансиска поддршка на микро, мали и средни претпријатија и занаетчии",
        source_url=PORTAL
        + "javen-povik-za-finansiska-poddrska-na-mikro-mali-i-sredni-pretprijatija-i-zanaetcii-file-tMVR.doc",
        file="msp-barane.doc",
        converted="msp-barane.docx",
        version="2026-05-15",
        sha256="838fae8417d1e9ae",
        cells=[
            ("Полн назив на барателот", "applicant_name"),
            ("Седиште и адреса", "applicant_address"),
            ("Телефон", "contact_details"),
            ("Одговорно лице", "responsible_person"),
            ("Број на вработени", "employees_exact"),
            ("Даночен број", "applicant_edb"),
            ("Матичен број", "applicant_embs"),
            ("Жиро сметка", "bank_account"),
            ("Година на основање", "applicant_founded"),
            ("Претежна дејност", "applicant_activity"),
            ("Намена на бараните средства", "funding_purpose"),
            ("Вкупен износ на бараните средства", "requested_amount"),
        ],
        lines=[("(назив на деловниот субјект)", "applicant_name")],
        signature_after="(nënshkrimi i personit përgjegjës)",
        by_hand_mk=(
            "Во барањето: како е регистриран субјектот (микро, мало, средно претпријатие или "
            "занаетчија), краткиот опис на дејноста, описот на направените трошоци и ознаките ✓ "
            "за приложената документација"
        ),
        attachments=[
            asked("notarska_zaverka", NOTARY),
            asked("zanaetciska_dozvola", "Според барањето: ја доставуваат само занаетчиите."),
            asked("tekovna_sostojba", TWO_MONTHS),
            asked("stecaj_potvrda", TWO_MONTHS),
            asked("likvidacija_potvrda", TWO_MONTHS),
            asked(
                "av_lista_vraboteni",
                "Според барањето: листа на моментално вработени, не постара од 2 (два) месеци; ја доставуваат само претпријатијата.",
            ),
            asked(
                "ujp_potvrda",
                "Според барањето: уверение за состојбата на даноци, придонеси и други јавни давачки, не постаро од 6 (шест) месеци.",
            ),
            asked(
                "godishna_smetka",
                "Според барањето: за 2025 година, со биланс на успех (претпријатија) или биланс на приходи и расходи (занаетчии).",
            ),
            asked(
                "fakturi",
                "Според барањето: за набавената машина или алат; фактура на странски јазик со превод од овластен преведувач.",
            ),
            asked("izvod_plakanje"),
            asked("dokaz_godina_masina"),
            asked("kopija_ziro_smetka"),
            asked("administrativna_taksa", FEES),
        ],
    ),
    Form(
        slug="msp-2026/izjava-drzavna-pomos",
        title_mk="Изјава за доделена државна помош 2026",
        source_url=PORTAL
        + "javen-povik-za-finansiska-poddrska-na-mikro-mali-i-sredni-pretprijatija-i-zanaetcii-file-WNW2.doc",
        file="msp-izjava-drzavna-pomos.doc",
        converted="msp-izjava-drzavna-pomos.docx",
        version="2026-05-15",
        sha256="2bacb03eb7f4d5f8",
        **STATE_AID,
    ),
    Form(
        slug="msp-2026/izjava",
        title_mk="Изјава 2026 (дека субјектот не користел средства од Буџетот за истата намена)",
        source_url=PORTAL
        + "javen-povik-za-finansiska-poddrska-na-mikro-mali-i-sredni-pretprijatija-i-zanaetcii-file-uVLz.docx",
        file="msp-izjava.docx",
        converted=None,
        version="2026-05-15",
        sha256="e517de62eb1455b7",
        signature_after="(nënshkrimi i kryerësit",
        **DECLARATION,
    ),
    # -- «Општествено прифатливи практики» (Барање – ОО 2026)
    Form(
        slug="socijalni-praktiki-2026/barane",
        title_mk="Барање – ОО 2026 (стандарди и извештаи за општествено прифатливи практики)",
        source_url=PORTAL
        + "javen-povik-za-nadomesti-standardi-od-oblasta-na-dokumenti-i-izvestai-od-blasta-na-prerabotuvacka-industrija-potrebni-za-poddrska-na-razvivanje-oddrzuvanje-i-primenuvanje-na-socijalno-prifatlivi-praktiki-na-delovnite-file-1s9N.doc",
        file="soc-barane.doc",
        converted="soc-barane.docx",
        version="2026-08-24",
        sha256="02bc4daa8853d24c",
        cells=OO_CELLS,
        lines=[("(полн назив на деловниот субјект)", "applicant_name")],
        signature_after=SIGNATURE_OO,
        by_hand_mk=(
            "Во барањето: главните производи и услуги, продажбата за 2025 и проекцијата за 2026, "
            "сертификациското тело, видот на сертификација (само еден), датумот на договорот и "
            "трошоците во денари"
        ),
        attachments=[
            asked("notarska_zaverka", NOTARY),
            asked("tekovna_sostojba", TWO_MONTHS),
            asked("ujp_potvrda", "Според барањето: не постаро од 2 (два) месеци."),
            asked(
                "ekonomsko_finansiska_informacija",
                "Според барањето: не постара од 2 (два) месеци, со позитивно работење.",
            ),
            asked(
                "dogovor_izveduvac",
                "Според барањето: со сертификациското тело или телото за оценување, склучен пред датумот на сертификатот или извештајот.",
            ),
            asked(
                "sertifikat_izvestaj",
                "Според барањето: од акредитирано тело, издаден во 2025 или 2026 година.",
            ),
            asked("fakturi"),
            asked("izvod_plakanje"),
            asked("administrativna_taksa", FEES),
        ],
    ),
    Form(
        slug="socijalni-praktiki-2026/izjava-drzavna-pomos",
        title_mk="Изјава за доделена државна помош 2026",
        source_url=PORTAL
        + "javen-povik-za-nadomesti-standardi-od-oblasta-na-dokumenti-i-izvestai-od-blasta-na-prerabotuvacka-industrija-potrebni-za-poddrska-na-razvivanje-oddrzuvanje-i-primenuvanje-na-socijalno-prifatlivi-praktiki-na-delovnite-file-z8pZ.doc",
        file="soc-izjava-drzavna-pomos.doc",
        converted="soc-izjava-drzavna-pomos.docx",
        version="2026-08-24",
        sha256="6648e4dff1c795fd",
        **STATE_AID_OO,
    ),
    # -- «Соработка со универзитетите» (ПИПОО 2026)
    Form(
        slug="univerziteti-2026/barane",
        title_mk="Барање ПИПОО 2026 (соработка помеѓу преработувачката индустрија и универзитетите)",
        source_url=PORTAL
        + "javen-povik-za-zajaknuvanje-na-sorbotkata-pomegju-delovnite-subjekti-od-prerabotuvackata-industrija-i-univerzitetite-preku-realizacija-na-zaednicki-proekti-so-vkupen-iznos-od-500000000-denari-file-cqsv.doc",
        file="uni-barane.doc",
        converted="uni-barane.docx",
        version="2026-08-24",
        sha256="0e67c1438bfb096f",
        cells=OO_CELLS,
        lines=[("(полн назив на деловниот субјект)", "applicant_name")],
        signature_after=SIGNATURE_OO,
        by_hand_mk=(
            "Во барањето: главните производи и услуги, продажбата за 2025 и проекцијата за 2026 "
            "и податоците за заедничкиот проект со универзитетот"
        ),
        attachments=[
            asked("notarska_zaverka", NOTARY),
            asked(
                "izvestaj_proekt",
                "Според барањето: подготвен според Упатството објавено со повикот.",
            ),
            asked("tekovna_sostojba", TWO_MONTHS),
            asked(
                "ekonomsko_finansiska_informacija",
                "Според барањето: не постара од 2 (два) месеци, со позитивно работење.",
            ),
            asked("ujp_potvrda", "Според барањето: не постаро од 2 (два) месеци."),
            asked(
                "av_lista_vraboteni",
                "Според барањето: доказ за 5 (пет) редовно вработени со полно работно време, не постар од 2 (два) месеци.",
            ),
            asked(
                "dogovor_izveduvac",
                "Според барањето: со изготвувачот, склучен во 2025 или 2026 година.",
            ),
            asked("fakturi", "Според барањето: фактура од изготвувачот од 2025 или 2026 година."),
            asked("izvod_plakanje"),
            asked("administrativna_taksa", FEES),
        ],
    ),
    Form(
        slug="univerziteti-2026/izjava-drzavna-pomos",
        title_mk="Изјава за доделена државна помош 2026",
        source_url=PORTAL
        + "javen-povik-za-zajaknuvanje-na-sorbotkata-pomegju-delovnite-subjekti-od-prerabotuvackata-industrija-i-univerzitetite-preku-realizacija-na-zaednicki-proekti-so-vkupen-iznos-od-500000000-denari-file-yzbm.doc",
        file="uni-izjava-drzavna-pomos.doc",
        converted="uni-izjava-drzavna-pomos.docx",
        version="2026-08-24",
        sha256="03ea911ca92e64c3",
        **STATE_AID_OO,
    ),
    # The two ОО calls publish the same «Изјава - 2026» (identical files).
    Form(
        slug="oo-2026/izjava",
        title_mk="Изјава 2026",
        source_url=PORTAL
        + "javen-povik-za-zajaknuvanje-na-sorbotkata-pomegju-delovnite-subjekti-od-prerabotuvackata-industrija-i-univerzitetite-preku-realizacija-na-zaednicki-proekti-so-vkupen-iznos-od-500000000-denari-file-G92p.docx",
        file="uni-izjava.docx",
        converted=None,
        version="2026-08-24",
        sha256="11223fd8928ea6d5",
        signature_after="(nënshkrimi i drejtuesit)",
        **DECLARATION,
    ),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--forms", default="var/forms/economy")
    args = parser.parse_args()
    for form in FORMS:
        print(f"wrote {build(form, Path(args.forms))}")


if __name__ == "__main__":
    main()
