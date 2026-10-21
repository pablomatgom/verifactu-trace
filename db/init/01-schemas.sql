-- One schema per service inside the single PostgreSQL instance.
-- By convention each service only touches the tables in its own schema.
-- This is not enforced yet: all services share one database user.
CREATE SCHEMA IF NOT EXISTS documents;
CREATE SCHEMA IF NOT EXISTS traceability;
CREATE SCHEMA IF NOT EXISTS submissions;
