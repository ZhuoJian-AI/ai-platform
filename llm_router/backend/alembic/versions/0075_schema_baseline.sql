-- AI Platform static PostgreSQL schema baseline at 0075_retired_schema_contract.
-- Generated from the historical 0001-0075 chain; do not edit without fingerprint verification.

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '120s';

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public VERSION '0.8.2';


--
-- Name: reject_ai_quota_event_mutation(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.reject_ai_quota_event_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            RAISE EXCEPTION 'ai_quota_events is append-only';
        END;
        $$;


--
-- Name: reject_new_usd_budget_cap(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.reject_new_usd_budget_cap() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.budget_cap_usd IS NOT NULL THEN
                    RAISE EXCEPTION 'USD budgets are legacy read-only; use token or credit budgets';
                END IF;
            ELSIF NEW.budget_cap_usd IS NOT NULL AND
                  NEW.budget_cap_usd IS DISTINCT FROM OLD.budget_cap_usd THEN
                RAISE EXCEPTION 'USD budgets are legacy read-only; use token or credit budgets';
            END IF;
            RETURN NEW;
        END;
        $$;




--
-- Name: admins; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.admins (
    id integer NOT NULL,
    username character varying(320) CONSTRAINT admins_email_not_null NOT NULL,
    password_hash character varying(255) NOT NULL,
    display_name character varying(255),
    role character varying(20) NOT NULL,
    is_active boolean NOT NULL,
    must_change_password boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    organization_id uuid,
    auth_epoch integer DEFAULT 0 NOT NULL,
    mfa_secret_encrypted text,
    mfa_enabled boolean DEFAULT false NOT NULL,
    mfa_recovery_code_hashes jsonb DEFAULT '[]'::jsonb NOT NULL,
    mfa_verified_at timestamp with time zone,
    mfa_last_totp_counter integer,
    CONSTRAINT ck_admin_role_organization CHECK (((((role)::text = 'platform_super_admin'::text) AND (organization_id IS NULL)) OR (((role)::text = 'enterprise_admin'::text) AND (organization_id IS NOT NULL))))
);


--
-- Name: admins_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.admins_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: admins_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.admins_id_seq OWNED BY public.admins.id;


--
-- Name: agent_run_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_run_events (
    id uuid NOT NULL,
    run_id bigint,
    task_id character varying,
    seq integer NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: agent_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_runs (
    id bigint NOT NULL,
    organization_id uuid NOT NULL,
    agent_id uuid,
    session_id character varying(128) NOT NULL,
    request text DEFAULT ''::text NOT NULL,
    __baseline_dropped_6 text,
    __baseline_dropped_7 text,
    input_tokens integer,
    output_tokens integer,
    latency_ms integer,
    status character varying(20) DEFAULT 'running'::character varying NOT NULL,
    error text,
    __baseline_dropped_13 text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    task_id uuid,
    user_id uuid,
    exec_mode character varying(20) DEFAULT 'craft'::character varying NOT NULL,
    __baseline_dropped_19 text
);
ALTER TABLE ONLY public.agent_runs DROP COLUMN __baseline_dropped_6;
ALTER TABLE ONLY public.agent_runs DROP COLUMN __baseline_dropped_7;
ALTER TABLE ONLY public.agent_runs DROP COLUMN __baseline_dropped_13;
ALTER TABLE ONLY public.agent_runs DROP COLUMN __baseline_dropped_19;


--
-- Name: agent_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.agent_runs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agent_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.agent_runs_id_seq OWNED BY public.agent_runs.id;


--
-- Name: agents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agents (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    name character varying(255) NOT NULL,
    slug character varying(100) NOT NULL,
    description text,
    system_prompt text DEFAULT ''::text NOT NULL,
    model_alias character varying(255) DEFAULT 'default'::character varying NOT NULL,
    __baseline_dropped_8 text,
    memory_config jsonb DEFAULT '{}'::jsonb NOT NULL,
    __baseline_dropped_10 text,
    workspace_id uuid,
    __baseline_dropped_12 text,
    __baseline_dropped_13 text,
    skill_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    temperature double precision,
    max_tokens integer,
    is_active boolean DEFAULT true NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    scope_type character varying(20) DEFAULT 'organization'::character varying NOT NULL,
    scope_id character varying(36),
    created_by character varying(36),
    rag_collection_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    application_id uuid,
    module_key character varying(128),
    page_key character varying(128)
);
ALTER TABLE ONLY public.agents DROP COLUMN __baseline_dropped_8;
ALTER TABLE ONLY public.agents DROP COLUMN __baseline_dropped_10;
ALTER TABLE ONLY public.agents DROP COLUMN __baseline_dropped_12;
ALTER TABLE ONLY public.agents DROP COLUMN __baseline_dropped_13;


--
-- Name: ai_quota_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ai_quota_events (
    id uuid NOT NULL,
    reservation_id character varying(128) NOT NULL,
    organization_id character varying(36) NOT NULL,
    department_id character varying(36),
    __baseline_dropped_5 text,
    api_key_id character varying(36),
    provider_id character varying(36),
    scope_type character varying(20) NOT NULL,
    scope_id character varying(36) NOT NULL,
    event_type character varying(24) NOT NULL,
    operation character varying(64),
    outcome character varying(24),
    reserved_tokens bigint DEFAULT '0'::bigint NOT NULL,
    reserved_credits integer DEFAULT 1 NOT NULL,
    actual_tokens bigint,
    actual_input_tokens bigint,
    actual_output_tokens bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_ai_quota_events_event_type CHECK (event_type IN ('reserved','settled')),
    CONSTRAINT ck_ai_quota_events_reserved_credits CHECK ((reserved_credits >= 0)),
    CONSTRAINT ck_ai_quota_events_reserved_tokens CHECK ((reserved_tokens >= 0))
);
ALTER TABLE ONLY public.ai_quota_events DROP COLUMN __baseline_dropped_5;


--
-- Name: ai_quota_monthly_rollups; Type: MATERIALIZED VIEW; Schema: public; Owner: -
--

CREATE MATERIALIZED VIEW public.ai_quota_monthly_rollups AS
 SELECT (date_trunc('month'::text, (created_at AT TIME ZONE 'UTC'::text)))::date AS period_month,
    organization_id,
    scope_type,
    scope_id,
    COALESCE(department_id, ''::character varying) AS department_key,
    COALESCE(api_key_id, ''::character varying) AS api_key_key,
    COALESCE(provider_id, ''::character varying) AS provider_key,
    COALESCE(operation, ''::character varying) AS operation_key,
    count(*) FILTER (WHERE ((event_type)::text = 'reserved'::text)) AS admitted_operations,
    (COALESCE(sum(reserved_tokens) FILTER (WHERE ((event_type)::text = 'reserved'::text)), (0)::numeric))::bigint AS reserved_tokens,
    COALESCE(sum(reserved_credits) FILTER (WHERE ((event_type)::text = 'reserved'::text)), (0)::bigint) AS admitted_credits,
    (COALESCE(sum(actual_tokens) FILTER (WHERE ((event_type)::text = 'settled'::text)), (0)::numeric))::bigint AS actual_tokens,
    count(*) FILTER (WHERE (((event_type)::text = 'settled'::text) AND ((outcome)::text ~~ 'failed%'::text))) AS failed_operations,
    max(created_at) AS refreshed_through
   FROM public.ai_quota_events
  GROUP BY ((date_trunc('month'::text, (created_at AT TIME ZONE 'UTC'::text)))::date), organization_id, scope_type, scope_id, COALESCE(department_id, ''::character varying), COALESCE(api_key_id, ''::character varying), COALESCE(provider_id, ''::character varying), COALESCE(operation, ''::character varying)
  WITH NO DATA;


--
-- Name: api_keys; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.api_keys (
    key_prefix character varying(12) NOT NULL,
    key_hash character varying(128) NOT NULL,
    key_name character varying(255) NOT NULL,
    scope_type character varying(20) NOT NULL,
    organization_id uuid NOT NULL,
    department_id uuid,
    __baseline_dropped_7 text,
    created_by uuid,
    allowed_models jsonb NOT NULL,
    rate_limit_rpm integer,
    rate_limit_tpm integer,
    budget_cap_usd numeric(12,2),
    is_active boolean NOT NULL,
    expires_at timestamp with time zone,
    last_used_at timestamp with time zone,
    revoked_at timestamp with time zone,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    key_encrypted text DEFAULT ''::text NOT NULL,
    budget_cap_tokens bigint,
    budget_cap_credits bigint,
    CONSTRAINT ck_api_keys_budget_cap_credits_nonnegative CHECK (((budget_cap_credits IS NULL) OR (budget_cap_credits >= 0)))
);
ALTER TABLE ONLY public.api_keys DROP COLUMN __baseline_dropped_7;


--
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_logs (
    id bigint NOT NULL,
    request_id character varying NOT NULL,
    api_key_id uuid,
    organization_id character varying NOT NULL,
    department_id character varying,
    __baseline_dropped_6 text,
    provider_id character varying,
    event_type character varying(50) NOT NULL,
    direction character varying(20),
    model_requested character varying(255),
    model_served character varying(255),
    input_tokens integer,
    output_tokens integer,
    latency_ms integer,
    dlp_violations jsonb NOT NULL,
    status_code integer,
    error_message text,
    metadata jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
ALTER TABLE ONLY public.audit_logs DROP COLUMN __baseline_dropped_6;


--
-- Name: audit_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audit_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.audit_logs_id_seq OWNED BY public.audit_logs.id;


--
-- Name: departments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.departments (
    organization_id uuid NOT NULL,
    name character varying(255) NOT NULL,
    slug character varying(100) NOT NULL,
    description text,
    settings jsonb NOT NULL,
    rate_limit_rpm integer,
    rate_limit_tpm integer,
    budget_cap_usd numeric(12,2),
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    budget_cap_tokens bigint,
    parent_id uuid,
    sort_order integer DEFAULT 0 NOT NULL,
    budget_cap_credits bigint,
    CONSTRAINT ck_departments_budget_cap_credits_nonnegative CHECK (((budget_cap_credits IS NULL) OR (budget_cap_credits >= 0)))
);


--
-- Name: dlp_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dlp_rules (
    organization_id uuid,
    name character varying(255) NOT NULL,
    description text,
    rule_type character varying(50) NOT NULL,
    severity character varying(20) NOT NULL,
    action character varying(20) NOT NULL,
    direction character varying(20) NOT NULL,
    pattern text NOT NULL,
    scope_type character varying(20) NOT NULL,
    scope_id uuid,
    is_active boolean NOT NULL,
    priority integer NOT NULL,
    created_by uuid,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone
);


--
-- Name: ecs_module_releases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ecs_module_releases (
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    organization_id uuid NOT NULL,
    runtime_id uuid NOT NULL,
    application_id uuid,
    application_slug character varying(80) NOT NULL,
    application_name character varying(255) NOT NULL,
    base_url text NOT NULL,
    requested_commit character varying(64) NOT NULL,
    last_success_commit character varying(64),
    image_ref text,
    contract_revision character varying(20),
    manifest_digest character varying(64),
    status character varying(40) DEFAULT 'verifying'::character varying NOT NULL,
    release_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    last_error text,
    deployed_at timestamp with time zone,
    last_seen_at timestamp with time zone,
    CONSTRAINT ck_ecs_module_release_status CHECK (status IN ('verifying','pending_review','healthy','failed'))
);


--
-- Name: ecs_runtimes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ecs_runtimes (
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    organization_id uuid NOT NULL,
    runtime_key character varying(80) NOT NULL,
    enterprise_key character varying(80) NOT NULL,
    environment character varying(40) DEFAULT 'staging'::character varying NOT NULL,
    domain_suffix character varying(255) NOT NULL,
    public_address character varying(255),
    credential_prefix character varying(24) NOT NULL,
    credential_hash character varying(64) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    credential_rotated_at timestamp with time zone DEFAULT now() NOT NULL,
    last_seen_at timestamp with time zone
);


--
-- Name: enterprise_application_action_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.enterprise_application_action_requests (
    application_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    action_id uuid NOT NULL,
    user_id uuid NOT NULL,
    request_id character varying(200) NOT NULL,
    module_key character varying(120) NOT NULL,
    params_encrypted text,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    resolved_at timestamp with time zone,
    result jsonb DEFAULT '{}'::jsonb NOT NULL,
    error text,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_enterprise_application_action_request_status CHECK (status IN ('pending','executing','completed','rejected','expired','failed'))
);


--
-- Name: enterprise_application_actions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.enterprise_application_actions (
    application_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    module_key character varying(120) NOT NULL,
    action_key character varying(160) NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    operation character varying(20) NOT NULL,
    ai_enabled boolean DEFAULT false NOT NULL,
    requires_confirmation boolean DEFAULT false NOT NULL,
    input_schema jsonb DEFAULT '{}'::jsonb NOT NULL,
    result_schema jsonb DEFAULT '{}'::jsonb NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    admin_disabled boolean DEFAULT false NOT NULL,
    CONSTRAINT ck_enterprise_application_action_operation CHECK (operation IN ('query','create','update','delete','export','approve'))
);


--
-- Name: enterprise_application_event_deliveries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.enterprise_application_event_deliveries (
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    organization_id uuid CONSTRAINT enterprise_application_event_deliverie_organization_id_not_null NOT NULL,
    route_id uuid NOT NULL,
    source_event_id uuid CONSTRAINT enterprise_application_event_deliverie_source_event_id_not_null NOT NULL,
    target_application_id uuid CONSTRAINT enterprise_application_event_del_target_application_id_not_null NOT NULL,
    delivery_id character varying(200) NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    delivered_at timestamp with time zone,
    response jsonb DEFAULT '{}'::jsonb NOT NULL,
    last_error text,
    CONSTRAINT ck_enterprise_event_delivery_status CHECK (status IN ('pending','delivering','delivered','failed'))
);


--
-- Name: enterprise_application_event_routes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.enterprise_application_event_routes (
    application_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    name character varying(160) NOT NULL,
    event_type character varying(160) NOT NULL,
    module_key character varying(120),
    target_scope_type character varying(20) NOT NULL,
    target_scope_id character varying(36),
    target_module_key character varying(120),
    is_active boolean DEFAULT true NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    target_application_id uuid,
    CONSTRAINT ck_enterprise_application_event_route_scope_type CHECK (target_scope_type IN ('organization','department','user'))
);


--
-- Name: enterprise_application_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.enterprise_application_events (
    application_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    event_id character varying(200) NOT NULL,
    source_sequence bigint NOT NULL,
    event_type character varying(160) NOT NULL,
    module_key character varying(120),
    entity_type character varying(120),
    entity_id character varying(200),
    action character varying(80),
    occurred_at timestamp with time zone,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: enterprise_application_grants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.enterprise_application_grants (
    application_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    scope_type character varying(20) NOT NULL,
    scope_id character varying(36),
    permissions jsonb DEFAULT '[]'::jsonb NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    module_keys jsonb DEFAULT '[]'::jsonb NOT NULL,
    module_access jsonb DEFAULT '{}'::jsonb NOT NULL,
    managed_key character varying(100),
    denied_resources jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT ck_enterprise_application_grant_scope_type CHECK (scope_type IN ('organization','department','user','role'))
);


--
-- Name: enterprise_application_integrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.enterprise_application_integrations (
    application_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    manifest_url text NOT NULL,
    events_url text,
    auth_token_encrypted text,
    protocol_version integer DEFAULT 1 NOT NULL,
    manifest jsonb DEFAULT '{}'::jsonb NOT NULL,
    cursor_sequence bigint DEFAULT '0'::bigint NOT NULL,
    sync_enabled boolean DEFAULT true NOT NULL,
    sync_status character varying(20) DEFAULT 'ready'::character varying NOT NULL,
    last_manifest_sync_at timestamp with time zone,
    last_event_sync_at timestamp with time zone,
    last_error text,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    credential_version integer DEFAULT 1 NOT NULL,
    sso_exchange_credential_prefix character varying(24),
    sso_exchange_credential_hash character varying(64),
    action_signing_secret_encrypted text,
    event_signing_secret_encrypted text,
    pending_manifest jsonb DEFAULT '{}'::jsonb NOT NULL,
    manifest_diff jsonb DEFAULT '[]'::jsonb NOT NULL,
    manifest_review_status character varying(20) DEFAULT 'approved'::character varying CONSTRAINT enterprise_application_integrat_manifest_review_status_not_null NOT NULL,
    pending_contract_revision character varying(20),
    CONSTRAINT ck_enterprise_application_integration_manifest_review CHECK (manifest_review_status IN ('approved','pending','rejected')),
    CONSTRAINT ck_enterprise_application_integration_status CHECK (sync_status IN ('unconfigured','ready','syncing','healthy','pending_review','error'))
);


--
-- Name: enterprise_application_sso_codes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.enterprise_application_sso_codes (
    application_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    user_id uuid NOT NULL,
    code_hash character varying(64) NOT NULL,
    module_key character varying(120) NOT NULL,
    redirect_path text NOT NULL,
    session_binding_hash character varying(64) NOT NULL,
    launch_nonce character varying(128) NOT NULL,
    claims_encrypted text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    consumed_at timestamp with time zone,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: enterprise_applications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.enterprise_applications (
    organization_id uuid NOT NULL,
    name character varying(255) NOT NULL,
    slug character varying(100) NOT NULL,
    description text,
    icon_url text,
    entry_url text NOT NULL,
    display_mode character varying(20) DEFAULT 'embedded'::character varying NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    assistant_enabled boolean DEFAULT true NOT NULL,
    assistant_prompt text,
    assistant_config jsonb DEFAULT '{}'::jsonb NOT NULL,
    health_status character varying(20) DEFAULT 'unknown'::character varying NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    admin_disabled boolean DEFAULT false NOT NULL,
    CONSTRAINT ck_enterprise_application_display_mode CHECK (display_mode IN ('embedded','external'))
);


--
-- Name: file_mutations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.file_mutations (
    organization_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    workspace_file_id uuid,
    actor_type character varying(16) NOT NULL,
    actor_id character varying(64) NOT NULL,
    operation character varying(32) NOT NULL,
    idempotency_key character varying(160) NOT NULL,
    request_hash character varying(64) NOT NULL,
    base_version_id uuid,
    result_file_id uuid,
    result_version_id uuid,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    result jsonb DEFAULT '{}'::jsonb NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: llm_providers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.llm_providers (
    organization_id uuid NOT NULL,
    name character varying(255) NOT NULL,
    provider_type character varying(50) NOT NULL,
    base_url text NOT NULL,
    api_key_encrypted text NOT NULL,
    api_key_version integer NOT NULL,
    is_active boolean NOT NULL,
    priority integer NOT NULL,
    weight integer NOT NULL,
    timeout_seconds integer NOT NULL,
    max_retries integer NOT NULL,
    supported_models jsonb NOT NULL,
    health_status character varying(20) NOT NULL,
    config jsonb NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    scope_type character varying(20) DEFAULT 'organization'::character varying NOT NULL,
    department_id uuid,
    __baseline_dropped_21 text,
    vendor character varying(50) DEFAULT 'custom'::character varying NOT NULL,
    region character varying(64),
    workspace_id character varying(255)
);
ALTER TABLE ONLY public.llm_providers DROP COLUMN __baseline_dropped_21;


--
-- Name: memories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.memories (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    scope_type character varying(20) NOT NULL,
    scope_id character varying(36),
    category character varying(100) DEFAULT 'general'::character varying NOT NULL,
    content text NOT NULL,
    source character varying(20) DEFAULT 'manual'::character varying NOT NULL,
    created_by uuid,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    embedding public.vector,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone
);


--
-- Name: model_deployments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.model_deployments (
    provider_id uuid NOT NULL,
    model_id character varying(255) NOT NULL,
    display_name character varying(255),
    adapter character varying(64) DEFAULT 'openai_chat_completions'::character varying NOT NULL,
    capabilities jsonb DEFAULT '[]'::jsonb NOT NULL,
    base_url_override text,
    endpoint_path character varying(255),
    embedding_dimensions integer,
    routing_priority integer DEFAULT 0 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    verification_status character varying(32) DEFAULT 'unverified'::character varying NOT NULL,
    last_error text,
    config jsonb DEFAULT '{}'::jsonb NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone
);


--
-- Name: multimodal_jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.multimodal_jobs (
    organization_id uuid NOT NULL,
    user_id uuid NOT NULL,
    department_id uuid,
    capability character varying(40) NOT NULL,
    deployment_id uuid,
    input_file_id uuid,
    output_file_ref text,
    voice_profile_id uuid,
    status character varying(20) DEFAULT 'queued'::character varying NOT NULL,
    request_id character varying(120) NOT NULL,
    idempotency_key character varying(160) NOT NULL,
    params jsonb DEFAULT '{}'::jsonb NOT NULL,
    result jsonb DEFAULT '{}'::jsonb NOT NULL,
    usage jsonb DEFAULT '{}'::jsonb NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    max_attempts integer DEFAULT 3 NOT NULL,
    available_at timestamp with time zone NOT NULL,
    locked_at timestamp with time zone,
    locked_by character varying(120),
    finished_at timestamp with time zone,
    audio_duration_ms bigint,
    latency_ms integer,
    error_category character varying(80),
    error_detail text,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    __baseline_dropped_28 text,
    CONSTRAINT ck_multimodal_job_status CHECK (status IN ('queued','processing','succeeded','failed','cancelled'))
);
ALTER TABLE ONLY public.multimodal_jobs DROP COLUMN __baseline_dropped_28;


--
-- Name: organization_slug_aliases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.organization_slug_aliases (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organization_id uuid NOT NULL,
    slug character varying(100) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: organizations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.organizations (
    name character varying(255) NOT NULL,
    slug character varying(100) NOT NULL,
    description text,
    settings jsonb NOT NULL,
    rate_limit_rpm integer,
    rate_limit_tpm integer,
    budget_cap_usd numeric(12,2),
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    budget_cap_tokens bigint,
    is_default boolean DEFAULT false NOT NULL,
    budget_cap_credits bigint,
    CONSTRAINT ck_organizations_budget_cap_credits_nonnegative CHECK (((budget_cap_credits IS NULL) OR (budget_cap_credits >= 0)))
);


--
-- Name: rag_chunks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rag_chunks (
    id uuid NOT NULL,
    collection_id uuid NOT NULL,
    document_id uuid,
    content text DEFAULT ''::text NOT NULL,
    embedding public.vector,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: rag_collections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rag_collections (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    name character varying(255) NOT NULL,
    slug character varying(100) NOT NULL,
    description text,
    embedding_model character varying(255) DEFAULT 'text-embedding-3-small'::character varying NOT NULL,
    embedding_dim integer,
    chunk_size integer DEFAULT 800 NOT NULL,
    chunk_overlap integer DEFAULT 100 NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    scope_type character varying(20) DEFAULT 'organization'::character varying NOT NULL,
    scope_id character varying(36),
    created_by character varying(36),
    purge_after timestamp with time zone
);


--
-- Name: rag_documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rag_documents (
    id uuid NOT NULL,
    collection_id uuid NOT NULL,
    source character varying(512) NOT NULL,
    title character varying(512),
    content text DEFAULT ''::text NOT NULL,
    doc_hash character varying(128),
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    folder_path character varying(1024) DEFAULT ''::character varying NOT NULL,
    created_by character varying(36),
    status character varying(20) DEFAULT 'ready'::character varying NOT NULL,
    progress integer DEFAULT 100 NOT NULL,
    parse_error text,
    purge_after timestamp with time zone
);


--
-- Name: rag_folders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rag_folders (
    id uuid NOT NULL,
    collection_id uuid NOT NULL,
    path character varying(1024) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    created_by character varying(36),
    purge_after timestamp with time zone
);


--
-- Name: role_data_departments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.role_data_departments (
    role_id uuid NOT NULL,
    department_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: role_permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.role_permissions (
    role_id uuid NOT NULL,
    permission_code character varying(160) NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.roles (
    organization_id uuid NOT NULL,
    name character varying(120) NOT NULL,
    code character varying(100) NOT NULL,
    description character varying(500),
    data_scope character varying(40) DEFAULT 'self'::character varying NOT NULL,
    is_builtin boolean DEFAULT false NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    system_key character varying(100),
    CONSTRAINT ck_role_data_scope CHECK (data_scope IN ('all','custom_departments','department','department_and_children','self'))
);


--
-- Name: routing_policies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.routing_policies (
    organization_id uuid NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    model_pattern character varying(255) NOT NULL,
    strategy character varying(50) NOT NULL,
    provider_ids jsonb NOT NULL,
    is_default boolean NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone
);


--
-- Name: skill_executions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.skill_executions (
    id bigint NOT NULL,
    organization_id uuid NOT NULL,
    user_id uuid,
    task_id uuid,
    agent_id uuid,
    skill_folder_id uuid NOT NULL,
    skill_version_id uuid NOT NULL,
    input_file_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    output_file_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    params jsonb DEFAULT '{}'::jsonb NOT NULL,
    status character varying(20) DEFAULT 'running'::character varying NOT NULL,
    latency_ms integer,
    error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: skill_executions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.skill_executions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: skill_executions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.skill_executions_id_seq OWNED BY public.skill_executions.id;


--
-- Name: skill_files; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.skill_files (
    id uuid NOT NULL,
    skill_folder_id uuid NOT NULL,
    path character varying(1024) NOT NULL,
    size bigint DEFAULT '0'::bigint NOT NULL,
    content_hash character varying(128),
    content text,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    purge_after timestamp with time zone
);


--
-- Name: skill_folders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.skill_folders (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    scope_type character varying(20) DEFAULT 'organization'::character varying NOT NULL,
    scope_id character varying(36),
    name character varying(255) NOT NULL,
    slug character varying(100) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    created_by character varying(36),
    is_active boolean DEFAULT true NOT NULL,
    active_version_id uuid,
    purge_after timestamp with time zone
);


--
-- Name: skill_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.skill_versions (
    skill_folder_id uuid NOT NULL,
    version_no integer NOT NULL,
    package_hash character varying(64) NOT NULL,
    manifest jsonb NOT NULL,
    archive bytea,
    runtime character varying(20) DEFAULT 'prompt'::character varying NOT NULL,
    entrypoint character varying(1024),
    is_executable boolean DEFAULT false NOT NULL,
    install_status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    install_error text,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    archive_ref text,
    archive_size bigint DEFAULT '0'::bigint NOT NULL,
    storage_status character varying(20) DEFAULT 'inline'::character varying NOT NULL,
    purge_after timestamp with time zone,
    archive_purged_at timestamp with time zone
);


--
-- Name: task_file_refs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_file_refs (
    task_id uuid NOT NULL,
    workspace_file_id uuid NOT NULL,
    version_id uuid,
    scope character varying(16) DEFAULT 'turn'::character varying NOT NULL,
    follow_latest boolean DEFAULT true NOT NULL,
    source character varying(32) DEFAULT 'message'::character varying NOT NULL,
    workspace_name character varying(255),
    canonical_path character varying(1400),
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: task_messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_messages (
    id uuid NOT NULL,
    task_id uuid NOT NULL,
    role character varying(20) NOT NULL,
    content text DEFAULT ''::text NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tasks (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    user_id uuid NOT NULL,
    department_id uuid,
    __baseline_dropped_5 text,
    session_id character varying(128) NOT NULL,
    title character varying(255) DEFAULT ''::character varying NOT NULL,
    message text DEFAULT ''::text NOT NULL,
    config jsonb DEFAULT '{}'::jsonb NOT NULL,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone
);
ALTER TABLE ONLY public.tasks DROP COLUMN __baseline_dropped_5;


--
-- Name: user_roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_roles (
    user_id uuid NOT NULL,
    role_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    organization_id uuid NOT NULL,
    username character varying(320) CONSTRAINT users_email_not_null NOT NULL,
    display_name character varying(255),
    __baseline_dropped_4 text,
    is_active boolean NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    password_hash character varying(255),
    must_change_password boolean DEFAULT false NOT NULL,
    department_id uuid,
    __baseline_dropped_13 text,
    auth_epoch integer DEFAULT 0 NOT NULL
);
ALTER TABLE ONLY public.users DROP COLUMN __baseline_dropped_4;
ALTER TABLE ONLY public.users DROP COLUMN __baseline_dropped_13;


--
-- Name: voice_authorization_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.voice_authorization_records (
    voice_profile_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    rights_holder character varying(255) NOT NULL,
    purpose text NOT NULL,
    evidence_file_id uuid NOT NULL,
    confirmed_by_user_id uuid,
    confirmed_by_admin_id integer,
    confirmed_at timestamp with time zone NOT NULL,
    valid_until timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    evidence_digest character varying(64) NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: voice_profile_grants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.voice_profile_grants (
    voice_profile_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    scope_type character varying(20) NOT NULL,
    scope_id character varying(36),
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    CONSTRAINT ck_voice_profile_grant_scope CHECK (scope_type IN ('organization','role','department','user'))
);


--
-- Name: voice_profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.voice_profiles (
    organization_id uuid NOT NULL,
    created_by_user_id uuid,
    created_by_admin_id integer,
    name character varying(160) NOT NULL,
    voice_type character varying(20) NOT NULL,
    provider_voice_id character varying(255),
    design_prompt text,
    sample_file_id uuid,
    config jsonb DEFAULT '{}'::jsonb NOT NULL,
    status character varying(24) DEFAULT 'active'::character varying NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    CONSTRAINT ck_voice_profile_status CHECK (status IN ('active','disabled','pending_cleanup')),
    CONSTRAINT ck_voice_profile_type CHECK (voice_type IN ('builtin','designed','cloned'))
);


--
-- Name: workspace_audit_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspace_audit_events (
    id bigint NOT NULL,
    organization_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    workspace_file_id uuid,
    version_id uuid,
    actor_user_id uuid,
    actor_admin_id bigint,
    action character varying(50) NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: workspace_audit_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.workspace_audit_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: workspace_audit_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.workspace_audit_events_id_seq OWNED BY public.workspace_audit_events.id;


--
-- Name: workspace_file_event_outbox; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspace_file_event_outbox (
    id bigint NOT NULL,
    organization_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    workspace_file_id uuid NOT NULL,
    version_id uuid,
    event_type character varying(40) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: workspace_file_event_outbox_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.workspace_file_event_outbox_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: workspace_file_event_outbox_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.workspace_file_event_outbox_id_seq OWNED BY public.workspace_file_event_outbox.id;


--
-- Name: workspace_file_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspace_file_versions (
    workspace_file_id uuid NOT NULL,
    version_no integer NOT NULL,
    size bigint DEFAULT '0'::bigint NOT NULL,
    content_hash character varying(128),
    content_ref text,
    content text,
    extracted_text text,
    parse_status character varying(20) DEFAULT 'unparsed'::character varying NOT NULL,
    parse_kind character varying(20),
    parse_error text,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_by_user_id uuid,
    created_by_admin_id bigint,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    mutation_idempotency_key character varying(160),
    mutation_request_hash character varying(64),
    storage_version_id character varying(1024),
    storage_etag character varying(256)
);


--
-- Name: workspace_files; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspace_files (
    id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    path character varying(1024) NOT NULL,
    size bigint DEFAULT '0'::bigint NOT NULL,
    content_hash character varying(128),
    content_ref text,
    content text,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    extracted_text text,
    parse_status character varying(20) DEFAULT 'unparsed'::character varying NOT NULL,
    parse_kind character varying(20),
    parse_error text,
    created_by_user_id uuid,
    deleted_by_user_id uuid,
    deleted_by_admin_id bigint,
    purge_after timestamp with time zone,
    parse_attempts integer DEFAULT 0 NOT NULL,
    parse_locked_at timestamp with time zone,
    parse_locked_by character varying(100),
    current_version_id uuid
);


--
-- Name: workspace_folders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspace_folders (
    id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    path character varying(1024) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    purge_after timestamp with time zone
);


--
-- Name: workspace_preview_jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspace_preview_jobs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    workspace_file_id uuid NOT NULL,
    file_version_id uuid NOT NULL,
    conversion_type character varying(32) DEFAULT 'pdf'::character varying NOT NULL,
    status character varying(20) DEFAULT 'queued'::character varying NOT NULL,
    attempt_count integer DEFAULT 0 NOT NULL,
    next_attempt_at timestamp with time zone DEFAULT now() NOT NULL,
    lease_expires_at timestamp with time zone,
    locked_by character varying(100),
    output_ref text,
    error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: workspace_share_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspace_share_links (
    workspace_file_id uuid NOT NULL,
    version_id uuid NOT NULL,
    token_hash character varying(64) NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    created_by_user_id uuid,
    created_by_admin_id bigint,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: workspace_upload_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspace_upload_sessions (
    organization_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    user_id uuid,
    admin_id bigint,
    path character varying(1024) NOT NULL,
    original_filename character varying(512) NOT NULL,
    content_type character varying(255) NOT NULL,
    expected_size bigint NOT NULL,
    content_ref text,
    upload_url text,
    upload_headers jsonb DEFAULT '{}'::jsonb NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    error text,
    expires_at timestamp with time zone NOT NULL,
    completed_at timestamp with time zone,
    workspace_file_id uuid,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_workspace_upload_session_one_actor CHECK (((user_id IS NOT NULL) <> (admin_id IS NOT NULL)))
);


--
-- Name: workspaces; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspaces (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    name character varying(255) NOT NULL,
    slug character varying(100) NOT NULL,
    description text,
    storage_backend character varying(20) DEFAULT 'local'::character varying NOT NULL,
    root_path character varying(512) DEFAULT ''::character varying NOT NULL,
    config jsonb DEFAULT '{}'::jsonb NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    scope_type character varying(20) DEFAULT 'organization'::character varying NOT NULL,
    scope_id character varying(36),
    purge_after timestamp with time zone
);


--
-- Name: admins id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admins ALTER COLUMN id SET DEFAULT nextval('public.admins_id_seq'::regclass);


--
-- Name: agent_runs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runs ALTER COLUMN id SET DEFAULT nextval('public.agent_runs_id_seq'::regclass);


--
-- Name: audit_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs ALTER COLUMN id SET DEFAULT nextval('public.audit_logs_id_seq'::regclass);


--
-- Name: skill_executions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skill_executions ALTER COLUMN id SET DEFAULT nextval('public.skill_executions_id_seq'::regclass);


--
-- Name: workspace_audit_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_audit_events ALTER COLUMN id SET DEFAULT nextval('public.workspace_audit_events_id_seq'::regclass);


--
-- Name: workspace_file_event_outbox id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_file_event_outbox ALTER COLUMN id SET DEFAULT nextval('public.workspace_file_event_outbox_id_seq'::regclass);


--
-- Name: admins admins_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admins
    ADD CONSTRAINT admins_pkey PRIMARY KEY (id);


--
-- Name: agent_run_events agent_run_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_run_events
    ADD CONSTRAINT agent_run_events_pkey PRIMARY KEY (id);


--
-- Name: agent_runs agent_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT agent_runs_pkey PRIMARY KEY (id);


--
-- Name: agents agents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agents_pkey PRIMARY KEY (id);


--
-- Name: ai_quota_events ai_quota_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_quota_events
    ADD CONSTRAINT ai_quota_events_pkey PRIMARY KEY (id);


--
-- Name: api_keys api_keys_key_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_key_hash_key UNIQUE (key_hash);


--
-- Name: api_keys api_keys_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_pkey PRIMARY KEY (id);


--
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);


--
-- Name: departments departments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.departments
    ADD CONSTRAINT departments_pkey PRIMARY KEY (id);


--
-- Name: dlp_rules dlp_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dlp_rules
    ADD CONSTRAINT dlp_rules_pkey PRIMARY KEY (id);


--
-- Name: ecs_module_releases ecs_module_releases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ecs_module_releases
    ADD CONSTRAINT ecs_module_releases_pkey PRIMARY KEY (id);


--
-- Name: ecs_runtimes ecs_runtimes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ecs_runtimes
    ADD CONSTRAINT ecs_runtimes_pkey PRIMARY KEY (id);


--
-- Name: enterprise_application_action_requests enterprise_application_action_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_action_requests
    ADD CONSTRAINT enterprise_application_action_requests_pkey PRIMARY KEY (id);


--
-- Name: enterprise_application_actions enterprise_application_actions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_actions
    ADD CONSTRAINT enterprise_application_actions_pkey PRIMARY KEY (id);


--
-- Name: enterprise_application_event_deliveries enterprise_application_event_deliveries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_event_deliveries
    ADD CONSTRAINT enterprise_application_event_deliveries_pkey PRIMARY KEY (id);


--
-- Name: enterprise_application_event_routes enterprise_application_event_routes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_event_routes
    ADD CONSTRAINT enterprise_application_event_routes_pkey PRIMARY KEY (id);


--
-- Name: enterprise_application_events enterprise_application_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_events
    ADD CONSTRAINT enterprise_application_events_pkey PRIMARY KEY (id);


--
-- Name: enterprise_application_grants enterprise_application_grants_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_grants
    ADD CONSTRAINT enterprise_application_grants_pkey PRIMARY KEY (id);


--
-- Name: enterprise_application_integrations enterprise_application_integrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_integrations
    ADD CONSTRAINT enterprise_application_integrations_pkey PRIMARY KEY (id);


--
-- Name: enterprise_application_sso_codes enterprise_application_sso_codes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_sso_codes
    ADD CONSTRAINT enterprise_application_sso_codes_pkey PRIMARY KEY (id);


--
-- Name: enterprise_applications enterprise_applications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_applications
    ADD CONSTRAINT enterprise_applications_pkey PRIMARY KEY (id);


--
-- Name: file_mutations file_mutations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.file_mutations
    ADD CONSTRAINT file_mutations_pkey PRIMARY KEY (id);


--
-- Name: llm_providers llm_providers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_providers
    ADD CONSTRAINT llm_providers_pkey PRIMARY KEY (id);


--
-- Name: memories memories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memories
    ADD CONSTRAINT memories_pkey PRIMARY KEY (id);


--
-- Name: model_deployments model_deployments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_deployments
    ADD CONSTRAINT model_deployments_pkey PRIMARY KEY (id);


--
-- Name: multimodal_jobs multimodal_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.multimodal_jobs
    ADD CONSTRAINT multimodal_jobs_pkey PRIMARY KEY (id);


--
-- Name: organization_slug_aliases organization_slug_aliases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organization_slug_aliases
    ADD CONSTRAINT organization_slug_aliases_pkey PRIMARY KEY (id);


--
-- Name: organizations organizations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organizations
    ADD CONSTRAINT organizations_pkey PRIMARY KEY (id);


--
-- Name: rag_chunks rag_chunks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rag_chunks
    ADD CONSTRAINT rag_chunks_pkey PRIMARY KEY (id);


--
-- Name: rag_collections rag_collections_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rag_collections
    ADD CONSTRAINT rag_collections_pkey PRIMARY KEY (id);


--
-- Name: rag_documents rag_documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rag_documents
    ADD CONSTRAINT rag_documents_pkey PRIMARY KEY (id);


--
-- Name: rag_folders rag_folders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rag_folders
    ADD CONSTRAINT rag_folders_pkey PRIMARY KEY (id);


--
-- Name: role_permissions role_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_pkey PRIMARY KEY (id);


--
-- Name: roles roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (id);


--
-- Name: routing_policies routing_policies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.routing_policies
    ADD CONSTRAINT routing_policies_pkey PRIMARY KEY (id);


--
-- Name: skill_executions skill_executions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skill_executions
    ADD CONSTRAINT skill_executions_pkey PRIMARY KEY (id);


--
-- Name: skill_files skill_files_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skill_files
    ADD CONSTRAINT skill_files_pkey PRIMARY KEY (id);


--
-- Name: skill_folders skill_folders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skill_folders
    ADD CONSTRAINT skill_folders_pkey PRIMARY KEY (id);


--
-- Name: skill_versions skill_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skill_versions
    ADD CONSTRAINT skill_versions_pkey PRIMARY KEY (id);


--
-- Name: task_file_refs task_file_refs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_file_refs
    ADD CONSTRAINT task_file_refs_pkey PRIMARY KEY (id);


--
-- Name: task_messages task_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_messages
    ADD CONSTRAINT task_messages_pkey PRIMARY KEY (id);


--
-- Name: tasks tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_pkey PRIMARY KEY (id);


--
-- Name: agents uq_agent_scope_slug; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT uq_agent_scope_slug UNIQUE (organization_id, scope_type, scope_id, slug);


--
-- Name: ai_quota_events uq_ai_quota_event_phase; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_quota_events
    ADD CONSTRAINT uq_ai_quota_event_phase UNIQUE (reservation_id, scope_type, scope_id, event_type);


--
-- Name: ecs_module_releases uq_ecs_module_release_org_slug; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ecs_module_releases
    ADD CONSTRAINT uq_ecs_module_release_org_slug UNIQUE (organization_id, application_slug);


--
-- Name: ecs_runtimes uq_ecs_runtime_credential_hash; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ecs_runtimes
    ADD CONSTRAINT uq_ecs_runtime_credential_hash UNIQUE (credential_hash);


--
-- Name: ecs_runtimes uq_ecs_runtime_credential_prefix; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ecs_runtimes
    ADD CONSTRAINT uq_ecs_runtime_credential_prefix UNIQUE (credential_prefix);


--
-- Name: ecs_runtimes uq_ecs_runtime_org_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ecs_runtimes
    ADD CONSTRAINT uq_ecs_runtime_org_key UNIQUE (organization_id, runtime_key);


--
-- Name: enterprise_application_actions uq_enterprise_application_action_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_actions
    ADD CONSTRAINT uq_enterprise_application_action_key UNIQUE (application_id, action_key);


--
-- Name: enterprise_application_action_requests uq_enterprise_application_action_request; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_action_requests
    ADD CONSTRAINT uq_enterprise_application_action_request UNIQUE (application_id, user_id, request_id);


--
-- Name: enterprise_application_event_deliveries uq_enterprise_application_event_deliveries_delivery_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_event_deliveries
    ADD CONSTRAINT uq_enterprise_application_event_deliveries_delivery_id UNIQUE (delivery_id);


--
-- Name: enterprise_application_events uq_enterprise_application_event_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_events
    ADD CONSTRAINT uq_enterprise_application_event_id UNIQUE (application_id, event_id);


--
-- Name: enterprise_application_events uq_enterprise_application_event_sequence; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_events
    ADD CONSTRAINT uq_enterprise_application_event_sequence UNIQUE (application_id, source_sequence);


--
-- Name: enterprise_application_grants uq_enterprise_application_grant_scope; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_grants
    ADD CONSTRAINT uq_enterprise_application_grant_scope UNIQUE (application_id, scope_type, scope_id);


--
-- Name: enterprise_application_integrations uq_enterprise_application_integration_app; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_integrations
    ADD CONSTRAINT uq_enterprise_application_integration_app UNIQUE (application_id);


--
-- Name: enterprise_application_integrations uq_enterprise_application_integration_sso_hash; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_integrations
    ADD CONSTRAINT uq_enterprise_application_integration_sso_hash UNIQUE (sso_exchange_credential_hash);


--
-- Name: enterprise_application_integrations uq_enterprise_application_integration_sso_prefix; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_integrations
    ADD CONSTRAINT uq_enterprise_application_integration_sso_prefix UNIQUE (sso_exchange_credential_prefix);


--
-- Name: enterprise_applications uq_enterprise_application_org_slug; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_applications
    ADD CONSTRAINT uq_enterprise_application_org_slug UNIQUE (organization_id, slug);


--
-- Name: enterprise_application_sso_codes uq_enterprise_application_sso_code_hash; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_sso_codes
    ADD CONSTRAINT uq_enterprise_application_sso_code_hash UNIQUE (code_hash);


--
-- Name: enterprise_application_event_deliveries uq_enterprise_event_delivery_route_event; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_event_deliveries
    ADD CONSTRAINT uq_enterprise_event_delivery_route_event UNIQUE (route_id, source_event_id);


--
-- Name: file_mutations uq_file_mutation_actor_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.file_mutations
    ADD CONSTRAINT uq_file_mutation_actor_key UNIQUE (organization_id, actor_type, actor_id, idempotency_key);


--
-- Name: multimodal_jobs uq_multimodal_job_idempotency; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.multimodal_jobs
    ADD CONSTRAINT uq_multimodal_job_idempotency UNIQUE (organization_id, user_id, idempotency_key);


--
-- Name: organization_slug_aliases uq_organization_slug_aliases_slug; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organization_slug_aliases
    ADD CONSTRAINT uq_organization_slug_aliases_slug UNIQUE (slug);


--
-- Name: rag_collections uq_ragcoll_org_slug; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rag_collections
    ADD CONSTRAINT uq_ragcoll_org_slug UNIQUE (organization_id, slug);


--
-- Name: rag_folders uq_ragfolder_path; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rag_folders
    ADD CONSTRAINT uq_ragfolder_path UNIQUE (collection_id, path);


--
-- Name: role_data_departments uq_role_data_department; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_data_departments
    ADD CONSTRAINT uq_role_data_department PRIMARY KEY (role_id, department_id);


--
-- Name: roles uq_role_org_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT uq_role_org_code UNIQUE (organization_id, code);


--
-- Name: roles uq_role_org_system_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT uq_role_org_system_key UNIQUE (organization_id, system_key);


--
-- Name: role_permissions uq_role_permission_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT uq_role_permission_code UNIQUE (role_id, permission_code);


--
-- Name: skill_versions uq_skill_version_hash; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skill_versions
    ADD CONSTRAINT uq_skill_version_hash UNIQUE (skill_folder_id, package_hash);


--
-- Name: skill_versions uq_skill_version_number; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skill_versions
    ADD CONSTRAINT uq_skill_version_number UNIQUE (skill_folder_id, version_no);


--
-- Name: task_file_refs uq_task_file_ref; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_file_refs
    ADD CONSTRAINT uq_task_file_ref UNIQUE (task_id, workspace_file_id);


--
-- Name: users uq_user_org_username; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT uq_user_org_username UNIQUE (organization_id, username);


--
-- Name: user_roles uq_user_role; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT uq_user_role PRIMARY KEY (user_id, role_id);


--
-- Name: voice_profile_grants uq_voice_profile_grant_scope; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.voice_profile_grants
    ADD CONSTRAINT uq_voice_profile_grant_scope UNIQUE (voice_profile_id, scope_type, scope_id);


--
-- Name: voice_profiles uq_voice_profile_org_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.voice_profiles
    ADD CONSTRAINT uq_voice_profile_org_name UNIQUE (organization_id, name);


--
-- Name: workspace_preview_jobs uq_workspace_preview_version_type; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_preview_jobs
    ADD CONSTRAINT uq_workspace_preview_version_type UNIQUE (file_version_id, conversion_type);


--
-- Name: workspace_share_links uq_workspace_share_token_hash; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_share_links
    ADD CONSTRAINT uq_workspace_share_token_hash UNIQUE (token_hash);


--
-- Name: workspace_file_versions uq_wsfile_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_file_versions
    ADD CONSTRAINT uq_wsfile_version UNIQUE (workspace_file_id, version_no);


--
-- Name: workspace_file_versions uq_wsfile_version_mutation_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_file_versions
    ADD CONSTRAINT uq_wsfile_version_mutation_key UNIQUE (workspace_file_id, mutation_idempotency_key);


--
-- Name: workspace_folders uq_wsfolder_path; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_folders
    ADD CONSTRAINT uq_wsfolder_path UNIQUE (workspace_id, path);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: voice_authorization_records voice_authorization_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.voice_authorization_records
    ADD CONSTRAINT voice_authorization_records_pkey PRIMARY KEY (id);


--
-- Name: voice_authorization_records voice_authorization_records_voice_profile_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.voice_authorization_records
    ADD CONSTRAINT voice_authorization_records_voice_profile_id_key UNIQUE (voice_profile_id);


--
-- Name: voice_profile_grants voice_profile_grants_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.voice_profile_grants
    ADD CONSTRAINT voice_profile_grants_pkey PRIMARY KEY (id);


--
-- Name: voice_profiles voice_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.voice_profiles
    ADD CONSTRAINT voice_profiles_pkey PRIMARY KEY (id);


--
-- Name: workspace_audit_events workspace_audit_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_audit_events
    ADD CONSTRAINT workspace_audit_events_pkey PRIMARY KEY (id);


--
-- Name: workspace_file_event_outbox workspace_file_event_outbox_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_file_event_outbox
    ADD CONSTRAINT workspace_file_event_outbox_pkey PRIMARY KEY (id);


--
-- Name: workspace_file_versions workspace_file_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_file_versions
    ADD CONSTRAINT workspace_file_versions_pkey PRIMARY KEY (id);


--
-- Name: workspace_files workspace_files_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_files
    ADD CONSTRAINT workspace_files_pkey PRIMARY KEY (id);


--
-- Name: workspace_folders workspace_folders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_folders
    ADD CONSTRAINT workspace_folders_pkey PRIMARY KEY (id);


--
-- Name: workspace_preview_jobs workspace_preview_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_preview_jobs
    ADD CONSTRAINT workspace_preview_jobs_pkey PRIMARY KEY (id);


--
-- Name: workspace_share_links workspace_share_links_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_share_links
    ADD CONSTRAINT workspace_share_links_pkey PRIMARY KEY (id);


--
-- Name: workspace_upload_sessions workspace_upload_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_upload_sessions
    ADD CONSTRAINT workspace_upload_sessions_pkey PRIMARY KEY (id);


--
-- Name: workspaces workspaces_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspaces
    ADD CONSTRAINT workspaces_pkey PRIMARY KEY (id);


--
-- Name: ix_agent_run_events_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_run_events_run_id ON public.agent_run_events USING btree (run_id);


--
-- Name: ix_agent_run_events_run_seq; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_run_events_run_seq ON public.agent_run_events USING btree (run_id, seq);


--
-- Name: ix_agent_run_events_task_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_run_events_task_id ON public.agent_run_events USING btree (task_id);


--
-- Name: ix_agent_run_events_task_seq; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_run_events_task_seq ON public.agent_run_events USING btree (task_id, seq);


--
-- Name: ix_agent_runs_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runs_agent_id ON public.agent_runs USING btree (agent_id);


--
-- Name: ix_agent_runs_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runs_organization_id ON public.agent_runs USING btree (organization_id);


--
-- Name: ix_agent_runs_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runs_session_id ON public.agent_runs USING btree (session_id);


--
-- Name: ix_agent_runs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runs_status ON public.agent_runs USING btree (status);


--
-- Name: ix_agent_runs_task_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runs_task_id ON public.agent_runs USING btree (task_id);


--
-- Name: ix_agent_runs_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runs_user_id ON public.agent_runs USING btree (user_id);


--
-- Name: ix_agents_application_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agents_application_id ON public.agents USING btree (application_id);


--
-- Name: ix_agents_created_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agents_created_by ON public.agents USING btree (created_by);


--
-- Name: ix_agents_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agents_organization_id ON public.agents USING btree (organization_id);


--
-- Name: ix_agents_scope_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agents_scope_id ON public.agents USING btree (scope_id);


--
-- Name: ix_agents_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agents_workspace_id ON public.agents USING btree (workspace_id);


--
-- Name: ix_ai_quota_events_created_at_brin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ai_quota_events_created_at_brin ON public.ai_quota_events USING brin (created_at);


--
-- Name: ix_ai_quota_events_org_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ai_quota_events_org_created ON public.ai_quota_events USING btree (organization_id, created_at);


--
-- Name: ix_ai_quota_events_reservation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ai_quota_events_reservation_id ON public.ai_quota_events USING btree (reservation_id);


--
-- Name: ix_ai_quota_events_scope_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ai_quota_events_scope_created ON public.ai_quota_events USING btree (scope_type, scope_id, created_at);


--
-- Name: ix_api_keys_department_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_api_keys_department_id ON public.api_keys USING btree (department_id);


--
-- Name: ix_api_keys_key_prefix; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_api_keys_key_prefix ON public.api_keys USING btree (key_prefix);


--
-- Name: ix_api_keys_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_api_keys_organization_id ON public.api_keys USING btree (organization_id);


--
-- Name: ix_audit_logs_event_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_event_type ON public.audit_logs USING btree (event_type);


--
-- Name: ix_audit_logs_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_organization_id ON public.audit_logs USING btree (organization_id);


--
-- Name: ix_audit_logs_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_request_id ON public.audit_logs USING btree (request_id);


--
-- Name: ix_departments_org_sort_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_departments_org_sort_order ON public.departments USING btree (organization_id, sort_order);


--
-- Name: ix_departments_parent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_departments_parent_id ON public.departments USING btree (parent_id);


--
-- Name: ix_dlp_rules_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dlp_rules_organization_id ON public.dlp_rules USING btree (organization_id);


--
-- Name: ix_ea_event_deliveries_event; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ea_event_deliveries_event ON public.enterprise_application_event_deliveries USING btree (source_event_id);


--
-- Name: ix_ea_event_deliveries_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ea_event_deliveries_org ON public.enterprise_application_event_deliveries USING btree (organization_id);


--
-- Name: ix_ea_event_deliveries_route; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ea_event_deliveries_route ON public.enterprise_application_event_deliveries USING btree (route_id);


--
-- Name: ix_ea_event_deliveries_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ea_event_deliveries_target ON public.enterprise_application_event_deliveries USING btree (target_application_id);


--
-- Name: ix_ecs_module_releases_application_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ecs_module_releases_application_id ON public.ecs_module_releases USING btree (application_id);


--
-- Name: ix_ecs_module_releases_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ecs_module_releases_organization_id ON public.ecs_module_releases USING btree (organization_id);


--
-- Name: ix_ecs_module_releases_runtime_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ecs_module_releases_runtime_id ON public.ecs_module_releases USING btree (runtime_id);


--
-- Name: ix_ecs_runtimes_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ecs_runtimes_organization_id ON public.ecs_runtimes USING btree (organization_id);


--
-- Name: ix_enterprise_application_action_requests_action_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_enterprise_application_action_requests_action_id ON public.enterprise_application_action_requests USING btree (action_id);


--
-- Name: ix_enterprise_application_action_requests_application_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_enterprise_application_action_requests_application_id ON public.enterprise_application_action_requests USING btree (application_id);


--
-- Name: ix_enterprise_application_action_requests_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_enterprise_application_action_requests_organization_id ON public.enterprise_application_action_requests USING btree (organization_id);


--
-- Name: ix_enterprise_application_action_requests_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_enterprise_application_action_requests_user_id ON public.enterprise_application_action_requests USING btree (user_id);


--
-- Name: ix_enterprise_application_actions_application_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_enterprise_application_actions_application_id ON public.enterprise_application_actions USING btree (application_id);


--
-- Name: ix_enterprise_application_actions_module_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_enterprise_application_actions_module_key ON public.enterprise_application_actions USING btree (module_key);


--
-- Name: ix_enterprise_application_actions_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_enterprise_application_actions_organization_id ON public.enterprise_application_actions USING btree (organization_id);


--
-- Name: ix_enterprise_application_event_routes_application_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_enterprise_application_event_routes_application_id ON public.enterprise_application_event_routes USING btree (application_id);


--
-- Name: ix_enterprise_application_event_routes_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_enterprise_application_event_routes_organization_id ON public.enterprise_application_event_routes USING btree (organization_id);


--
-- Name: ix_enterprise_application_event_routes_target_application_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_enterprise_application_event_routes_target_application_id ON public.enterprise_application_event_routes USING btree (target_application_id);


--
-- Name: ix_enterprise_application_events_application_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_enterprise_application_events_application_id ON public.enterprise_application_events USING btree (application_id);


--
-- Name: ix_enterprise_application_events_event_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_enterprise_application_events_event_type ON public.enterprise_application_events USING btree (event_type);


--
-- Name: ix_enterprise_application_events_module_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_enterprise_application_events_module_key ON public.enterprise_application_events USING btree (module_key);


--
-- Name: ix_enterprise_application_events_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_enterprise_application_events_organization_id ON public.enterprise_application_events USING btree (organization_id);


--
-- Name: ix_enterprise_application_grants_application_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_enterprise_application_grants_application_id ON public.enterprise_application_grants USING btree (application_id);


--
-- Name: ix_enterprise_application_grants_managed_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_enterprise_application_grants_managed_key ON public.enterprise_application_grants USING btree (managed_key);


--
-- Name: ix_enterprise_application_grants_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_enterprise_application_grants_organization_id ON public.enterprise_application_grants USING btree (organization_id);


--
-- Name: ix_enterprise_application_grants_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_enterprise_application_grants_scope ON public.enterprise_application_grants USING btree (organization_id, scope_type, scope_id);


--
-- Name: ix_enterprise_application_grants_scope_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_enterprise_application_grants_scope_id ON public.enterprise_application_grants USING btree (scope_id);


--
-- Name: ix_enterprise_application_integrations_application_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_enterprise_application_integrations_application_id ON public.enterprise_application_integrations USING btree (application_id);


--
-- Name: ix_enterprise_application_integrations_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_enterprise_application_integrations_organization_id ON public.enterprise_application_integrations USING btree (organization_id);


--
-- Name: ix_enterprise_application_sso_codes_application_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_enterprise_application_sso_codes_application_id ON public.enterprise_application_sso_codes USING btree (application_id);


--
-- Name: ix_enterprise_application_sso_codes_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_enterprise_application_sso_codes_expires_at ON public.enterprise_application_sso_codes USING btree (expires_at);


--
-- Name: ix_enterprise_application_sso_codes_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_enterprise_application_sso_codes_organization_id ON public.enterprise_application_sso_codes USING btree (organization_id);


--
-- Name: ix_enterprise_application_sso_codes_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_enterprise_application_sso_codes_user_id ON public.enterprise_application_sso_codes USING btree (user_id);


--
-- Name: ix_enterprise_applications_active_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_enterprise_applications_active_order ON public.enterprise_applications USING btree (organization_id, is_active, sort_order);


--
-- Name: ix_enterprise_applications_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_enterprise_applications_organization_id ON public.enterprise_applications USING btree (organization_id);


--
-- Name: ix_file_mutations_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_file_mutations_organization_id ON public.file_mutations USING btree (organization_id);


--
-- Name: ix_file_mutations_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_file_mutations_status ON public.file_mutations USING btree (status);


--
-- Name: ix_file_mutations_workspace_file_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_file_mutations_workspace_file_id ON public.file_mutations USING btree (workspace_file_id);


--
-- Name: ix_file_mutations_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_file_mutations_workspace_id ON public.file_mutations USING btree (workspace_id);


--
-- Name: ix_llm_providers_department_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_llm_providers_department_id ON public.llm_providers USING btree (department_id);


--
-- Name: ix_llm_providers_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_llm_providers_organization_id ON public.llm_providers USING btree (organization_id);


--
-- Name: ix_llm_providers_scope_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_llm_providers_scope_type ON public.llm_providers USING btree (scope_type);


--
-- Name: ix_llm_providers_vendor; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_llm_providers_vendor ON public.llm_providers USING btree (vendor);


--
-- Name: ix_memories_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memories_organization_id ON public.memories USING btree (organization_id);


--
-- Name: ix_memory_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_scope ON public.memories USING btree (organization_id, scope_type, scope_id);


--
-- Name: ix_model_deployments_model_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_model_deployments_model_id ON public.model_deployments USING btree (model_id);


--
-- Name: ix_model_deployments_provider_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_model_deployments_provider_id ON public.model_deployments USING btree (provider_id);


--
-- Name: ix_model_deployments_verification_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_model_deployments_verification_status ON public.model_deployments USING btree (verification_status);


--
-- Name: ix_multimodal_jobs_capability; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_multimodal_jobs_capability ON public.multimodal_jobs USING btree (capability);


--
-- Name: ix_multimodal_jobs_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_multimodal_jobs_organization_id ON public.multimodal_jobs USING btree (organization_id);


--
-- Name: ix_multimodal_jobs_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_multimodal_jobs_request_id ON public.multimodal_jobs USING btree (request_id);


--
-- Name: ix_multimodal_jobs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_multimodal_jobs_status ON public.multimodal_jobs USING btree (status);


--
-- Name: ix_multimodal_jobs_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_multimodal_jobs_user_id ON public.multimodal_jobs USING btree (user_id);


--
-- Name: ix_organization_slug_aliases_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_organization_slug_aliases_organization_id ON public.organization_slug_aliases USING btree (organization_id);


--
-- Name: ix_rag_chunks_collection_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rag_chunks_collection_id ON public.rag_chunks USING btree (collection_id);


--
-- Name: ix_rag_collections_created_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rag_collections_created_by ON public.rag_collections USING btree (created_by);


--
-- Name: ix_rag_collections_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rag_collections_organization_id ON public.rag_collections USING btree (organization_id);


--
-- Name: ix_rag_collections_purge_after; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rag_collections_purge_after ON public.rag_collections USING btree (purge_after);


--
-- Name: ix_rag_collections_scope_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rag_collections_scope_id ON public.rag_collections USING btree (scope_id);


--
-- Name: ix_rag_documents_collection_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rag_documents_collection_id ON public.rag_documents USING btree (collection_id);


--
-- Name: ix_rag_documents_created_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rag_documents_created_by ON public.rag_documents USING btree (created_by);


--
-- Name: ix_rag_documents_purge_after; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rag_documents_purge_after ON public.rag_documents USING btree (purge_after);


--
-- Name: ix_rag_folders_collection_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rag_folders_collection_id ON public.rag_folders USING btree (collection_id);


--
-- Name: ix_rag_folders_created_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rag_folders_created_by ON public.rag_folders USING btree (created_by);


--
-- Name: ix_rag_folders_purge_after; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rag_folders_purge_after ON public.rag_folders USING btree (purge_after);


--
-- Name: ix_role_permissions_permission_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_role_permissions_permission_code ON public.role_permissions USING btree (permission_code);


--
-- Name: ix_role_permissions_role_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_role_permissions_role_id ON public.role_permissions USING btree (role_id);


--
-- Name: ix_roles_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_roles_organization_id ON public.roles USING btree (organization_id);


--
-- Name: ix_skill_executions_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_executions_agent_id ON public.skill_executions USING btree (agent_id);


--
-- Name: ix_skill_executions_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_executions_organization_id ON public.skill_executions USING btree (organization_id);


--
-- Name: ix_skill_executions_skill_folder_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_executions_skill_folder_id ON public.skill_executions USING btree (skill_folder_id);


--
-- Name: ix_skill_executions_skill_version_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_executions_skill_version_id ON public.skill_executions USING btree (skill_version_id);


--
-- Name: ix_skill_executions_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_executions_status ON public.skill_executions USING btree (status);


--
-- Name: ix_skill_executions_task_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_executions_task_id ON public.skill_executions USING btree (task_id);


--
-- Name: ix_skill_executions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_executions_user_id ON public.skill_executions USING btree (user_id);


--
-- Name: ix_skill_files_folder; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_files_folder ON public.skill_files USING btree (skill_folder_id);


--
-- Name: ix_skill_files_purge_after; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_files_purge_after ON public.skill_files USING btree (purge_after);


--
-- Name: ix_skill_folders_active_version; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_folders_active_version ON public.skill_folders USING btree (active_version_id);


--
-- Name: ix_skill_folders_created_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_folders_created_by ON public.skill_folders USING btree (created_by);


--
-- Name: ix_skill_folders_org_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_folders_org_scope ON public.skill_folders USING btree (organization_id, scope_type, scope_id);


--
-- Name: ix_skill_folders_purge_after; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_folders_purge_after ON public.skill_folders USING btree (purge_after);


--
-- Name: ix_skill_versions_folder; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_versions_folder ON public.skill_versions USING btree (skill_folder_id);


--
-- Name: ix_skill_versions_purge_after; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_versions_purge_after ON public.skill_versions USING btree (purge_after);


--
-- Name: ix_skill_versions_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_versions_status ON public.skill_versions USING btree (install_status);


--
-- Name: ix_skill_versions_storage_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_versions_storage_status ON public.skill_versions USING btree (storage_status);


--
-- Name: ix_task_file_refs_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_file_refs_scope ON public.task_file_refs USING btree (scope);


--
-- Name: ix_task_file_refs_task_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_file_refs_task_id ON public.task_file_refs USING btree (task_id);


--
-- Name: ix_task_file_refs_workspace_file_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_file_refs_workspace_file_id ON public.task_file_refs USING btree (workspace_file_id);


--
-- Name: ix_task_messages_task_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_messages_task_id ON public.task_messages USING btree (task_id);


--
-- Name: ix_tasks_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tasks_organization_id ON public.tasks USING btree (organization_id);


--
-- Name: ix_tasks_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tasks_session_id ON public.tasks USING btree (session_id);


--
-- Name: ix_tasks_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tasks_user_id ON public.tasks USING btree (user_id);


--
-- Name: ix_users_department_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_department_id ON public.users USING btree (department_id);


--
-- Name: ix_voice_authorization_records_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_voice_authorization_records_organization_id ON public.voice_authorization_records USING btree (organization_id);


--
-- Name: ix_voice_profile_grants_voice_profile_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_voice_profile_grants_voice_profile_id ON public.voice_profile_grants USING btree (voice_profile_id);


--
-- Name: ix_voice_profiles_created_by_admin_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_voice_profiles_created_by_admin_id ON public.voice_profiles USING btree (created_by_admin_id);


--
-- Name: ix_voice_profiles_created_by_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_voice_profiles_created_by_user_id ON public.voice_profiles USING btree (created_by_user_id);


--
-- Name: ix_voice_profiles_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_voice_profiles_organization_id ON public.voice_profiles USING btree (organization_id);


--
-- Name: ix_workspace_audit_events_action; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_audit_events_action ON public.workspace_audit_events USING btree (action);


--
-- Name: ix_workspace_audit_events_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_audit_events_organization_id ON public.workspace_audit_events USING btree (organization_id);


--
-- Name: ix_workspace_audit_events_workspace_file_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_audit_events_workspace_file_id ON public.workspace_audit_events USING btree (workspace_file_id);


--
-- Name: ix_workspace_audit_events_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_audit_events_workspace_id ON public.workspace_audit_events USING btree (workspace_id);


--
-- Name: ix_workspace_file_event_outbox_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_file_event_outbox_created_at ON public.workspace_file_event_outbox USING btree (created_at);


--
-- Name: ix_workspace_file_event_outbox_event_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_file_event_outbox_event_type ON public.workspace_file_event_outbox USING btree (event_type);


--
-- Name: ix_workspace_file_event_outbox_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_file_event_outbox_organization_id ON public.workspace_file_event_outbox USING btree (organization_id);


--
-- Name: ix_workspace_file_event_outbox_workspace_file_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_file_event_outbox_workspace_file_id ON public.workspace_file_event_outbox USING btree (workspace_file_id);


--
-- Name: ix_workspace_file_event_outbox_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_file_event_outbox_workspace_id ON public.workspace_file_event_outbox USING btree (workspace_id);


--
-- Name: ix_workspace_file_versions_workspace_file_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_file_versions_workspace_file_id ON public.workspace_file_versions USING btree (workspace_file_id);


--
-- Name: ix_workspace_files_created_by_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_files_created_by_user_id ON public.workspace_files USING btree (created_by_user_id);


--
-- Name: ix_workspace_files_purge_after; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_files_purge_after ON public.workspace_files USING btree (purge_after);


--
-- Name: ix_workspace_files_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_files_workspace_id ON public.workspace_files USING btree (workspace_id);


--
-- Name: ix_workspace_folders_purge_after; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_folders_purge_after ON public.workspace_folders USING btree (purge_after);


--
-- Name: ix_workspace_folders_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_folders_workspace_id ON public.workspace_folders USING btree (workspace_id);


--
-- Name: ix_workspace_preview_jobs_file_version_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_preview_jobs_file_version_id ON public.workspace_preview_jobs USING btree (file_version_id);


--
-- Name: ix_workspace_preview_jobs_lease_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_preview_jobs_lease_expires_at ON public.workspace_preview_jobs USING btree (lease_expires_at);


--
-- Name: ix_workspace_preview_jobs_next_attempt_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_preview_jobs_next_attempt_at ON public.workspace_preview_jobs USING btree (next_attempt_at);


--
-- Name: ix_workspace_preview_jobs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_preview_jobs_status ON public.workspace_preview_jobs USING btree (status);


--
-- Name: ix_workspace_preview_jobs_workspace_file_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_preview_jobs_workspace_file_id ON public.workspace_preview_jobs USING btree (workspace_file_id);


--
-- Name: ix_workspace_share_links_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_share_links_expires_at ON public.workspace_share_links USING btree (expires_at);


--
-- Name: ix_workspace_share_links_token_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_share_links_token_hash ON public.workspace_share_links USING btree (token_hash);


--
-- Name: ix_workspace_share_links_version_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_share_links_version_id ON public.workspace_share_links USING btree (version_id);


--
-- Name: ix_workspace_share_links_workspace_file_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_share_links_workspace_file_id ON public.workspace_share_links USING btree (workspace_file_id);


--
-- Name: ix_workspace_upload_sessions_admin_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_upload_sessions_admin_id ON public.workspace_upload_sessions USING btree (admin_id);


--
-- Name: ix_workspace_upload_sessions_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_upload_sessions_expires_at ON public.workspace_upload_sessions USING btree (expires_at);


--
-- Name: ix_workspace_upload_sessions_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_upload_sessions_organization_id ON public.workspace_upload_sessions USING btree (organization_id);


--
-- Name: ix_workspace_upload_sessions_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_upload_sessions_status ON public.workspace_upload_sessions USING btree (status);


--
-- Name: ix_workspace_upload_sessions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_upload_sessions_user_id ON public.workspace_upload_sessions USING btree (user_id);


--
-- Name: ix_workspace_upload_sessions_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_upload_sessions_workspace_id ON public.workspace_upload_sessions USING btree (workspace_id);


--
-- Name: ix_workspaces_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspaces_organization_id ON public.workspaces USING btree (organization_id);


--
-- Name: ix_workspaces_purge_after; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspaces_purge_after ON public.workspaces USING btree (purge_after);


--
-- Name: ix_workspaces_scope_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspaces_scope_id ON public.workspaces USING btree (scope_id);


--
-- Name: uq_admins_username_org; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_admins_username_org ON public.admins USING btree (organization_id, username) WHERE (organization_id IS NOT NULL);


--
-- Name: uq_admins_username_platform; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_admins_username_platform ON public.admins USING btree (username) WHERE (organization_id IS NULL);


--
-- Name: uq_ai_quota_monthly_rollups_dimensions; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_ai_quota_monthly_rollups_dimensions ON public.ai_quota_monthly_rollups USING btree (period_month, organization_id, scope_type, scope_id, department_key, api_key_key, provider_key, operation_key);


--
-- Name: uq_dept_org_slug_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_dept_org_slug_active ON public.departments USING btree (organization_id, slug) WHERE (deleted_at IS NULL);


--
-- Name: uq_enterprise_application_grant_org_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_enterprise_application_grant_org_scope ON public.enterprise_application_grants USING btree (application_id) WHERE (((scope_type)::text = 'organization'::text) AND (scope_id IS NULL) AND (deleted_at IS NULL));


--
-- Name: uq_model_deployment_provider_model_adapter_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_model_deployment_provider_model_adapter_active ON public.model_deployments USING btree (provider_id, model_id, adapter) WHERE (deleted_at IS NULL);


--
-- Name: uq_organizations_is_default; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_organizations_is_default ON public.organizations USING btree (is_default) WHERE ((is_default = true) AND (deleted_at IS NULL));


--
-- Name: uq_organizations_name_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_organizations_name_active ON public.organizations USING btree (name) WHERE (deleted_at IS NULL);


--
-- Name: uq_organizations_slug_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_organizations_slug_active ON public.organizations USING btree (slug) WHERE (deleted_at IS NULL);


--
-- Name: uq_skill_file_path_live; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_skill_file_path_live ON public.skill_files USING btree (skill_folder_id, path) WHERE (deleted_at IS NULL);


--
-- Name: uq_skill_folder_scope_slug_live; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_skill_folder_scope_slug_live ON public.skill_folders USING btree (organization_id, scope_type, COALESCE(scope_id, ''::character varying), slug) WHERE (deleted_at IS NULL);


--
-- Name: uq_workspace_org_slug_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_workspace_org_slug_active ON public.workspaces USING btree (organization_id, slug) WHERE (deleted_at IS NULL);


--
-- Name: uq_wsfile_path_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_wsfile_path_active ON public.workspace_files USING btree (workspace_id, path) WHERE (deleted_at IS NULL);


--
-- Name: ai_quota_events trg_ai_quota_events_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_ai_quota_events_append_only BEFORE DELETE OR UPDATE ON public.ai_quota_events FOR EACH ROW EXECUTE FUNCTION public.reject_ai_quota_event_mutation();


--
-- Name: api_keys trg_api_keys_freeze_usd_budget; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_api_keys_freeze_usd_budget BEFORE INSERT OR UPDATE OF budget_cap_usd ON public.api_keys FOR EACH ROW EXECUTE FUNCTION public.reject_new_usd_budget_cap();


--
-- Name: departments trg_departments_freeze_usd_budget; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_departments_freeze_usd_budget BEFORE INSERT OR UPDATE OF budget_cap_usd ON public.departments FOR EACH ROW EXECUTE FUNCTION public.reject_new_usd_budget_cap();


--
-- Name: organizations trg_organizations_freeze_usd_budget; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_organizations_freeze_usd_budget BEFORE INSERT OR UPDATE OF budget_cap_usd ON public.organizations FOR EACH ROW EXECUTE FUNCTION public.reject_new_usd_budget_cap();


--
-- Name: agent_run_events agent_run_events_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_run_events
    ADD CONSTRAINT agent_run_events_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.agent_runs(id) ON DELETE CASCADE;


--
-- Name: agent_runs agent_runs_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT agent_runs_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE CASCADE;


--
-- Name: agent_runs agent_runs_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT agent_runs_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE RESTRICT;


--
-- Name: agents agents_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agents_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.enterprise_applications(id) ON DELETE SET NULL;


--
-- Name: agents agents_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agents_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE RESTRICT;


--
-- Name: agents agents_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agents_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE SET NULL;


--
-- Name: api_keys api_keys_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: api_keys api_keys_department_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_department_id_fkey FOREIGN KEY (department_id) REFERENCES public.departments(id) ON DELETE SET NULL;


--
-- Name: api_keys api_keys_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE RESTRICT;


--
-- Name: audit_logs audit_logs_api_key_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_api_key_id_fkey FOREIGN KEY (api_key_id) REFERENCES public.api_keys(id);


--
-- Name: departments departments_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.departments
    ADD CONSTRAINT departments_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE RESTRICT;


--
-- Name: dlp_rules dlp_rules_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dlp_rules
    ADD CONSTRAINT dlp_rules_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: dlp_rules dlp_rules_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dlp_rules
    ADD CONSTRAINT dlp_rules_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: ecs_module_releases ecs_module_releases_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ecs_module_releases
    ADD CONSTRAINT ecs_module_releases_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.enterprise_applications(id) ON DELETE SET NULL;


--
-- Name: ecs_module_releases ecs_module_releases_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ecs_module_releases
    ADD CONSTRAINT ecs_module_releases_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: ecs_module_releases ecs_module_releases_runtime_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ecs_module_releases
    ADD CONSTRAINT ecs_module_releases_runtime_id_fkey FOREIGN KEY (runtime_id) REFERENCES public.ecs_runtimes(id) ON DELETE RESTRICT;


--
-- Name: ecs_runtimes ecs_runtimes_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ecs_runtimes
    ADD CONSTRAINT ecs_runtimes_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: enterprise_application_action_requests enterprise_application_action_requests_action_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_action_requests
    ADD CONSTRAINT enterprise_application_action_requests_action_id_fkey FOREIGN KEY (action_id) REFERENCES public.enterprise_application_actions(id) ON DELETE CASCADE;


--
-- Name: enterprise_application_action_requests enterprise_application_action_requests_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_action_requests
    ADD CONSTRAINT enterprise_application_action_requests_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.enterprise_applications(id) ON DELETE CASCADE;


--
-- Name: enterprise_application_action_requests enterprise_application_action_requests_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_action_requests
    ADD CONSTRAINT enterprise_application_action_requests_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: enterprise_application_action_requests enterprise_application_action_requests_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_action_requests
    ADD CONSTRAINT enterprise_application_action_requests_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: enterprise_application_actions enterprise_application_actions_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_actions
    ADD CONSTRAINT enterprise_application_actions_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.enterprise_applications(id) ON DELETE CASCADE;


--
-- Name: enterprise_application_actions enterprise_application_actions_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_actions
    ADD CONSTRAINT enterprise_application_actions_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: enterprise_application_event_deliveries enterprise_application_event_deliver_target_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_event_deliveries
    ADD CONSTRAINT enterprise_application_event_deliver_target_application_id_fkey FOREIGN KEY (target_application_id) REFERENCES public.enterprise_applications(id) ON DELETE CASCADE;


--
-- Name: enterprise_application_event_deliveries enterprise_application_event_deliveries_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_event_deliveries
    ADD CONSTRAINT enterprise_application_event_deliveries_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: enterprise_application_event_deliveries enterprise_application_event_deliveries_route_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_event_deliveries
    ADD CONSTRAINT enterprise_application_event_deliveries_route_id_fkey FOREIGN KEY (route_id) REFERENCES public.enterprise_application_event_routes(id) ON DELETE CASCADE;


--
-- Name: enterprise_application_event_deliveries enterprise_application_event_deliveries_source_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_event_deliveries
    ADD CONSTRAINT enterprise_application_event_deliveries_source_event_id_fkey FOREIGN KEY (source_event_id) REFERENCES public.enterprise_application_events(id) ON DELETE CASCADE;


--
-- Name: enterprise_application_event_routes enterprise_application_event_routes_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_event_routes
    ADD CONSTRAINT enterprise_application_event_routes_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.enterprise_applications(id) ON DELETE CASCADE;


--
-- Name: enterprise_application_event_routes enterprise_application_event_routes_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_event_routes
    ADD CONSTRAINT enterprise_application_event_routes_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: enterprise_application_events enterprise_application_events_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_events
    ADD CONSTRAINT enterprise_application_events_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.enterprise_applications(id) ON DELETE CASCADE;


--
-- Name: enterprise_application_events enterprise_application_events_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_events
    ADD CONSTRAINT enterprise_application_events_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: enterprise_application_grants enterprise_application_grants_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_grants
    ADD CONSTRAINT enterprise_application_grants_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.enterprise_applications(id) ON DELETE CASCADE;


--
-- Name: enterprise_application_grants enterprise_application_grants_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_grants
    ADD CONSTRAINT enterprise_application_grants_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: enterprise_application_integrations enterprise_application_integrations_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_integrations
    ADD CONSTRAINT enterprise_application_integrations_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.enterprise_applications(id) ON DELETE CASCADE;


--
-- Name: enterprise_application_integrations enterprise_application_integrations_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_integrations
    ADD CONSTRAINT enterprise_application_integrations_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: enterprise_application_sso_codes enterprise_application_sso_codes_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_sso_codes
    ADD CONSTRAINT enterprise_application_sso_codes_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.enterprise_applications(id) ON DELETE CASCADE;


--
-- Name: enterprise_application_sso_codes enterprise_application_sso_codes_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_sso_codes
    ADD CONSTRAINT enterprise_application_sso_codes_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: enterprise_application_sso_codes enterprise_application_sso_codes_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_sso_codes
    ADD CONSTRAINT enterprise_application_sso_codes_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: enterprise_applications enterprise_applications_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_applications
    ADD CONSTRAINT enterprise_applications_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE RESTRICT;


--
-- Name: file_mutations file_mutations_base_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.file_mutations
    ADD CONSTRAINT file_mutations_base_version_id_fkey FOREIGN KEY (base_version_id) REFERENCES public.workspace_file_versions(id) ON DELETE SET NULL;


--
-- Name: file_mutations file_mutations_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.file_mutations
    ADD CONSTRAINT file_mutations_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: file_mutations file_mutations_result_file_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.file_mutations
    ADD CONSTRAINT file_mutations_result_file_id_fkey FOREIGN KEY (result_file_id) REFERENCES public.workspace_files(id) ON DELETE SET NULL;


--
-- Name: file_mutations file_mutations_result_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.file_mutations
    ADD CONSTRAINT file_mutations_result_version_id_fkey FOREIGN KEY (result_version_id) REFERENCES public.workspace_file_versions(id) ON DELETE SET NULL;


--
-- Name: file_mutations file_mutations_workspace_file_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.file_mutations
    ADD CONSTRAINT file_mutations_workspace_file_id_fkey FOREIGN KEY (workspace_file_id) REFERENCES public.workspace_files(id) ON DELETE SET NULL;


--
-- Name: file_mutations file_mutations_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.file_mutations
    ADD CONSTRAINT file_mutations_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: admins fk_admins_organization_id_organizations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admins
    ADD CONSTRAINT fk_admins_organization_id_organizations FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE RESTRICT;


--
-- Name: agent_runs fk_agent_runs_task_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT fk_agent_runs_task_id FOREIGN KEY (task_id) REFERENCES public.tasks(id) ON DELETE SET NULL;


--
-- Name: agent_runs fk_agent_runs_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT fk_agent_runs_user_id FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: departments fk_departments_parent_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.departments
    ADD CONSTRAINT fk_departments_parent_id FOREIGN KEY (parent_id) REFERENCES public.departments(id) ON DELETE SET NULL;


--
-- Name: enterprise_application_event_routes fk_enterprise_event_route_target_application; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enterprise_application_event_routes
    ADD CONSTRAINT fk_enterprise_event_route_target_application FOREIGN KEY (target_application_id) REFERENCES public.enterprise_applications(id) ON DELETE CASCADE;


--
-- Name: skill_folders fk_skill_folder_active_version; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skill_folders
    ADD CONSTRAINT fk_skill_folder_active_version FOREIGN KEY (active_version_id) REFERENCES public.skill_versions(id) ON DELETE SET NULL;


--
-- Name: users fk_users_department_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT fk_users_department_id FOREIGN KEY (department_id) REFERENCES public.departments(id) ON DELETE SET NULL;


--
-- Name: workspace_files fk_wsfile_creator; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_files
    ADD CONSTRAINT fk_wsfile_creator FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: workspace_files fk_wsfile_current_version; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_files
    ADD CONSTRAINT fk_wsfile_current_version FOREIGN KEY (current_version_id) REFERENCES public.workspace_file_versions(id) ON DELETE SET NULL;


--
-- Name: workspace_files fk_wsfile_deleted_admin; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_files
    ADD CONSTRAINT fk_wsfile_deleted_admin FOREIGN KEY (deleted_by_admin_id) REFERENCES public.admins(id) ON DELETE SET NULL;


--
-- Name: workspace_files fk_wsfile_deleted_user; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_files
    ADD CONSTRAINT fk_wsfile_deleted_user FOREIGN KEY (deleted_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: llm_providers llm_providers_department_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_providers
    ADD CONSTRAINT llm_providers_department_id_fkey FOREIGN KEY (department_id) REFERENCES public.departments(id) ON DELETE SET NULL;


--
-- Name: llm_providers llm_providers_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_providers
    ADD CONSTRAINT llm_providers_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: memories memories_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memories
    ADD CONSTRAINT memories_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: memories memories_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memories
    ADD CONSTRAINT memories_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE RESTRICT;


--
-- Name: model_deployments model_deployments_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_deployments
    ADD CONSTRAINT model_deployments_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.llm_providers(id) ON DELETE CASCADE;


--
-- Name: multimodal_jobs multimodal_jobs_department_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.multimodal_jobs
    ADD CONSTRAINT multimodal_jobs_department_id_fkey FOREIGN KEY (department_id) REFERENCES public.departments(id) ON DELETE SET NULL;


--
-- Name: multimodal_jobs multimodal_jobs_deployment_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.multimodal_jobs
    ADD CONSTRAINT multimodal_jobs_deployment_id_fkey FOREIGN KEY (deployment_id) REFERENCES public.model_deployments(id) ON DELETE SET NULL;


--
-- Name: multimodal_jobs multimodal_jobs_input_file_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.multimodal_jobs
    ADD CONSTRAINT multimodal_jobs_input_file_id_fkey FOREIGN KEY (input_file_id) REFERENCES public.workspace_files(id) ON DELETE SET NULL;


--
-- Name: multimodal_jobs multimodal_jobs_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.multimodal_jobs
    ADD CONSTRAINT multimodal_jobs_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: multimodal_jobs multimodal_jobs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.multimodal_jobs
    ADD CONSTRAINT multimodal_jobs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: multimodal_jobs multimodal_jobs_voice_profile_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.multimodal_jobs
    ADD CONSTRAINT multimodal_jobs_voice_profile_id_fkey FOREIGN KEY (voice_profile_id) REFERENCES public.voice_profiles(id) ON DELETE SET NULL;


--
-- Name: organization_slug_aliases organization_slug_aliases_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organization_slug_aliases
    ADD CONSTRAINT organization_slug_aliases_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: rag_chunks rag_chunks_collection_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rag_chunks
    ADD CONSTRAINT rag_chunks_collection_id_fkey FOREIGN KEY (collection_id) REFERENCES public.rag_collections(id) ON DELETE CASCADE;


--
-- Name: rag_chunks rag_chunks_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rag_chunks
    ADD CONSTRAINT rag_chunks_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.rag_documents(id) ON DELETE SET NULL;


--
-- Name: rag_collections rag_collections_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rag_collections
    ADD CONSTRAINT rag_collections_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE RESTRICT;


--
-- Name: rag_documents rag_documents_collection_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rag_documents
    ADD CONSTRAINT rag_documents_collection_id_fkey FOREIGN KEY (collection_id) REFERENCES public.rag_collections(id) ON DELETE CASCADE;


--
-- Name: rag_folders rag_folders_collection_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rag_folders
    ADD CONSTRAINT rag_folders_collection_id_fkey FOREIGN KEY (collection_id) REFERENCES public.rag_collections(id) ON DELETE CASCADE;


--
-- Name: role_data_departments role_data_departments_department_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_data_departments
    ADD CONSTRAINT role_data_departments_department_id_fkey FOREIGN KEY (department_id) REFERENCES public.departments(id) ON DELETE CASCADE;


--
-- Name: role_data_departments role_data_departments_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_data_departments
    ADD CONSTRAINT role_data_departments_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;


--
-- Name: role_permissions role_permissions_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;


--
-- Name: roles roles_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: routing_policies routing_policies_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.routing_policies
    ADD CONSTRAINT routing_policies_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: skill_executions skill_executions_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skill_executions
    ADD CONSTRAINT skill_executions_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE SET NULL;


--
-- Name: skill_executions skill_executions_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skill_executions
    ADD CONSTRAINT skill_executions_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE RESTRICT;


--
-- Name: skill_executions skill_executions_skill_folder_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skill_executions
    ADD CONSTRAINT skill_executions_skill_folder_id_fkey FOREIGN KEY (skill_folder_id) REFERENCES public.skill_folders(id) ON DELETE RESTRICT;


--
-- Name: skill_executions skill_executions_skill_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skill_executions
    ADD CONSTRAINT skill_executions_skill_version_id_fkey FOREIGN KEY (skill_version_id) REFERENCES public.skill_versions(id) ON DELETE RESTRICT;


--
-- Name: skill_executions skill_executions_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skill_executions
    ADD CONSTRAINT skill_executions_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id) ON DELETE SET NULL;


--
-- Name: skill_executions skill_executions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skill_executions
    ADD CONSTRAINT skill_executions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: skill_files skill_files_skill_folder_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skill_files
    ADD CONSTRAINT skill_files_skill_folder_id_fkey FOREIGN KEY (skill_folder_id) REFERENCES public.skill_folders(id) ON DELETE CASCADE;


--
-- Name: skill_folders skill_folders_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skill_folders
    ADD CONSTRAINT skill_folders_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE RESTRICT;


--
-- Name: skill_versions skill_versions_skill_folder_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skill_versions
    ADD CONSTRAINT skill_versions_skill_folder_id_fkey FOREIGN KEY (skill_folder_id) REFERENCES public.skill_folders(id) ON DELETE CASCADE;


--
-- Name: task_file_refs task_file_refs_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_file_refs
    ADD CONSTRAINT task_file_refs_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id) ON DELETE CASCADE;


--
-- Name: task_file_refs task_file_refs_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_file_refs
    ADD CONSTRAINT task_file_refs_version_id_fkey FOREIGN KEY (version_id) REFERENCES public.workspace_file_versions(id) ON DELETE SET NULL;


--
-- Name: task_file_refs task_file_refs_workspace_file_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_file_refs
    ADD CONSTRAINT task_file_refs_workspace_file_id_fkey FOREIGN KEY (workspace_file_id) REFERENCES public.workspace_files(id) ON DELETE CASCADE;


--
-- Name: task_messages task_messages_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_messages
    ADD CONSTRAINT task_messages_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id) ON DELETE CASCADE;


--
-- Name: tasks tasks_department_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_department_id_fkey FOREIGN KEY (department_id) REFERENCES public.departments(id) ON DELETE SET NULL;


--
-- Name: tasks tasks_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE RESTRICT;


--
-- Name: tasks tasks_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: user_roles user_roles_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT user_roles_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;


--
-- Name: user_roles user_roles_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT user_roles_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: users users_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE RESTRICT;


--
-- Name: voice_authorization_records voice_authorization_records_confirmed_by_admin_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.voice_authorization_records
    ADD CONSTRAINT voice_authorization_records_confirmed_by_admin_id_fkey FOREIGN KEY (confirmed_by_admin_id) REFERENCES public.admins(id) ON DELETE SET NULL;


--
-- Name: voice_authorization_records voice_authorization_records_confirmed_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.voice_authorization_records
    ADD CONSTRAINT voice_authorization_records_confirmed_by_user_id_fkey FOREIGN KEY (confirmed_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: voice_authorization_records voice_authorization_records_evidence_file_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.voice_authorization_records
    ADD CONSTRAINT voice_authorization_records_evidence_file_id_fkey FOREIGN KEY (evidence_file_id) REFERENCES public.workspace_files(id) ON DELETE RESTRICT;


--
-- Name: voice_authorization_records voice_authorization_records_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.voice_authorization_records
    ADD CONSTRAINT voice_authorization_records_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: voice_authorization_records voice_authorization_records_voice_profile_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.voice_authorization_records
    ADD CONSTRAINT voice_authorization_records_voice_profile_id_fkey FOREIGN KEY (voice_profile_id) REFERENCES public.voice_profiles(id) ON DELETE CASCADE;


--
-- Name: voice_profile_grants voice_profile_grants_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.voice_profile_grants
    ADD CONSTRAINT voice_profile_grants_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: voice_profile_grants voice_profile_grants_voice_profile_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.voice_profile_grants
    ADD CONSTRAINT voice_profile_grants_voice_profile_id_fkey FOREIGN KEY (voice_profile_id) REFERENCES public.voice_profiles(id) ON DELETE CASCADE;


--
-- Name: voice_profiles voice_profiles_created_by_admin_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.voice_profiles
    ADD CONSTRAINT voice_profiles_created_by_admin_id_fkey FOREIGN KEY (created_by_admin_id) REFERENCES public.admins(id) ON DELETE SET NULL;


--
-- Name: voice_profiles voice_profiles_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.voice_profiles
    ADD CONSTRAINT voice_profiles_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: voice_profiles voice_profiles_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.voice_profiles
    ADD CONSTRAINT voice_profiles_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: voice_profiles voice_profiles_sample_file_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.voice_profiles
    ADD CONSTRAINT voice_profiles_sample_file_id_fkey FOREIGN KEY (sample_file_id) REFERENCES public.workspace_files(id) ON DELETE SET NULL;


--
-- Name: workspace_audit_events workspace_audit_events_actor_admin_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_audit_events
    ADD CONSTRAINT workspace_audit_events_actor_admin_id_fkey FOREIGN KEY (actor_admin_id) REFERENCES public.admins(id) ON DELETE SET NULL;


--
-- Name: workspace_audit_events workspace_audit_events_actor_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_audit_events
    ADD CONSTRAINT workspace_audit_events_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: workspace_audit_events workspace_audit_events_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_audit_events
    ADD CONSTRAINT workspace_audit_events_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: workspace_audit_events workspace_audit_events_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_audit_events
    ADD CONSTRAINT workspace_audit_events_version_id_fkey FOREIGN KEY (version_id) REFERENCES public.workspace_file_versions(id) ON DELETE SET NULL;


--
-- Name: workspace_audit_events workspace_audit_events_workspace_file_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_audit_events
    ADD CONSTRAINT workspace_audit_events_workspace_file_id_fkey FOREIGN KEY (workspace_file_id) REFERENCES public.workspace_files(id) ON DELETE SET NULL;


--
-- Name: workspace_audit_events workspace_audit_events_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_audit_events
    ADD CONSTRAINT workspace_audit_events_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: workspace_file_event_outbox workspace_file_event_outbox_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_file_event_outbox
    ADD CONSTRAINT workspace_file_event_outbox_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: workspace_file_event_outbox workspace_file_event_outbox_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_file_event_outbox
    ADD CONSTRAINT workspace_file_event_outbox_version_id_fkey FOREIGN KEY (version_id) REFERENCES public.workspace_file_versions(id) ON DELETE SET NULL;


--
-- Name: workspace_file_event_outbox workspace_file_event_outbox_workspace_file_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_file_event_outbox
    ADD CONSTRAINT workspace_file_event_outbox_workspace_file_id_fkey FOREIGN KEY (workspace_file_id) REFERENCES public.workspace_files(id) ON DELETE CASCADE;


--
-- Name: workspace_file_event_outbox workspace_file_event_outbox_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_file_event_outbox
    ADD CONSTRAINT workspace_file_event_outbox_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: workspace_file_versions workspace_file_versions_created_by_admin_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_file_versions
    ADD CONSTRAINT workspace_file_versions_created_by_admin_id_fkey FOREIGN KEY (created_by_admin_id) REFERENCES public.admins(id) ON DELETE SET NULL;


--
-- Name: workspace_file_versions workspace_file_versions_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_file_versions
    ADD CONSTRAINT workspace_file_versions_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: workspace_file_versions workspace_file_versions_workspace_file_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_file_versions
    ADD CONSTRAINT workspace_file_versions_workspace_file_id_fkey FOREIGN KEY (workspace_file_id) REFERENCES public.workspace_files(id) ON DELETE CASCADE;


--
-- Name: workspace_files workspace_files_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_files
    ADD CONSTRAINT workspace_files_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: workspace_folders workspace_folders_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_folders
    ADD CONSTRAINT workspace_folders_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: workspace_preview_jobs workspace_preview_jobs_file_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_preview_jobs
    ADD CONSTRAINT workspace_preview_jobs_file_version_id_fkey FOREIGN KEY (file_version_id) REFERENCES public.workspace_file_versions(id) ON DELETE CASCADE;


--
-- Name: workspace_preview_jobs workspace_preview_jobs_workspace_file_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_preview_jobs
    ADD CONSTRAINT workspace_preview_jobs_workspace_file_id_fkey FOREIGN KEY (workspace_file_id) REFERENCES public.workspace_files(id) ON DELETE CASCADE;


--
-- Name: workspace_share_links workspace_share_links_created_by_admin_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_share_links
    ADD CONSTRAINT workspace_share_links_created_by_admin_id_fkey FOREIGN KEY (created_by_admin_id) REFERENCES public.admins(id) ON DELETE SET NULL;


--
-- Name: workspace_share_links workspace_share_links_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_share_links
    ADD CONSTRAINT workspace_share_links_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: workspace_share_links workspace_share_links_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_share_links
    ADD CONSTRAINT workspace_share_links_version_id_fkey FOREIGN KEY (version_id) REFERENCES public.workspace_file_versions(id) ON DELETE CASCADE;


--
-- Name: workspace_share_links workspace_share_links_workspace_file_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_share_links
    ADD CONSTRAINT workspace_share_links_workspace_file_id_fkey FOREIGN KEY (workspace_file_id) REFERENCES public.workspace_files(id) ON DELETE CASCADE;


--
-- Name: workspace_upload_sessions workspace_upload_sessions_admin_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_upload_sessions
    ADD CONSTRAINT workspace_upload_sessions_admin_id_fkey FOREIGN KEY (admin_id) REFERENCES public.admins(id) ON DELETE CASCADE;


--
-- Name: workspace_upload_sessions workspace_upload_sessions_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_upload_sessions
    ADD CONSTRAINT workspace_upload_sessions_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: workspace_upload_sessions workspace_upload_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_upload_sessions
    ADD CONSTRAINT workspace_upload_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: workspace_upload_sessions workspace_upload_sessions_workspace_file_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_upload_sessions
    ADD CONSTRAINT workspace_upload_sessions_workspace_file_id_fkey FOREIGN KEY (workspace_file_id) REFERENCES public.workspace_files(id) ON DELETE SET NULL;


--
-- Name: workspace_upload_sessions workspace_upload_sessions_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_upload_sessions
    ADD CONSTRAINT workspace_upload_sessions_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: workspaces workspaces_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspaces
    ADD CONSTRAINT workspaces_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE RESTRICT;


--
-- PostgreSQL database dump complete
--
