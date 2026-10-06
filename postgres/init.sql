-- Local demonstration credentials; do not reuse on a shared/public server.
CREATE ROLE agent_reader LOGIN PASSWORD 'demo-reader-local';
GRANT CONNECT ON DATABASE reporting TO agent_reader;
GRANT USAGE ON SCHEMA public TO agent_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE importer IN SCHEMA public GRANT SELECT ON TABLES TO agent_reader;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
ALTER ROLE agent_reader SET default_transaction_read_only = on;
