-- Runs once, on first initialisation of the postgres volume.
--
-- The first Alembic migration (P0.5 session 3) repeats these with IF NOT EXISTS,
-- so a database created some other way -- a managed instance, a restore into an
-- empty volume -- still ends up correct. Extensions need superuser, which the
-- compose postgres user has and a managed provider's may not; if that ever
-- becomes true, this is the line that has to move.

CREATE EXTENSION IF NOT EXISTS vector;     -- embeddings for hybrid retrieval
CREATE EXTENSION IF NOT EXISTS pg_trgm;    -- trigram search: no Macedonian FTS dictionary exists
CREATE EXTENSION IF NOT EXISTS citext;     -- case-insensitive email
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()
