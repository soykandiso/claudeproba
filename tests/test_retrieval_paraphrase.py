"""Roadmap P1 s12 acceptance: a clause retrieved by paraphrase appears in the top 3.

Real model, real PostgreSQL, the extraction fixtures. The queries are
hand-written questions a person might ask, worded differently from the clause
that answers them; `needle` is a phrase from that clause. To make the test
harder than production, the scope is all the documents at once, where a call
searches only its own.

Skipped unless the model has been fetched (`flask ingest fetch-model`); embedding
the fixtures takes about a minute on two cores.
"""

# ruff: noqa: E501 -- the query tables read best one case per line.
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import load_settings
from app.ingestion.normalise import find_quote
from app.models import RawSnapshot, SourceFeed
from app.models.enums import AccessMethod
from app.retrieval.embedder import LocalEmbedder, ModelNotDownloaded
from app.retrieval.index import index_pending
from app.retrieval.search import hybrid_retrieve
from tests.test_extract_schema import CASES, CASSETTES, fixture_text
from tests.test_gateway import DATABASE_AVAILABLE

settings = load_settings()

pytestmark = pytest.mark.skipif(
    not DATABASE_AVAILABLE, reason="no database reachable; start `docker compose up -d`"
)

PARAPHRASES = [
    ("economy-call-3", "Кои трошоци не се признаваат за субвенција?", "Износот платен за ДДВ"),
    ("economy-call-3", "Колку најмногу пари може да добие една фирма?", "не повеќе од 200.000 денари"),
    ("economy-call-3", "Купената опрема не смее да се продаде неколку години", "да не ги оттуѓува"),
    ("economy-call-3", "Посебен услов за фирми чиј сопственик е жена", "во сопственост и управувано од жена"),
    ("economy-call-3", "До кој датум може да се аплицира?", "Крајниот рок за аплицирање"),
    ("economy-call-3", "Што ако парите не се доволни за сите пријавени?", "секој барател ќе биде намален"),
    ("economy-call-3", "На која адреса се носи пријавата?", "ул. „Јуриј Гагарин”"),
    ("economy-call-3", "Занаетчиите кои плаќаат паушален данок се исклучени", "паушално утврден нето-доход"),
    ("economy-call-3", "Што ако во пријавата недостасува некој документ?", "недостасува некој од потребните документи"),
    ("economy-call-3", "Колку изнесуваат административните такси?", "Уплатница на износ од 250,00 денари"),
    ("economy-call-3", "Фирмата мора да работи во производство, не во услуги", "Преработувачка индустрија"),
    ("economy-call-3", "Колку вработени мора да има претпријатието?", "минимум 2 (двајца) вработени"),
    ("economy-call-3", "Фирмата не смее да е во стечај", "не е покрената стечајна постапка"),
    ("economy-call-3", "Колку стара смее да биде машината?", "не порано од 2 (две) години"),
    ("economy-call-3", "Дали министерството може да дојде на контрола?", "задржува правото да изврши контрола"),
    ("economy-call-3", "Помош од мало значење во последните три години", "300.000 евра"),
    ("economy-call-3", "Треба ли превод на фактури на туѓ јазик?", "овластен судски преведувач"),
    ("av-measure-819", "Кој може да се пријави како работодавач?", "од приватен и од граѓански сектор"),
    ("av-measure-819", "Колку плаќа агенцијата месечно за практикант?", "12.000,00 денари месечно"),
    ("av-measure-819", "Колку трае обуката?", "до 3 (три) месеци"),
    ("av-measure-819", "Каде се поднесува пријавата и во кое време?", "во работниот клуб"),
    ("av-measure-819", "Кои млади лица може да се ангажираат?", "до 29 години"),
    ("ipard-notice-03-2025", "Колку дена е отворен повикот?", "45 дена"),
    ("ipard-notice-03-2025", "Поддршка за туризам на село", "Поддршка на руралниот туризам"),
    ("ipard-notice-03-2025", "Кој врши надзор на терен над договорот?", "Контрола на самото место"),
    ("ipard-notice-03-2025", "Бесплатни совети за земјоделци при аплицирање", "бесплатно да добијат"),
]  # fmt: skip


# Exact strings a paraphrase-trained model blurs: the reason trigram search exists.
EXACT = [
    ("economy-call-3", "Приходна шифра 722313", "722313 00"),
    ("economy-call-3", "11.340.000 денари", "11.340.000"),
    ("ipard-notice-03-2025", "02 3097-460", "3097-460"),
    ("av-measure-819", "21.08.2026", "21.08.2026"),
]


