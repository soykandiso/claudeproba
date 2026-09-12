-- =============================================================================
-- DRAFT SCHEMA — DESIGN ARTIFACT ONLY
-- =============================================================================
-- This file exists to make the data model reviewable before any code is written.
-- From P0.5 onward the source of truth is the SQLAlchemy models plus Alembic
-- migrations; this file is then REGENERATED from the live database with
--     pg_dump --schema-only --no-owner
-- and is never hand-edited. Hand-maintaining it alongside ORM models guarantees
-- the two disagree within a month. (See architecture.md §9.6.)
--
-- Target: PostgreSQL 16 + pgvector + pg_trgm.
-- Verified 2026-09-12: applies cleanly to pgvector/pgvector:pg16 (28 tables, 10 enums,
-- 27 indexes incl. HNSW + trigram); the chk_has_citation constraint was confirmed to
-- reject an approved criterion that carries no citation.
--
-- -----------------------------------------------------------------------------
-- ANSWERING THE CHALLENGE IN BRIEF §4
-- -----------------------------------------------------------------------------
-- 1. KEEP programme SEPARATE FROM call.
--    For:  criteria, document templates and institutional knowledge are stable
--          at programme level and change slowly, so re-extracting them per call
--          burns tokens and invites drift; the SEO archive wants durable
--          programme pages that accumulate authority while calls close; the
--          monitoring subscription is naturally "alert me when this programme
--          reopens"; document templates map to programmes, not to calls.
--    Against: some sources publish genuine one-offs, and forcing a parent row
--          creates junk.
--    Resolution: every call has a programme_id (NOT NULL), and a one-off gets an
--          auto-created programme with is_singleton = true. Criteria live on the
--          CALL (authoritative and cited) but may be seeded from the programme as
--          defaults that extraction confirms or overrides.
--
-- 2. CRITERIA THAT ARE GENUINELY UNSTRUCTURABLE get a kind enum rather than a
--    modelling hack. Only kind='hard_structured' may exclude an applicant.
--    The honest answer to "unstructurable" is 'applicant_attest': turn it into a
--    question for the human instead of a guess by the machine.
--
-- 3. applicant SPLIT INTO account + applicant_profile, because a profile edited
--    after a report was purchased must not change that report's inputs.
--
-- 4. evidence CITES A SNAPSHOT AND A CHARACTER SPAN, never a live URL, so a
--    citation stays verifiable after the source page changes.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS citext;      -- case-insensitive email

-- =============================================================================
-- ENUMS
-- =============================================================================

CREATE TYPE lang              AS ENUM ('mk', 'sq', 'en', 'tr');
CREATE TYPE entity_type       AS ENUM ('sole_trader','micro','small','medium','large',
                                       'ngo','municipality','individual','farm','startup','other');
CREATE TYPE call_status       AS ENUM ('draft','open','closed','cancelled','announced');
CREATE TYPE criterion_kind    AS ENUM ('hard_structured','soft_scored','narrative_verify',
                                       'applicant_attest','documentary');
CREATE TYPE verdict           AS ENUM ('eligible','likely_eligible','needs_verification','not_eligible');
CREATE TYPE review_kind       AS ENUM ('extraction','report','document_package','source_health');
CREATE TYPE review_state      AS ENUM ('pending','approved','edited','rejected');
CREATE TYPE order_state       AS ENUM ('created','invoiced','paid','in_progress','delivered','cancelled','refunded');
CREATE TYPE invoice_kind      AS ENUM ('proforma','final','credit_note');
CREATE TYPE access_method     AS ENUM ('api','rss','html','pdf_index','manual');

-- =============================================================================
-- SOURCES AND INGESTION
-- Rationale: ingestion provenance is the backbone of the accuracy contract. If
-- you cannot say where a fact came from and when, you cannot publish it.
-- =============================================================================

