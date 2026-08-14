-- Allow ai_infra role to connect with password from external hosts
-- This runs as the init user which has superuser privileges
ALTER ROLE ai_infra WITH LOGIN PASSWORD 'ai_infra';
