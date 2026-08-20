-- SCRUM-41 diagnostic-only initialization. The server command supplies the
-- preload and timing settings; this file is safe to run more than once on a
-- fresh diagnostic database.
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
