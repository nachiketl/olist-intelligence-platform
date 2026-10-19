-- =====================================================================
-- Day 7 (part B): roles and permissions (least privilege)
-- Roles: bi_ro (Power BI), agent_ro (AI agent reads), agent_rw (AI agent logs),
--        approver_rw (humans approve recommended actions).
-- Passwords are NOT in this file: python/etl/create_db_users.py sets them from .env.
-- Safe to re-run: privileges are reset and granted again.
-- =====================================================================
DO $$
DECLARE r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['bi_ro', 'agent_ro', 'agent_rw', 'approver_rw'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE', r);
        END IF;
    END LOOP;
END $$;

-- ---------- database level: nothing is open to PUBLIC ----------------------
DO $$
BEGIN
    EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO bi_ro, agent_ro, agent_rw, approver_rw', current_database());
END $$;

REVOKE ALL ON SCHEMA raw, staging, core, marts, ref, agent, audit FROM PUBLIC;

-- ---------- reset, then grant again ------------------------------------------
REVOKE ALL ON ALL TABLES IN SCHEMA raw, staging, core, marts, ref, agent, audit FROM bi_ro, agent_ro, agent_rw, approver_rw;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA agent FROM bi_ro, agent_ro, agent_rw, approver_rw;
REVOKE ALL ON SCHEMA raw, staging, core, marts, ref, agent, audit FROM bi_ro, agent_ro, agent_rw, approver_rw;

-- ---------- bi_ro: Power BI reads the model and the pipeline/AI results ---------
GRANT USAGE ON SCHEMA core, marts, ref, audit, agent TO bi_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA core, marts, ref, audit TO bi_ro;
GRANT SELECT ON agent.insights, agent.action_queue TO bi_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA core, marts, ref, audit GRANT SELECT ON TABLES TO bi_ro;
ALTER ROLE bi_ro SET default_transaction_read_only = on;
ALTER ROLE bi_ro SET statement_timeout = '60s';
ALTER ROLE bi_ro CONNECTION LIMIT 10;

-- ---------- agent_ro: the AI agent can read the marts and approved context only ---
-- Views run with their owner's rights, so core stays hidden while marts views still work.
GRANT USAGE ON SCHEMA marts, ref TO agent_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA marts, ref TO agent_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA marts, ref GRANT SELECT ON TABLES TO agent_ro;
ALTER ROLE agent_ro SET default_transaction_read_only = on;
ALTER ROLE agent_ro SET statement_timeout = '10s';
ALTER ROLE agent_ro SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE agent_ro SET search_path = marts, ref;
ALTER ROLE agent_ro CONNECTION LIMIT 5;

-- ---------- agent_rw: the AI agent can only append to its own log tables -----------
GRANT USAGE ON SCHEMA agent TO agent_rw;
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA agent TO agent_rw;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA agent TO agent_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA agent GRANT SELECT, INSERT ON TABLES TO agent_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA agent GRANT USAGE, SELECT ON SEQUENCES TO agent_rw;
ALTER ROLE agent_rw SET statement_timeout = '10s';
ALTER ROLE agent_rw SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE agent_rw CONNECTION LIMIT 5;

-- ---------- approver_rw: humans change only the review columns of an action -----------
GRANT USAGE ON SCHEMA agent TO approver_rw;
GRANT SELECT ON agent.action_queue TO approver_rw;
GRANT UPDATE (status, reviewed_by, reviewed_at) ON agent.action_queue TO approver_rw;
ALTER ROLE approver_rw SET statement_timeout = '10s';
ALTER ROLE approver_rw CONNECTION LIMIT 5;