-- One row per institution/feed we crawl. Cadence + SLA drive the staleness alarm,
-- which is the single most important operational alert in the system (risks R1).
CREATE TABLE source_feed (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug                text NOT NULL UNIQUE,
    name_mk             text NOT NULL,
    name_en             text NOT NULL,
    institution         text NOT NULL,
    base_url            text NOT NULL,
    access_method       access_method NOT NULL,
    robots_checked_at   timestamptz,
    terms_url           text,
    terms_note          text,
    expected_cadence    interval NOT NULL,        -- how often new items normally appear
    staleness_sla       interval NOT NULL,        -- alert if no new item within this
    rate_limit_rps      numeric(5,2) NOT NULL DEFAULT 0.2,
    is_active           boolean NOT NULL DEFAULT true,
    priority            smallint NOT NULL DEFAULT 100,
    created_at          timestamptz NOT NULL DEFAULT now()
);

-- Denormalised health state, updated by every run. Kept separate from source_feed
-- so that a hot per-run write does not contend with configuration reads.
CREATE TABLE source_health (
    source_feed_id      uuid PRIMARY KEY REFERENCES source_feed(id) ON DELETE CASCADE,
    last_attempt_at     timestamptz,
    last_success_at     timestamptz,
    last_new_item_at    timestamptz,
    consecutive_failures int NOT NULL DEFAULT 0,
    last_error          text,
    is_alerting         boolean NOT NULL DEFAULT false
);

-- One row per crawl execution. Gives you a post-mortem when an overnight run
-- goes wrong, which APScheduler-style in-process scheduling would not.
CREATE TABLE ingestion_run (
    id                  bigserial PRIMARY KEY,
    source_feed_id      uuid NOT NULL REFERENCES source_feed(id) ON DELETE CASCADE,
    started_at          timestamptz NOT NULL DEFAULT now(),
    finished_at         timestamptz,
    ok                  boolean,
    urls_seen           int NOT NULL DEFAULT 0,
    urls_changed        int NOT NULL DEFAULT 0,
    items_created       int NOT NULL DEFAULT 0,
    items_updated       int NOT NULL DEFAULT 0,
    queued_for_review   int NOT NULL DEFAULT 0,
    error               text
);
CREATE INDEX ix_ingestion_run_source_time ON ingestion_run (source_feed_id, started_at DESC);

-- Immutable record of what a URL returned at a point in time. BYTES LIVE IN
-- OBJECT STORAGE, not here: only the pointer and hash are in Postgres, so nightly
-- pg_dump stays small and restores stay fast. normalised_text IS stored, because
-- citations index into it by character offset and must survive independently of
-- the parser version that produced them.
CREATE TABLE raw_snapshot (
    id                  bigserial PRIMARY KEY,
    source_feed_id      uuid NOT NULL REFERENCES source_feed(id) ON DELETE CASCADE,
    url                 text NOT NULL,
    content_sha256      char(64) NOT NULL,
    http_status         int NOT NULL,
    content_type        text,
    byte_length         int,
    storage_key         text NOT NULL,            -- snapshots/<source>/<sha256>
    fetched_at          timestamptz NOT NULL DEFAULT now(),
    normalised_text     text,                     -- citation offsets index into THIS
    normaliser_version  text,
    UNIQUE (url, content_sha256)
);
CREATE INDEX ix_snapshot_url_time ON raw_snapshot (url, fetched_at DESC);
CREATE INDEX ix_snapshot_hash     ON raw_snapshot (content_sha256);

-- =============================================================================
-- FUNDING REGISTRY
-- =============================================================================

-- Durable funding instrument. Survives across years and individual calls; owns
-- document templates and the SEO-stable public page.
CREATE TABLE programme (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_feed_id      uuid NOT NULL REFERENCES source_feed(id),
    slug                text NOT NULL UNIQUE,
    name_mk             text NOT NULL,
    name_sq             text,
    name_en             text,
    institution         text NOT NULL,
    description_mk      text,
    is_singleton        boolean NOT NULL DEFAULT false,  -- auto-created for one-off calls
    typical_cadence     interval,                        -- powers "reopens around March" hints
    created_at          timestamptz NOT NULL DEFAULT now()
);

