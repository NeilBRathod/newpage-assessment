-- Runs once, on first boot of an empty data directory.
--
-- The pgvector image ships the extension binaries but does not enable it in the
-- database; `CREATE EXTENSION` is still required. Doing it here means `make up`
-- yields a database that is actually ready, rather than one that looks fine
-- until the first embedding is written. Migrations repeat this idempotently so
-- a database created by other means is not left behind.
CREATE EXTENSION IF NOT EXISTS vector;
