-- One-time database setup on Cloud SQL for PostgreSQL. Safe to run again.
-- Run by db-init.sh as the 'postgres' user, connected to the 'postgres' database.
-- The values arrive through environment variables (DB_APP_USER, DB_APP_PASSWORD, DB_NAME), read
-- with \getenv, so no password is ever on a command line. Needs psql 15 or later.
--
-- psql does not substitute :'var' inside $$ ... $$ blocks, so each statement is built with
-- format() and run with \gexec. The extensions are created by db-init.sh in the new database.

\set ON_ERROR_STOP on

\getenv app_user DB_APP_USER
\getenv app_password DB_APP_PASSWORD
\getenv db_name DB_NAME

-- The application role: created if missing, password always set to the current secret.
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'app_user', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user')
\gexec

SELECT format('ALTER ROLE %I PASSWORD %L', :'app_user', :'app_password')
\gexec

-- Cloud SQL only lets a user create a database owned by a role it belongs to.
SELECT format('GRANT %I TO CURRENT_USER', :'app_user')
\gexec

-- The database, owned by the application role (so migrations can create tables).
SELECT format('CREATE DATABASE %I OWNER %I', :'db_name', :'app_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db_name')
\gexec