-- A dated instance with a deadline, budget and document set. This is what a user
-- actually applies to and what the matching engine ranks.
CREATE TABLE call (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    programme_id        uuid NOT NULL REFERENCES programme(id) ON DELETE RESTRICT,
    source_feed_id      uuid NOT NULL REFERENCES source_feed(id),
    reference_code      text,
    title_mk            text NOT NULL,
    title_sq            text,
    title_en            text,
    summary_mk          text,
    status              call_status NOT NULL DEFAULT 'draft',
    published_at        date,
    opens_at            date,
    deadline_at         timestamptz,
    total_budget_mkd    numeric(14,2),
    total_budget_eur    numeric(14,2),
    grant_min_mkd       numeric(14,2),
    grant_max_mkd       numeric(14,2),
    cofinancing_pct     numeric(5,2),             -- applicant's own share, %
    -- Denormalised hard-filter columns. These five carry stage 1 of the matching
    -- engine and are the only columns the fast path touches; everything else is
    -- evaluated by the rule interpreter over the surviving candidates.
    allowed_entity_types entity_type[] NOT NULL DEFAULT '{}',
    allowed_nace_prefixes text[] NOT NULL DEFAULT '{}',
    allowed_regions      text[] NOT NULL DEFAULT '{}',   -- municipality or region codes; empty = national
    min_company_age_months int,
    max_company_age_months int,
    -- Provenance and freshness, surfaced in the UI per brief §5 and §12.
    canonical_url       text NOT NULL,
    primary_snapshot_id bigint REFERENCES raw_snapshot(id),
    last_verified_at    timestamptz NOT NULL DEFAULT now(),
    extraction_confidence numeric(3,2),
    is_published        boolean NOT NULL DEFAULT false,   -- false until review approved
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);
-- The hot path: open calls with a future deadline, ordered by urgency.
CREATE INDEX ix_call_open ON call (status, deadline_at)
    WHERE is_published AND status = 'open';
CREATE INDEX ix_call_entity_types ON call USING gin (allowed_entity_types);
CREATE INDEX ix_call_nace         ON call USING gin (allowed_nace_prefixes);
CREATE INDEX ix_call_regions      ON call USING gin (allowed_regions);
CREATE INDEX ix_call_programme    ON call (programme_id, published_at DESC);
CREATE INDEX ix_call_title_trgm   ON call USING gin (title_mk gin_trgm_ops);

-- Documents belonging to a call (guidelines, forms, annexes). Separate from the
-- call so that a 40-page guideline PDF and a 2-page form are retrieved and
-- chunked independently.
CREATE TABLE call_document (
    id                  bigserial PRIMARY KEY,
    call_id             uuid NOT NULL REFERENCES call(id) ON DELETE CASCADE,
    snapshot_id         bigint NOT NULL REFERENCES raw_snapshot(id),
    role                text NOT NULL,            -- 'guidelines' | 'form' | 'annex' | 'announcement'
    title               text,
    is_primary          boolean NOT NULL DEFAULT false
);
CREATE INDEX ix_call_document_call ON call_document (call_id);

