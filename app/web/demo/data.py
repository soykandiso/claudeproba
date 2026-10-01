"""Invented calls for the demo platform at /demo.

NOTHING HERE IS REAL. The calls, amounts, clause numbers and document texts are
made up so the whole journey can be tried before P1 has ingested enough real
calls and P2 has built matching over them. Institution names are real only so
the layout carries realistic lengths.

Each call carries the text of its (invented) source document, assembled from
numbered clauses. Citations are located in that text in code, the same way
app/ingestion/extract.py locates them in a real snapshot, so every
(snapshot_id, char_start, char_end) shown in the demo round-trips to its quote.
tests/test_demo.py checks that for every published call.

Not reference data (that lives in data/) and not an evaluation fixture. Delete
this package once P2 session 28 renders the shortlist from real match runs.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from functools import cached_property

from app.matching import intake
from app.matching.hard_filter import Range
from app.matching.operators import Operator, ProfileField
from app.models.enums import CriterionKind

EUR_TO_MKD = 61.5  # docs/decisions.md, "Rate used throughout"

# The intake question, not a demo list of its own: the calls below name these keys.
PURPOSES = intake.PURPOSES


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
class Criterion:
    key: str
    label: str  # the condition, in the applicant's words
    kind: CriterionKind
    clause: str  # the clause the quote comes from
    quote: str  # must be verbatim in the document; extraction review catches it if not
    # hard_structured
    field: ProfileField | None = None
    operator: Operator | None = None
    value: object = None
    # narrative_verify: the demo has no model, so the answer is pre-recorded. With
    # purpose_any set it is satisfied when the profile names one of those purposes.
    purpose_any: frozenset[str] = frozenset()
    recorded: str = "unclear"
    confidence: float = 0.9
    model_note: str = ""
    # What a reviewer changes the quote to (extraction review demo only).
    corrected_quote: str | None = None


@dataclass(frozen=True)
class DemoCall:
    slug: str
    title: str
    institution: str
    reference: str
    source_url: str
    snapshot_id: str
    summary: str
    max_eur: int
    deadline: date
    last_verified: date
    clauses: tuple[tuple[str, str], ...]
    criteria: tuple[Criterion, ...]
    documents: tuple[str, ...]
    purposes: frozenset[str] = frozenset()
    priority_nace: tuple[str, ...] = ()  # empty: open to every activity
    project_mkd: Range | None = None  # eligible project size; None: no limit stated
    cofinancing_pct: int = 0
    published: bool = True  # False: waiting in the extraction review queue
    review_flag: str = ""

    @property
    def max_mkd(self) -> int:
        return int(round(self.max_eur * EUR_TO_MKD, -3))

    @cached_property
    def document_text(self) -> str:
        parts = [f"{self.institution}\n{self.title}\n{self.reference}\n"]
        parts += [f"\n{ref}\n{text}\n" for ref, text in self.clauses]
        return "".join(parts)

    def citation(self, criterion: Criterion, quote: str | None = None) -> Citation | None:
        """Locate the quote in the document. None when it is not there verbatim."""
        quote = quote or criterion.quote
        start = self.document_text.find(quote)
        if start == -1:
            return None
        return Citation(
            quote=quote,
            clause=criterion.clause,
            snapshot_id=self.snapshot_id,
            char_start=start,
            char_end=start + len(quote),
            source_url=self.source_url,
            retrieved=self.last_verified,
        )


def _hard(key, label, clause, quote, field_, operator, value, **kw):
    return Criterion(
        key, label, CriterionKind.HARD_STRUCTURED, clause, quote, field_, operator, value, **kw
    )


def _narrative(key, label, clause, quote, **kw):
    return Criterion(key, label, CriterionKind.NARRATIVE_VERIFY, clause, quote, **kw)


def _attest(key, label, clause, quote):
    return Criterion(key, label, CriterionKind.APPLICANT_ATTEST, clause, quote)


F = ProfileField
O = Operator  # noqa: E741


def _calls(today: date) -> list[DemoCall]:
    def days(n: int) -> date:
        return today + timedelta(days=n)

    return [
        DemoCall(
            slug="fitr-novoosnovani",
            title="Кофинансирани грантови за новоосновани претпријатија и спин-оф компании",
            institution="Фонд за иновации и технолошки развој",
            reference="ФИТР-КГ-03/2026",
            source_url="https://fitr.mk/primer/povik-2026-03",
            snapshot_id="snap_7f3a1c",
            summary="Грант до 85% од прифатливите трошоци за развој на нов производ или услуга.",
            max_eur=30_000,
            deadline=days(38),
            last_verified=days(-1),
            purposes=frozenset({"digital", "rnd", "equipment"}),
            project_mkd=Range(300_000, 2_200_000),
            cofinancing_pct=15,
            clauses=(
                (
                    "Член 1",
                    "Со овој јавен повик се доделуваат кофинансирани грантови за "
                    "новоосновани претпријатија и спин-оф компании.",
                ),
                (
                    "Член 4, став 1",
                    "Право на учество имаат микро и мали трговски друштва кои се регистрирани "
                    "најмногу шест години пред денот на објавување на повикот.",
                ),
                (
                    "Член 4, став 2",
                    "Барателот има најмногу 49 вработени според последниот годишен извештај "
                    "доставен до Централниот регистар.",
                ),
                (
                    "Член 5",
                    "Не се прифатливи баратели чија главна дејност е трговија на мало, "
                    "угостителство или производство на тутунски производи.",
                ),
                (
                    "Член 6",
                    "Се финансираат проекти за развој на нов или значително подобрен производ, "
                    "услуга или технолошки процес.",
                ),
                (
                    "Член 8",
                    "Фондот кофинансира до 85% од прифатливите трошоци, а најмногу 30.000 евра "
                    "по барател. Барателот обезбедува најмалку 15% од сопствени средства.",
                ),
            ),
            criteria=(
                _hard(
                    "age",
                    "Фирмата е регистрирана најмногу шест години пред објавувањето на повикот.",
                    "Член 4, став 1",
                    "регистрирани најмногу шест години пред денот на објавување на повикот",
                    F.AGE_MONTHS,
                    O.LTE,
                    72,
                ),
                _hard(
                    "form",
                    "Барателот е микро или мало трговско друштво.",
                    "Член 4, став 1",
                    "Право на учество имаат микро и мали трговски друштва",
                    F.ENTITY_TYPE,
                    O.IN,
                    ["micro", "small"],
                ),
                _hard(
                    "headcount",
                    "Фирмата има најмногу 49 вработени.",
                    "Член 4, став 2",
                    "Барателот има најмногу 49 вработени според последниот годишен извештај "
                    "доставен до Централниот регистар.",
                    F.HEADCOUNT,
                    O.LTE,
                    49,
                ),
                _hard(
                    "nace",
                    "Главната дејност не е трговија на мало, угостителство или тутун.",
                    "Член 5",
                    "Не се прифатливи баратели чија главна дејност е трговија на мало, "
                    "угостителство или производство на тутунски производи.",
                    F.NACE_CODE,
                    O.PREFIX_NOT_IN,
                    ["47", "56", "12"],
                ),
                _narrative(
                    "innovation",
                    "Проектот развива нов или значително подобрен производ, услуга или процес.",
                    "Член 6",
                    "Се финансираат проекти за развој на нов или значително подобрен производ, "
                    "услуга или технолошки процес.",
                    purpose_any=frozenset({"rnd", "digital"}),
                    confidence=0.82,
                    model_note="Планираната инвестиција е развој или дигитализација, што "
                    "одговара на намената од Член 6.",
                ),
            ),
            documents=(
                "Тековна состојба од Централниот регистар, не постара од 6 месеци",
                "Биланс на состојба и биланс на успех за претходната година",
                "Образец за апликација на Фондот, пополнет",
                "Бизнис план со опис на иновацијата",
                "Буџет на проектот според образецот од повикот",
            ),
        ),
        DemoCall(
            slug="met-digitalizacija",
            title=(
                "Програма за конкурентност: поддршка за дигитализација "
                "на микро, мали и средни претпријатија"
            ),
            institution="Министерство за економија и труд",
            reference="МЕТ-ДИГ-2026",
            source_url="https://economy.gov.mk/primer/digitalizacija-2026.pdf",
            snapshot_id="snap_2b90de",
            summary="Повраток до 50% од трошоците за софтвер, хардвер и обука за дигитализација.",
            max_eur=6_000,
            deadline=days(9),
            last_verified=days(-1),
            purposes=frozenset({"digital"}),
            project_mkd=Range(100_000, 750_000),
            cofinancing_pct=50,
            clauses=(
                (
                    "Точка 2.1",
                    "Корисници на мерката се микро, мали и средни претпријатија и трговци "
                    "поединци со најмалку една година деловна активност.",
                ),
                (
                    "Точка 2.2",
                    "Големи претпријатија, здруженија на граѓани и единици на локалната "
                    "самоуправа не можат да бидат корисници.",
                ),
                (
                    "Точка 3.1",
                    "Прифатливи трошоци се набавка на софтверски решенија, компјутерска опрема "
                    "и обука на вработените за нивна употреба.",
                ),
                (
                    "Точка 5.2",
                    "Кон барањето се приложува потврда од Управата за јавни приходи за платени "
                    "даноци, не постара од 30 дена.",
                ),
            ),
            criteria=(
                _hard(
                    "form",
                    "Барателот не е големо претпријатие, здружение или општина.",
                    "Точка 2.2",
                    "Големи претпријатија, здруженија на граѓани и единици на локалната "
                    "самоуправа не можат да бидат корисници.",
                    F.ENTITY_TYPE,
                    O.NOT_IN,
                    ["large", "ngo", "municipality", "individual"],
                ),
                _hard(
                    "age",
                    "Фирмата има најмалку една година деловна активност.",
                    "Точка 2.1",
                    "со најмалку една година деловна активност",
                    F.AGE_MONTHS,
                    O.GTE,
                    12,
                ),
                _narrative(
                    "costs",
                    "Планираната инвестиција е меѓу прифатливите трошоци.",
                    "Точка 3.1",
                    "Прифатливи трошоци се набавка на софтверски решенија, компјутерска опрема "
                    "и обука на вработените за нивна употреба.",
                    purpose_any=frozenset({"digital"}),
                    confidence=0.88,
                    model_note="Дигитализацијата одговара на прифатливите трошоци од точка 3.1.",
                ),
                _attest(
                    "tax",
                    "Немате неплатени даночни обврски. Тоа го потврдувате вие, не може да се "
                    "провери од профилот.",
                    "Точка 5.2",
                    "потврда од Управата за јавни приходи за платени даноци",
                ),
            ),
            documents=(
                "Потврда од Управата за јавни приходи за платени даноци, не постара од 30 дена",
                "Понуди или фактури за софтверот и опремата",
                "Тековна состојба од Централниот регистар",
            ),
        ),
        DemoCall(
            slug="fitr-komercijalizacija",
            title="Кофинансирани грантови за комерцијализација на иновации",
            institution="Фонд за иновации и технолошки развој",
            reference="ФИТР-КИ-04/2026",
            source_url="https://fitr.mk/primer/povik-2026-04",
            snapshot_id="snap_a61c09",
            summary="До 60% од трошоците за пазарно воведување на развиен иновативен производ.",
            max_eur=100_000,
            deadline=days(61),
            last_verified=days(-2),
            purposes=frozenset({"rnd", "equipment", "export"}),
            project_mkd=Range(1_500_000, 11_000_000),
            cofinancing_pct=40,
            clauses=(
                (
                    "Член 3",
                    "Право на учество имаат микро, мали и средни претпријатија со најмногу "
                    "249 вработени.",
                ),
                (
                    "Член 6",
                    "Проектот мора да се однесува на комерцијализација на производ или услуга "
                    "што е резултат на сопствено истражување и развој.",
                ),
                ("Член 9", "Барателот обезбедува најмалку 40% од вкупниот буџет на проектот."),
            ),
            criteria=(
                _hard(
                    "form",
                    "Барателот е микро, мало или средно претпријатие.",
                    "Член 3",
                    "Право на учество имаат микро, мали и средни претпријатија",
                    F.ENTITY_TYPE,
                    O.IN,
                    ["micro", "small", "medium"],
                ),
                _hard(
                    "headcount",
                    "Фирмата има најмногу 249 вработени.",
                    "Член 3",
                    "со најмногу 249 вработени",
                    F.HEADCOUNT,
                    O.LTE,
                    249,
                ),
                _narrative(
                    "rnd",
                    "Производот е резултат на сопствено истражување и развој.",
                    "Член 6",
                    "производ или услуга што е резултат на сопствено истражување и развој",
                    purpose_any=frozenset({"rnd"}),
                    confidence=0.74,
                    model_note="Профилот не наведува истражување и развој, па условот од "
                    "Член 6 не може да се потврди.",
                ),
            ),
            documents=(
                "Доказ за сопствено истражување и развој (патент, прототип, извештај)",
                "Маркетинг план за воведување на пазар",
                "Финансиски извештаи за последните две години",
            ),
        ),
        DemoCall(
            slug="skopje-zeleni",
            title="Поддршка за зелени инвестиции на мали претпријатија со седиште во Град Скопје",
            institution="Град Скопје",
            reference="ГС-ЗИ-07/2026",
            source_url="https://skopje.gov.mk/primer/zeleni-investicii-2026.pdf",
            snapshot_id="snap_c41e07",
            summary="Субвенција за енергетска ефикасност и соларни панели во деловни простори.",
            max_eur=4_000,
            deadline=days(52),
            last_verified=days(-4),
            purposes=frozenset({"green"}),
            project_mkd=Range(150_000, 1_500_000),
            cofinancing_pct=30,
            clauses=(
                (
                    "Член 3",
                    "Барателот има регистрирано седиште на подрачјето на Град Скопје и "
                    "најмногу 49 вработени.",
                ),
                (
                    "Член 6",
                    "Средствата се наменети исклучиво за мерки за енергетска ефикасност и за "
                    "производство на енергија од обновливи извори.",
                ),
            ),
            criteria=(
                _attest(
                    "seat",
                    "Седиштето на фирмата е на подрачјето на Град Скопје.",
                    "Член 3",
                    "регистрирано седиште на подрачјето на Град Скопје",
                ),
                _hard(
                    "headcount",
                    "Фирмата има најмногу 49 вработени.",
                    "Член 3",
                    "најмногу 49 вработени",
                    F.HEADCOUNT,
                    O.LTE,
                    49,
                ),
                _narrative(
                    "green",
                    "Инвестицијата е мерка за енергетска ефикасност или обновлива енергија.",
                    "Член 6",
                    "Средствата се наменети исклучиво за мерки за енергетска ефикасност и за "
                    "производство на енергија од обновливи извори.",
                    purpose_any=frozenset({"green"}),
                    confidence=0.91,
                    model_note="Повикот финансира само енергетска ефикасност и обновлива "
                    "енергија; проверете дали планираната опрема спаѓа тука.",
                ),
            ),
            documents=(
                "Енергетска ревизија или проценка на заштедата",
                "Понуди за опремата",
                "Доказ за сопственост или закуп на деловниот простор",
            ),
        ),
        DemoCall(
            slug="avrsm-mladi",
            title="Субвенционирано вработување на млади лица до 29 години",
            institution="Агенција за вработување на Република Северна Македонија",
            reference="АВРСМ-14/2026",
            source_url="https://av.gov.mk/primer/merka-2026-14",
            snapshot_id="snap_91aa40",
            summary="Месечна субвенција на плата за секое ново вработување во траење од 12 месеци.",
            max_eur=3_600,
            deadline=days(21),
            last_verified=days(-1),
            purposes=frozenset({"jobs"}),
            clauses=(
                (
                    "Дел II, точка 1",
                    "Право на учество имаат работодавачи од приватниот сектор со најмалку еден "
                    "вработен.",
                ),
                (
                    "Дел II, точка 2",
                    "Работодавачот во последните три месеци пред објавувањето на јавниот повик "
                    "не го намалил бројот на вработени.",
                ),
                (
                    "Дел III",
                    "Субвенцијата се користи за ново вработување на незапишано лице до 29 "
                    "години, на неопределено време.",
                ),
            ),
            criteria=(
                _hard(
                    "headcount",
                    "Фирмата има најмалку еден вработен.",
                    "Дел II, точка 1",
                    "со најмалку еден вработен",
                    F.HEADCOUNT,
                    O.GTE,
                    1,
                ),
                _attest(
                    "no_layoffs",
                    "Во последните три месеци не сте го намалиле бројот на вработени.",
                    "Дел II, точка 2",
                    "Работодавачот во последните три месеци пред објавувањето на јавниот повик "
                    "не го намалил бројот на вработени.",
                ),
                _narrative(
                    "new_job",
                    "Планирате ново вработување на млад човек.",
                    "Дел III",
                    "за ново вработување на незапишано лице до 29 години",
                    purpose_any=frozenset({"jobs"}),
                    confidence=0.86,
                    model_note="Во профилот се наведени нови вработувања.",
                ),
            ),
            documents=(
                "Образец за пријава на работодавачот",
                "Потврда од Агенцијата дека лицето е запишано како незапишано",
                "Договор за вработување на неопределено време, по одобрувањето",
            ),
        ),
        DemoCall(
            slug="eu-digital-ai",
            title="Digital Europe: поддршка за усвојување вештачка интелигенција во МСП",
            institution="Европска комисија, Funding & Tenders Portal",
            reference="DIGITAL-2026-AI-SME-04",
            source_url="https://ec.europa.eu/info/funding-tenders/primer/DIGITAL-2026-AI-SME-04",
            snapshot_id="snap_e5d213",
            summary="Конзорциумски проекти за воведување вештачка интелигенција во производство и "
            "услуги.",
            max_eur=60_000,
            deadline=days(74),
            last_verified=days(-1),
            purposes=frozenset({"digital", "rnd"}),
            priority_nace=("C", "J"),
            project_mkd=Range(2_000_000, 30_000_000),
            cofinancing_pct=50,
            clauses=(
                (
                    "Topic conditions",
                    "Eligible countries: as described in the call document, section 6.",
                ),
                (
                    "Section 6",
                    "Legal entities established in EU Member States and in countries "
                    "associated to the Digital Europe Programme.",
                ),
            ),
            criteria=(
                _narrative(
                    "country",
                    "Северна Македонија е меѓу прифатливите земји за овој повик.",
                    "Topic conditions",
                    "Eligible countries: as described in the call document, section 6.",
                    recorded="unclear",
                    confidence=0.41,
                    model_note="Листата на придружени земји е во посебен документ што не е "
                    "преземен. Потребна е рачна проверка.",
                ),
            ),
            documents=(
                "Регистрација на Funding & Tenders Portal (PIC број)",
                "Договор за конзорциум",
                "Техничка апликација, дел Б",
            ),
        ),
        DemoCall(
            slug="apptr-smestuvanje",
            title="Субвенции за подобрување на сместувачките капацитети во туризмот",
            institution="Агенција за промоција и поддршка на туризмот",
            reference="АППТ-СК-02/2026",
            source_url="https://tourismmacedonia.gov.mk/primer/smestuvanje-2026",
            snapshot_id="snap_5c02b7",
            summary="Поврат на дел од трошоците за опремување на хотели, мотели и апартмани.",
            max_eur=5_000,
            deadline=days(30),
            last_verified=days(-3),
            purposes=frozenset({"equipment", "green"}),
            priority_nace=("55",),
            project_mkd=Range(200_000, 2_000_000),
            cofinancing_pct=50,
            clauses=(
                (
                    "Член 2",
                    "Право на субвенција имаат правни лица и трговци поединци регистрирани за "
                    "дејност сместување, во рамки на оддел 55 од Националната класификација на "
                    "дејностите.",
                ),
                (
                    "Член 4",
                    "Се субвенционира до 50% од трошоците за опрема и енергетска ефикасност.",
                ),
            ),
            criteria=(
                _hard(
                    "nace",
                    "Фирмата е регистрирана за дејност сместување (оддел 55).",
                    "Член 2",
                    "регистрирани за дејност сместување, во рамки на оддел 55",
                    F.NACE_CODE,
                    O.PREFIX_IN,
                    ["55"],
                ),
                _hard(
                    "form",
                    "Барателот е правно лице или трговец поединец.",
                    "Член 2",
                    "Право на субвенција имаат правни лица и трговци поединци",
                    F.ENTITY_TYPE,
                    O.NOT_IN,
                    ["ngo", "municipality", "individual", "farm"],
                ),
            ),
            documents=(
                "Решение за категоризација на објектот",
                "Фактури за набавената опрема",
            ),
        ),
        DemoCall(
            slug="ipard-merka-1",
            title="ИПАРД III, Мерка 1: инвестиции во физички средства на земјоделски стопанства",
            institution="Агенција за финансиска поддршка во земјоделството и руралниот развој",
            reference="ИПАРД-01/2026",
            source_url="https://www.ipardpa.gov.mk/primer/ipard-01-2026",
            snapshot_id="snap_4d7f88",
            summary="Кофинансирање на механизација, објекти и опрема за примарно земјоделско "
            "производство.",
            max_eur=700_000,
            deadline=days(45),
            last_verified=days(-2),
            purposes=frozenset({"equipment", "green"}),
            priority_nace=("01",),
            project_mkd=Range(600_000, 70_000_000),
            cofinancing_pct=40,
            clauses=(
                (
                    "Член 7, став 1",
                    "Корисник на мерката е земјоделско стопанство запишано во Единствениот "
                    "регистар на земјоделски стопанства.",
                ),
                (
                    "Член 7, став 3",
                    "Корисникот има право на сопственост или закуп на земјиштето најмалку пет "
                    "години од денот на поднесување на барањето.",
                ),
            ),
            criteria=(
                _hard(
                    "form",
                    "Барателот е земјоделско стопанство.",
                    "Член 7, став 1",
                    "Корисник на мерката е земјоделско стопанство запишано во Единствениот "
                    "регистар на земјоделски стопанства.",
                    F.ENTITY_TYPE,
                    O.IN,
                    ["farm"],
                ),
                _attest(
                    "land",
                    "Имате сопственост или закуп на земјиштето за најмалку пет години.",
                    "Член 7, став 3",
                    "право на сопственост или закуп на земјиштето најмалку пет години",
                ),
            ),
            documents=(
                "Решение за упис во Единствениот регистар на земјоделски стопанства",
                "Имотен лист или договор за закуп на земјиштето",
                "Бизнис план според образецот на Агенцијата",
                "Три понуди за секоја ставка од инвестицијата",
            ),
        ),
        # In the extraction review queue until a reviewer accepts it. One quote was
        # paraphrased by the model and is not in the document: acceptance is blocked
        # until the reviewer corrects it (CLAUDE.md invariant 2).
        DemoCall(
            slug="met-izvoz",
            title="Поддршка за извозно ориентирани мали претпријатија: настап на меѓународни саеми",
            institution="Министерство за економија и труд",
            reference="МЕТ-ИЗВ-2026",
            source_url="https://economy.gov.mk/primer/izvoz-2026.pdf",
            snapshot_id="snap_d20f5e",
            summary="Поврат до 70% од трошоците за штанд, патување и промотивни материјали на "
            "меѓународен саем.",
            max_eur=3_000,
            deadline=days(27),
            last_verified=days(0),
            purposes=frozenset({"export", "digital"}),
            project_mkd=Range(50_000, 400_000),
            cofinancing_pct=30,
            published=False,
            review_flag="Еден цитат не е пронајден дословно во документот.",
            clauses=(
                (
                    "Точка 2",
                    "Право на учество имаат микро и мали претпријатија со најмалку две години "
                    "деловна активност.",
                ),
                (
                    "Точка 4",
                    "Се надоместуваат трошоци за закуп на штанд, патување и промотивни "
                    "материјали, до 70% од вкупниот износ.",
                ),
            ),
            criteria=(
                _hard(
                    "form",
                    "Барателот е микро или мало претпријатие.",
                    "Точка 2",
                    "Право на учество имаат микро и мали претпријатија",
                    F.ENTITY_TYPE,
                    O.IN,
                    ["micro", "small"],
                ),
                _hard(
                    "age",
                    "Фирмата има најмалку две години деловна активност.",
                    "Точка 2",
                    # Paraphrased by the model: not in the document, so not a citation.
                    "активни на пазарот најмалку две години",
                    F.AGE_MONTHS,
                    O.GTE,
                    24,
                    corrected_quote="со најмалку две години деловна активност",
                ),
            ),
            documents=(
                "Покана или договор со организаторот на саемот",
                "Понуди за штанд и патување",
            ),
        ),
        DemoCall(
            slug="met-vest-sajam",
            title="Министерот за економија и труд ги посети изложувачите на саемот за мебел",
            institution="Министерство за економија и труд",
            reference="без број",
            source_url="https://economy.gov.mk/primer/vesti/sajam-mebel",
            snapshot_id="snap_77b1a3",
            summary="Вест за посета на саем. Нема рок, износ ни услови за учество.",
            max_eur=0,
            deadline=days(0),
            last_verified=days(0),
            published=False,
            review_flag="Нема рок и нема услови за учество. Можеби е вест, а не јавен повик.",
            clauses=(
                (
                    "Вест",
                    "Министерот најави дека во наредниот период ќе бидат објавени нови мерки "
                    "за поддршка на дрвната индустрија.",
                ),
            ),
            criteria=(),
            documents=(),
        ),
    ]


def all_calls(today: date | None = None) -> list[DemoCall]:
    return _calls(today or date.today())


def find(slug: str, today: date | None = None) -> DemoCall | None:
    return next((c for c in all_calls(today) if c.slug == slug), None)


@dataclass(frozen=True)
class SourceHealth:
    name: str
    access: str
    last_success_days_ago: int
    sla_days: int
    calls_open: int
    note: str = ""
    real_fetcher: bool = False

    @property
    def stale(self) -> bool:
        return self.last_success_days_ago > self.sla_days


SOURCES: tuple[SourceHealth, ...] = (
    SourceHealth("Агенција за вработување", "HTML", 0, 1, 2, "Вистински fetcher (P1 s11)", True),
    SourceHealth("Фонд за иновации и технолошки развој", "HTML", 9, 1, 2,
                 "Страницата не одговара од 07.09. (sources.md §6.1)"),
    SourceHealth("Министерство за економија и труд", "PDF", 1, 2, 1),
    SourceHealth("Град Скопје", "PDF", 4, 7, 1),
    SourceHealth("АФПЗРР / ИПАРД", "PDF", 2, 3, 1),
    SourceHealth("EU Funding & Tenders", "API", 1, 1, 1),
)  # fmt: skip


def by_snapshot(snapshot_id: str) -> DemoCall | None:
    """The call whose (invented) document is stored under this snapshot id."""
    return next((c for c in all_calls() if c.snapshot_id == snapshot_id), None)
