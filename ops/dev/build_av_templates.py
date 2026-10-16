"""Template set 1 (roadmap P5 s58): the Employment Agency's forms for employers, as templates.

    PYTHONPATH=. uv run python ops/dev/build_av_templates.py [--forms var/forms/av]

Reads the official forms as downloaded from https://av.gov.mk/obrasci.nspx (15.10.2026) and
writes each as a template with its manifest into app/documents/templates/av/<document>/.
The form itself is not retyped: `app/documents/derive.py` places fields into its empty answer
cells only, and fails if a label is gone, which is how a changed form is noticed.

To refresh after АВ publishes a new form: download it into --forms (by hand, as a person: the
form is a document for applicants, not a page the crawler reads), convert a .doc with Word
(«Save as .docx»), set its date and hash below, run this, then `flask documents check`.

What is filled, what is marked, what is left: the employer's identity from the order (name,
ЕМБС, ЕДБ, address) and the profile (municipality, activity); the applicant's alone (contact
person, phone, e-mail, salary, the trainee's allowance, the authorised person, the signature)
as markers; every cell about the vacancy or the trainees left blank as АВ printed it, with
one checklist line saying so. «Пополнува Агенцијата» is never touched.
"""

import argparse
import datetime as dt
from functools import partial
from pathlib import Path

from app.documents.forms import FormSpec, build

OBRASCI = "https://av.gov.mk/content/Обрасци/"
RETRIEVED = dt.date(2026, 10, 15)
COMMON_NOTE = (
    "Пријавата се поднесува во работниот клуб на центарот за вработување. Таму проверете кои "
    "образци се потребни за мерката на која аплицирате."
)


Form = partial(FormSpec, programme="av", retrieved=RETRIEVED, package_note_mk=COMMON_NOTE)


FORMS = [
    Form(
        slug="ppr",
        title_mk="Пријава за потреба од работник (образец ППР)",
        source_url=OBRASCI + "PPR 24 word.docx",
        file="PPR 24 word.docx",
        converted=None,
        version="2024-04-11",
        sha256="589c90580c063687",
        cells=[
            ("Назив на работодавачот", "applicant_name"),
            ("Единствен матичен број на субјектот", "applicant_embs"),
            ("Шифра и назив на претежната дејност", "applicant_activity"),
            ("Улица и број", "applicant_address"),
            ("Општина", "applicant_municipality"),
            ("Телефон", "contact_phone"),
            ("Е-маил", "contact_email"),
            ("Единствен даночен број", "applicant_edb"),
            ("Лице за контакт", "contact_person"),
            ("Паричен износ на основна плата", "basic_salary"),
            ("Адреса за контакт", "applicant_address"),
            ("Телефон за контакт", "contact_phone"),
            ("Е-пошта за контакт", "contact_email"),
        ],
        signature_after="Датум / Data",
        by_hand_mk=(
            "Празните полиња за работното место (занимање, работно време, образование, "
            "искуство, начин на обезбедување работници)"
        ),
    ),
    Form(
        slug="oglas-praktikant",
        title_mk="Оглас за практикантска работа",
        source_url=OBRASCI + "Oglas za praktikant.doc",
        file="Oglas za praktikant.doc",
        converted="Oglas za praktikant.docx",
        version="2022-09-16",
        sha256="1fc98fcad334dd67",
        cells=[
            ("Назив", "applicant_name"),
            ("Единствен матичен број на субјектот", "applicant_embs"),
            ("Висина на месечен надоместок", "intern_monthly_allowance"),
            ("Адреса", "applicant_address"),
            ("Телефон", "contact_phone"),
            ("Е-пошта", "contact_email"),
        ],
        by_hand_mk=(
            "Празните полиња на огласот (број и датум на огласот, работното место, "
            "предусловите за практикантот)"
        ),
    ),
    Form(
        slug="ovlastuvanje-praktikant",
        title_mk="Овластување за пријавување на практикант/и",
        source_url=OBRASCI + "Prijava praktikant.docx",
        file="Prijava praktikant.docx",
        converted=None,
        version="2022-09-16",
        sha256="b0a89538a2e84feb",
        cells=[],
        # One wide cell per row, the answer written after the label.
        appended=[
            ("Назив на работодавачот", "applicant_name"),
            ("Седиште и адреса на работодавачот", "applicant_address"),
            ("Единствен даночен број на работодавачот", "applicant_edb"),
            ("Единствен матичен број", "applicant_embs"),
            ("Овластено лице", "authorized_person"),
        ],
        signature_after="(потпис и печат на работодавачот)",
        by_hand_mk=(
            "Списокот на практиканти (име и презиме, ЕМБГ, договор, почеток и времетраење); "
            "ги внесувате вие, најмногу дваесет на образец"
        ),
    ),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--forms", default="var/forms/av")
    args = parser.parse_args()
    for form in FORMS:
        print(f"wrote {build(form, Path(args.forms))}")


if __name__ == "__main__":
    main()
