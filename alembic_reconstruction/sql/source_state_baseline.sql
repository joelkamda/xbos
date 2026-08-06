--
-- PostgreSQL database dump
--

-- Dumped from database version 17.5
-- Dumped by pg_dump version 17.5

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


--
-- Name: xbos_taxonomy_tree(integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.xbos_taxonomy_tree(p_domain_id integer) RETURNS TABLE(tree_line text, path text)
    LANGUAGE sql
    AS $$

WITH RECURSIVE taxo_tree AS (

    -- Root node
    SELECT
        id,
        name,
        parent_id,
        sort_order,
        name::text AS path,
        0 AS depth
    FROM taxonomy_nodes
    WHERE id = p_domain_id

    UNION ALL

    -- Child nodes
    SELECT
        tn.id,
        tn.name,
        tn.parent_id,
        tn.sort_order,
        tt.path || '.' || LPAD(tn.sort_order::text,3,'0'),
        tt.depth + 1
    FROM taxonomy_nodes tn
    JOIN taxo_tree tt
        ON tn.parent_id = tt.id
),

tree_lines AS (

    SELECT
        CASE
            WHEN depth = 0 THEN name
            WHEN depth = 1 THEN 'ÃÄÄ ' || name
            WHEN depth = 2 THEN '³   ÃÄÄ ' || name
        END AS tree_line,
        path,
        id,
        depth
    FROM taxo_tree
),

atomic_lines AS (

    SELECT
        '³   ³   ÀÄÄ ' || au.name AS tree_line,
        tl.path || '.999' AS path
    FROM tree_lines tl
    JOIN atomic_unit_taxonomy aut
        ON aut.taxonomy_node_id = tl.id
    JOIN atomic_units au
        ON au.id = aut.atomic_unit_id
    WHERE tl.depth = 2
)

SELECT tree_line, path
FROM (
    SELECT tree_line, path FROM tree_lines
    UNION ALL
    SELECT tree_line, path FROM atomic_lines
) t
ORDER BY path;

$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: accounts_receivable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.accounts_receivable (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    branch_id integer NOT NULL,
    order_id integer,
    sale_id integer,
    payment_intent_id text,
    customer_name text,
    customer_phone text,
    note text,
    original_amount numeric(12,2) DEFAULT 0 NOT NULL,
    paid_amount numeric(12,2) DEFAULT 0 NOT NULL,
    balance_due numeric(12,2) DEFAULT 0 NOT NULL,
    status character varying(30) DEFAULT 'open'::character varying NOT NULL,
    created_by_user_id integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    settled_at timestamp without time zone
);


--
-- Name: accounts_receivable_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.accounts_receivable_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: accounts_receivable_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.accounts_receivable_id_seq OWNED BY public.accounts_receivable.id;


--
-- Name: accounts_receivable_repayments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.accounts_receivable_repayments (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    branch_id integer NOT NULL,
    ar_id integer NOT NULL,
    amount numeric(12,2) NOT NULL,
    payment_method character varying(50) DEFAULT 'cash'::character varying NOT NULL,
    reference text,
    note text,
    created_by_user_id integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: accounts_receivable_repayments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.accounts_receivable_repayments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: accounts_receivable_repayments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.accounts_receivable_repayments_id_seq OWNED BY public.accounts_receivable_repayments.id;


--
-- Name: atomic_unit_taxonomy; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.atomic_unit_taxonomy (
    atomic_unit_id integer NOT NULL,
    taxonomy_node_id integer NOT NULL
);


--
-- Name: atomic_units; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.atomic_units (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    name character varying NOT NULL,
    sku character varying,
    unit_price numeric(12,2),
    unit_type character varying,
    is_active boolean NOT NULL,
    meta jsonb,
    parent_unit_id integer,
    is_sellable boolean DEFAULT true
);


--
-- Name: billable_unit_taxonomy; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.billable_unit_taxonomy (
    atomic_unit_id integer NOT NULL,
    taxonomy_node_id integer NOT NULL
);


--
-- Name: billable_units_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.billable_units_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: billable_units_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.billable_units_id_seq OWNED BY public.atomic_units.id;


--
-- Name: branches; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.branches (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    branch_code character varying NOT NULL,
    name character varying NOT NULL,
    city character varying,
    address character varying,
    is_active boolean,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone
);


--
-- Name: branches_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.branches_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: branches_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.branches_id_seq OWNED BY public.branches.id;


--
-- Name: idempotency_keys; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.idempotency_keys (
    id integer NOT NULL,
    key text NOT NULL,
    scope text NOT NULL,
    reference_id integer,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: idempotency_keys_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.idempotency_keys_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: idempotency_keys_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.idempotency_keys_id_seq OWNED BY public.idempotency_keys.id;


--
-- Name: inventory_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.inventory_items (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    branch_id integer NOT NULL,
    atomic_unit_id integer NOT NULL,
    quantity_on_hand integer NOT NULL,
    reorder_level integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: inventory_items_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.inventory_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: inventory_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.inventory_items_id_seq OWNED BY public.inventory_items.id;


--
-- Name: inventory_movements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.inventory_movements (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    branch_id integer NOT NULL,
    inventory_item_id integer NOT NULL,
    atomic_unit_id integer NOT NULL,
    quantity_delta integer NOT NULL,
    movement_type character varying NOT NULL,
    source character varying NOT NULL,
    reference_type character varying,
    reference_id integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: inventory_movements_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.inventory_movements_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: inventory_movements_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.inventory_movements_id_seq OWNED BY public.inventory_movements.id;


--
-- Name: order_item_modifiers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.order_item_modifiers (
    id integer NOT NULL,
    order_item_id integer NOT NULL,
    modifier_type character varying(50) DEFAULT 'side'::character varying NOT NULL,
    name_snapshot text NOT NULL,
    price_delta numeric(12,2) DEFAULT 0 NOT NULL,
    quantity integer DEFAULT 1 NOT NULL,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: order_item_modifiers_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.order_item_modifiers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: order_item_modifiers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.order_item_modifiers_id_seq OWNED BY public.order_item_modifiers.id;


--
-- Name: order_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.order_items (
    id integer NOT NULL,
    order_id integer NOT NULL,
    atomic_unit_id integer NOT NULL,
    name_snapshot text NOT NULL,
    unit_price numeric(12,2) NOT NULL,
    quantity integer NOT NULL,
    line_total numeric(12,2) NOT NULL,
    fulfillment_status character varying(50) DEFAULT 'waiting'::character varying,
    fulfilled_at timestamp without time zone,
    fulfilled_by_user_id integer
);


--
-- Name: order_items_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.order_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: order_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.order_items_id_seq OWNED BY public.order_items.id;


--
-- Name: orders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.orders (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    branch_id integer NOT NULL,
    status character varying(50) DEFAULT 'pending'::character varying NOT NULL,
    subtotal numeric(12,2) DEFAULT 0 NOT NULL,
    total numeric(12,2) DEFAULT 0 NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    paid_at timestamp without time zone,
    created_by_user_id integer
);


--
-- Name: orders_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.orders_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: orders_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.orders_id_seq OWNED BY public.orders.id;


--
-- Name: payment_attempts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.payment_attempts (
    id integer NOT NULL,
    payment_intent_id integer NOT NULL,
    sale_id integer,
    method character varying(32) NOT NULL,
    provider character varying(32),
    settlement_mode character varying(32) NOT NULL,
    amount numeric(12,2) NOT NULL,
    status character varying(32) NOT NULL,
    client_reference character varying(64) NOT NULL,
    callback_reference character varying(128),
    gateway_reference character varying(128),
    provider_reference character varying(128),
    cashier_id integer,
    provider_meta json,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    meta jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT ck_pa_amount_positive CHECK ((amount > (0)::numeric))
);


--
-- Name: COLUMN payment_attempts.method; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.payment_attempts.method IS 'PaymentMethod enum value';


--
-- Name: COLUMN payment_attempts.provider; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.payment_attempts.provider IS 'PaymentProvider enum value';


--
-- Name: COLUMN payment_attempts.settlement_mode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.payment_attempts.settlement_mode IS 'SettlementMode enum value';


--
-- Name: COLUMN payment_attempts.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.payment_attempts.status IS 'PaymentAttemptStatus enum value';


--
-- Name: COLUMN payment_attempts.client_reference; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.payment_attempts.client_reference IS 'Client idempotency key (POS/API)';


--
-- Name: COLUMN payment_attempts.callback_reference; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.payment_attempts.callback_reference IS 'Provider webhook idempotency key';


--
-- Name: payment_attempts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.payment_attempts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: payment_attempts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.payment_attempts_id_seq OWNED BY public.payment_attempts.id;


--
-- Name: payment_intents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.payment_intents (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    branch_id integer NOT NULL,
    payable_type character varying(32) NOT NULL,
    payable_id integer NOT NULL,
    currency character varying(8) NOT NULL,
    amount numeric(12,2) NOT NULL,
    status character varying(32) NOT NULL,
    created_by_user_id integer NOT NULL,
    channel character varying(16) NOT NULL,
    total_paid numeric(12,2) DEFAULT '0'::numeric NOT NULL,
    balance_due numeric(12,2) DEFAULT '0'::numeric NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    gateway_intent_id character varying(255),
    meta jsonb
);


--
-- Name: COLUMN payment_intents.payable_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.payment_intents.payable_type IS 'PayableType enum value';


--
-- Name: COLUMN payment_intents.payable_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.payment_intents.payable_id IS 'ID in payable table (e.g. sales.id)';


--
-- Name: COLUMN payment_intents.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.payment_intents.status IS 'PaymentIntentStatus enum value';


--
-- Name: COLUMN payment_intents.channel; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.payment_intents.channel IS 'pos|api|invoice';


--
-- Name: payment_intents_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.payment_intents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: payment_intents_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.payment_intents_id_seq OWNED BY public.payment_intents.id;


--
-- Name: payments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.payments (
    id integer NOT NULL,
    sale_id integer,
    method character varying NOT NULL,
    provider character varying,
    amount numeric(12,2) NOT NULL,
    status character varying NOT NULL,
    reference character varying,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    gateway_intent_id character varying
);


--
-- Name: payments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.payments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: payments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.payments_id_seq OWNED BY public.payments.id;


--
-- Name: recon_sheets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.recon_sheets (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    branch_id integer NOT NULL,
    shift character varying(30) NOT NULL,
    window_start timestamp with time zone NOT NULL,
    window_end timestamp with time zone NOT NULL,
    channel character varying(32) NOT NULL,
    opening_amount numeric(14,2) NOT NULL,
    income_amount numeric(14,2) NOT NULL,
    expense_amount numeric(14,2) NOT NULL,
    cash_in_amount numeric(14,2) NOT NULL,
    cash_out_amount numeric(14,2) NOT NULL,
    expected_closing_amount numeric(14,2) NOT NULL,
    actual_closing_amount numeric(14,2) NOT NULL,
    variance_amount numeric(14,2) NOT NULL,
    note character varying,
    status character varying(30) NOT NULL,
    closed_by_user_id integer,
    approved_by_user_id integer,
    closed_at timestamp with time zone,
    approved_at timestamp with time zone,
    meta json,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: recon_sheets_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.recon_sheets_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: recon_sheets_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.recon_sheets_id_seq OWNED BY public.recon_sheets.id;


--
-- Name: roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.roles (
    id integer NOT NULL,
    name character varying NOT NULL,
    description character varying,
    permissions json,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone
);


--
-- Name: roles_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.roles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: roles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.roles_id_seq OWNED BY public.roles.id;


--
-- Name: sale_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sale_items (
    id integer NOT NULL,
    sale_id integer NOT NULL,
    atomic_unit_id integer NOT NULL,
    name_snapshot character varying NOT NULL,
    unit_price numeric(12,2) NOT NULL,
    quantity integer NOT NULL,
    line_total numeric(12,2) NOT NULL
);


--
-- Name: sale_items_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sale_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sale_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sale_items_id_seq OWNED BY public.sale_items.id;


--
-- Name: sales; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sales (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    branch_id integer NOT NULL,
    cashier_id integer NOT NULL,
    status character varying NOT NULL,
    payment_method character varying NOT NULL,
    subtotal numeric(12,2) NOT NULL,
    total numeric(12,2) NOT NULL,
    payment_summary json,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    paid_at timestamp with time zone,
    receipt_no character varying(32) NOT NULL,
    discount_total numeric(12,2) DEFAULT 0 NOT NULL,
    discount_reason character varying(64),
    complimentary_total numeric(12,2) DEFAULT 0 NOT NULL,
    tendered_total numeric(12,2) DEFAULT 0 NOT NULL,
    change_amount numeric(12,2) DEFAULT 0 NOT NULL,
    unpaid_amount numeric(12,2) DEFAULT 0 NOT NULL,
    order_id integer
);


--
-- Name: sales_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sales_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sales_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sales_id_seq OWNED BY public.sales.id;


--
-- Name: taxonomy_nodes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.taxonomy_nodes (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    parent_id integer,
    name character varying NOT NULL,
    semantic_level character varying,
    sort_order integer NOT NULL,
    is_active boolean NOT NULL,
    taxonomy_type character varying(50) NOT NULL,
    meta jsonb
);


--
-- Name: taxonomy_nodes_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.taxonomy_nodes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: taxonomy_nodes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.taxonomy_nodes_id_seq OWNED BY public.taxonomy_nodes.id;


--
-- Name: tenants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tenants (
    id integer NOT NULL,
    code character varying NOT NULL,
    name character varying NOT NULL,
    country_code character varying(2) NOT NULL,
    country_name character varying,
    currency character varying(3) NOT NULL,
    locale character varying NOT NULL,
    timezone character varying NOT NULL,
    settings json,
    extra_metadata json,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone
);


--
-- Name: tenants_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tenants_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tenants_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tenants_id_seq OWNED BY public.tenants.id;


--
-- Name: treasury_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.treasury_logs (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    branch_id integer NOT NULL,
    event_type character varying(64) NOT NULL,
    sale_id integer,
    payment_attempt_id integer,
    amount numeric(12,2) NOT NULL,
    currency character varying(8) DEFAULT 'XAF'::character varying NOT NULL,
    channel character varying(32),
    meta json,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    direction character varying(10) NOT NULL,
    reference_type character varying(32) NOT NULL,
    reference_id integer NOT NULL,
    taxonomy_node_id integer,
    idempotency_key character varying(128),
    occurred_at timestamp with time zone NOT NULL,
    CONSTRAINT treasury_logs_direction_check CHECK (((direction)::text = ANY (ARRAY[('debit'::character varying)::text, ('credit'::character varying)::text])))
);


--
-- Name: COLUMN treasury_logs.event_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.treasury_logs.event_type IS 'SALE_REVENUE_GROSS | PAYMENT_RECEIVED | DEBT_CREATED | DISCOUNT_APPLIED | COMPLIMENTARY_APPLIED';


--
-- Name: COLUMN treasury_logs.channel; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.treasury_logs.channel IS 'cash | mtn | orange | wallet | card | xafpay';


--
-- Name: COLUMN treasury_logs.meta; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.treasury_logs.meta IS 'additional event metadata';


--
-- Name: treasury_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.treasury_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: treasury_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.treasury_logs_id_seq OWNED BY public.treasury_logs.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id integer NOT NULL,
    username character varying(50) NOT NULL,
    password_hash character varying(255) NOT NULL,
    full_name character varying(100),
    phone character varying(30),
    role character varying(50),
    tenant_id integer NOT NULL,
    branch_id integer NOT NULL,
    is_active boolean,
    created_at timestamp without time zone
);


--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: wnd_inventory_aliases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.wnd_inventory_aliases (
    source_product_name text NOT NULL,
    atomic_unit_id integer NOT NULL,
    canonical_xbos_name text NOT NULL,
    note text
);


--
-- Name: wnd_inventory_real_staging; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.wnd_inventory_real_staging (
    product_name text,
    category text,
    buying_price numeric,
    selling_price numeric,
    quantity_on_hand integer,
    last_updated date
);


--
-- Name: wnd_inventory_staging; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.wnd_inventory_staging (
    product_name text,
    category text,
    buying_price numeric,
    selling_price numeric,
    quantity_on_hand integer,
    last_updated date
);


--
-- Name: accounts_receivable id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts_receivable ALTER COLUMN id SET DEFAULT nextval('public.accounts_receivable_id_seq'::regclass);


--
-- Name: accounts_receivable_repayments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts_receivable_repayments ALTER COLUMN id SET DEFAULT nextval('public.accounts_receivable_repayments_id_seq'::regclass);


--
-- Name: atomic_units id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.atomic_units ALTER COLUMN id SET DEFAULT nextval('public.billable_units_id_seq'::regclass);


--
-- Name: branches id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.branches ALTER COLUMN id SET DEFAULT nextval('public.branches_id_seq'::regclass);


--
-- Name: idempotency_keys id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.idempotency_keys ALTER COLUMN id SET DEFAULT nextval('public.idempotency_keys_id_seq'::regclass);


--
-- Name: inventory_items id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_items ALTER COLUMN id SET DEFAULT nextval('public.inventory_items_id_seq'::regclass);


--
-- Name: inventory_movements id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_movements ALTER COLUMN id SET DEFAULT nextval('public.inventory_movements_id_seq'::regclass);


--
-- Name: order_item_modifiers id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_item_modifiers ALTER COLUMN id SET DEFAULT nextval('public.order_item_modifiers_id_seq'::regclass);


--
-- Name: order_items id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_items ALTER COLUMN id SET DEFAULT nextval('public.order_items_id_seq'::regclass);


--
-- Name: orders id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.orders ALTER COLUMN id SET DEFAULT nextval('public.orders_id_seq'::regclass);


--
-- Name: payment_attempts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payment_attempts ALTER COLUMN id SET DEFAULT nextval('public.payment_attempts_id_seq'::regclass);


--
-- Name: payment_intents id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payment_intents ALTER COLUMN id SET DEFAULT nextval('public.payment_intents_id_seq'::regclass);


--
-- Name: payments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payments ALTER COLUMN id SET DEFAULT nextval('public.payments_id_seq'::regclass);


--
-- Name: recon_sheets id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recon_sheets ALTER COLUMN id SET DEFAULT nextval('public.recon_sheets_id_seq'::regclass);


--
-- Name: roles id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles ALTER COLUMN id SET DEFAULT nextval('public.roles_id_seq'::regclass);


--
-- Name: sale_items id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sale_items ALTER COLUMN id SET DEFAULT nextval('public.sale_items_id_seq'::regclass);


--
-- Name: sales id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sales ALTER COLUMN id SET DEFAULT nextval('public.sales_id_seq'::regclass);


--
-- Name: taxonomy_nodes id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.taxonomy_nodes ALTER COLUMN id SET DEFAULT nextval('public.taxonomy_nodes_id_seq'::regclass);


--
-- Name: tenants id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenants ALTER COLUMN id SET DEFAULT nextval('public.tenants_id_seq'::regclass);


--
-- Name: treasury_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.treasury_logs ALTER COLUMN id SET DEFAULT nextval('public.treasury_logs_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: accounts_receivable accounts_receivable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts_receivable
    ADD CONSTRAINT accounts_receivable_pkey PRIMARY KEY (id);


--
-- Name: accounts_receivable_repayments accounts_receivable_repayments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts_receivable_repayments
    ADD CONSTRAINT accounts_receivable_repayments_pkey PRIMARY KEY (id);


--
-- Name: atomic_unit_taxonomy billable_unit_taxonomy_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.atomic_unit_taxonomy
    ADD CONSTRAINT billable_unit_taxonomy_pkey PRIMARY KEY (atomic_unit_id, taxonomy_node_id);


--
-- Name: billable_unit_taxonomy billable_unit_taxonomy_pkey1; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billable_unit_taxonomy
    ADD CONSTRAINT billable_unit_taxonomy_pkey1 PRIMARY KEY (atomic_unit_id, taxonomy_node_id);


--
-- Name: atomic_units billable_units_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.atomic_units
    ADD CONSTRAINT billable_units_pkey PRIMARY KEY (id);


--
-- Name: branches branches_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.branches
    ADD CONSTRAINT branches_pkey PRIMARY KEY (id);


--
-- Name: idempotency_keys idempotency_keys_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.idempotency_keys
    ADD CONSTRAINT idempotency_keys_pkey PRIMARY KEY (id);


--
-- Name: inventory_items inventory_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_items
    ADD CONSTRAINT inventory_items_pkey PRIMARY KEY (id);


--
-- Name: inventory_movements inventory_movements_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_movements
    ADD CONSTRAINT inventory_movements_pkey PRIMARY KEY (id);


--
-- Name: order_item_modifiers order_item_modifiers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_item_modifiers
    ADD CONSTRAINT order_item_modifiers_pkey PRIMARY KEY (id);


--
-- Name: order_items order_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_items
    ADD CONSTRAINT order_items_pkey PRIMARY KEY (id);


--
-- Name: orders orders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_pkey PRIMARY KEY (id);


--
-- Name: payment_attempts payment_attempts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payment_attempts
    ADD CONSTRAINT payment_attempts_pkey PRIMARY KEY (id);


--
-- Name: payment_intents payment_intents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payment_intents
    ADD CONSTRAINT payment_intents_pkey PRIMARY KEY (id);


--
-- Name: payments payments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payments
    ADD CONSTRAINT payments_pkey PRIMARY KEY (id);


--
-- Name: recon_sheets recon_sheets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recon_sheets
    ADD CONSTRAINT recon_sheets_pkey PRIMARY KEY (id);


--
-- Name: roles roles_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_name_key UNIQUE (name);


--
-- Name: roles roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (id);


--
-- Name: sale_items sale_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sale_items
    ADD CONSTRAINT sale_items_pkey PRIMARY KEY (id);


--
-- Name: sales sales_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sales
    ADD CONSTRAINT sales_pkey PRIMARY KEY (id);


--
-- Name: taxonomy_nodes taxonomy_nodes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.taxonomy_nodes
    ADD CONSTRAINT taxonomy_nodes_pkey PRIMARY KEY (id);


--
-- Name: tenants tenants_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenants
    ADD CONSTRAINT tenants_code_key UNIQUE (code);


--
-- Name: tenants tenants_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenants
    ADD CONSTRAINT tenants_pkey PRIMARY KEY (id);


--
-- Name: treasury_logs treasury_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.treasury_logs
    ADD CONSTRAINT treasury_logs_pkey PRIMARY KEY (id);


--
-- Name: atomic_units unique_au_per_tenant; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.atomic_units
    ADD CONSTRAINT unique_au_per_tenant UNIQUE (tenant_id, name);


--
-- Name: atomic_units uq_billable_unit_sku_per_tenant; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.atomic_units
    ADD CONSTRAINT uq_billable_unit_sku_per_tenant UNIQUE (tenant_id, sku);


--
-- Name: idempotency_keys uq_idempotency; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.idempotency_keys
    ADD CONSTRAINT uq_idempotency UNIQUE (key, scope);


--
-- Name: sales uq_sales_order_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sales
    ADD CONSTRAINT uq_sales_order_id UNIQUE (order_id);


--
-- Name: taxonomy_nodes uq_taxonomy_node_name_per_parent; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.taxonomy_nodes
    ADD CONSTRAINT uq_taxonomy_node_name_per_parent UNIQUE (tenant_id, parent_id, name);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: users users_username_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_username_key UNIQUE (username);


--
-- Name: payment_attempts ux_pa_callback_reference; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payment_attempts
    ADD CONSTRAINT ux_pa_callback_reference UNIQUE (callback_reference);


--
-- Name: payment_attempts ux_pa_client_reference; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payment_attempts
    ADD CONSTRAINT ux_pa_client_reference UNIQUE (client_reference);


--
-- Name: wnd_inventory_aliases wnd_inventory_aliases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wnd_inventory_aliases
    ADD CONSTRAINT wnd_inventory_aliases_pkey PRIMARY KEY (source_product_name);


--
-- Name: idx_payment_intents_gateway_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_payment_intents_gateway_id ON public.payment_intents USING btree (gateway_intent_id);


--
-- Name: idx_payment_intents_meta_gin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_payment_intents_meta_gin ON public.payment_intents USING gin (meta);


--
-- Name: ix_accounts_receivable_order_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_accounts_receivable_order_id ON public.accounts_receivable USING btree (order_id);


--
-- Name: ix_accounts_receivable_repayments_ar_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_accounts_receivable_repayments_ar_id ON public.accounts_receivable_repayments USING btree (ar_id);


--
-- Name: ix_accounts_receivable_sale_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_accounts_receivable_sale_id ON public.accounts_receivable USING btree (sale_id);


--
-- Name: ix_accounts_receivable_tenant_branch_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_accounts_receivable_tenant_branch_status ON public.accounts_receivable USING btree (tenant_id, branch_id, status);


--
-- Name: ix_billable_unit_tenant_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_billable_unit_tenant_active ON public.atomic_units USING btree (tenant_id, is_active);


--
-- Name: ix_billable_units_tenant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_billable_units_tenant_id ON public.atomic_units USING btree (tenant_id);


--
-- Name: ix_branches_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_branches_id ON public.branches USING btree (id);


--
-- Name: ix_inventory_item_tenant_branch; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_inventory_item_tenant_branch ON public.inventory_items USING btree (tenant_id, branch_id);


--
-- Name: ix_inventory_items_billable_unit_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_inventory_items_billable_unit_id ON public.inventory_items USING btree (atomic_unit_id);


--
-- Name: ix_inventory_items_branch_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_inventory_items_branch_id ON public.inventory_items USING btree (branch_id);


--
-- Name: ix_inventory_items_tenant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_inventory_items_tenant_id ON public.inventory_items USING btree (tenant_id);


--
-- Name: ix_inventory_movement_branch_unit_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_inventory_movement_branch_unit_time ON public.inventory_movements USING btree (branch_id, atomic_unit_id, created_at);


--
-- Name: ix_inventory_movements_billable_unit_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_inventory_movements_billable_unit_id ON public.inventory_movements USING btree (atomic_unit_id);


--
-- Name: ix_inventory_movements_branch_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_inventory_movements_branch_id ON public.inventory_movements USING btree (branch_id);


--
-- Name: ix_inventory_movements_inventory_item_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_inventory_movements_inventory_item_id ON public.inventory_movements USING btree (inventory_item_id);


--
-- Name: ix_inventory_movements_movement_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_inventory_movements_movement_type ON public.inventory_movements USING btree (movement_type);


--
-- Name: ix_inventory_movements_reference_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_inventory_movements_reference_id ON public.inventory_movements USING btree (reference_id);


--
-- Name: ix_inventory_movements_tenant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_inventory_movements_tenant_id ON public.inventory_movements USING btree (tenant_id);


--
-- Name: ix_order_item_modifiers_order_item_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_order_item_modifiers_order_item_id ON public.order_item_modifiers USING btree (order_item_id);


--
-- Name: ix_orders_created_by_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_orders_created_by_user_id ON public.orders USING btree (created_by_user_id);


--
-- Name: ix_pa_intent_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pa_intent_status ON public.payment_attempts USING btree (payment_intent_id, status);


--
-- Name: ix_payment_attempts_cashier_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_payment_attempts_cashier_id ON public.payment_attempts USING btree (cashier_id);


--
-- Name: ix_payment_attempts_gateway_reference; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_payment_attempts_gateway_reference ON public.payment_attempts USING btree (gateway_reference);


--
-- Name: ix_payment_attempts_method; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_payment_attempts_method ON public.payment_attempts USING btree (method);


--
-- Name: ix_payment_attempts_payment_intent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_payment_attempts_payment_intent_id ON public.payment_attempts USING btree (payment_intent_id);


--
-- Name: ix_payment_attempts_provider; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_payment_attempts_provider ON public.payment_attempts USING btree (provider);


--
-- Name: ix_payment_attempts_provider_reference; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_payment_attempts_provider_reference ON public.payment_attempts USING btree (provider_reference);


--
-- Name: ix_payment_attempts_sale_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_payment_attempts_sale_id ON public.payment_attempts USING btree (sale_id);


--
-- Name: ix_payment_attempts_settlement_mode; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_payment_attempts_settlement_mode ON public.payment_attempts USING btree (settlement_mode);


--
-- Name: ix_payment_attempts_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_payment_attempts_status ON public.payment_attempts USING btree (status);


--
-- Name: ix_payment_gateway_intent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_payment_gateway_intent ON public.payments USING btree (gateway_intent_id);


--
-- Name: ix_payment_intents_branch_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_payment_intents_branch_id ON public.payment_intents USING btree (branch_id);


--
-- Name: ix_payment_intents_created_by_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_payment_intents_created_by_user_id ON public.payment_intents USING btree (created_by_user_id);


--
-- Name: ix_payment_intents_payable_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_payment_intents_payable_id ON public.payment_intents USING btree (payable_id);


--
-- Name: ix_payment_intents_payable_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_payment_intents_payable_type ON public.payment_intents USING btree (payable_type);


--
-- Name: ix_payment_intents_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_payment_intents_status ON public.payment_intents USING btree (status);


--
-- Name: ix_payment_intents_tenant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_payment_intents_tenant_id ON public.payment_intents USING btree (tenant_id);


--
-- Name: ix_payment_sale_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_payment_sale_status ON public.payments USING btree (sale_id, status);


--
-- Name: ix_payments_method; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_payments_method ON public.payments USING btree (method);


--
-- Name: ix_payments_provider; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_payments_provider ON public.payments USING btree (provider);


--
-- Name: ix_payments_reference; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_payments_reference ON public.payments USING btree (reference);


--
-- Name: ix_payments_sale_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_payments_sale_id ON public.payments USING btree (sale_id);


--
-- Name: ix_payments_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_payments_status ON public.payments USING btree (status);


--
-- Name: ix_pi_payable_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pi_payable_lookup ON public.payment_intents USING btree (payable_type, payable_id);


--
-- Name: ix_pi_tenant_branch_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pi_tenant_branch_created ON public.payment_intents USING btree (tenant_id, branch_id, created_at);


--
-- Name: ix_recon_previous_close; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recon_previous_close ON public.recon_sheets USING btree (tenant_id, branch_id, channel, window_end);


--
-- Name: ix_recon_sheets_approved_by_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recon_sheets_approved_by_user_id ON public.recon_sheets USING btree (approved_by_user_id);


--
-- Name: ix_recon_sheets_branch_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recon_sheets_branch_id ON public.recon_sheets USING btree (branch_id);


--
-- Name: ix_recon_sheets_channel; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recon_sheets_channel ON public.recon_sheets USING btree (channel);


--
-- Name: ix_recon_sheets_closed_by_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recon_sheets_closed_by_user_id ON public.recon_sheets USING btree (closed_by_user_id);


--
-- Name: ix_recon_sheets_shift; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recon_sheets_shift ON public.recon_sheets USING btree (shift);


--
-- Name: ix_recon_sheets_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recon_sheets_status ON public.recon_sheets USING btree (status);


--
-- Name: ix_recon_sheets_tenant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recon_sheets_tenant_id ON public.recon_sheets USING btree (tenant_id);


--
-- Name: ix_recon_sheets_window_end; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recon_sheets_window_end ON public.recon_sheets USING btree (window_end);


--
-- Name: ix_recon_sheets_window_start; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recon_sheets_window_start ON public.recon_sheets USING btree (window_start);


--
-- Name: ix_recon_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recon_status ON public.recon_sheets USING btree (status);


--
-- Name: ix_recon_window; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recon_window ON public.recon_sheets USING btree (tenant_id, branch_id, window_start, window_end);


--
-- Name: ix_sale_item_sale; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sale_item_sale ON public.sale_items USING btree (sale_id);


--
-- Name: ix_sale_items_billable_unit_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sale_items_billable_unit_id ON public.sale_items USING btree (atomic_unit_id);


--
-- Name: ix_sale_items_sale_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sale_items_sale_id ON public.sale_items USING btree (sale_id);


--
-- Name: ix_sale_tenant_branch_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sale_tenant_branch_created ON public.sales USING btree (tenant_id, branch_id, created_at);


--
-- Name: ix_sales_branch_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sales_branch_id ON public.sales USING btree (branch_id);


--
-- Name: ix_sales_cashier_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sales_cashier_id ON public.sales USING btree (cashier_id);


--
-- Name: ix_sales_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sales_status ON public.sales USING btree (status);


--
-- Name: ix_sales_tenant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sales_tenant_id ON public.sales USING btree (tenant_id);


--
-- Name: ix_taxonomy_nodes_parent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_taxonomy_nodes_parent_id ON public.taxonomy_nodes USING btree (parent_id);


--
-- Name: ix_taxonomy_nodes_tenant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_taxonomy_nodes_tenant_id ON public.taxonomy_nodes USING btree (tenant_id);


--
-- Name: ix_taxonomy_tenant_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_taxonomy_tenant_parent ON public.taxonomy_nodes USING btree (tenant_id, parent_id);


--
-- Name: ix_tenants_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tenants_id ON public.tenants USING btree (id);


--
-- Name: ix_treasury_logs_attempt; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_treasury_logs_attempt ON public.treasury_logs USING btree (payment_attempt_id);


--
-- Name: ix_treasury_logs_occurred; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_treasury_logs_occurred ON public.treasury_logs USING btree (tenant_id, occurred_at DESC);


--
-- Name: ix_treasury_logs_reference; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_treasury_logs_reference ON public.treasury_logs USING btree (reference_type, reference_id);


--
-- Name: ix_treasury_logs_sale; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_treasury_logs_sale ON public.treasury_logs USING btree (sale_id);


--
-- Name: ix_treasury_logs_tenant_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_treasury_logs_tenant_created ON public.treasury_logs USING btree (tenant_id, created_at);


--
-- Name: ix_users_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_id ON public.users USING btree (id);


--
-- Name: treasury_logs_idempotency_key_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX treasury_logs_idempotency_key_idx ON public.treasury_logs USING btree (tenant_id, idempotency_key);


--
-- Name: uq_inventory_item_branch_unit; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_inventory_item_branch_unit ON public.inventory_items USING btree (branch_id, atomic_unit_id);


--
-- Name: ux_accounts_receivable_order_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_accounts_receivable_order_id ON public.accounts_receivable USING btree (order_id) WHERE (order_id IS NOT NULL);


--
-- Name: ux_pa_callback_reference_not_null; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_pa_callback_reference_not_null ON public.payment_attempts USING btree (callback_reference) WHERE (callback_reference IS NOT NULL);


--
-- Name: ux_recon_tenant_branch_shift_window_channel; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_recon_tenant_branch_shift_window_channel ON public.recon_sheets USING btree (tenant_id, branch_id, shift, window_start, window_end, channel);


--
-- Name: ux_sales_receipt_no; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_sales_receipt_no ON public.sales USING btree (tenant_id, branch_id, receipt_no);


--
-- Name: accounts_receivable_repayments accounts_receivable_repayments_ar_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts_receivable_repayments
    ADD CONSTRAINT accounts_receivable_repayments_ar_id_fkey FOREIGN KEY (ar_id) REFERENCES public.accounts_receivable(id);


--
-- Name: billable_unit_taxonomy billable_unit_taxonomy_atomic_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billable_unit_taxonomy
    ADD CONSTRAINT billable_unit_taxonomy_atomic_unit_id_fkey FOREIGN KEY (atomic_unit_id) REFERENCES public.atomic_units(id) ON DELETE CASCADE;


--
-- Name: atomic_unit_taxonomy billable_unit_taxonomy_billable_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.atomic_unit_taxonomy
    ADD CONSTRAINT billable_unit_taxonomy_billable_unit_id_fkey FOREIGN KEY (atomic_unit_id) REFERENCES public.atomic_units(id) ON DELETE CASCADE;


--
-- Name: atomic_unit_taxonomy billable_unit_taxonomy_taxonomy_node_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.atomic_unit_taxonomy
    ADD CONSTRAINT billable_unit_taxonomy_taxonomy_node_id_fkey FOREIGN KEY (taxonomy_node_id) REFERENCES public.taxonomy_nodes(id) ON DELETE CASCADE;


--
-- Name: billable_unit_taxonomy billable_unit_taxonomy_taxonomy_node_id_fkey1; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billable_unit_taxonomy
    ADD CONSTRAINT billable_unit_taxonomy_taxonomy_node_id_fkey1 FOREIGN KEY (taxonomy_node_id) REFERENCES public.taxonomy_nodes(id) ON DELETE CASCADE;


--
-- Name: atomic_units billable_units_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.atomic_units
    ADD CONSTRAINT billable_units_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: branches branches_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.branches
    ADD CONSTRAINT branches_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id);


--
-- Name: atomic_units fk_atomic_units_parent; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.atomic_units
    ADD CONSTRAINT fk_atomic_units_parent FOREIGN KEY (parent_unit_id) REFERENCES public.atomic_units(id) ON DELETE SET NULL;


--
-- Name: inventory_items inventory_items_billable_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_items
    ADD CONSTRAINT inventory_items_billable_unit_id_fkey FOREIGN KEY (atomic_unit_id) REFERENCES public.atomic_units(id);


--
-- Name: inventory_movements inventory_movements_billable_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_movements
    ADD CONSTRAINT inventory_movements_billable_unit_id_fkey FOREIGN KEY (atomic_unit_id) REFERENCES public.atomic_units(id);


--
-- Name: inventory_movements inventory_movements_inventory_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_movements
    ADD CONSTRAINT inventory_movements_inventory_item_id_fkey FOREIGN KEY (inventory_item_id) REFERENCES public.inventory_items(id) ON DELETE CASCADE;


--
-- Name: order_item_modifiers order_item_modifiers_order_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_item_modifiers
    ADD CONSTRAINT order_item_modifiers_order_item_id_fkey FOREIGN KEY (order_item_id) REFERENCES public.order_items(id) ON DELETE CASCADE;


--
-- Name: order_items order_items_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_items
    ADD CONSTRAINT order_items_order_id_fkey FOREIGN KEY (order_id) REFERENCES public.orders(id) ON DELETE CASCADE;


--
-- Name: orders orders_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


--
-- Name: payment_attempts payment_attempts_cashier_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payment_attempts
    ADD CONSTRAINT payment_attempts_cashier_id_fkey FOREIGN KEY (cashier_id) REFERENCES public.users(id);


--
-- Name: payment_attempts payment_attempts_payment_intent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payment_attempts
    ADD CONSTRAINT payment_attempts_payment_intent_id_fkey FOREIGN KEY (payment_intent_id) REFERENCES public.payment_intents(id) ON DELETE CASCADE;


--
-- Name: payment_attempts payment_attempts_sale_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payment_attempts
    ADD CONSTRAINT payment_attempts_sale_id_fkey FOREIGN KEY (sale_id) REFERENCES public.sales(id) ON DELETE SET NULL;


--
-- Name: payment_intents payment_intents_branch_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payment_intents
    ADD CONSTRAINT payment_intents_branch_id_fkey FOREIGN KEY (branch_id) REFERENCES public.branches(id) ON DELETE CASCADE;


--
-- Name: payment_intents payment_intents_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payment_intents
    ADD CONSTRAINT payment_intents_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


--
-- Name: payment_intents payment_intents_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payment_intents
    ADD CONSTRAINT payment_intents_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: payments payments_sale_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payments
    ADD CONSTRAINT payments_sale_id_fkey FOREIGN KEY (sale_id) REFERENCES public.sales(id) ON DELETE CASCADE;


--
-- Name: sale_items sale_items_billable_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sale_items
    ADD CONSTRAINT sale_items_billable_unit_id_fkey FOREIGN KEY (atomic_unit_id) REFERENCES public.atomic_units(id);


--
-- Name: sale_items sale_items_sale_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sale_items
    ADD CONSTRAINT sale_items_sale_id_fkey FOREIGN KEY (sale_id) REFERENCES public.sales(id) ON DELETE CASCADE;


--
-- Name: sales sales_branch_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sales
    ADD CONSTRAINT sales_branch_id_fkey FOREIGN KEY (branch_id) REFERENCES public.branches(id) ON DELETE CASCADE;


--
-- Name: sales sales_cashier_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sales
    ADD CONSTRAINT sales_cashier_id_fkey FOREIGN KEY (cashier_id) REFERENCES public.users(id);


--
-- Name: sales sales_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sales
    ADD CONSTRAINT sales_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: taxonomy_nodes taxonomy_nodes_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.taxonomy_nodes
    ADD CONSTRAINT taxonomy_nodes_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.taxonomy_nodes(id) ON DELETE CASCADE;


--
-- Name: taxonomy_nodes taxonomy_nodes_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.taxonomy_nodes
    ADD CONSTRAINT taxonomy_nodes_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: users users_branch_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_branch_id_fkey FOREIGN KEY (branch_id) REFERENCES public.branches(id);


--
-- Name: users users_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id);


--
-- PostgreSQL database dump complete
--