# Criteria whose chunk is not first, each for a reason production does not share or that
# P2 s30 decides (16.09.2026). Strict: if one starts passing, the test says so.
KNOWN_MISSES = {
    # A Macedonian label over an English quote: across all documents the label pulls
    # Macedonian exclusion clauses ahead. Within its own call, as production searches,
    # the chunk is first; the quote alone is first either way.
    "4. Financial and operational capacity and exclusion": "cross-language query",
    # A standard required document, worded almost the same in the Economy call: first
    # within its own call, second across documents.
    "Тековна состојба од Централниот регистар на Република Северна Македонија не постара "
    "од 6 (шест) месеци;": "the same standard clause in another call",
    # The call states this condition twice; the other statement, without the OCR error
    # "Дане", ranks first even within the call. Right clause, other chunk.
    "Дане користеле средства од Град Скопје во тековната година;": "condition stated twice",
}


def verification_queries():
    """docs/matching.md §5 builds its query from a criterion: label_mk + ' ' + source_quote."""
    for name in CASES:
        reply = json.loads((CASSETTES / f"{name}.json").read_text(encoding="utf-8"))
        for criterion in reply["criteria"]:
            args = (name, f"{criterion['label_mk']} {criterion['quote']}", criterion["quote"])
            if criterion["quote"] in KNOWN_MISSES:
                reason = f"{KNOWN_MISSES[criterion['quote']]}; see KNOWN_MISSES"
                yield pytest.param(*args, marks=pytest.mark.xfail(strict=True, reason=reason))
            else:
                yield args


@pytest.fixture(scope="module")
def embedder():
    embedder = LocalEmbedder(settings.model_dir)
    try:
        embedder.query("проверка")
    except ModelNotDownloaded:
        pytest.skip(f"embedding model not in {settings.model_dir}; run `flask ingest fetch-model`")
    return embedder


@pytest.fixture(scope="module")
def indexed(embedder):
    engine = create_engine(settings.sqlalchemy_url)
    connection = engine.connect()
    transaction = connection.begin()
    sessions = sessionmaker(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    snapshot_ids = {}
    with sessions() as session:
        feed = SourceFeed(
            slug="test-paraphrase", name_mk="Тест", name_en="Test", institution="Test",
            base_url="https://gov.example", access_method=AccessMethod.HTML,
            expected_cadence="7 days", staleness_sla="30 days",
        )  # fmt: skip
        session.add(feed)
        session.flush()
        for name in CASES:
            snapshot = RawSnapshot(
                source_feed_id=feed.id, url=f"https://gov.example/{name}",
                content_sha256=name.ljust(64, "0"), http_status=200, storage_key=f"test/{name}",
                normalised_text=fixture_text(name),
            )  # fmt: skip
            session.add(snapshot)
            session.flush()
            snapshot_ids[name] = snapshot.id
        session.commit()
    index_pending(sessions, embedder)
    yield sessions, snapshot_ids
    transaction.rollback()
    connection.close()
    engine.dispose()


def rank_of(indexed, embedder, name, query, needle, k):
    sessions, snapshot_ids = indexed
    with sessions() as session:
        result = hybrid_retrieve(session, embedder, list(snapshot_ids.values()), query, k=k)
    assert result.complete
    for rank, passage in enumerate(result.passages, 1):
        # Folded like citations are located: the IPARD notice writes "Aлтернативно"
        # with a Latin A, and the cassette quotes it in Cyrillic.
        if passage.snapshot_id == snapshot_ids[name] and find_quote(
            passage.text, needle, fold=True
        ):
            return rank
    return None


@pytest.mark.parametrize(("name", "query", "needle"), PARAPHRASES)
def test_a_clause_asked_for_in_other_words_is_in_the_top_3(indexed, embedder, name, query, needle):
    assert rank_of(indexed, embedder, name, query, needle, k=3) is not None


@pytest.mark.parametrize(("name", "query", "needle"), EXACT)
def test_an_exact_code_amount_or_date_comes_first(indexed, embedder, name, query, needle):
    assert rank_of(indexed, embedder, name, query, needle, k=1) == 1


@pytest.mark.parametrize(("name", "query", "quote"), list(verification_queries()))
def test_a_criterion_finds_the_chunk_it_was_extracted_from_first(
    indexed, embedder, name, query, quote
):
    # Whole in one chunk (the chunker's overlap is there for that), and that chunk first.
    assert rank_of(indexed, embedder, name, query, quote, k=1) == 1