-- THE CENTRAL TABLE OF THE ACCURACY CONTRACT.
-- kind decides who evaluates it and whether it may exclude an applicant.
-- Only 'hard_structured' may produce 'not_eligible'. Everything the model touches
-- caps out at 'needs_verification'. source_quote/snapshot span make every
-- criterion independently auditable months later.
CREATE TABLE eligibility_criterion (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    call_id             uuid NOT NULL REFERENCES call(id) ON DELETE CASCADE,
    kind                criterion_kind NOT NULL,
    code                text,                     -- stable slug, e.g. 'company_age_min'
    label_mk            text NOT NULL,
    -- Machine-evaluable form. NULL for narrative/attest/documentary kinds.
    field               text,                     -- profile attribute path, e.g. 'headcount'
    operator            text,                     -- 'eq','neq','lt','lte','gt','gte','in','not_in','overlaps'
    value_json          jsonb,
    -- Ranking weight, used only by kind='soft_scored'.
    weight              numeric(4,2),
    -- Provenance. No citation, no publication.
    source_quote        text,
    snapshot_id         bigint REFERENCES raw_snapshot(id),
    quote_start         int,
    quote_end           int,
    source_url          text,
    confidence          numeric(3,2),
    extracted_at        timestamptz NOT NULL DEFAULT now(),
    prompt_version      text,
    is_approved         boolean NOT NULL DEFAULT false,
    CONSTRAINT chk_structured_has_predicate
        CHECK (kind <> 'hard_structured' OR (field IS NOT NULL AND operator IS NOT NULL)),
    CONSTRAINT chk_has_citation
        CHECK (NOT is_approved OR (snapshot_id IS NOT NULL AND source_quote IS NOT NULL))
);
CREATE INDEX ix_criterion_call ON eligibility_criterion (call_id, kind);

-- Retrieval unit. One row per chunk of one snapshot, with offsets back into
-- raw_snapshot.normalised_text so a retrieved passage can become a citation
-- without a second lookup. Hybrid retrieval: vector for prose, trigram for codes,
-- numbers and dates — Postgres has no Macedonian FTS dictionary, which is the
-- actual reason pgvector earns its place here.
CREATE TABLE chunk (
    id                  bigserial PRIMARY KEY,
    snapshot_id         bigint NOT NULL REFERENCES raw_snapshot(id) ON DELETE CASCADE,
    call_id             uuid REFERENCES call(id) ON DELETE CASCADE,
    ordinal             int NOT NULL,
    char_start          int NOT NULL,
    char_end            int NOT NULL,
    text                text NOT NULL,
    embedding           vector(1024),
    embedding_model     text,
    UNIQUE (snapshot_id, ordinal)
);
CREATE INDEX ix_chunk_call      ON chunk (call_id);
CREATE INDEX ix_chunk_embedding ON chunk USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ix_chunk_text_trgm ON chunk USING gin (text gin_trgm_ops);

-- =============================================================================
-- APPLICANTS
-- account = who they are. applicant_profile = what they told us, versioned.
-- Splitting these is what makes a delivered report reproducible (architecture §9.3).
-- =============================================================================

CREATE TABLE account (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email               citext NOT NULL UNIQUE,
    email_verified_at   timestamptz,
    preferred_lang      lang NOT NULL DEFAULT 'mk',
    is_admin            boolean NOT NULL DEFAULT false,
    created_at          timestamptz NOT NULL DEFAULT now(),
    last_seen_at        timestamptz,
    anonymised_at       timestamptz                -- GDPR erasure without losing invoice rows
);

