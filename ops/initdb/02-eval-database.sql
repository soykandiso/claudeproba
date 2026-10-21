-- Runs once, on first initialisation of the postgres volume.
--
-- The weekly tier C evaluation's own database (docker-compose.yml `eval`, P2 s36).
-- The harness replaces the registry of calls it runs on, so it never runs against
-- the real one. Alembic builds its tables at the start of every run. On a volume
-- created before this file existed: docs/runbook.md §14.

CREATE DATABASE grants_eval;
