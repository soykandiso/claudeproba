"""Invented example data for the clickable demo at /demo.

NOTHING HERE IS REAL. The calls, amounts, clause numbers, quotes and snapshot ids
are made up so the screens can be judged before the matching engine exists. The
institutions are real names only so the layout carries realistic lengths.

This is not reference data (that lives in data/) and not a fixture for the
evaluation harness. Delete this module together with app/web/demo.py once P2
session 28 renders the shortlist from real match runs.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

EUR_TO_MKD = 61.5  # docs/decisions.md, "Rate used throughout"


@dataclass(frozen=True)
class Citation:
    quote: str
    clause: str
    snapshot_id: str
    char_start: int
    char_end: int
    source_url: str
    retrieved: date


@dataclass(frozen=True)
class Reason:
    text: str
    # satisfied / not_satisfied / unclear as reported, or attest for an applicant_attest
    # criterion only the company can confirm (docs/matching.md §7)
    outcome: str
    citation: Citation
    decided_by: str  # "rule" (hard_filter) or "model"


@dataclass(frozen=True)
class DemoCall:
    slug: str
    title: str
    institution: str
    reference: str
    verdict: str
    max_eur: int
    deadline: date
    last_verified: date
    summary: str
    reasons: list[Reason] = field(default_factory=list)

    @property
    def max_mkd(self) -> int:
        return round(self.max_eur * EUR_TO_MKD, -3)


PROFILE = {
    "entity": "ДООЕЛ",
    "nace": "62.01 Компјутерско програмирање",
    "municipality": "Центар, Скопски плански регион",
    "founded": "2022",
    "employees": "2–9",
    "turnover": "до 10 милиони МКД",
    "investment": "Дигитализација, опрема",
    "amount": "1–3 милиони МКД",
    "timeline": "Во наредните 6 месеци",
}


def _calls(today: date) -> list[DemoCall]:
    verified = today - timedelta(days=1)

    def cite(quote, clause, snap, start, url, days_ago=1):
        return Citation(
            quote, clause, snap, start, start + len(quote), url, today - timedelta(days=days_ago)
        )

    fitr = "https://fitr.mk/primer/povik-2026-03"
    mdt = "https://portal.mdt.gov.mk/primer/digitalizacija-2026.pdf"
    avrm = "https://av.gov.mk/primer/merka-2026-14"
    skopje = "https://skopje.gov.mk/primer/zeleni-investicii-2026.pdf"
    eu = "https://ec.europa.eu/info/funding-tenders/primer/DIGITAL-2026-SME"
    ipard = "https://www.ipardpa.gov.mk/primer/ipard-01-2026"

    return [
        DemoCall(
            slug="fitr-novoosnovani",
            title="Кофинансирани грантови за новоосновани претпријатија и спин-оф компании",
            institution="Фонд за иновации и технолошки развој",
            reference="ФИТР-КГ-03/2026",
            verdict="eligible",
            max_eur=30_000,
            deadline=today + timedelta(days=38),
            last_verified=verified,
            summary="Грант до 85% од прифатливите трошоци за развој на нов производ или услуга.",
            reasons=[
                Reason(
                    "Фирмата е основана пред помалку од 6 години.",
                    "satisfied",
                    cite(
                        "Право на учество имаат микро и мали трговски друштва кои се "
                        "регистрирани најмногу шест години пред денот на објавување на повикот.",
                        "Член 4, став 1",
                        "snap_7f3a1c",
                        4812,
                        fitr,
                    ),
                    "rule",
                ),
                Reason(
                    "Бројот на вработени е во границите за микро претпријатие.",
                    "satisfied",
                    cite(
                        "Барателот има најмногу 49 вработени според последниот годишен "
                        "извештај доставен до Централниот регистар.",
                        "Член 4, став 2",
                        "snap_7f3a1c",
                        5104,
                        fitr,
                    ),
                    "rule",
                ),
                Reason(
                    "Дејноста 62.01 не е меѓу исклучените дејности.",
                    "satisfied",
                    cite(
                        "Не се прифатливи баратели чија главна дејност е трговија на мало, "
                        "угостителство или производство на тутунски производи.",
                        "Член 5",
                        "snap_7f3a1c",
                        5690,
                        fitr,
                    ),
                    "rule",
                ),
            ],
        ),
        DemoCall(
            slug="mdt-digitalizacija",
            title=(
                "Програма за конкурентност: поддршка за дигитализација "
                "на микро, мали и средни претпријатија"
            ),
            institution="Министерство за економија и труд",
            reference="МЕТ-ДИГ-2026",
            verdict="likely_eligible",
            max_eur=6_000,
            deadline=today + timedelta(days=9),
            last_verified=verified,
            summary="Повраток до 50% од трошоците за софтвер, хардвер и обука за дигитализација.",
            reasons=[
                Reason(
                    "Планираната инвестиција е дигитализација, што повикот ја финансира.",
                    "satisfied",
                    cite(
                        "Прифатливи трошоци се набавка на софтверски решенија, компјутерска "
                        "опрема и обука на вработените за нивна употреба.",
                        "Точка 3.1",
                        "snap_2b90de",
                        2230,
                        mdt,
                    ),
                    "model",
                ),
                Reason(
                    "Повикот бара потврда дека немате неплатени даночни обврски. "
                    "Тоа го потврдувате вие, не може да се провери од профилот.",
                    "attest",
                    cite(
                        "Кон барањето се приложува потврда од Управата за јавни приходи за "
                        "платени даноци, не постара од 30 дена.",
                        "Точка 5.2",
                        "snap_2b90de",
                        3918,
                        mdt,
                    ),
                    "model",
                ),
            ],
        ),
        DemoCall(
            slug="skopje-zeleni",
            title="Поддршка за зелени инвестиции на мали претпријатија со седиште во Град Скопје",
            institution="Град Скопје",
            reference="ГС-ЗИ-07/2026",
            verdict="needs_verification",
            max_eur=4_000,
            deadline=today + timedelta(days=52),
            last_verified=today - timedelta(days=4),
            summary="Субвенција за енергетска ефикасност и соларни панели во деловни простори.",
            reasons=[
                Reason(
                    "Седиштето е во општина на Град Скопје.",
                    "satisfied",
                    cite(
                        "Барателот има регистрирано седиште на подрачјето на Град Скопје.",
                        "Член 3",
                        "snap_c41e07",
                        1377,
                        skopje,
                        days_ago=4,
                    ),
                    "rule",
                ),
                Reason(
                    "Повикот финансира зелени инвестиции. Вашата планирана инвестиција е "
                    "дигитализација, па треба да проверите дали опремата се квалификува.",
                    "not_satisfied",
                    cite(
                        "Средствата се наменети исклучиво за мерки за енергетска ефикасност "
                        "и за производство на енергија од обновливи извори.",
                        "Член 6",
                        "snap_c41e07",
                        2045,
                        skopje,
                        days_ago=4,
                    ),
                    "model",
                ),
            ],
        ),
        DemoCall(
            slug="avrm-vrabotuvanje",
            title="Субвенционирано вработување на млади лица до 29 години",
            institution="Агенција за вработување на Република Северна Македонија",
            reference="АВРСМ-14/2026",
            verdict="needs_verification",
            max_eur=3_600,
            deadline=today + timedelta(days=21),
            last_verified=verified,
            summary="Месечна субвенција на плата за секое ново вработување во траење од 12 месеци.",
            reasons=[
                Reason(
                    "Повикот бара во последните 3 месеци да немате намалено број на вработени. "
                    "Профилот не го содржи тој податок.",
                    "unclear",
                    cite(
                        "Работодавачот во последните три месеци пред објавувањето на јавниот "
                        "повик не го намалил бројот на вработени.",
                        "Дел II, точка 2",
                        "snap_91aa40",
                        3302,
                        avrm,
                    ),
                    "model",
                ),
            ],
        ),
        DemoCall(
            slug="eu-digital-sme",
            title="Digital Europe: поддршка за усвојување вештачка интелигенција во МСП",
            institution="Европска комисија, Funding & Tenders Portal",
            reference="DIGITAL-2026-AI-SME-04",
            verdict="needs_verification",
            max_eur=60_000,
            deadline=today + timedelta(days=74),
            last_verified=verified,
            summary="Конзорциумски проекти за воведување ВИ во производство и услуги.",
            reasons=[
                Reason(
                    "Листата на прифатливи земји е во посебен документ што сè уште не е "
                    "проверен за Северна Македонија.",
                    "unclear",
                    cite(
                        "Eligible countries: as described in the call document, section 6.",
                        "Topic conditions",
                        "snap_e5d213",
                        912,
                        eu,
                    ),
                    "model",
                ),
            ],
        ),
        DemoCall(
            slug="ipard-merka-1",
            title="ИПАРД III, Мерка 1: инвестиции во физички средства на земјоделски стопанства",
            institution="Агенција за финансиска поддршка во земјоделството и руралниот развој",
            reference="ИПАРД-01/2026",
            verdict="not_eligible",
            max_eur=700_000,
            deadline=today + timedelta(days=45),
            last_verified=today - timedelta(days=2),
            summary=(
                "Кофинансирање на механизација, објекти и опрема "
                "за примарно земјоделско производство."
            ),
            reasons=[
                Reason(
                    "Повикот е само за земјоделски стопанства. Вашиот вид на субјект е ДООЕЛ "
                    "со дејност 62.01.",
                    "not_satisfied",
                    cite(
                        "Корисник на мерката е земјоделско стопанство запишано во Единствениот "
                        "регистар на земјоделски стопанства.",
                        "Член 7, став 1",
                        "snap_4d7f88",
                        6120,
                        ipard,
                        days_ago=2,
                    ),
                    "rule",
                ),
            ],
        ),
    ]


def shortlist(today: date | None = None) -> list[DemoCall]:
    return _calls(today or date.today())


def find(slug: str, today: date | None = None) -> DemoCall | None:
    return next((c for c in shortlist(today) if c.slug == slug), None)