-- Purpose-scoped consent. Service consent and marketing consent are separate
-- rows; never inferred from each other.
CREATE TABLE consent_record (
    id                  bigserial PRIMARY KEY,
    account_id          uuid NOT NULL REFERENCES account(id) ON DELETE CASCADE,
    purpose             text NOT NULL,            -- 'service' | 'marketing' | 'profiling'
    granted             boolean NOT NULL,
    policy_version      text NOT NULL,
    ip_address          inet,
    created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_consent_account ON consent_record (account_id, purpose, created_at DESC);

-- Immutable once superseded. A purchased report points at an exact version.
CREATE TABLE applicant_profile (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id          uuid NOT NULL REFERENCES account(id) ON DELETE CASCADE,
    version             int NOT NULL DEFAULT 1,
    superseded_at       timestamptz,
    label               text,
    entity_type         entity_type NOT NULL,
    nace_code           text,                     -- e.g. '62.01'
    municipality_code   text,
    region_code         text,
    founded_year        smallint,
    headcount           int,
    turnover_band_mkd   text,                     -- banded, not exact: minimisation by design
    is_woman_owned      boolean,
    is_youth_owned      boolean,
    is_export_oriented  boolean,
    investment_type     text,
    investment_size_mkd numeric(14,2),
    cofinancing_capable_pct numeric(5,2),
    timeline_months     smallint,
    project_keywords    text,
    project_description text,
    created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_profile_account ON applicant_profile (account_id, version DESC);

-- =============================================================================
-- MATCHING
-- A match_run is immutable and records the exact rule and weight versions used,
-- so any delivered report is reproducible byte-for-byte months later.
-- =============================================================================

CREATE TABLE match_run (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id          uuid NOT NULL REFERENCES applicant_profile(id) ON DELETE CASCADE,
    ruleset_version     text NOT NULL,
    weights_version     text NOT NULL,
    stage_reached       smallint NOT NULL,        -- 2 = free shortlist, 3 = verified, 4 = reviewed
    candidates_considered int,
    duration_ms         int,
    created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_match_run_profile ON match_run (profile_id, created_at DESC);

CREATE TABLE match_result (
    id                  bigserial PRIMARY KEY,
    match_run_id        uuid NOT NULL REFERENCES match_run(id) ON DELETE CASCADE,
    call_id             uuid NOT NULL REFERENCES call(id) ON DELETE CASCADE,
    verdict             verdict NOT NULL,
    score               numeric(6,4) NOT NULL,
    score_breakdown     jsonb NOT NULL,           -- {component: {value, weight, reason}}
    rank                int NOT NULL,
    UNIQUE (match_run_id, call_id)
);
CREATE INDEX ix_match_result_run ON match_result (match_run_id, rank);

-- Per-criterion outcome. This is what the report prints, one row per line item.
CREATE TABLE match_criterion_outcome (
    id                  bigserial PRIMARY KEY,
    match_result_id     bigint NOT NULL REFERENCES match_result(id) ON DELETE CASCADE,
    criterion_id        uuid NOT NULL REFERENCES eligibility_criterion(id) ON DELETE CASCADE,
    verdict             verdict NOT NULL,
    confidence          numeric(3,2),
    decided_by          text NOT NULL,            -- 'rule' | 'model' | 'human'
    reason_mk           text,
    UNIQUE (match_result_id, criterion_id)
);

-- A retrieved passage backing one specific statement. Cites a SNAPSHOT and a
-- character span, never a live URL — so the citation is still checkable after
-- the source website changes.
CREATE TABLE evidence (
    id                  bigserial PRIMARY KEY,
    outcome_id          bigint REFERENCES match_criterion_outcome(id) ON DELETE CASCADE,
    snapshot_id         bigint NOT NULL REFERENCES raw_snapshot(id),
    chunk_id            bigint REFERENCES chunk(id),
    quote               text NOT NULL,
    char_start          int NOT NULL,
    char_end            int NOT NULL,
    retrieved_at        timestamptz NOT NULL DEFAULT now(),
    source_url          text NOT NULL,
    section_ref         text
);
CREATE INDEX ix_evidence_outcome ON evidence (outcome_id);

-- =============================================================================
-- HUMAN REVIEW — a first-class feature, per brief §6.4, not a workaround.
-- Every rejection here becomes an evaluation case (see matching.md §6).
-- =============================================================================

CREATE TABLE review_queue_item (
    id                  bigserial PRIMARY KEY,
    kind                review_kind NOT NULL,
    state               review_state NOT NULL DEFAULT 'pending',
    priority            smallint NOT NULL DEFAULT 100,
    call_id             uuid REFERENCES call(id) ON DELETE CASCADE,
    match_run_id        uuid REFERENCES match_run(id) ON DELETE CASCADE,
    order_id            uuid,
    payload             jsonb NOT NULL DEFAULT '{}'::jsonb,
    reason              text NOT NULL,            -- why it landed here
    reviewer_id         uuid REFERENCES account(id),
    reviewer_note       text,
    corrected_payload   jsonb,                    -- the diff that seeds an eval case
    created_at          timestamptz NOT NULL DEFAULT now(),
    resolved_at         timestamptz
);
CREATE INDEX ix_review_pending ON review_queue_item (state, priority, created_at)
    WHERE state = 'pending';

-- =============================================================================
-- COMMERCE
-- v1 is proforma invoice + bank transfer in denars, reconciled by hand. The
-- provider column exists so a local card gateway slots in later without touching
-- order logic (brief §3.2).
-- =============================================================================

CREATE TABLE product (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sku                 text NOT NULL UNIQUE,     -- 'report_deep' | 'package_fitr' | 'sub_monitor'
    name_mk             text NOT NULL,
    price_mkd           numeric(12,2) NOT NULL,   -- ex-VAT
    vat_rate            numeric(5,2) NOT NULL DEFAULT 18.00,
    is_recurring        boolean NOT NULL DEFAULT false,
    is_active           boolean NOT NULL DEFAULT true
);

CREATE TABLE "order" (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id          uuid NOT NULL REFERENCES account(id) ON DELETE RESTRICT,
    profile_id          uuid NOT NULL REFERENCES applicant_profile(id),
    match_run_id        uuid REFERENCES match_run(id),
    product_id          uuid NOT NULL REFERENCES product(id),
    state               order_state NOT NULL DEFAULT 'created',
    amount_mkd          numeric(12,2) NOT NULL,
    vat_mkd             numeric(12,2) NOT NULL,
    provider            text NOT NULL DEFAULT 'invoice',   -- PaymentProvider implementation
    -- Legal identity of the buyer. Collected for the invoice only, and NEVER
    -- forwarded to a model (architecture §8).
    buyer_name          text,
    buyer_address       text,
    buyer_edb           text,                     -- tax number
    buyer_embs          text,                     -- registration number
    created_at          timestamptz NOT NULL DEFAULT now(),
    delivered_at        timestamptz
);
CREATE INDEX ix_order_state   ON "order" (state, created_at);
CREATE INDEX ix_order_account ON "order" (account_id, created_at DESC);

CREATE TABLE invoice (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id            uuid NOT NULL REFERENCES "order"(id) ON DELETE RESTRICT,
    kind                invoice_kind NOT NULL,
    number              text NOT NULL UNIQUE,     -- gapless per fiscal year
    fiscal_year         smallint NOT NULL,
    issued_at           date NOT NULL,
    due_at              date,
    amount_mkd          numeric(12,2) NOT NULL,
    vat_mkd             numeric(12,2) NOT NULL,
    total_mkd           numeric(12,2) NOT NULL,
    pdf_storage_key     text,
    paid_at             timestamptz,
    bank_reference      text,                     -- filled during manual reconciliation
    reconciled_by       uuid REFERENCES account(id)
);
CREATE INDEX ix_invoice_unpaid ON invoice (issued_at) WHERE paid_at IS NULL;

CREATE TABLE subscription (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id          uuid NOT NULL REFERENCES account(id) ON DELETE CASCADE,
    profile_id          uuid NOT NULL REFERENCES applicant_profile(id),
    product_id          uuid NOT NULL REFERENCES product(id),
    started_on          date NOT NULL,
    renews_on           date NOT NULL,
    cancelled_at        timestamptz,
    last_alert_at       timestamptz
);
CREATE INDEX ix_subscription_due ON subscription (renews_on) WHERE cancelled_at IS NULL;

-- =============================================================================
-- DOCUMENT GENERATION (P5)
-- Templates are version-controlled FILES; these tables track which version
-- produced which output, so a delivered package is reproducible.
-- =============================================================================

CREATE TABLE document_template (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    programme_id        uuid NOT NULL REFERENCES programme(id) ON DELETE CASCADE,
    slug                text NOT NULL,
    version             text NOT NULL,
    file_path           text NOT NULL,            -- path in repo, e.g. templates/fitr/business_plan.docx
    lang                lang NOT NULL DEFAULT 'mk',
    required_fields     jsonb NOT NULL DEFAULT '[]'::jsonb,
    UNIQUE (programme_id, slug, version)
);

CREATE TABLE document_package (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id            uuid NOT NULL REFERENCES "order"(id) ON DELETE CASCADE,
    call_id             uuid NOT NULL REFERENCES call(id),
    state               review_state NOT NULL DEFAULT 'pending',
    checklist           jsonb NOT NULL DEFAULT '[]'::jsonb,  -- what the applicant must still supply
    created_at          timestamptz NOT NULL DEFAULT now(),
    delivered_at        timestamptz
);

CREATE TABLE generated_document (
    id                  bigserial PRIMARY KEY,
    package_id          uuid NOT NULL REFERENCES document_package(id) ON DELETE CASCADE,
    template_id         uuid NOT NULL REFERENCES document_template(id),
    storage_key         text NOT NULL,
    format              text NOT NULL,            -- 'docx' | 'pdf'
    is_ai_assisted      boolean NOT NULL DEFAULT true,
    human_reviewed_at   timestamptz,
    unfilled_fields     jsonb NOT NULL DEFAULT '[]'::jsonb  -- never invent figures (brief §8)
);

-- =============================================================================
-- AI AUDIT
-- Every model call, with cost. This is how you learn a feature is expensive
-- before the monthly invoice tells you (brief §7).
-- =============================================================================

CREATE TABLE prompt_version (
    id                  text PRIMARY KEY,         -- 'extract_call@2026-09-12.1'
    task                text NOT NULL,
    file_path           text NOT NULL,
    content_sha256      char(64) NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE model_call (
    id                  bigserial PRIMARY KEY,
    task                text NOT NULL,            -- 'extract' | 'verify' | 'compose' | 'embed'
    prompt_version_id   text REFERENCES prompt_version(id),
    model               text NOT NULL,
    cache_hit           boolean NOT NULL DEFAULT false,
    input_hash          char(64) NOT NULL,
    input_tokens        int,
    output_tokens       int,
    cost_usd            numeric(10,6),
    latency_ms          int,
    ok                  boolean NOT NULL,
    validation_error    text,
    call_id             uuid REFERENCES call(id) ON DELETE SET NULL,
    match_run_id        uuid REFERENCES match_run(id) ON DELETE SET NULL,
    created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_model_call_cost ON model_call (created_at DESC, task);
CREATE INDEX ix_model_call_cache ON model_call (input_hash);

-- Full prompt/response audit storage (brief §7). Separate from model_call because
-- these rows are large, rarely read, and pruned on a different retention schedule.
CREATE TABLE model_call_payload (
    model_call_id       bigint PRIMARY KEY REFERENCES model_call(id) ON DELETE CASCADE,
    request_json        jsonb NOT NULL,           -- post-scrubbing: exactly what left the building
    response_json       jsonb
);

-- =============================================================================
-- MARKETING / FUNNEL
-- =============================================================================

CREATE TABLE email_event (
    id                  bigserial PRIMARY KEY,
    account_id          uuid REFERENCES account(id) ON DELETE CASCADE,
    kind                text NOT NULL,            -- 'magic_link' | 'shortlist' | 'invoice' | 'alert'
    sent_at             timestamptz NOT NULL DEFAULT now(),
    provider_message_id text,
    opened_at           timestamptz,
    bounced             boolean NOT NULL DEFAULT false
);
CREATE INDEX ix_email_account ON email_event (account_id, sent_at DESC);
