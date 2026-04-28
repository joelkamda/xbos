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
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


ALTER TABLE public.alembic_version OWNER TO postgres;

--
-- Name: atomic_unit_taxonomy; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.atomic_unit_taxonomy (
    atomic_unit_id integer NOT NULL,
    taxonomy_node_id integer NOT NULL
);


ALTER TABLE public.atomic_unit_taxonomy OWNER TO postgres;

--
-- Name: atomic_units; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.atomic_units (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    name character varying NOT NULL,
    sku character varying,
    unit_price numeric(12,2),
    unit_type character varying,
    is_active boolean NOT NULL,
    meta jsonb
);


ALTER TABLE public.atomic_units OWNER TO postgres;

--
-- Name: billable_unit_taxonomy; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.billable_unit_taxonomy (
    atomic_unit_id integer NOT NULL,
    taxonomy_node_id integer NOT NULL
);


ALTER TABLE public.billable_unit_taxonomy OWNER TO postgres;

--
-- Name: billable_units_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.billable_units_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.billable_units_id_seq OWNER TO postgres;

--
-- Name: billable_units_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.billable_units_id_seq OWNED BY public.atomic_units.id;


--
-- Name: branches; Type: TABLE; Schema: public; Owner: postgres
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


ALTER TABLE public.branches OWNER TO postgres;

--
-- Name: branches_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.branches_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.branches_id_seq OWNER TO postgres;

--
-- Name: branches_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.branches_id_seq OWNED BY public.branches.id;


--
-- Name: inventory_items; Type: TABLE; Schema: public; Owner: postgres
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


ALTER TABLE public.inventory_items OWNER TO postgres;

--
-- Name: inventory_items_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.inventory_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.inventory_items_id_seq OWNER TO postgres;

--
-- Name: inventory_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.inventory_items_id_seq OWNED BY public.inventory_items.id;


--
-- Name: inventory_movements; Type: TABLE; Schema: public; Owner: postgres
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


ALTER TABLE public.inventory_movements OWNER TO postgres;

--
-- Name: inventory_movements_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.inventory_movements_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.inventory_movements_id_seq OWNER TO postgres;

--
-- Name: inventory_movements_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.inventory_movements_id_seq OWNED BY public.inventory_movements.id;


--
-- Name: payment_attempts; Type: TABLE; Schema: public; Owner: postgres
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


ALTER TABLE public.payment_attempts OWNER TO postgres;

--
-- Name: COLUMN payment_attempts.method; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.payment_attempts.method IS 'PaymentMethod enum value';


--
-- Name: COLUMN payment_attempts.provider; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.payment_attempts.provider IS 'PaymentProvider enum value';


--
-- Name: COLUMN payment_attempts.settlement_mode; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.payment_attempts.settlement_mode IS 'SettlementMode enum value';


--
-- Name: COLUMN payment_attempts.status; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.payment_attempts.status IS 'PaymentAttemptStatus enum value';


--
-- Name: COLUMN payment_attempts.client_reference; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.payment_attempts.client_reference IS 'Client idempotency key (POS/API)';


--
-- Name: COLUMN payment_attempts.callback_reference; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.payment_attempts.callback_reference IS 'Provider webhook idempotency key';


--
-- Name: payment_attempts_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.payment_attempts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.payment_attempts_id_seq OWNER TO postgres;

--
-- Name: payment_attempts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.payment_attempts_id_seq OWNED BY public.payment_attempts.id;


--
-- Name: payment_intents; Type: TABLE; Schema: public; Owner: postgres
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


ALTER TABLE public.payment_intents OWNER TO postgres;

--
-- Name: COLUMN payment_intents.payable_type; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.payment_intents.payable_type IS 'PayableType enum value';


--
-- Name: COLUMN payment_intents.payable_id; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.payment_intents.payable_id IS 'ID in payable table (e.g. sales.id)';


--
-- Name: COLUMN payment_intents.status; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.payment_intents.status IS 'PaymentIntentStatus enum value';


--
-- Name: COLUMN payment_intents.channel; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.payment_intents.channel IS 'pos|api|invoice';


--
-- Name: payment_intents_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.payment_intents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.payment_intents_id_seq OWNER TO postgres;

--
-- Name: payment_intents_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.payment_intents_id_seq OWNED BY public.payment_intents.id;


--
-- Name: payments; Type: TABLE; Schema: public; Owner: postgres
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


ALTER TABLE public.payments OWNER TO postgres;

--
-- Name: payments_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.payments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.payments_id_seq OWNER TO postgres;

--
-- Name: payments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.payments_id_seq OWNED BY public.payments.id;


--
-- Name: roles; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.roles (
    id integer NOT NULL,
    name character varying NOT NULL,
    description character varying,
    permissions json,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone
);


ALTER TABLE public.roles OWNER TO postgres;

--
-- Name: roles_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.roles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.roles_id_seq OWNER TO postgres;

--
-- Name: roles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.roles_id_seq OWNED BY public.roles.id;


--
-- Name: sale_items; Type: TABLE; Schema: public; Owner: postgres
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


ALTER TABLE public.sale_items OWNER TO postgres;

--
-- Name: sale_items_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.sale_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.sale_items_id_seq OWNER TO postgres;

--
-- Name: sale_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.sale_items_id_seq OWNED BY public.sale_items.id;


--
-- Name: sales; Type: TABLE; Schema: public; Owner: postgres
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
    unpaid_amount numeric(12,2) DEFAULT 0 NOT NULL
);


ALTER TABLE public.sales OWNER TO postgres;

--
-- Name: sales_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.sales_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.sales_id_seq OWNER TO postgres;

--
-- Name: sales_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.sales_id_seq OWNED BY public.sales.id;


--
-- Name: taxonomy_nodes; Type: TABLE; Schema: public; Owner: postgres
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


ALTER TABLE public.taxonomy_nodes OWNER TO postgres;

--
-- Name: taxonomy_nodes_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.taxonomy_nodes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.taxonomy_nodes_id_seq OWNER TO postgres;

--
-- Name: taxonomy_nodes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.taxonomy_nodes_id_seq OWNED BY public.taxonomy_nodes.id;


--
-- Name: tenants; Type: TABLE; Schema: public; Owner: postgres
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


ALTER TABLE public.tenants OWNER TO postgres;

--
-- Name: tenants_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.tenants_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.tenants_id_seq OWNER TO postgres;

--
-- Name: tenants_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.tenants_id_seq OWNED BY public.tenants.id;


--
-- Name: treasury_logs; Type: TABLE; Schema: public; Owner: postgres
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
    CONSTRAINT treasury_logs_direction_check CHECK (((direction)::text = ANY ((ARRAY['debit'::character varying, 'credit'::character varying])::text[])))
);


ALTER TABLE public.treasury_logs OWNER TO postgres;

--
-- Name: COLUMN treasury_logs.event_type; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.treasury_logs.event_type IS 'SALE_REVENUE_GROSS | PAYMENT_RECEIVED | DEBT_CREATED | DISCOUNT_APPLIED | COMPLIMENTARY_APPLIED';


--
-- Name: COLUMN treasury_logs.channel; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.treasury_logs.channel IS 'cash | mtn | orange | wallet | card | xafpay';


--
-- Name: COLUMN treasury_logs.meta; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.treasury_logs.meta IS 'additional event metadata';


--
-- Name: treasury_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.treasury_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.treasury_logs_id_seq OWNER TO postgres;

--
-- Name: treasury_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.treasury_logs_id_seq OWNED BY public.treasury_logs.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: postgres
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


ALTER TABLE public.users OWNER TO postgres;

--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.users_id_seq OWNER TO postgres;

--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: atomic_units id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.atomic_units ALTER COLUMN id SET DEFAULT nextval('public.billable_units_id_seq'::regclass);


--
-- Name: branches id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.branches ALTER COLUMN id SET DEFAULT nextval('public.branches_id_seq'::regclass);


--
-- Name: inventory_items id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.inventory_items ALTER COLUMN id SET DEFAULT nextval('public.inventory_items_id_seq'::regclass);


--
-- Name: inventory_movements id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.inventory_movements ALTER COLUMN id SET DEFAULT nextval('public.inventory_movements_id_seq'::regclass);


--
-- Name: payment_attempts id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payment_attempts ALTER COLUMN id SET DEFAULT nextval('public.payment_attempts_id_seq'::regclass);


--
-- Name: payment_intents id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payment_intents ALTER COLUMN id SET DEFAULT nextval('public.payment_intents_id_seq'::regclass);


--
-- Name: payments id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payments ALTER COLUMN id SET DEFAULT nextval('public.payments_id_seq'::regclass);


--
-- Name: roles id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.roles ALTER COLUMN id SET DEFAULT nextval('public.roles_id_seq'::regclass);


--
-- Name: sale_items id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sale_items ALTER COLUMN id SET DEFAULT nextval('public.sale_items_id_seq'::regclass);


--
-- Name: sales id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sales ALTER COLUMN id SET DEFAULT nextval('public.sales_id_seq'::regclass);


--
-- Name: taxonomy_nodes id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.taxonomy_nodes ALTER COLUMN id SET DEFAULT nextval('public.taxonomy_nodes_id_seq'::regclass);


--
-- Name: tenants id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenants ALTER COLUMN id SET DEFAULT nextval('public.tenants_id_seq'::regclass);


--
-- Name: treasury_logs id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.treasury_logs ALTER COLUMN id SET DEFAULT nextval('public.treasury_logs_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Data for Name: alembic_version; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.alembic_version (version_num) FROM stdin;
5c706797029a
\.


--
-- Data for Name: atomic_unit_taxonomy; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.atomic_unit_taxonomy (atomic_unit_id, taxonomy_node_id) FROM stdin;
21	45
22	45
23	45
24	45
25	45
26	44
27	44
28	44
29	44
30	44
31	44
32	44
33	44
34	44
35	44
36	44
37	44
38	44
39	44
40	44
41	44
42	44
43	44
44	47
45	47
46	46
47	46
48	46
49	46
50	46
51	48
52	48
53	48
54	48
55	48
56	48
57	48
58	48
59	48
60	48
61	48
62	48
63	48
64	48
65	48
66	48
67	48
68	48
69	48
70	48
71	48
72	48
73	48
74	48
75	49
76	49
77	49
78	49
79	49
80	49
81	49
82	49
83	49
84	49
85	54
86	54
87	54
88	54
89	54
90	54
91	54
92	50
93	50
34	51
69	51
94	51
95	51
96	51
97	51
98	51
99	51
100	51
101	51
102	51
106	51
108	51
109	51
110	51
111	53
112	53
113	53
114	53
115	53
116	53
117	53
118	53
119	53
120	53
121	53
122	52
123	52
124	52
125	52
126	52
127	52
128	52
129	52
130	52
131	52
132	52
133	52
134	52
135	52
136	52
137	52
138	52
18	43
19	43
20	43
\.


--
-- Data for Name: atomic_units; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.atomic_units (id, tenant_id, name, sku, unit_price, unit_type, is_active, meta) FROM stdin;
18	2	Cigarettes	\N	1000.00	unit	t	\N
19	2	Shisha	\N	3500.00	unit	t	\N
20	2	Charcoal	\N	500.00	unit	t	\N
21	2	Eggs Simple	\N	500.00	unit	t	\N
22	2	Eggs Plus Complement	\N	1000.00	unit	t	\N
23	2	Salade Simple	\N	1500.00	unit	t	\N
24	2	Salade Complete	\N	2500.00	unit	t	\N
25	2	Full Breakfast	\N	2500.00	unit	t	\N
26	2	Chicken	\N	2500.00	unit	t	\N
27	2	Goat	\N	3500.00	unit	t	\N
28	2	Snails	\N	5000.00	unit	t	\N
29	2	Pork	\N	3000.00	unit	t	\N
30	2	Towel	\N	2500.00	unit	t	\N
31	2	Ndole	\N	2500.00	unit	t	\N
32	2	Eru	\N	2500.00	unit	t	\N
33	2	Okro and Egussi	\N	2500.00	unit	t	\N
34	2	White Beans	\N	2500.00	unit	t	\N
35	2	Cornchaff	\N	1500.00	unit	t	\N
36	2	Koki	\N	1500.00	unit	t	\N
37	2	Kati-Kati	\N	3000.00	unit	t	\N
38	2	Achu	\N	3000.00	unit	t	\N
39	2	Gambas	\N	7000.00	unit	t	\N
40	2	Fish	\N	3500.00	unit	t	\N
41	2	Poulet DG 1/4	\N	2500.00	unit	t	\N
42	2	Poulet DG 1/2	\N	5000.00	unit	t	\N
43	2	Poulet DG 1	\N	10000.00	unit	t	\N
44	2	Simple Complement	\N	500.00	unit	t	\N
45	2	Complete Complement	\N	1000.00	unit	t	\N
46	2	Ice Scream 300	\N	300.00	unit	t	\N
47	2	Ice Scream 500	\N	500.00	unit	t	\N
48	2	Ice Scream 1000	\N	1000.00	unit	t	\N
49	2	Ice Scream 1500	\N	1500.00	unit	t	\N
50	2	Ice Scream 2000	\N	2000.00	unit	t	\N
51	2	ISENBECK	\N	1000.00	unit	t	\N
52	2	EXPORT	\N	1000.00	unit	t	\N
53	2	CASTEL	\N	1000.00	unit	t	\N
54	2	MUTZIG	\N	1000.00	unit	t	\N
55	2	BOOSTER	\N	1000.00	unit	t	\N
56	2	BOOSTER CANNETTE	\N	1500.00	unit	t	\N
57	2	BAVARIA	\N	1500.00	unit	t	\N
58	2	G GUINNESS	\N	2000.00	unit	t	\N
59	2	P GUINNESS	\N	1000.00	unit	t	\N
60	2	MALTA	\N	1000.00	unit	t	\N
61	2	ICE BLACK	\N	1000.00	unit	t	\N
62	2	ICE PINEAPPLE	\N	1000.00	unit	t	\N
63	2	SMOOTH	\N	1500.00	unit	t	\N
64	2	ORIGIN	\N	1000.00	unit	t	\N
65	2	HARP	\N	1000.00	unit	t	\N
66	2	BEAUFORT	\N	1000.00	unit	t	\N
67	2	KADJI	\N	1000.00	unit	t	\N
68	2	CASTLE	\N	1000.00	unit	t	\N
69	2	RED BULL	\N	1500.00	unit	t	\N
70	2	DOPPLE	\N	1000.00	unit	t	\N
71	2	HEINEKEN	\N	1500.00	unit	t	\N
72	2	1664	\N	1500.00	unit	t	\N
73	2	SKOLL	\N	1500.00	unit	t	\N
74	2	VK BLUE	\N	1500.00	unit	t	\N
75	2	DJINO	\N	1000.00	unit	t	\N
76	2	VIMTO	\N	1000.00	unit	t	\N
77	2	WATER 1.5L	\N	1000.00	unit	t	\N
78	2	WATER 0.5L	\N	500.00	unit	t	\N
79	2	TONI	\N	1000.00	unit	t	\N
80	2	COCACOLA PM	\N	500.00	unit	t	\N
81	2	COCA COLA GM	\N	1000.00	unit	t	\N
82	2	UCB PAMPLEMOUSSE	\N	1000.00	unit	t	\N
83	2	GRENADINE	\N	1000.00	unit	t	\N
84	2	YOUZOU	\N	1000.00	unit	t	\N
85	2	MANGUE	\N	2000.00	unit	t	\N
86	2	ANANA GINGEMBRE	\N	2000.00	unit	t	\N
87	2	ANANA PASSION	\N	2000.00	unit	t	\N
88	2	BAOBA	\N	2000.00	unit	t	\N
89	2	CASSIMANGO	\N	2000.00	unit	t	\N
90	2	GOYAVE	\N	2000.00	unit	t	\N
91	2	COCKTAIL	\N	2000.00	unit	t	\N
92	2	COFFEE	\N	1000.00	unit	t	\N
93	2	TEA	\N	1000.00	unit	t	\N
94	2	ROBINSON (WHITE)	\N	10000.00	unit	t	\N
95	2	LOUIS ESCHENAUER (WHITE)	\N	10000.00	unit	t	\N
96	2	BALLART DE GUEST (WHITE)	\N	10000.00	unit	t	\N
97	2	SANDARA (WHITE)	\N	10000.00	unit	t	\N
98	2	ISABELLE DE FRANCE (WHITE)	\N	7000.00	unit	t	\N
99	2	DOMAINE OLIVER (WHITE)	\N	7000.00	unit	t	\N
100	2	VIEUX MOULIN (WHITE)	\N	7000.00	unit	t	\N
101	2	BALLART DE GUEST (RED)	\N	12000.00	unit	t	\N
102	2	ROBINSON (RED)	\N	10000.00	unit	t	\N
103	2	CHATEAU BARREYRES	\N	25000.00	unit	t	\N
104	2	CALVET GRAND RESERVE	\N	15000.00	unit	t	\N
105	2	ROCHE MAZET	\N	12000.00	unit	t	\N
106	2	LOUIS ESCHENAUER (RED)	\N	12000.00	unit	t	\N
107	2	CARRILLONADE	\N	12000.00	unit	t	\N
108	2	JP CHENET (RED)	\N	10000.00	unit	t	\N
109	2	CALVET (RED)	\N	10000.00	unit	t	\N
110	2	VIEUX MOULIN (RED)	\N	7000.00	unit	t	\N
111	2	JP CHENET (CHAMPAGNE)	\N	15000.00	unit	t	\N
112	2	MOSCATO	\N	15000.00	unit	t	\N
113	2	MOET ICE	\N	80000.00	unit	t	\N
114	2	MOET BRUT	\N	55000.00	unit	t	\N
115	2	VEUVE CLICQUOT	\N	70000.00	unit	t	\N
116	2	RUINART BRUT	\N	75000.00	unit	t	\N
117	2	RUINART BLANC	\N	80000.00	unit	t	\N
118	2	RUINART ROSE	\N	100000.00	unit	t	\N
119	2	DON PERIGNON	\N	100000.00	unit	t	\N
120	2	CRYSTAL	\N	100000.00	unit	t	\N
121	2	RIGNAC	\N	100000.00	unit	t	\N
122	2	BAILEYS	\N	20000.00	unit	t	\N
123	2	MARTINI	\N	20000.00	unit	t	\N
124	2	CAMPARI	\N	20000.00	unit	t	\N
125	2	BLUE CURACAO	\N	20000.00	unit	t	\N
126	2	ABSOLUT VODKA	\N	20000.00	unit	t	\N
127	2	VODKA BELVEDERE	\N	50000.00	unit	t	\N
128	2	CHIVAS 18	\N	80000.00	unit	t	\N
129	2	LANTAIN	\N	20000.00	unit	t	\N
130	2	CHIVAS 12	\N	35000.00	unit	t	\N
131	2	GOLD LABEL	\N	70000.00	unit	t	\N
132	2	MONKEY SHOULDER	\N	40000.00	unit	t	\N
133	2	BLACK LABEL	\N	35000.00	unit	t	\N
134	2	SINGLETON	\N	45000.00	unit	t	\N
135	2	GLENFIDDICH 12	\N	45000.00	unit	t	\N
136	2	JACK DANIELS	\N	30000.00	unit	t	\N
137	2	JACK DANIELS HONEY	\N	30000.00	unit	t	\N
138	2	HENNESSY	\N	40000.00	unit	t	\N
9999	2	Manual Payment	MANUAL-PAYMENT	0.00	SERVICE	t	\N
\.


--
-- Data for Name: billable_unit_taxonomy; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.billable_unit_taxonomy (atomic_unit_id, taxonomy_node_id) FROM stdin;
\.


--
-- Data for Name: branches; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.branches (id, tenant_id, branch_code, name, city, address, is_active, created_at, updated_at) FROM stdin;
1	2	BR001	Head Office	\N	\N	t	2025-12-10 13:15:49.947708	\N
2	3	BR001	Head Office	\N	\N	t	2025-12-10 14:07:50.372926	\N
3	4	BR001	Head Office	\N	\N	t	2025-12-10 14:10:34.348438	\N
4	3	BR002	Logpom Branch	\N	\N	t	2025-12-10 14:12:31.315533	\N
\.


--
-- Data for Name: inventory_items; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.inventory_items (id, tenant_id, branch_id, atomic_unit_id, quantity_on_hand, reorder_level, created_at) FROM stdin;
\.


--
-- Data for Name: inventory_movements; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.inventory_movements (id, tenant_id, branch_id, inventory_item_id, atomic_unit_id, quantity_delta, movement_type, source, reference_type, reference_id, created_at) FROM stdin;
\.


--
-- Data for Name: payment_attempts; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.payment_attempts (id, payment_intent_id, sale_id, method, provider, settlement_mode, amount, status, client_reference, callback_reference, gateway_reference, provider_reference, cashier_id, provider_meta, created_at, completed_at, meta) FROM stdin;
5	12	202	xafpay	tranzak	async	4000.00	succeeded	5df25d22-0ec8-48d5-a0df-1706b28d8c84	\N	\N	\N	\N	\N	2026-03-02 10:42:37.408575-05	\N	{"event": "payment.unknown", "currency": "XAF", "occurred_at": "2026-03-02T10:42:37.408565", "merchant_reference": null}
51	13	203	xafpay	tranzak	async	5500.00	succeeded	26fa9527-2188-4015-b853-87687cb36f1d	\N	\N	\N	\N	\N	2026-03-02 10:43:56.145645-05	\N	{"event": "payment.unknown", "currency": "XAF", "occurred_at": "2026-03-02T10:43:56.145635", "merchant_reference": null}
52	15	205	xafpay	tranzak	async	2500.00	succeeded	37372432-b7c2-4f9d-82fe-5a7026661f3c	\N	\N	\N	\N	\N	2026-03-02 10:46:16.316341-05	\N	{"event": "payment.unknown", "currency": "XAF", "occurred_at": "2026-03-02T10:46:16.316315", "merchant_reference": null}
53	14	204	xafpay	tranzak	async	7500.00	succeeded	c68657ad-5198-4986-a535-82d86323b306	\N	\N	\N	\N	\N	2026-03-02 10:48:16.519764-05	\N	{"event": "payment.unknown", "currency": "XAF", "occurred_at": "2026-03-02T10:48:16.519746", "merchant_reference": null}
54	6	195	xafpay	tranzak	async	16500.00	succeeded	036b1cba-41d2-4e16-ac29-c86ea762325b	\N	\N	\N	\N	\N	2026-03-02 10:50:11.630219-05	\N	{"event": "payment.unknown", "currency": "XAF", "occurred_at": "2026-03-02T10:50:11.630194", "merchant_reference": null}
55	16	206	xafpay	tranzak	async	10500.00	succeeded	dd265bdc-3117-4464-a682-400fa74caf1d	\N	\N	\N	\N	\N	2026-03-02 10:54:41.986338-05	\N	{"event": "payment.unknown", "currency": "XAF", "occurred_at": "2026-03-02T10:54:41.986328", "merchant_reference": null}
56	7	196	xafpay	tranzak	async	3000.00	succeeded	83e98513-7022-4e3c-a213-6d8f0a53b942	\N	\N	\N	\N	\N	2026-03-02 11:06:17.970099-05	\N	{"event": "payment.unknown", "currency": "XAF", "occurred_at": "2026-03-02T11:06:17.970086", "merchant_reference": null}
57	4	193	xafpay	tranzak	async	1500.00	succeeded	13f23732-e441-4f64-b61d-b4501544d5f4	\N	\N	\N	\N	\N	2026-03-02 11:14:13.70283-05	\N	{"event": "payment.unknown", "currency": "XAF", "occurred_at": "2026-03-02T11:14:13.702819", "merchant_reference": null}
58	8	197	xafpay	tranzak	async	2500.00	succeeded	fdd144cf-d995-4a9f-b604-d40819ee61d2	\N	\N	\N	\N	\N	2026-03-02 11:32:35.383819-05	\N	{"event": "payment.unknown", "currency": "XAF", "occurred_at": "2026-03-02T11:32:35.383807", "merchant_reference": null}
59	27	221	xafpay	tranzak	async	8500.00	succeeded	e77f4b27-950e-44e7-b598-bd8447d1c352	\N	\N	\N	\N	\N	2026-03-03 07:00:14.438582-05	\N	{"event": "payment.unknown", "currency": "XAF", "occurred_at": "2026-03-03T07:00:14.434126", "merchant_reference": null}
60	28	222	xafpay	tranzak	async	7500.00	succeeded	41ac2f05-556c-42f2-b164-55f3e709006b	\N	\N	\N	\N	\N	2026-03-03 07:03:34.659335-05	\N	{"event": "payment.unknown", "currency": "XAF", "occurred_at": "2026-03-03T07:03:34.658326", "merchant_reference": null}
61	29	223	cash	pos	manual	7500.00	succeeded	sale-cash:2:1:223	\N	\N	\N	\N	\N	2026-03-03 07:24:06.608233-05	\N	{"change_amount": "0", "unpaid_amount": "0", "tendered_total": "0"}
62	38	232	orange	\N	manual	10000.00	succeeded	04a270ce-575c-4b9b-ace6-bdb12b4135d0:line:0:orange	\N	\N	\N	\N	\N	2026-03-03 11:52:09.982075-05	\N	{}
63	39	233	orange	\N	manual	10000.00	succeeded	35bc7f14-facb-48c0-9e10-a4acd0a8304b:line:0:orange	\N	\N	\N	\N	\N	2026-03-03 11:58:17.183029-05	\N	{}
64	40	234	cash	\N	manual	5000.00	succeeded	6a0caff5-4af3-4124-a767-17b2caa6d7af:line:0:cash	\N	\N	\N	\N	\N	2026-03-03 12:00:23.372544-05	\N	{"received": 5000, "split_change_due": 0, "split_change_owed": 0, "customerLeftChange": false, "split_change_given_now": 0}
65	41	235	cash	\N	manual	1000.00	succeeded	5fb98aca-d934-4383-b681-a60db55350e7:line:0:cash	\N	\N	\N	\N	\N	2026-03-03 12:27:55.745764-05	\N	{"received": 1000, "split_change_due": 0, "split_change_owed": 0, "customerLeftChange": false, "split_change_given_now": 0}
66	42	236	mtn	\N	manual	6000.00	succeeded	3499c88f-4639-4eaa-a133-151fe1d30e7e:line:0:mtn	\N	\N	\N	\N	\N	2026-03-03 12:33:20.742831-05	\N	{"due": 6000}
67	43	237	cash	\N	manual	4000.00	succeeded	pos-settle:237:75ec4271-35d2-4c15-8039-ea6807535a96:line:0:cash	\N	\N	\N	\N	\N	2026-03-03 13:37:06.456113-05	\N	{"received": 4000, "split_change_due": 0, "split_change_owed": 0, "customerLeftChange": false, "split_change_given_now": 0}
68	44	238	cash	\N	manual	4000.00	succeeded	pos-settle:238:713f3633-6862-4236-9c03-c38fa04f1678:line:0:cash	\N	\N	\N	\N	\N	2026-03-03 13:50:54.647454-05	\N	{"received": 4000, "split_change_due": 0, "split_change_owed": 0, "customerLeftChange": false, "split_change_given_now": 0}
69	45	239	cash	\N	manual	15000.00	succeeded	pos-settle:239:b0bb91a7-c559-4e12-a320-53dea0b57337:line:0:cash	\N	\N	\N	\N	\N	2026-03-03 13:59:26.237548-05	\N	{"received": 15000, "split_change_due": 0, "split_change_owed": 0, "customerLeftChange": false, "split_change_given_now": 0}
72	47	241	cash	\N	manual	1000.00	succeeded	ps:241:0:cash:01a104365867f72c	\N	\N	\N	\N	\N	2026-03-03 16:54:25.7848-05	\N	{"received": 1000, "split_change_due": 0, "split_change_owed": 0, "customerLeftChange": false, "split_change_given_now": 0}
73	47	241	mtn	\N	manual	3000.00	succeeded	ps:241:1:mtn:3abf84f6411139c9	\N	\N	\N	\N	\N	2026-03-03 16:54:25.785755-05	\N	{}
74	47	241	orange	\N	manual	2000.00	succeeded	ps:241:2:orange:a1a9b13c7a354527	\N	\N	\N	\N	\N	2026-03-03 16:54:25.786515-05	\N	{}
75	48	242	cash	\N	manual	1000.00	succeeded	ps:242:0:cash:a6d7cbaef199a2ea	\N	\N	\N	\N	\N	2026-03-03 17:14:01.862489-05	\N	{"received": 1000, "split_change_due": 0, "split_change_owed": 0, "customerLeftChange": false, "split_change_given_now": 0}
76	48	242	mtn	\N	manual	3000.00	succeeded	ps:242:1:mtn:f64ee8a38e88fa45	\N	\N	\N	\N	\N	2026-03-03 17:14:01.863272-05	\N	{}
77	48	242	orange	\N	manual	2000.00	succeeded	ps:242:2:orange:f5efed8fbf6ab5c3	\N	\N	\N	\N	\N	2026-03-03 17:14:01.864-05	\N	{}
78	49	243	cash	\N	manual	1000.00	succeeded	ps:243:0:cash:38aa8dc20d6f9449	\N	\N	\N	\N	\N	2026-03-03 17:34:56.825905-05	\N	{"received": 1000, "split_change_due": 0, "split_change_owed": 0, "customerLeftChange": false, "split_change_given_now": 0}
79	49	243	mtn	\N	manual	3000.00	succeeded	ps:243:1:mtn:7a93124962cfbbfb	\N	\N	\N	\N	\N	2026-03-03 17:34:56.826525-05	\N	{}
80	49	243	orange	\N	manual	2000.00	succeeded	ps:243:2:orange:ea1b031d54a3e530	\N	\N	\N	\N	\N	2026-03-03 17:34:56.827179-05	\N	{}
81	50	244	cash	\N	manual	1000.00	succeeded	ps:244:0:cash:c05ca9a1383c744c	\N	\N	\N	\N	\N	2026-03-04 07:34:45.103767-05	\N	{"received": 1000, "split_change_due": 0, "split_change_owed": 0, "customerLeftChange": false, "split_change_given_now": 0}
82	50	244	mtn	\N	manual	3000.00	succeeded	ps:244:1:mtn:1d34d591bc08224e	\N	\N	\N	\N	\N	2026-03-04 07:34:45.104574-05	\N	{}
83	50	244	orange	\N	manual	2000.00	succeeded	ps:244:2:orange:157cf0df07400d3a	\N	\N	\N	\N	\N	2026-03-04 07:34:45.105327-05	\N	{}
84	51	245	cash	\N	manual	1000.00	succeeded	ps:245:0:cash:ee0813db8b418bab	\N	\N	\N	\N	\N	2026-03-04 07:45:55.233841-05	\N	{"received": 1000, "split_change_due": 0, "split_change_owed": 0, "customerLeftChange": false, "split_change_given_now": 0}
85	51	245	mtn	\N	manual	3000.00	succeeded	ps:245:1:mtn:3ef4189f755f73c1	\N	\N	\N	\N	\N	2026-03-04 07:45:55.234428-05	\N	{}
86	51	245	orange	\N	manual	2000.00	succeeded	ps:245:2:orange:7a522105af8dbcc8	\N	\N	\N	\N	\N	2026-03-04 07:45:55.234869-05	\N	{}
87	52	246	cash	\N	manual	1000.00	succeeded	ps:246:0:cash:edbbf082b6a0863a	\N	\N	\N	\N	\N	2026-03-04 07:51:13.943022-05	\N	{"received": 1000, "split_change_due": 0, "split_change_owed": 0, "customerLeftChange": false, "split_change_given_now": 0}
88	52	246	mtn	\N	manual	3000.00	succeeded	ps:246:1:mtn:3fbc86afdad9cede	\N	\N	\N	\N	\N	2026-03-04 07:51:13.943991-05	\N	{}
89	52	246	orange	\N	manual	2000.00	succeeded	ps:246:2:orange:3dee5bcc4c6fc99d	\N	\N	\N	\N	\N	2026-03-04 07:51:13.944712-05	\N	{}
90	53	247	cash	\N	manual	2000.00	succeeded	ps:247:0:cash:d6347501aa386738	\N	\N	\N	\N	\N	2026-03-04 11:05:37.278225-05	\N	{"received": 2000, "split_change_due": 0, "split_change_owed": 0, "customerLeftChange": false, "split_change_given_now": 0}
91	53	247	mtn	\N	manual	4000.00	succeeded	ps:247:1:mtn:0248f1e680f99412	\N	\N	\N	\N	\N	2026-03-04 11:05:37.27889-05	\N	{}
92	53	247	orange	\N	manual	3000.00	succeeded	ps:247:2:orange:4aa7cd2b3aed25ce	\N	\N	\N	\N	\N	2026-03-04 11:05:37.279411-05	\N	{}
93	54	248	cash	\N	manual	5000.00	succeeded	ps:248:0:cash:3921a4d09950f4b0	\N	\N	\N	\N	\N	2026-03-04 11:43:08.72082-05	\N	{"received": 5000, "split_change_due": 0, "split_change_owed": 0, "customerLeftChange": false, "split_change_given_now": 0}
94	54	248	mtn	\N	manual	10000.00	succeeded	ps:248:1:mtn:cdefcaf1469368ab	\N	\N	\N	\N	\N	2026-03-04 11:43:08.722419-05	\N	{}
95	54	248	orange	\N	manual	10000.00	succeeded	ps:248:2:orange:56439b7d12c3f974	\N	\N	\N	\N	\N	2026-03-04 11:43:08.723984-05	\N	{}
96	55	249	cash	\N	manual	1000.00	succeeded	ps:249:0:cash:4dcc97af2c8afb67	\N	\N	\N	\N	\N	2026-03-04 12:37:25.616714-05	\N	{}
97	56	250	cash	\N	manual	10500.00	succeeded	ps:250:0:cash:d4124a7470861250	\N	\N	\N	\N	\N	2026-03-04 12:42:20.752837-05	\N	{}
98	57	251	xafpay	mtn	manual	5000.00	succeeded	ps:251:0:xafpay:d860c07c4634ad4b	\N	\N	\N	\N	\N	2026-03-04 12:47:03.079178-05	\N	{}
99	58	252	cash	\N	manual	5000.00	succeeded	ps:252:0:cash:8507fcb7108bff78	\N	\N	\N	\N	\N	2026-03-04 14:13:09.443064-05	\N	{}
100	60	254	cash	\N	manual	10000.00	succeeded	ps:254:0:cash:bc167f7a679e9545	\N	\N	\N	\N	\N	2026-03-04 14:32:28.174961-05	\N	{"due": 10000, "change": 10000, "applied": 10000.0, "received": 20000, "tendered": 20000.0}
101	61	255	cash	\N	manual	10000.00	succeeded	ps:255:0:cash:b424f3904a51aefd	\N	\N	\N	\N	\N	2026-03-04 14:33:31.513821-05	\N	{"due": 10000, "change": 10000, "applied": 10000.0, "received": 20000, "tendered": 20000.0}
102	62	256	cash	\N	manual	14000.00	succeeded	ps:256:0:cash:e541ba7768104f44	\N	\N	\N	\N	\N	2026-03-04 14:35:21.350239-05	\N	{"due": 14000, "change": 6000, "applied": 14000.0, "received": 20000, "tendered": 20000.0}
103	63	257	cash	\N	manual	9000.00	succeeded	ps:257:0:cash:6710932caadf8068	\N	\N	\N	\N	\N	2026-03-05 07:44:01.615003-05	\N	{"due": 9000, "change": 1000, "applied": 9000, "received": 10000, "tendered": 10000}
104	64	258	cash	\N	manual	15500.00	succeeded	ps:258:0:cash:a5933e3886b242a8	\N	\N	\N	\N	\N	2026-03-05 07:47:38.760361-05	\N	{"due": 15500, "change": 4500, "applied": 15500, "received": 20000, "tendered": 20000}
105	65	259	cash	\N	manual	15500.00	succeeded	ps:259:0:cash:86e02236a1f06db6	\N	\N	\N	\N	\N	2026-03-05 07:48:40.364335-05	\N	{"due": 15500, "change": 4500, "applied": 15500.0, "received": 20000, "tendered": 20000.0}
106	66	260	cash	\N	manual	15500.00	succeeded	ps:260:0:cash:f0099204c029e93b	\N	\N	\N	\N	\N	2026-03-05 07:49:40.199428-05	\N	{"due": 15500, "change": 4500, "applied": 15500, "received": 20000, "tendered": 20000}
107	67	261	cash	\N	manual	15500.00	succeeded	ps:261:0:cash:0773faaac4bd1de4	\N	\N	\N	\N	\N	2026-03-05 07:57:23.138104-05	\N	{"due": 15500, "change": 4500, "applied": 15500, "received": 20000, "tendered": 20000}
108	68	262	cash	\N	manual	1000.00	succeeded	ps:262:0:cash:b9fc1ac1244ee0d4	\N	\N	\N	\N	\N	2026-03-05 08:18:01.906633-05	\N	{"change": 0, "applied": 1000, "received": 1000, "tendered": 1000, "split_change_due": 0, "split_change_owed": 0, "customerLeftChange": false, "split_change_given_now": 0}
109	68	262	mtn	\N	manual	3000.00	succeeded	ps:262:1:mtn:1f57917d60a3b7e2	\N	\N	\N	\N	\N	2026-03-05 08:18:01.907116-05	\N	{"applied": 3000}
110	68	262	orange	\N	manual	2000.00	succeeded	ps:262:2:orange:10aab0a0977437d2	\N	\N	\N	\N	\N	2026-03-05 08:18:01.907582-05	\N	{"applied": 2000}
111	69	263	cash	\N	manual	6000.00	succeeded	ps:263:0:cash:8a7b1af0b15cd334	\N	\N	\N	\N	\N	2026-03-05 08:19:10.054294-05	\N	{"due": 7500, "change": 0, "applied": 6000, "received": 6000, "tendered": 6000}
112	70	264	cash	\N	manual	7500.00	succeeded	ps:264:0:cash:d2293295e77fde07	\N	\N	\N	\N	\N	2026-03-05 08:20:10.453441-05	\N	{"due": 7500, "change": 2500, "applied": 7500, "received": 10000, "tendered": 10000}
113	71	265	cash	\N	manual	6000.00	succeeded	ps:265:0:cash:da19ac36c0bd1331	\N	\N	\N	\N	\N	2026-03-05 08:21:40.160677-05	\N	{"due": 7500, "change": 0, "applied": 6000, "received": 6000, "tendered": 6000}
114	72	266	cash	\N	manual	7500.00	succeeded	ps:266:0:cash:01142d89aaf325da	\N	\N	\N	\N	\N	2026-03-05 08:22:24.057844-05	\N	{"change": 2500, "applied": 7500, "received": 10000, "tendered": 10000, "split_change_due": 0, "split_change_owed": 0, "customerLeftChange": false, "split_change_given_now": 0}
115	73	267	cash	\N	manual	7000.00	succeeded	ps:267:0:cash:2093488f8ff84b8f	\N	\N	\N	\N	\N	2026-03-05 08:26:21.706801-05	\N	{"change": 0, "applied": 7000, "received": 7000, "tendered": 7000, "split_change_due": 500, "split_change_owed": 500, "customerLeftChange": false, "split_change_given_now": 0}
116	73	267	orange	\N	manual	1000.00	succeeded	ps:267:1:orange:39f0831699f05b21	\N	\N	\N	\N	\N	2026-03-05 08:26:21.70731-05	\N	{"applied": 1000}
117	74	268	cash	\N	manual	7500.00	succeeded	ps:268:0:cash:bddf176585ebfc7d	\N	\N	\N	\N	\N	2026-03-05 08:27:52.031948-05	\N	{"due": 7500, "change": 2500, "applied": 7500, "received": 10000, "tendered": 10000}
118	75	269	cash	\N	manual	6000.00	succeeded	ps:269:0:cash:d141b0f2f820b63b	\N	\N	\N	\N	\N	2026-03-05 08:28:09.608826-05	\N	{"due": 7500, "change": 0, "applied": 6000, "received": 6000, "tendered": 6000}
119	76	270	cash	\N	manual	7000.00	succeeded	ps:270:0:cash:a910469fcc4884ce	\N	\N	\N	\N	\N	2026-03-05 08:29:10.110422-05	\N	{"change": 0, "applied": 7000, "received": 7000, "tendered": 7000, "split_change_due": 500, "split_change_owed": 500, "customerLeftChange": false, "split_change_given_now": 0}
120	76	270	orange	\N	manual	1000.00	succeeded	ps:270:1:orange:85254aff9e053a17	\N	\N	\N	\N	\N	2026-03-05 08:29:10.111176-05	\N	{"applied": 1000}
121	77	271	cash	\N	manual	7500.00	succeeded	ps:271:0:cash:2e2eb3acfdb6efdc	\N	\N	\N	\N	\N	2026-03-05 08:39:40.127483-05	\N	{"due": 7500, "change": 2500, "applied": 7500, "received": 10000, "tendered": 10000}
122	78	272	cash	\N	manual	3000.00	succeeded	ps:272:0:cash:3406731eeafdef05	\N	\N	\N	\N	\N	2026-03-05 08:40:04.470615-05	\N	{"change": 0, "applied": 3000, "received": 3000, "tendered": 3000, "split_change_due": 0, "split_change_owed": 0, "customerLeftChange": false, "split_change_given_now": 0}
123	78	272	orange	\N	manual	3000.00	succeeded	ps:272:1:orange:947a301de4be07f4	\N	\N	\N	\N	\N	2026-03-05 08:40:04.471176-05	\N	{"applied": 3000}
124	79	273	cash	\N	manual	15500.00	succeeded	ps:273:0:cash:3220fe369b824e83	\N	\N	\N	\N	\N	2026-03-05 10:13:03.442036-05	\N	{"due": 15500, "change": 4500, "applied": 15500, "received": 20000, "tendered": 20000}
125	80	274	cash	\N	manual	10000.00	succeeded	ps:274:0:cash:d548e91642d03683	\N	\N	\N	\N	\N	2026-03-05 10:14:54.789031-05	\N	{"due": 15500, "change": 0, "applied": 10000, "received": 10000, "tendered": 10000}
160	106	300	xafpay	mtn	manual	17500.00	succeeded	ps:300:0:xafpay:df08446bfa7026fd	\N	\N	\N	\N	\N	2026-03-08 11:10:03.449561-04	\N	{"due": 17500, "phone": "258258258", "applied": 17500}
126	81	275	cash	\N	manual	2000.00	succeeded	ps:275:0:cash:e3ea6d9d44874006	\N	\N	\N	\N	\N	2026-03-05 10:16:12.042327-05	\N	{"change": 0, "applied": 2000, "received": 2000, "tendered": 2000, "split_change_due": 0, "split_change_owed": 0, "customerLeftChange": false, "split_change_given_now": 0}
127	81	275	mtn	\N	manual	3000.00	succeeded	ps:275:1:mtn:e41df9ee39a9a975	\N	\N	\N	\N	\N	2026-03-05 10:16:12.044468-05	\N	{"applied": 3000}
128	81	275	orange	\N	manual	1000.00	succeeded	ps:275:2:orange:8732d85f6d3c67f2	\N	\N	\N	\N	\N	2026-03-05 10:16:12.046422-05	\N	{"applied": 1000}
129	82	276	cash	\N	manual	3000.00	succeeded	ps:276:0:cash:bf16b7ad15d39c33	\N	\N	\N	\N	\N	2026-03-05 10:20:38.682131-05	\N	{"change": 0, "applied": 3000, "received": 3000, "tendered": 3000, "split_change_due": 0, "split_change_owed": 0, "customerLeftChange": false, "split_change_given_now": 0}
130	82	276	mtn	\N	manual	4000.00	succeeded	ps:276:1:mtn:5b61c9992f51de4a	\N	\N	\N	\N	\N	2026-03-05 10:20:38.683672-05	\N	{"applied": 4000}
131	82	276	orange	\N	manual	2000.00	succeeded	ps:276:2:orange:72d546e855c6e657	\N	\N	\N	\N	\N	2026-03-05 10:20:38.685271-05	\N	{"applied": 2000}
132	83	277	xafpay	mtn	manual	15500.00	succeeded	ps:277:0:xafpay:b7ca71ab47980279	\N	\N	\N	\N	\N	2026-03-05 10:37:41.441513-05	\N	{"due": 15500, "phone": "677123456", "applied": 15500}
134	85	279	cash	\N	manual	500.00	succeeded	ps:279:0:cash:c6baeadc2f691c59	\N	\N	\N	\N	\N	2026-03-05 18:32:09.500493-05	\N	{"change": 0, "applied": 500, "received": 500, "tendered": 500, "split_change_due": 0, "split_change_owed": 0, "customerLeftChange": false, "split_change_given_now": 0}
135	85	279	mtn	\N	manual	4000.00	succeeded	ps:279:1:mtn:9c4f1778f65c146b	\N	\N	\N	\N	\N	2026-03-05 18:32:09.507017-05	\N	{"applied": 4000}
136	85	279	orange	\N	manual	1000.00	succeeded	ps:279:2:orange:a002458770d3a1fc	\N	\N	\N	\N	\N	2026-03-05 18:32:09.510654-05	\N	{"applied": 1000}
137	86	280	cash	\N	manual	6500.00	succeeded	ps:280:0:cash:67c4982ef22d2c34	\N	\N	\N	\N	\N	2026-03-05 18:36:03.461796-05	\N	{"due": 6500, "change": 3500, "applied": 6500, "received": 10000, "tendered": 10000}
138	87	281	cash	\N	manual	50000.00	succeeded	ps:281:0:cash:725a9ade76742a76	\N	\N	\N	\N	\N	2026-03-06 06:30:15.611017-05	\N	{"change": 0, "applied": 50000, "received": 50000, "tendered": 50000, "split_change_due": 0, "split_change_owed": 0, "customerLeftChange": false, "split_change_given_now": 0}
139	87	281	mtn	\N	manual	2000.00	succeeded	ps:281:1:mtn:98a27808a77e133a	\N	\N	\N	\N	\N	2026-03-06 06:30:15.629957-05	\N	{"applied": 2000}
140	87	281	orange	\N	manual	1000.00	succeeded	ps:281:2:orange:f8cf1d54ca461f9c	\N	\N	\N	\N	\N	2026-03-06 06:30:15.633464-05	\N	{"applied": 1000}
141	89	283	cash	\N	manual	1500.00	succeeded	ps:283:0:cash:0e0c64e15d712dd7	\N	\N	\N	\N	\N	2026-03-06 21:33:33.776646-05	\N	{"due": 1500, "change": 0, "applied": 1500, "received": 1500, "tendered": 1500}
142	91	285	mtn	\N	manual	1000.00	succeeded	ps:285:0:mtn:b59d078e424386f3	\N	\N	\N	\N	\N	2026-03-06 22:23:05.731029-05	\N	{"due": 1000, "applied": 1000}
143	92	286	cash	\N	manual	1000.00	succeeded	ps:286:0:cash:40575faa471f85f0	\N	\N	\N	\N	\N	2026-03-07 07:07:50.737807-05	\N	{"due": 1000, "change": 0, "applied": 1000, "received": 1000, "tendered": 1000}
144	93	287	mtn	\N	manual	3000.00	succeeded	ps:287:0:mtn:e8e08648f393a5f6	\N	\N	\N	\N	\N	2026-03-07 07:13:18.21834-05	\N	{"due": 3000, "applied": 3000}
145	94	288	mtn	\N	manual	21000.00	succeeded	ps:288:0:mtn:8feadbeb4a93bde9	\N	\N	\N	\N	\N	2026-03-07 07:28:19.956957-05	\N	{"due": 21000, "applied": 21000}
146	95	289	cash	\N	manual	22000.00	succeeded	ps:289:0:cash:0ca871c1d189b5e4	\N	\N	\N	\N	\N	2026-03-07 07:28:55.069212-05	\N	{"due": 22000, "change": 0, "applied": 22000, "received": 22000, "tendered": 22000}
147	96	290	cash	\N	manual	5.00	succeeded	ps:290:0:cash:7d1b0e9bba174628	\N	\N	\N	\N	\N	2026-03-07 08:00:22.315261-05	\N	{"change": 0, "applied": 5, "received": 5, "tendered": 5, "split_change_due": 0, "split_change_owed": 0, "customerLeftChange": false, "split_change_given_now": 0}
148	97	291	cash	\N	manual	4500.00	succeeded	ps:291:0:cash:c956042227488a4e	\N	\N	\N	\N	\N	2026-03-07 10:13:58.067988-05	\N	{"due": 4500, "change": 0, "applied": 4500, "received": 4500, "tendered": 4500}
149	99	293	cash	\N	manual	4500.00	succeeded	ps:293:0:cash:e17e5bf7b75a67dd	\N	\N	\N	\N	\N	2026-03-08 10:28:03.011741-04	\N	{"change": 500, "applied": 4500, "received": 5000, "tendered": 5000, "split_change_due": 0, "split_change_owed": 0, "customerLeftChange": false, "split_change_given_now": 0}
150	100	294	cash	\N	manual	500.00	succeeded	ps:294:0:cash:c22ef6e576e55265	\N	\N	\N	\N	\N	2026-03-08 10:28:54.595864-04	\N	{"change": 0, "applied": 500, "received": 500, "tendered": 500, "split_change_due": 0, "split_change_owed": 0, "customerLeftChange": false, "split_change_given_now": 0}
151	101	295	cash	\N	manual	2000.00	succeeded	ps:295:0:cash:f62e2fd589cd48d0	\N	\N	\N	\N	\N	2026-03-08 10:33:41.19174-04	\N	{"change": 0, "applied": 2000, "received": 2000, "tendered": 2000, "split_change_due": 0, "split_change_owed": 0, "customerLeftChange": false, "split_change_given_now": 0}
152	102	296	cash	\N	manual	1000.00	succeeded	ps:296:0:cash:ffed0f4d9b8d6a33	\N	\N	\N	\N	\N	2026-03-08 10:40:28.78499-04	\N	{"change": 0, "applied": 1000, "received": 1000, "tendered": 1000, "split_change_due": 0, "split_change_owed": 0, "customerLeftChange": false, "split_change_given_now": 0}
153	103	297	cash	\N	manual	1000.00	succeeded	ps:297:0:cash:ca5ec73ec4d6b7f6	\N	\N	\N	\N	\N	2026-03-08 10:58:24.972752-04	\N	{"change": 0, "applied": 1000, "received": 1000, "tendered": 1000, "split_change_due": 0, "split_change_owed": 0, "customerLeftChange": false, "split_change_given_now": 0}
154	103	297	mtn	\N	manual	1500.00	succeeded	ps:297:1:mtn:3b694103f650190e	\N	\N	\N	\N	\N	2026-03-08 10:58:24.979885-04	\N	{"applied": 1500}
155	103	297	orange	\N	manual	500.00	succeeded	ps:297:2:orange:024060cb3b643aa7	\N	\N	\N	\N	\N	2026-03-08 10:58:24.993013-04	\N	{"applied": 500}
156	104	298	cash	\N	manual	4500.00	succeeded	ps:298:0:cash:2ee2325d1e610706	\N	\N	\N	\N	\N	2026-03-08 11:00:07.526181-04	\N	{"due": 4500, "change": 500, "applied": 4500, "received": 5000, "tendered": 5000}
157	105	299	cash	\N	manual	2000.00	succeeded	ps:299:0:cash:8ba6bac08358c7d0	\N	\N	\N	\N	\N	2026-03-08 11:02:34.826959-04	\N	{"change": 0, "applied": 2000, "received": 2000, "tendered": 2000, "split_change_due": 0, "split_change_owed": 0, "customerLeftChange": false, "split_change_given_now": 0}
158	105	299	mtn	\N	manual	3000.00	succeeded	ps:299:1:mtn:613bb4a4e50354c9	\N	\N	\N	\N	\N	2026-03-08 11:02:34.851445-04	\N	{"applied": 3000}
159	105	299	orange	\N	manual	1000.00	succeeded	ps:299:2:orange:6efaebd2fc9b6050	\N	\N	\N	\N	\N	2026-03-08 11:02:34.862394-04	\N	{"applied": 1000}
161	116	310	cash	\N	manual	8000.00	succeeded	ps:310:0:cash:8fac814cf0074698	\N	\N	\N	\N	\N	2026-03-09 17:25:44.348666-04	\N	{"due": 8000, "change": 0, "applied": 8000, "received": 8000, "tendered": 8000}
162	117	311	cash	\N	manual	10000.00	succeeded	ps:311:0:cash:ea4204d896ee452d	\N	\N	\N	\N	\N	2026-03-09 17:28:55.970267-04	\N	{"due": 10000, "change": 0, "applied": 10000, "received": 10000, "tendered": 10000}
163	118	312	mtn	\N	manual	5000.00	succeeded	ps:312:0:mtn:a4760f3a35e62d38	\N	\N	\N	\N	\N	2026-03-10 08:21:38.168293-04	\N	{"due": 5000, "applied": 5000}
164	120	314	cash	\N	manual	5000.00	succeeded	ps:314:0:cash:63ab096f19b57f3d	\N	\N	\N	\N	\N	2026-03-10 14:41:46.922191-04	\N	{"due": 5000, "change": 0, "applied": 5000, "received": 5000, "tendered": 5000}
165	121	315	cash	\N	manual	5000.00	succeeded	ps:315:0:cash:75f37338ce4b5cd6	\N	\N	\N	\N	\N	2026-03-10 14:46:31.530277-04	\N	{"due": 5000, "change": 0, "applied": 5000, "received": 5000, "tendered": 5000}
\.


--
-- Data for Name: payment_intents; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.payment_intents (id, tenant_id, branch_id, payable_type, payable_id, currency, amount, status, created_by_user_id, channel, total_paid, balance_due, created_at, updated_at, gateway_intent_id, meta) FROM stdin;
13	2	1	sale	203	XAF	5500.00	processing	1	xafpay	0.00	5500.00	2026-03-02 05:12:08.874833-05	2026-03-02 05:12:08.874833-05	3377ba38-a615-4337-adf2-76df7d1ed74f	{"rail": "mtn", "sale_id": 203}
1	2	1	sale	190	XAF	9000.00	pending	1	xafpay	0.00	9000.00	2026-02-28 12:34:46.725519-05	2026-02-28 12:34:46.725519-05	6e8ecf13-7782-4cfd-8ab5-73ba025eb5ca	{"rail": "mtn", "sale_id": 190}
15	2	1	sale	205	XAF	2500.00	processing	1	xafpay	0.00	2500.00	2026-03-02 05:30:28.589433-05	2026-03-02 05:30:28.589433-05	0ea003ef-63fd-4200-87b4-9fdf57dfa019	{"rail": "mtn", "sale_id": 205}
14	2	1	sale	204	XAF	7500.00	processing	1	xafpay	0.00	7500.00	2026-03-02 05:16:33.053386-05	2026-03-02 05:16:33.053386-05	0456cfb2-ed94-47c9-b4ef-e4f9050651e5	{"rail": "mtn", "sale_id": 204}
6	2	1	sale	195	XAF	16500.00	processing	1	xafpay	0.00	16500.00	2026-03-01 14:45:53.853483-05	2026-03-01 14:45:53.853483-05	24cd3e9e-ed5e-4540-b730-7af5f4b459cc	{"rail": "mtn", "sale_id": 195}
16	2	1	sale	206	XAF	10500.00	processing	1	xafpay	0.00	10500.00	2026-03-02 05:53:42.471716-05	2026-03-02 05:53:42.471716-05	1036255e-2ef0-42ce-b4ef-2351467d70e2	{"rail": "mtn", "sale_id": 206}
7	2	1	sale	196	XAF	3000.00	processing	1	xafpay	0.00	3000.00	2026-03-01 14:52:51.188487-05	2026-03-01 14:52:51.188487-05	c8d4552d-6d8a-4668-a75c-1abbf2110da4	{"rail": "mtn", "sale_id": 196}
4	2	1	sale	193	XAF	1500.00	processing	1	xafpay	0.00	1500.00	2026-03-01 14:07:34.190961-05	2026-03-01 14:07:34.190961-05	773b01a8-4e43-4000-ac96-2806d096df1f	{"rail": "mtn", "sale_id": 193}
8	2	1	sale	197	XAF	2500.00	processing	1	xafpay	0.00	2500.00	2026-03-02 04:24:36.267735-05	2026-03-02 04:24:36.267735-05	526a348d-7cc1-46d2-8026-dada202f3e6e	{"rail": "mtn", "sale_id": 197}
17	2	1	sale	211	XAF	10500.00	pending	1	pos	0.00	10500.00	2026-03-02 12:13:17.20387-05	2026-03-02 12:13:17.20387-05	\N	{"source": "SaleService.create_sale", "receipt_no": "R-0201-0326-00021", "payment_method_intent": "cash"}
18	2	1	sale	212	XAF	12500.00	pending	1	pos	0.00	12500.00	2026-03-02 12:18:36.265299-05	2026-03-02 12:18:36.265299-05	\N	{"source": "SaleService.create_sale", "receipt_no": "R-0201-0326-00022", "payment_method_intent": "cash"}
19	2	1	sale	213	XAF	6000.00	pending	1	pos	0.00	6000.00	2026-03-02 13:10:37.854875-05	2026-03-02 13:10:37.854875-05	\N	{"source": "SaleService.create_sale", "receipt_no": "R-0201-0326-00023", "payment_method_intent": "cash"}
20	2	1	sale	214	XAF	8500.00	pending	1	pos	0.00	8500.00	2026-03-02 14:08:46.458706-05	2026-03-02 14:08:46.458706-05	\N	{"source": "SaleService.create_sale", "receipt_no": "R-0201-0326-00024", "payment_method_intent": "cash"}
21	2	1	sale	215	XAF	5500.00	pending	1	pos	0.00	5500.00	2026-03-02 14:17:31.05174-05	2026-03-02 14:17:31.05174-05	\N	{"source": "SaleService.create_sale", "receipt_no": "R-0201-0326-00025", "payment_method_intent": "cash"}
22	2	1	sale	216	XAF	10000.00	pending	1	pos	0.00	10000.00	2026-03-02 22:59:15.260758-05	2026-03-02 17:59:15.227727-05	\N	{"source": "SaleService.create_sale", "receipt_no": "R-0201-0326-00026", "initial_payment_method": "cash"}
23	2	1	sale	217	XAF	9500.00	pending	1	pos	0.00	9500.00	2026-03-02 23:01:04.590348-05	2026-03-02 18:01:04.567997-05	\N	{"source": "SaleService.create_sale", "receipt_no": "R-0201-0326-00027", "initial_payment_method": "cash"}
24	2	1	sale	218	XAF	22500.00	pending	1	pos	0.00	22500.00	2026-03-02 23:05:05.960328-05	2026-03-02 18:05:05.927556-05	\N	{"source": "SaleService.create_sale", "receipt_no": "R-0201-0326-00028", "initial_payment_method": "cash"}
25	2	1	sale	219	XAF	5500.00	pending	1	pos	0.00	5500.00	2026-03-03 06:46:31.460993-05	2026-03-03 01:46:31.449038-05	\N	{"source": "SaleService.create_sale", "receipt_no": "R-0201-0326-00029", "initial_payment_method": "cash"}
26	2	1	sale	220	XAF	5500.00	pending	1	pos	0.00	5500.00	2026-03-03 06:49:20.909831-05	2026-03-03 01:49:20.901867-05	\N	{"source": "SaleService.create_sale", "receipt_no": "R-0201-0326-00030", "initial_payment_method": "cash"}
27	2	1	sale	221	XAF	8500.00	processing	1	pos	0.00	8500.00	2026-03-03 06:59:17.798632-05	2026-03-03 01:59:17.788808-05	e945f647-ee55-4dd5-a009-48f6a6bd3e64	{"source": "SaleService.create_sale", "receipt_no": "R-0201-0326-00031", "initial_payment_method": "xafpay"}
28	2	1	sale	222	XAF	7500.00	processing	1	pos	0.00	7500.00	2026-03-03 07:02:33.57593-05	2026-03-03 02:02:33.563836-05	657c5adf-f4f0-4a0e-a4c9-317d8a1ca3c8	{"source": "SaleService.create_sale", "receipt_no": "R-0201-0326-00032", "initial_payment_method": "xafpay"}
12	2	1	sale	202	XAF	4000.00	processing	1	xafpay	0.00	4000.00	2026-03-02 05:06:58.147865-05	2026-03-02 05:06:58.147865-05	3cbcd3cb-0205-42c5-a2c7-13dfc5216078	{"rail": "mtn", "sale_id": 202}
29	2	1	sale	223	XAF	7500.00	processing	1	pos	0.00	7500.00	2026-03-03 07:24:06.590737-05	2026-03-03 02:24:06.560078-05	\N	{"source": "SaleService.create_sale", "net_total": "7500.00", "receipt_no": "R-0201-0326-00033", "gross_total": "7500.00", "change_amount": "0", "unpaid_amount": "0", "discount_total": "0", "tendered_total": "0", "discount_reason": null, "complimentary_total": "0", "paid_amount_expected": "7500.00", "initial_payment_method": "cash"}
30	2	1	sale	224	XAF	2500.00	pending	1	pos	0.00	2500.00	2026-03-03 08:02:18.51492-05	2026-03-03 03:02:18.45062-05	\N	{"source": "SaleService.create_sale", "receipt_no": "R-0201-0326-00034", "gross_total": 2500.0, "client_total": 2500.0, "discount_total": 0.0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
31	2	1	sale	225	XAF	5000.00	pending	1	pos	0.00	5000.00	2026-03-03 08:04:01.549146-05	2026-03-03 03:04:01.498505-05	\N	{"source": "SaleService.create_sale", "receipt_no": "R-0201-0326-00035", "gross_total": 5000.0, "client_total": 5000.0, "discount_total": 0.0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
32	2	1	sale	226	XAF	8000.00	pending	1	pos	0.00	8000.00	2026-03-03 09:39:29.2466-05	2026-03-03 04:39:29.196843-05	\N	{"source": "SaleService.create_sale", "receipt_no": "R-0201-0326-00036", "gross_total": 8000.0, "client_total": 8000.0, "discount_total": 0.0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
33	2	1	sale	227	XAF	11000.00	pending	1	pos	0.00	11000.00	2026-03-03 10:29:26.56116-05	2026-03-03 05:29:26.534844-05	\N	{"source": "SaleService.create_sale", "receipt_no": "R-0201-0326-00037", "gross_total": 11000.0, "client_total": 11000.0, "discount_total": 0.0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
34	2	1	sale	228	XAF	5500.00	pending	1	pos	0.00	5500.00	2026-03-03 10:31:48.584159-05	2026-03-03 05:31:48.566088-05	\N	{"source": "SaleService.create_sale", "receipt_no": "R-0201-0326-00038", "gross_total": 5500.0, "client_total": 5500.0, "discount_total": 0.0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
35	2	1	sale	229	XAF	5500.00	pending	1	pos	0.00	5500.00	2026-03-03 10:34:35.205702-05	2026-03-03 05:34:35.185278-05	\N	{"source": "SaleService.create_sale", "receipt_no": "R-0201-0326-00039", "gross_total": 5500.0, "client_total": 5500.0, "discount_total": 0.0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
36	2	1	sale	230	XAF	25500.00	pending	1	pos	0.00	25500.00	2026-03-03 10:37:46.650956-05	2026-03-03 05:37:46.596306-05	\N	{"source": "SaleService.create_sale", "receipt_no": "R-0201-0326-00040", "gross_total": 25500.0, "client_total": 25500.0, "discount_total": 0.0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
37	2	1	sale	231	XAF	10000.00	pending	1	pos	0.00	10000.00	2026-03-03 11:50:10.117734-05	2026-03-03 06:50:10.080408-05	\N	{"source": "SaleService.create_sale", "net_total": 10000.0, "receipt_no": "R-0201-0326-00041", "gross_total": 10000.0, "discount_total": 0.0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
38	2	1	sale	232	XAF	15500.00	pending	1	pos	0.00	15500.00	2026-03-03 11:52:09.948272-05	2026-03-03 06:52:09.9272-05	\N	{"source": "SaleService.create_sale", "net_total": 15500.0, "receipt_no": "R-0201-0326-00042", "gross_total": 15500.0, "unpaid_total": 4500.0, "discount_total": 0.0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
39	2	1	sale	233	XAF	12500.00	pending	1	pos	0.00	12500.00	2026-03-03 11:58:17.134159-05	2026-03-03 06:58:17.107718-05	\N	{"source": "SaleService.create_sale", "net_total": 12500.0, "receipt_no": "R-0201-0326-00043", "gross_total": 12500.0, "unpaid_total": 2000.0, "discount_total": 0.0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
40	2	1	sale	234	XAF	7000.00	pending	1	pos	0.00	7000.00	2026-03-03 12:00:23.35679-05	2026-03-03 07:00:23.344204-05	\N	{"source": "SaleService.create_sale", "net_total": 7000.0, "receipt_no": "R-0201-0326-00044", "gross_total": 7000.0, "unpaid_total": 1500.0, "discount_total": 0.0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
41	2	1	sale	235	XAF	2500.00	pending	1	pos	0.00	2500.00	2026-03-03 12:27:55.714757-05	2026-03-03 07:27:55.697834-05	\N	{"source": "SaleService.create_sale", "net_total": 2500.0, "receipt_no": "R-0201-0326-00045", "gross_total": 2500.0, "unpaid_total": 1500.0, "discount_total": 0.0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
42	2	1	sale	236	XAF	6000.00	pending	1	pos	0.00	6000.00	2026-03-03 12:33:20.727584-05	2026-03-03 07:33:20.719692-05	\N	{"source": "SaleService.create_sale", "net_total": 6000.0, "receipt_no": "R-0201-0326-00046", "gross_total": 6000.0, "discount_total": 0.0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
43	2	1	sale	237	XAF	9000.00	pending	1	pos	0.00	9000.00	2026-03-03 13:37:06.308927-05	2026-03-03 08:37:06.21651-05	\N	{"source": "SaleService.create_sale", "net_total": 9000.0, "receipt_no": "R-0201-0326-00047", "gross_total": 9000.0, "unpaid_total": 4500.0, "discount_total": 0.0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
44	2	1	sale	238	XAF	11500.00	pending	1	pos	0.00	11500.00	2026-03-03 13:50:54.584399-05	2026-03-03 08:50:54.524539-05	\N	{"source": "SaleService.create_sale", "net_total": 11500.0, "receipt_no": "R-0201-0326-00048", "gross_total": 11500.0, "unpaid_total": 6000.0, "discount_total": 0.0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
45	2	1	sale	239	XAF	20000.00	pending	1	pos	0.00	20000.00	2026-03-03 13:59:26.223337-05	2026-03-03 08:59:26.201668-05	\N	{"source": "SaleService.create_sale", "net_total": 20000.0, "receipt_no": "R-0201-0326-00049", "gross_total": 20000.0, "unpaid_total": 5000.0, "discount_total": 0.0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
46	2	1	sale	240	XAF	9500.00	pending	1	pos	0.00	9500.00	2026-03-03 16:35:36.027712-05	2026-03-03 11:35:36.010869-05	\N	{"source": "SaleService.create_sale", "net_total": 9500.0, "receipt_no": "R-0201-0326-00050", "gross_total": 9500.0, "discount_total": 0.0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
47	2	1	sale	241	XAF	8000.00	pending	1	pos	0.00	8000.00	2026-03-03 16:54:25.747523-05	2026-03-03 11:54:25.72075-05	\N	{"source": "SaleService.create_sale", "net_total": 8000.0, "receipt_no": "R-0201-0326-00051", "gross_total": 8000.0, "unpaid_total": 1500.0, "discount_total": 0.0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
48	2	1	sale	242	XAF	17500.00	pending	1	pos	0.00	17500.00	2026-03-03 17:14:01.844879-05	2026-03-03 12:14:01.821788-05	\N	{"source": "SaleService.create_sale", "net_total": 17500.0, "receipt_no": "R-0201-0326-00052", "gross_total": 17500.0, "unpaid_total": 8000.0, "discount_total": 0.0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
49	2	1	sale	243	XAF	16000.00	pending	1	pos	0.00	16000.00	2026-03-03 17:34:56.807375-05	2026-03-03 12:34:56.777297-05	\N	{"source": "SaleService.create_sale", "net_total": 16000.0, "receipt_no": "R-0201-0326-00053", "gross_total": 16000.0, "unpaid_total": 7500.0, "discount_total": 0.0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
50	2	1	sale	244	XAF	12500.00	pending	1	pos	0.00	12500.00	2026-03-04 07:34:45.035148-05	2026-03-04 02:34:44.985571-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 12500.0, "receipt_no": "R-0201-0326-00054", "gross_total": 12500, "unpaid_notes": [], "unpaid_total": 5000.0, "change_amount": 0.0, "discount_total": 500, "tendered_total": 11000.0, "discount_reason": "Manager override", "has_store_credit": false, "complimentary_items": [], "complimentary_total": 1000, "store_credit_amount": 0, "initial_payment_method": "cash"}
51	2	1	sale	245	XAF	12500.00	pending	1	pos	0.00	12500.00	2026-03-04 07:45:55.217438-05	2026-03-04 02:45:55.202719-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 12500.0, "receipt_no": "R-0201-0326-00055", "gross_total": 12500, "unpaid_notes": [], "unpaid_total": 5000.0, "change_amount": 0.0, "discount_total": 500, "tendered_total": 11000.0, "discount_reason": "Manager override", "has_store_credit": false, "complimentary_items": [], "complimentary_total": 1000, "store_credit_amount": 0, "initial_payment_method": "cash"}
52	2	1	sale	246	XAF	14000.00	pending	1	pos	0.00	14000.00	2026-03-04 07:51:13.892629-05	2026-03-04 02:51:13.866488-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 17000.0, "receipt_no": "R-0201-0326-00056", "gross_total": 17000, "unpaid_notes": [], "unpaid_total": 8000.0, "change_amount": 0.0, "discount_total": 500, "tendered_total": 14000.0, "discount_reason": "Manager override", "has_store_credit": false, "complimentary_items": [], "complimentary_total": 2500, "store_credit_amount": 0, "initial_payment_method": "cash"}
53	2	1	sale	247	XAF	15000.00	processing	1	pos	9000.00	6000.00	2026-03-04 11:05:37.212792-05	2026-03-04 06:05:37.179978-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 15000.0, "receipt_no": "R-0201-0326-00057", "gross_total": 17000.0, "unpaid_notes": [], "unpaid_total": 6000.0, "change_amount": 0.0, "discount_total": 500.0, "tendered_total": 15000.0, "discount_reason": "Manager override", "has_store_credit": false, "complimentary_items": [], "complimentary_total": 1500.0, "store_credit_amount": 0, "initial_payment_method": "cash"}
54	2	1	sale	248	XAF	31500.00	processing	1	pos	25000.00	6500.00	2026-03-04 11:43:08.699912-05	2026-03-04 06:43:08.668881-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 31500.0, "receipt_no": "R-0201-0326-00058", "gross_total": 38500.0, "unpaid_notes": [], "unpaid_total": 6500.0, "change_amount": 0.0, "discount_total": 5000.0, "tendered_total": 31500.0, "discount_reason": "Manager override", "has_store_credit": false, "complimentary_items": [], "complimentary_total": 2000.0, "store_credit_amount": 0, "initial_payment_method": "cash"}
55	2	1	sale	249	XAF	1000.00	succeeded	1	pos	1000.00	0.00	2026-03-04 12:37:25.502947-05	2026-03-04 07:37:25.469178-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 1000.0, "accounting": {"cash_movement": 1000.0, "sales_revenue": 1500.0, "discount_expense": 500.0, "accounts_receivable": 0.0, "complimentary_expense": 0.0}, "receipt_no": "R-0201-0326-00059", "gross_total": 1500.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 0.0, "discount_total": 500.0, "tendered_total": 1000.0, "discount_reason": "Manager override", "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0, "initial_payment_method": "cash"}
56	2	1	sale	250	XAF	10500.00	succeeded	1	pos	10500.00	0.00	2026-03-04 12:42:20.714491-05	2026-03-04 07:42:20.69915-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 10500.0, "accounting": {"cash_movement": 10500.0, "sales_revenue": 10500.0, "discount_expense": 0.0, "accounts_receivable": 0.0, "complimentary_expense": 0.0}, "receipt_no": "R-0201-0326-00060", "gross_total": 10500.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 10500.0, "discount_reason": null, "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0, "initial_payment_method": "cash"}
57	2	1	sale	251	XAF	5000.00	succeeded	1	pos	5000.00	0.00	2026-03-04 12:47:03.034618-05	2026-03-04 07:47:03.022029-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 5000.0, "accounting": {"cash_movement": 5000.0, "sales_revenue": 5000.0, "discount_expense": 0.0, "accounts_receivable": 0.0, "complimentary_expense": 0.0}, "receipt_no": "R-0201-0326-00061", "gross_total": 5000.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 5000.0, "discount_reason": null, "payment_methods": ["xafpay"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0, "initial_payment_method": "cash"}
58	2	1	sale	252	XAF	5000.00	succeeded	1	pos	5000.00	0.00	2026-03-04 14:13:09.40148-05	2026-03-04 09:13:09.382796-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 5000.0, "accounting": {"cash_movement": 5000.0, "sales_revenue": 5500.0, "discount_expense": 500.0, "accounts_receivable": 0.0, "complimentary_expense": 0.0}, "receipt_no": "R-0201-0326-00062", "gross_total": 5500.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 0.0, "discount_total": 500.0, "tendered_total": 5000.0, "discount_reason": "Manager override", "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0, "initial_payment_method": "cash"}
59	2	1	sale	253	XAF	6500.00	pending	1	pos	0.00	6500.00	2026-03-04 14:24:40.376233-05	2026-03-04 09:24:40.330249-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 6500.0, "receipt_no": "R-0201-0326-00063", "gross_total": 6500.0, "unpaid_notes": [], "change_amount": 0, "discount_total": 0.0, "tendered_total": 0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
60	2	1	sale	254	XAF	10000.00	succeeded	1	pos	10000.00	0.00	2026-03-04 14:32:28.043473-05	2026-03-04 09:32:27.966851-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 10000.0, "accounting": {"discount_expense": 500.0, "cash_movement_total": 10000.0, "sales_revenue_gross": 10500.0, "complimentary_expense": 0.0, "accounts_receivable_delta": 0.0}, "receipt_no": "R-0201-0326-00064", "gross_total": 10500.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 0.0, "discount_total": 500.0, "tendered_total": 10000.0, "discount_reason": "Manager override", "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0, "initial_payment_method": "cash"}
61	2	1	sale	255	XAF	10000.00	succeeded	1	pos	10000.00	0.00	2026-03-04 14:33:31.47069-05	2026-03-04 09:33:31.426374-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 10000.0, "accounting": {"discount_expense": 500.0, "cash_movement_total": 10000.0, "sales_revenue_gross": 10500.0, "complimentary_expense": 0.0, "accounts_receivable_delta": 0.0}, "receipt_no": "R-0201-0326-00065", "gross_total": 10500.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 0.0, "discount_total": 500.0, "tendered_total": 10000.0, "discount_reason": "Manager override", "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0, "initial_payment_method": "cash"}
62	2	1	sale	256	XAF	14000.00	succeeded	1	pos	14000.00	0.00	2026-03-04 14:35:21.306135-05	2026-03-04 09:35:21.255484-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 14000.0, "accounting": {"discount_expense": 500.0, "cash_movement_total": 14000.0, "sales_revenue_gross": 14500.0, "complimentary_expense": 0.0, "accounts_receivable_delta": 0.0}, "receipt_no": "R-0201-0326-00066", "gross_total": 14500.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 0.0, "discount_total": 500.0, "tendered_total": 14000.0, "discount_reason": "Manager override", "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0, "initial_payment_method": "cash"}
63	2	1	sale	257	XAF	9000.00	processing	1	pos	9000.00	9000.00	2026-03-05 07:44:01.548385-05	2026-03-05 02:44:01.512952-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 9000.0, "accounting": {"cash_movement": 9000.0, "discount_expense": 0.0, "accounts_receivable": 9000.0, "sales_revenue_gross": 9000.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00067", "gross_total": 9000.0, "unpaid_notes": [], "unpaid_total": 9000.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 9000.0, "discount_reason": null, "payment_methods": ["cash"], "has_store_credit": false, "invariant_warning": "paid(9000)+due(9000)!=net(9000)", "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash"}
64	2	1	sale	258	XAF	15500.00	processing	1	pos	15500.00	15500.00	2026-03-05 07:47:38.730841-05	2026-03-05 02:47:38.718857-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 15500.0, "accounting": {"cash_movement": 15500.0, "discount_expense": 0.0, "accounts_receivable": 15500.0, "sales_revenue_gross": 15500.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00068", "gross_total": 15500.0, "unpaid_notes": [], "unpaid_total": 15500.0, "change_amount": 4500.0, "discount_total": 0.0, "tendered_total": 20000.0, "discount_reason": null, "payment_methods": ["cash"], "has_store_credit": false, "invariant_warning": "paid(15500)+due(15500)!=net(15500)", "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash"}
65	2	1	sale	259	XAF	15500.00	succeeded	1	pos	15500.00	0.00	2026-03-05 07:48:40.320998-05	2026-03-05 02:48:40.295875-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 15500.0, "accounting": {"discount_expense": 0.0, "cash_movement_total": 15500.0, "sales_revenue_gross": 15500.0, "complimentary_expense": 0.0, "accounts_receivable_delta": 0.0}, "receipt_no": "R-0201-0326-00069", "gross_total": 15500.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 4500.0, "discount_total": 0.0, "tendered_total": 20000.0, "discount_reason": null, "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0, "initial_payment_method": "cash"}
66	2	1	sale	260	XAF	15500.00	processing	1	pos	15500.00	15500.00	2026-03-05 07:49:40.163095-05	2026-03-05 02:49:40.141207-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 15500.0, "accounting": {"cash_movement": 15500.0, "discount_expense": 0.0, "accounts_receivable": 15500.0, "sales_revenue_gross": 15500.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00070", "gross_total": 15500.0, "unpaid_notes": [], "unpaid_total": 15500.0, "change_amount": 4500.0, "discount_total": 0.0, "tendered_total": 20000.0, "discount_reason": null, "payment_methods": ["cash"], "has_store_credit": false, "invariant_warning": "paid(15500)+due(15500)!=net(15500)", "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash"}
67	2	1	sale	261	XAF	15500.00	succeeded	1	pos	15500.00	0.00	2026-03-05 07:57:23.099495-05	2026-03-05 02:57:23.080412-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 15500.0, "accounting": {"cash_movement": 15500.0, "discount_expense": 0.0, "accounts_receivable": 0.0, "sales_revenue_gross": 15500.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00071", "gross_total": 15500.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 4500.0, "discount_total": 0.0, "tendered_total": 20000.0, "discount_reason": null, "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 15500.0}
68	2	1	sale	262	XAF	7500.00	processing	1	pos	6000.00	1500.00	2026-03-05 08:18:01.887107-05	2026-03-05 03:18:01.876968-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 7500.0, "accounting": {"cash_movement": 6000.0, "discount_expense": 0.0, "accounts_receivable": 1500.0, "sales_revenue_gross": 7500.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00072", "gross_total": 7500.0, "unpaid_notes": [], "unpaid_total": 1500.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 7500.0, "discount_reason": null, "payment_methods": ["cash", "mtn", "orange"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 1500.0}
69	2	1	sale	263	XAF	7500.00	processing	1	pos	6000.00	1500.00	2026-03-05 08:19:10.028765-05	2026-03-05 03:19:10.01848-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 7500.0, "accounting": {"cash_movement": 6000.0, "discount_expense": 0.0, "accounts_receivable": 1500.0, "sales_revenue_gross": 7500.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00073", "gross_total": 7500.0, "unpaid_notes": [], "unpaid_total": 1500.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 6000.0, "discount_reason": null, "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 7500.0}
70	2	1	sale	264	XAF	7500.00	succeeded	1	pos	7500.00	0.00	2026-03-05 08:20:10.435749-05	2026-03-05 03:20:10.426677-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 7500.0, "accounting": {"cash_movement": 7500.0, "discount_expense": 0.0, "accounts_receivable": 0.0, "sales_revenue_gross": 7500.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00074", "gross_total": 7500.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 2500.0, "discount_total": 0.0, "tendered_total": 10000.0, "discount_reason": null, "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 7500.0}
71	2	1	sale	265	XAF	7500.00	processing	1	pos	6000.00	1500.00	2026-03-05 08:21:40.142935-05	2026-03-05 03:21:40.131997-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 7500.0, "accounting": {"cash_movement": 6000.0, "discount_expense": 0.0, "accounts_receivable": 1500.0, "sales_revenue_gross": 7500.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00075", "gross_total": 7500.0, "unpaid_notes": [], "unpaid_total": 1500.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 6000.0, "discount_reason": null, "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 7500.0}
72	2	1	sale	266	XAF	7500.00	succeeded	1	pos	7500.00	0.00	2026-03-05 08:22:24.040607-05	2026-03-05 03:22:24.031404-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 7500.0, "accounting": {"cash_movement": 7500.0, "discount_expense": 0.0, "accounts_receivable": 0.0, "sales_revenue_gross": 7500.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00076", "gross_total": 7500.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 2500.0, "discount_total": 0.0, "tendered_total": 10000.0, "discount_reason": null, "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 0.0}
73	2	1	sale	267	XAF	7500.00	succeeded	1	pos	8000.00	0.00	2026-03-05 08:26:21.690748-05	2026-03-05 03:26:21.681196-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 7500.0, "accounting": {"cash_movement": 8000.0, "discount_expense": 0.0, "accounts_receivable": 0.0, "sales_revenue_gross": 7500.0, "complimentary_expense": 0.0, "store_credit_liability": 500.0}, "receipt_no": "R-0201-0326-00077", "gross_total": 7500.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 8500.0, "discount_reason": null, "payment_methods": ["cash", "orange"], "has_store_credit": true, "invariant_warning": "paid(8000)+due(0)!=net(7500)", "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 500.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 0.0}
74	2	1	sale	268	XAF	7500.00	succeeded	1	pos	7500.00	0.00	2026-03-05 08:27:52.014363-05	2026-03-05 03:27:52.004538-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 7500.0, "accounting": {"cash_movement": 7500.0, "discount_expense": 0.0, "accounts_receivable": 0.0, "sales_revenue_gross": 7500.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00078", "gross_total": 7500.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 7500.0, "discount_reason": null, "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 0.0}
75	2	1	sale	269	XAF	7500.00	processing	1	pos	6000.00	1500.00	2026-03-05 08:28:09.592086-05	2026-03-05 03:28:09.58343-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 7500.0, "accounting": {"cash_movement": 6000.0, "discount_expense": 0.0, "accounts_receivable": 1500.0, "sales_revenue_gross": 7500.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00079", "gross_total": 7500.0, "unpaid_notes": [], "unpaid_total": 1500.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 6000.0, "discount_reason": null, "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 7500.0}
76	2	1	sale	270	XAF	7500.00	succeeded	1	pos	8000.00	0.00	2026-03-05 08:29:10.094725-05	2026-03-05 03:29:10.085226-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 7500.0, "accounting": {"cash_movement": 8000.0, "discount_expense": 0.0, "accounts_receivable": 0.0, "sales_revenue_gross": 7500.0, "complimentary_expense": 0.0, "store_credit_liability": 500.0}, "receipt_no": "R-0201-0326-00080", "gross_total": 7500.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 8500.0, "discount_reason": null, "payment_methods": ["cash", "orange"], "has_store_credit": true, "invariant_warning": "paid(8000)+due(0)!=net(7500)", "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 500.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 0.0}
77	2	1	sale	271	XAF	7500.00	succeeded	1	pos	7500.00	0.00	2026-03-05 08:39:40.107564-05	2026-03-05 03:39:40.093082-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 7500.0, "accounting": {"cash_movement": 7500.0, "discount_expense": 0.0, "accounts_receivable": 0.0, "sales_revenue_gross": 7500.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00081", "gross_total": 7500.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 2500.0, "discount_total": 0.0, "tendered_total": 10000.0, "discount_reason": null, "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 7500.0}
78	2	1	sale	272	XAF	7500.00	processing	1	pos	6000.00	1500.00	2026-03-05 08:40:04.454078-05	2026-03-05 03:40:04.444581-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 7500.0, "accounting": {"cash_movement": 6000.0, "discount_expense": 0.0, "accounts_receivable": 1500.0, "sales_revenue_gross": 7500.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00082", "gross_total": 7500.0, "unpaid_notes": [], "unpaid_total": 1500.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 6000.0, "discount_reason": null, "payment_methods": ["cash", "orange"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 1500.0}
89	2	1	sale	283	XAF	1500.00	succeeded	1	pos	1500.00	0.00	2026-03-06 21:33:33.673431-05	2026-03-06 16:33:33.6664-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 1500.0, "accounting": {"cash_movement": 1500.0, "discount_expense": 0.0, "accounts_receivable": 0.0, "sales_revenue_gross": 1500.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00092", "gross_total": 1500.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 1500.0, "discount_reason": null, "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 1500.0}
79	2	1	sale	273	XAF	15500.00	succeeded	1	pos	15500.00	0.00	2026-03-05 10:13:03.284406-05	2026-03-05 05:13:03.213854-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 15500.0, "accounting": {"cash_movement": 15500.0, "discount_expense": 0.0, "accounts_receivable": 0.0, "sales_revenue_gross": 15500.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00083", "gross_total": 15500.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 4500.0, "discount_total": 0.0, "tendered_total": 20000.0, "discount_reason": null, "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 15500.0}
80	2	1	sale	274	XAF	15500.00	processing	1	pos	10000.00	5500.00	2026-03-05 10:14:54.748942-05	2026-03-05 05:14:54.722205-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 15500.0, "accounting": {"cash_movement": 10000.0, "discount_expense": 0.0, "accounts_receivable": 5500.0, "sales_revenue_gross": 15500.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00084", "gross_total": 15500.0, "unpaid_notes": [], "unpaid_total": 5500.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 10000.0, "discount_reason": null, "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 15500.0}
81	2	1	sale	275	XAF	12500.00	processing	1	pos	6000.00	6500.00	2026-03-05 10:16:11.999982-05	2026-03-05 05:16:11.967254-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 12500.0, "accounting": {"cash_movement": 6000.0, "discount_expense": 500.0, "accounts_receivable": 6500.0, "sales_revenue_gross": 15500.0, "complimentary_expense": 2500.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00085", "gross_total": 15500.0, "unpaid_notes": [], "unpaid_total": 6500.0, "change_amount": 0.0, "discount_total": 500.0, "tendered_total": 6000.0, "discount_reason": "Manager override", "payment_methods": ["cash", "mtn", "orange"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 2500.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 6500.0}
82	2	1	sale	276	XAF	12500.00	processing	1	pos	9000.00	3500.00	2026-03-05 10:20:38.639378-05	2026-03-05 05:20:38.607601-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 12500.0, "accounting": {"cash_movement": 9000.0, "discount_expense": 500.0, "accounts_receivable": 3500.0, "sales_revenue_gross": 15500.0, "complimentary_expense": 2500.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00086", "gross_total": 15500.0, "unpaid_notes": [], "unpaid_total": 3500.0, "change_amount": 0.0, "discount_total": 500.0, "tendered_total": 9000.0, "discount_reason": "Manager override", "payment_methods": ["cash", "mtn", "orange"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 2500.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 3500.0}
83	2	1	sale	277	XAF	15500.00	succeeded	1	pos	15500.00	0.00	2026-03-05 10:37:41.394526-05	2026-03-05 05:37:41.363752-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 15500.0, "accounting": {"cash_movement": 15500.0, "discount_expense": 0.0, "accounts_receivable": 0.0, "sales_revenue_gross": 15500.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00087", "gross_total": 15500.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 15500.0, "discount_reason": null, "payment_methods": ["xafpay"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 15500.0}
84	2	1	sale	278	XAF	9000.00	pending	1	pos	0.00	9000.00	2026-03-05 18:14:17.082924-05	2026-03-05 13:14:17.02932-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 9000.0, "receipt_no": "R-0201-0326-00088", "gross_total": 9000.0, "unpaid_notes": [], "change_amount": 0, "discount_total": 0.0, "tendered_total": 0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
85	2	1	sale	279	XAF	6500.00	processing	1	pos	5500.00	1000.00	2026-03-05 18:32:09.458358-05	2026-03-05 13:32:09.437356-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 6500.0, "accounting": {"cash_movement": 5500.0, "discount_expense": 0.0, "accounts_receivable": 1000.0, "sales_revenue_gross": 6500.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00089", "gross_total": 6500.0, "unpaid_notes": [], "unpaid_total": 1000.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 6500.0, "discount_reason": null, "payment_methods": ["cash", "mtn", "orange"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 1000.0}
86	2	1	sale	280	XAF	6500.00	succeeded	1	pos	6500.00	0.00	2026-03-05 18:36:03.441973-05	2026-03-05 13:36:03.422995-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 6500.0, "accounting": {"cash_movement": 6500.0, "discount_expense": 0.0, "accounts_receivable": 0.0, "sales_revenue_gross": 6500.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00090", "gross_total": 6500.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 6500.0, "discount_reason": null, "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 6500.0}
90	2	1	sale	284	XAF	7500.00	pending	1	pos	0.00	7500.00	2026-03-06 21:35:03.082153-05	2026-03-06 16:35:03.068056-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 7500.0, "accounting": {"cash_movement": 0.0, "discount_expense": 0.0, "accounts_receivable": 7500.0, "sales_revenue_gross": 9000.0, "complimentary_expense": 1500.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00093", "gross_total": 9000.0, "unpaid_notes": [], "unpaid_total": 7500.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 0.0, "discount_reason": null, "payment_methods": [], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 1500.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 7500.0}
87	2	1	sale	281	XAF	55500.00	processing	1	pos	53000.00	2500.00	2026-03-06 06:30:15.517768-05	2026-03-06 01:30:15.410397-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 55500.0, "accounting": {"cash_movement": 53000.0, "discount_expense": 1500.0, "accounts_receivable": 2500.0, "sales_revenue_gross": 58000.0, "complimentary_expense": 1000.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00091", "gross_total": 58000.0, "unpaid_notes": [], "unpaid_total": 2500.0, "change_amount": 0.0, "discount_total": 1500.0, "tendered_total": 53000.0, "discount_reason": "Manager override", "payment_methods": ["cash", "mtn", "orange"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 1000.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 2500.0}
91	2	1	sale	285	XAF	1000.00	succeeded	1	pos	1000.00	0.00	2026-03-06 22:23:05.708589-05	2026-03-06 17:23:05.703139-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 1000.0, "accounting": {"cash_movement": 1000.0, "discount_expense": 0.0, "accounts_receivable": 0.0, "sales_revenue_gross": 1000.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00094", "gross_total": 1000.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 1000.0, "discount_reason": null, "payment_methods": ["mtn"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 1000.0}
92	2	1	sale	286	XAF	1000.00	succeeded	1	pos	1000.00	0.00	2026-03-07 07:07:50.709797-05	2026-03-07 02:07:50.693188-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 1000.0, "accounting": {"cash_movement": 1000.0, "discount_expense": 0.0, "accounts_receivable": 0.0, "sales_revenue_gross": 1000.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00095", "gross_total": 1000.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 1000.0, "discount_reason": null, "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 1000.0}
93	2	1	sale	287	XAF	3000.00	succeeded	1	pos	3000.00	0.00	2026-03-07 07:13:18.198498-05	2026-03-07 02:13:18.189433-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 3000.0, "accounting": {"cash_movement": 3000.0, "discount_expense": 0.0, "accounts_receivable": 0.0, "sales_revenue_gross": 3000.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00096", "gross_total": 3000.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 3000.0, "discount_reason": null, "payment_methods": ["mtn"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 3000.0}
94	2	1	sale	288	XAF	21000.00	succeeded	1	pos	21000.00	0.00	2026-03-07 07:28:19.930248-05	2026-03-07 02:28:19.903074-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 21000.0, "accounting": {"cash_movement": 21000.0, "discount_expense": 0.0, "accounts_receivable": 0.0, "sales_revenue_gross": 21000.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00097", "gross_total": 21000.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 21000.0, "discount_reason": null, "payment_methods": ["mtn"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 21000.0}
95	2	1	sale	289	XAF	22000.00	succeeded	1	pos	22000.00	0.00	2026-03-07 07:28:55.036218-05	2026-03-07 02:28:55.012469-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 22000.0, "accounting": {"cash_movement": 22000.0, "discount_expense": 0.0, "accounts_receivable": 0.0, "sales_revenue_gross": 23000.0, "complimentary_expense": 1000.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00098", "gross_total": 23000.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 22000.0, "discount_reason": null, "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 1000.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 22000.0}
96	2	1	sale	290	XAF	3500.00	processing	1	pos	5.00	3495.00	2026-03-07 08:00:22.282072-05	2026-03-07 03:00:22.269468-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 3500.0, "accounting": {"cash_movement": 5.0, "discount_expense": 0.0, "accounts_receivable": 3495.0, "sales_revenue_gross": 3500.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00099", "gross_total": 3500.0, "unpaid_notes": [], "unpaid_total": 3495.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 5.0, "discount_reason": null, "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 3495.0}
97	2	1	sale	291	XAF	4500.00	succeeded	1	pos	4500.00	0.00	2026-03-07 10:13:58.045276-05	2026-03-07 05:13:58.03545-05	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 4500.0, "accounting": {"cash_movement": 4500.0, "discount_expense": 0.0, "accounts_receivable": 0.0, "sales_revenue_gross": 4500.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00100", "gross_total": 4500.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 4500.0, "discount_reason": null, "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 4500.0}
98	2	1	sale	292	XAF	3500.00	pending	1	pos	0.00	3500.00	2026-03-08 07:48:34.385083-04	2026-03-08 03:48:34.316198-04	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 3500.0, "accounting": {"cash_movement": 0.0, "discount_expense": 0.0, "accounts_receivable": 3500.0, "sales_revenue_gross": 3500.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00101", "gross_total": 3500.0, "unpaid_notes": [], "unpaid_total": 3500.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 0.0, "discount_reason": null, "payment_methods": [], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 3500.0}
100	2	1	sale	294	XAF	2000.00	processing	1	pos	500.00	1500.00	2026-03-08 10:28:54.541414-04	2026-03-08 06:28:54.523116-04	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 2000.0, "accounting": {"cash_movement": 500.0, "discount_expense": 0.0, "accounts_receivable": 1500.0, "sales_revenue_gross": 2000.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00103", "gross_total": 2000.0, "unpaid_notes": [], "unpaid_total": 1500.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 500.0, "discount_reason": null, "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 1500.0}
107	2	1	sale	301	XAF	3500.00	pending	1	pos	0.00	3500.00	2026-03-08 12:11:16.540706-04	2026-03-08 08:11:16.522753-04	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 3500.0, "receipt_no": "R-0201-0326-00110", "gross_total": 3500.0, "unpaid_notes": [], "change_amount": 0, "discount_total": 0.0, "tendered_total": 0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
103	2	1	sale	297	XAF	4000.00	processing	1	pos	3000.00	1000.00	2026-03-08 10:58:24.896617-04	2026-03-08 06:58:24.869792-04	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 4000.0, "accounting": {"cash_movement": 3000.0, "discount_expense": 500.0, "accounts_receivable": 1000.0, "sales_revenue_gross": 4500.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00106", "gross_total": 4500.0, "unpaid_notes": [], "unpaid_total": 1000.0, "change_amount": 0.0, "discount_total": 500.0, "tendered_total": 3000.0, "discount_reason": "Manager override", "payment_methods": ["cash", "mtn", "orange"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 1000.0}
111	2	1	sale	305	XAF	1000.00	pending	1	pos	0.00	1000.00	2026-03-08 13:09:17.729992-04	2026-03-08 09:09:17.720742-04	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 1000.0, "receipt_no": "R-0201-0326-00114", "gross_total": 1000.0, "unpaid_notes": [], "change_amount": 0, "discount_total": 0.0, "tendered_total": 0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
105	2	1	sale	299	XAF	10500.00	processing	1	pos	6000.00	4500.00	2026-03-08 11:02:34.755668-04	2026-03-08 07:02:34.695189-04	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 10500.0, "accounting": {"cash_movement": 6000.0, "discount_expense": 4000.0, "accounts_receivable": 4500.0, "sales_revenue_gross": 17500.0, "complimentary_expense": 3000.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00108", "gross_total": 17500.0, "unpaid_notes": [], "unpaid_total": 4500.0, "change_amount": 0.0, "discount_total": 4000.0, "tendered_total": 6000.0, "discount_reason": "Manager override", "payment_methods": ["cash", "mtn", "orange"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 3000.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 4500.0}
114	2	1	sale	308	XAF	1500.00	pending	1	pos	0.00	1500.00	2026-03-08 13:35:59.728096-04	2026-03-08 09:35:59.72065-04	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 1500.0, "receipt_no": "R-0201-0326-00117", "gross_total": 1500.0, "unpaid_notes": [], "change_amount": 0, "discount_total": 0.0, "tendered_total": 0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
116	2	1	sale	310	XAF	8000.00	succeeded	1	pos	8000.00	0.00	2026-03-09 17:25:44.275787-04	2026-03-09 13:25:44.216713-04	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 8000.0, "accounting": {"cash_movement": 8000.0, "discount_expense": 0.0, "accounts_receivable": 0.0, "sales_revenue_gross": 8000.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00119", "gross_total": 8000.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 8000.0, "discount_reason": null, "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 8000.0}
99	2	1	sale	293	XAF	4500.00	succeeded	1	pos	4500.00	0.00	2026-03-08 10:28:02.943073-04	2026-03-08 06:28:02.905759-04	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 4500.0, "accounting": {"cash_movement": 4500.0, "discount_expense": 0.0, "accounts_receivable": 0.0, "sales_revenue_gross": 4500.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00102", "gross_total": 4500.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 500.0, "discount_total": 0.0, "tendered_total": 5000.0, "discount_reason": null, "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 0.0}
101	2	1	sale	295	XAF	3000.00	processing	1	pos	2000.00	1000.00	2026-03-08 10:33:41.143918-04	2026-03-08 06:33:41.117498-04	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 3000.0, "accounting": {"cash_movement": 2000.0, "discount_expense": 0.0, "accounts_receivable": 1000.0, "sales_revenue_gross": 3000.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00104", "gross_total": 3000.0, "unpaid_notes": [], "unpaid_total": 1000.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 2000.0, "discount_reason": null, "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 1000.0}
102	2	1	sale	296	XAF	2500.00	processing	1	pos	1000.00	1500.00	2026-03-08 10:40:28.74083-04	2026-03-08 06:40:28.724855-04	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 2500.0, "accounting": {"cash_movement": 1000.0, "discount_expense": 0.0, "accounts_receivable": 1500.0, "sales_revenue_gross": 2500.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00105", "gross_total": 2500.0, "unpaid_notes": [], "unpaid_total": 1500.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 1000.0, "discount_reason": null, "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 1500.0}
104	2	1	sale	298	XAF	4500.00	succeeded	1	pos	4500.00	0.00	2026-03-08 11:00:07.471728-04	2026-03-08 07:00:07.447666-04	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 4500.0, "accounting": {"cash_movement": 4500.0, "discount_expense": 0.0, "accounts_receivable": 0.0, "sales_revenue_gross": 4500.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00107", "gross_total": 4500.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 500.0, "discount_total": 0.0, "tendered_total": 5000.0, "discount_reason": null, "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 4500.0}
106	2	1	sale	300	XAF	17500.00	succeeded	1	pos	17500.00	0.00	2026-03-08 11:10:03.359472-04	2026-03-08 07:10:03.298066-04	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 17500.0, "accounting": {"cash_movement": 17500.0, "discount_expense": 0.0, "accounts_receivable": 0.0, "sales_revenue_gross": 17500.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00109", "gross_total": 17500.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 17500.0, "discount_reason": null, "payment_methods": ["xafpay"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 17500.0}
108	2	1	sale	302	XAF	3500.00	pending	1	pos	0.00	3500.00	2026-03-08 12:25:24.980803-04	2026-03-08 08:25:24.967863-04	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 3500.0, "receipt_no": "R-0201-0326-00111", "gross_total": 3500.0, "unpaid_notes": [], "change_amount": 0, "discount_total": 0.0, "tendered_total": 0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
109	2	1	sale	303	XAF	3500.00	pending	1	pos	0.00	3500.00	2026-03-08 13:00:34.562-04	2026-03-08 09:00:34.548229-04	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 3500.0, "receipt_no": "R-0201-0326-00112", "gross_total": 3500.0, "unpaid_notes": [], "change_amount": 0, "discount_total": 0.0, "tendered_total": 0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
110	2	1	sale	304	XAF	1000.00	pending	1	pos	0.00	1000.00	2026-03-08 13:08:50.897266-04	2026-03-08 09:08:50.889919-04	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 1000.0, "receipt_no": "R-0201-0326-00113", "gross_total": 1000.0, "unpaid_notes": [], "change_amount": 0, "discount_total": 0.0, "tendered_total": 0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
112	2	1	sale	306	XAF	1000.00	pending	1	pos	0.00	1000.00	2026-03-08 13:09:47.828224-04	2026-03-08 09:09:47.817537-04	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 1000.0, "receipt_no": "R-0201-0326-00115", "gross_total": 1000.0, "unpaid_notes": [], "change_amount": 0, "discount_total": 0.0, "tendered_total": 0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
113	2	1	sale	307	XAF	1500.00	pending	1	pos	0.00	1500.00	2026-03-08 13:34:36.269942-04	2026-03-08 09:34:36.263676-04	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 1500.0, "receipt_no": "R-0201-0326-00116", "gross_total": 1500.0, "unpaid_notes": [], "change_amount": 0, "discount_total": 0.0, "tendered_total": 0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
115	2	1	sale	309	XAF	5000.00	pending	1	pos	0.00	5000.00	2026-03-08 17:09:16.440787-04	2026-03-08 13:09:16.393071-04	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 5000.0, "receipt_no": "R-0201-0326-00118", "gross_total": 5000.0, "unpaid_notes": [], "change_amount": 0, "discount_total": 0.0, "tendered_total": 0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
117	2	1	sale	311	XAF	10000.00	succeeded	1	pos	10000.00	0.00	2026-03-09 17:28:55.940362-04	2026-03-09 13:28:55.919988-04	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 10000.0, "accounting": {"cash_movement": 10000.0, "discount_expense": 0.0, "accounts_receivable": 0.0, "sales_revenue_gross": 10000.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00120", "gross_total": 10000.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 10000.0, "discount_reason": null, "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 10000.0}
118	2	1	sale	312	XAF	5000.00	succeeded	1	pos	5000.00	0.00	2026-03-10 08:21:38.095746-04	2026-03-10 04:21:38.029213-04	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 5000.0, "accounting": {"cash_movement": 5000.0, "discount_expense": 0.0, "accounts_receivable": 0.0, "sales_revenue_gross": 5000.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00121", "gross_total": 5000.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 5000.0, "discount_reason": null, "payment_methods": ["mtn"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 5000.0}
119	2	1	sale	313	XAF	1500.00	pending	1	pos	0.00	1500.00	2026-03-10 13:35:28.845657-04	2026-03-10 09:35:28.78265-04	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 1500.0, "receipt_no": "R-0201-0326-00122", "gross_total": 1500.0, "unpaid_notes": [], "change_amount": 0, "discount_total": 0.0, "tendered_total": 0, "discount_reason": null, "complimentary_items": [], "complimentary_total": 0.0, "initial_payment_method": "cash"}
120	2	1	sale	314	XAF	5000.00	succeeded	1	pos	5000.00	0.00	2026-03-10 14:41:46.875537-04	2026-03-10 10:41:46.86504-04	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 5000.0, "accounting": {"cash_movement": 5000.0, "discount_expense": 0.0, "accounts_receivable": 0.0, "sales_revenue_gross": 5000.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00123", "gross_total": 5000.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 5000.0, "discount_reason": null, "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 5000.0}
121	2	1	sale	315	XAF	5000.00	succeeded	1	pos	5000.00	0.00	2026-03-10 14:46:31.505756-04	2026-03-10 10:46:31.488697-04	\N	{"source": "SaleService.create_sale", "pos_note": null, "net_total": 5000.0, "accounting": {"cash_movement": 5000.0, "discount_expense": 0.0, "accounts_receivable": 0.0, "sales_revenue_gross": 5000.0, "complimentary_expense": 0.0, "store_credit_liability": 0.0}, "receipt_no": "R-0201-0326-00124", "gross_total": 5000.0, "unpaid_notes": [], "unpaid_total": 0.0, "change_amount": 0.0, "discount_total": 0.0, "tendered_total": 5000.0, "discount_reason": null, "payment_methods": ["cash"], "has_store_credit": false, "complimentary_items": [], "complimentary_total": 0.0, "store_credit_amount": 0.0, "initial_payment_method": "cash", "unpaid_amount_client_hint": 5000.0}
\.


--
-- Data for Name: payments; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.payments (id, sale_id, method, provider, amount, status, reference, created_at, completed_at, gateway_intent_id) FROM stdin;
3	15	cash	\N	2500.00	paid	\N	2025-12-17 11:45:05.976798-05	2025-12-17 16:45:05.980013-05	\N
4	16	cash	\N	3500.00	paid	\N	2025-12-17 11:49:32.479385-05	2025-12-17 16:49:32.486255-05	\N
5	18	cash	\N	2500.00	paid	\N	2025-12-17 14:04:19.545516-05	2025-12-17 19:04:19.550126-05	\N
6	19	cash	\N	6500.00	paid	\N	2025-12-17 14:10:26.452532-05	2025-12-17 19:10:26.457537-05	\N
7	20	cash	\N	7000.00	paid	\N	2025-12-17 14:13:35.458729-05	2025-12-17 19:13:35.465789-05	\N
8	21	cash	\N	100000.00	paid	\N	2025-12-17 14:19:50.497484-05	2025-12-17 19:19:50.49921-05	\N
9	22	cash	\N	1500.00	paid	\N	2025-12-17 14:30:23.113937-05	2025-12-17 19:30:23.117071-05	\N
10	23	cash	\N	2500.00	paid	\N	2025-12-17 14:34:03.147198-05	2025-12-17 19:34:03.150464-05	\N
11	24	cash	\N	3500.00	paid	\N	2025-12-17 14:35:51.85917-05	2025-12-17 19:35:51.862282-05	\N
12	25	cash	\N	2500.00	paid	\N	2025-12-17 14:38:04.135848-05	2025-12-17 19:38:04.137978-05	\N
13	26	cash	\N	3000.00	paid	\N	2025-12-17 14:50:49.685537-05	2025-12-17 19:50:49.688581-05	\N
14	27	cash	\N	14000.00	paid	\N	2025-12-17 20:53:07.191986-05	2025-12-18 01:53:07.224677-05	\N
15	28	cash	\N	100000.00	paid	\N	2025-12-17 21:08:25.08113-05	2025-12-18 02:08:25.083333-05	\N
16	29	cash	\N	12000.00	paid	\N	2025-12-17 21:23:34.209016-05	2025-12-18 02:23:34.21726-05	\N
17	30	cash	\N	3000.00	paid	\N	2025-12-17 21:32:00.302716-05	2025-12-18 02:32:00.306351-05	\N
18	31	cash	\N	2500.00	paid	\N	2025-12-17 22:00:22.838908-05	2025-12-18 03:00:22.841555-05	\N
19	32	cash	\N	10000.00	paid	\N	2025-12-17 22:01:34.016176-05	2025-12-18 03:01:34.022559-05	\N
20	33	cash	\N	7000.00	paid	\N	2025-12-17 22:23:26.616688-05	2025-12-18 03:23:26.619039-05	\N
21	34	cash	\N	7500.00	paid	\N	2025-12-18 07:42:31.062524-05	2025-12-18 12:42:31.073509-05	\N
22	35	cash	\N	1500.00	paid	\N	2025-12-18 07:47:09.175601-05	2025-12-18 12:47:09.178427-05	\N
23	36	cash	\N	15000.00	paid	\N	2025-12-18 07:51:36.933221-05	2025-12-18 12:51:36.945699-05	\N
24	37	cash	\N	8000.00	paid	\N	2025-12-18 08:21:34.686386-05	2025-12-18 13:21:34.698899-05	\N
25	38	cash	\N	2500.00	paid	\N	2025-12-18 08:24:42.403435-05	2025-12-18 13:24:42.405992-05	\N
26	39	cash	\N	9500.00	paid	\N	2025-12-18 23:23:39.877992-05	2025-12-19 04:23:39.886428-05	\N
27	40	cash	\N	16500.00	paid	\N	2025-12-18 23:28:48.667996-05	2025-12-19 04:28:48.677465-05	\N
28	41	cash	\N	330000.00	paid	\N	2025-12-20 08:51:12.530672-05	2025-12-20 13:51:12.559348-05	\N
29	42	cash	\N	10000.00	paid	\N	2025-12-21 10:06:43.451328-05	2025-12-21 15:06:43.460243-05	\N
30	43	cash	\N	17000.00	paid	\N	2025-12-21 10:18:35.364602-05	2025-12-21 15:18:35.375045-05	\N
31	44	cash	\N	59000.00	paid	\N	2025-12-21 13:30:02.488374-05	2025-12-21 18:30:02.505311-05	\N
32	45	cash	\N	8000.00	paid	\N	2025-12-21 21:59:22.421896-05	2025-12-22 02:59:22.425414-05	\N
33	46	cash	\N	29500.00	paid	\N	2025-12-22 00:49:08.942246-05	2025-12-22 05:49:08.956486-05	\N
34	47	cash	\N	9500.00	paid	\N	2025-12-22 01:04:57.074615-05	2025-12-22 06:04:57.084512-05	\N
35	48	cash	\N	17500.00	paid	\N	2025-12-24 22:05:05.831872-05	2025-12-25 03:05:05.851519-05	\N
36	49	cash	\N	2500.00	paid	\N	2025-12-25 13:43:18.868911-05	2025-12-25 18:43:18.871442-05	\N
37	50	cash	\N	66000.00	paid	\N	2025-12-25 13:44:04.571667-05	2025-12-25 18:44:04.581233-05	\N
38	51	cash	\N	66000.00	paid	\N	2025-12-25 13:44:31.85028-05	2025-12-25 18:44:31.860852-05	\N
39	52	cash	\N	15500.00	paid	\N	2025-12-25 14:35:35.705762-05	2025-12-25 19:35:35.717366-05	\N
40	53	cash	\N	7500.00	paid	\N	2025-12-25 14:35:54.705873-05	2025-12-25 19:35:54.71461-05	\N
41	54	cash	\N	9000.00	paid	\N	2025-12-25 14:55:02.908838-05	2025-12-25 19:55:02.916932-05	\N
42	55	cash	\N	10000.00	paid	\N	2025-12-25 14:55:17.620608-05	2025-12-25 19:55:17.627866-05	\N
43	56	cash	\N	8000.00	paid	\N	2025-12-25 15:02:04.522556-05	2025-12-25 20:02:04.529153-05	\N
44	57	cash	\N	30000.00	paid	\N	2025-12-25 15:27:16.324922-05	2025-12-25 20:27:16.330426-05	\N
45	58	cash	\N	13500.00	paid	\N	2025-12-25 15:40:02.485154-05	2025-12-25 20:40:02.494109-05	\N
46	59	cash	\N	25000.00	paid	\N	2025-12-25 16:10:18.167704-05	2025-12-25 21:10:18.177302-05	\N
47	60	cash	\N	6000.00	paid	\N	2025-12-25 17:07:15.319444-05	2025-12-25 22:07:15.326229-05	\N
48	61	cash	\N	11500.00	paid	\N	2025-12-25 17:07:55.320283-05	2025-12-25 22:07:55.327029-05	\N
49	62	cash	\N	51500.00	paid	\N	2025-12-25 17:18:40.259903-05	2025-12-25 22:18:40.271689-05	\N
50	63	cash	\N	15500.00	paid	\N	2025-12-25 17:20:47.617181-05	2025-12-25 22:20:47.625532-05	\N
51	64	cash	\N	15500.00	paid	\N	2025-12-25 17:38:48.71227-05	2025-12-25 22:38:48.721214-05	\N
52	65	cash	\N	10000.00	paid	\N	2025-12-25 17:39:04.315526-05	2025-12-25 22:39:04.320215-05	\N
53	66	cash	\N	13000.00	paid	\N	2025-12-25 17:43:10.977505-05	2025-12-25 22:43:10.98468-05	\N
54	67	cash	\N	54500.00	paid	\N	2025-12-25 18:06:15.893057-05	2025-12-25 23:06:15.90765-05	\N
55	68	cash	\N	7500.00	paid	\N	2025-12-25 18:20:50.733155-05	2025-12-25 23:20:50.739715-05	\N
56	69	cash	\N	2500.00	paid	\N	2025-12-25 18:24:59.265769-05	2025-12-25 23:24:59.268168-05	\N
57	70	cash	\N	15500.00	paid	\N	2025-12-25 18:50:35.089879-05	2025-12-25 23:50:35.095062-05	\N
58	71	cash	\N	7000.00	paid	\N	2025-12-25 18:51:00.881734-05	2025-12-25 23:51:00.885233-05	\N
59	72	cash	\N	7000.00	paid	\N	2025-12-25 18:54:45.289058-05	2025-12-25 23:54:45.290816-05	\N
60	73	cash	\N	2500.00	paid	\N	2025-12-25 19:27:27.613044-05	2025-12-26 00:27:27.615148-05	\N
61	74	cash	\N	3500.00	paid	\N	2025-12-25 19:42:24.480218-05	2025-12-26 00:42:24.482954-05	\N
62	75	cash	\N	2500.00	paid	\N	2025-12-26 00:20:38.943309-05	2025-12-26 05:20:38.945405-05	\N
63	76	cash	\N	2500.00	paid	\N	2025-12-26 00:27:12.203203-05	2025-12-26 05:27:12.204948-05	\N
64	77	cash	\N	2500.00	paid	\N	2025-12-26 00:38:12.5751-05	2025-12-26 05:38:12.577564-05	\N
65	78	cash	\N	1500.00	paid	\N	2025-12-26 00:41:59.810917-05	2025-12-26 05:41:59.814081-05	\N
66	79	cash	\N	3000.00	paid	\N	2025-12-26 00:43:25.567298-05	2025-12-26 05:43:25.569392-05	\N
67	80	cash	\N	2000.00	paid	\N	2025-12-28 10:34:36.11235-05	2025-12-28 15:34:36.126054-05	\N
68	81	cash	\N	7500.00	paid	\N	2025-12-28 10:36:38.009018-05	2025-12-28 15:36:38.019335-05	\N
69	82	cash	\N	225000.00	paid	\N	2026-01-02 10:47:07.218639-05	2026-01-02 15:47:07.232096-05	\N
70	83	cash	\N	7500.00	paid	\N	2026-01-02 10:47:29.351571-05	2026-01-02 15:47:29.36252-05	\N
71	84	cash	\N	9000.00	paid	\N	2026-01-04 10:49:38.477939-05	2026-01-04 15:49:38.506888-05	\N
72	85	cash	\N	13500.00	paid	\N	2026-01-05 05:52:24.695826-05	2026-01-05 10:52:24.703334-05	\N
73	86	cash	\N	1500.00	paid	\N	2026-02-19 01:27:12.053686-05	2026-02-19 06:27:12.060214-05	\N
74	87	cash	\N	6000.00	paid	\N	2026-02-19 03:30:59.228662-05	2026-02-19 08:30:59.239727-05	\N
75	88	cash	\N	2500.00	paid	\N	2026-02-19 04:03:32.158286-05	2026-02-19 09:03:32.197515-05	\N
76	92	cash	\N	2500.00	paid	\N	2026-02-19 07:12:37.371517-05	2026-02-19 12:12:37.378164-05	\N
77	100	cash	\N	1500.00	paid	\N	2026-02-19 08:23:49.510022-05	2026-02-19 13:23:49.520037-05	\N
95	126	xafpay	wallet	1500.00	paid	REQ2602201253A3AZ5A2	2026-02-20 07:53:43.945411-05	2026-02-20 13:04:12.977285-05	\N
94	125	xafpay	wallet	70000.00	paid	REQ2602201159D431WPS	2026-02-20 06:59:25.385369-05	2026-02-20 13:17:49.256075-05	\N
91	122	xafpay	mtn	2500.00	failed	REQ26022011137W908K5	2026-02-20 06:13:33.868065-05	2026-02-20 13:20:04.475154-05	\N
92	123	xafpay	mtn	10000.00	failed	REQ26022011310SWPWVU	2026-02-20 06:31:40.110783-05	2026-02-20 13:41:05.972361-05	\N
96	127	xafpay	orange	1500.00	paid	REQ2602201307ALKOJBC	2026-02-20 08:07:14.081516-05	2026-02-20 13:42:51.148926-05	\N
93	124	xafpay	mtn	10000.00	failed	REQ26022011557IUM76F	2026-02-20 06:55:54.86887-05	2026-02-20 14:00:02.699522-05	\N
104	135	xafpay	wallet	2500.00	paid	REQ2602202342WZRX3CD	2026-02-20 18:42:40.636839-05	2026-02-20 23:43:20.381788-05	\N
105	136	xafpay	mtn	5000.00	paid	REQ26022023527YP39S6	2026-02-20 18:52:32.388247-05	2026-02-20 23:53:06.300003-05	\N
106	137	cash	\N	2500.00	paid	\N	2026-02-20 18:54:37.212882-05	2026-02-20 23:54:37.215672-05	\N
107	138	xafpay	orange	1500.00	paid	REQ2602211042N5TKGUD	2026-02-21 05:42:23.915978-05	2026-02-21 10:42:56.74883-05	\N
108	139	cash	\N	10500.00	paid	\N	2026-02-21 07:32:12.671995-05	2026-02-21 12:32:12.679966-05	\N
109	140	cash	\N	15000.00	paid	\N	2026-02-21 12:21:02.542153-05	2026-02-21 17:21:02.551404-05	\N
110	141	xafpay	orange	5000.00	paid	REQ2602211903AXVR7AI	2026-02-21 14:03:28.30577-05	2026-02-21 19:04:06.663235-05	\N
111	142	xafpay	card	4000.00	paid	REQ2602221311B0ORZNP	2026-02-22 08:11:12.096708-05	2026-02-22 13:11:54.947034-05	\N
112	143	xafpay	orange	5500.00	paid	REQ2602230928JI69EEO	2026-02-23 04:28:25.962173-05	2026-02-23 09:29:26.091561-05	\N
113	144	xafpay	orange	5500.00	paid	REQ2602231852GSA4J7U	2026-02-23 13:52:24.280498-05	2026-02-23 18:53:15.840679-05	\N
114	145	cash	\N	4000.00	paid	\N	2026-02-23 13:53:47.57144-05	2026-02-23 18:53:47.578031-05	\N
117	148	cash	\N	2500.00	paid	\N	2026-02-24 06:09:19.075359-05	2026-02-24 11:09:19.081514-05	\N
118	149	cash	\N	103500.00	paid	\N	2026-02-24 06:09:57.165681-05	2026-02-24 11:09:57.176493-05	\N
119	150	cash	\N	17500.00	paid	\N	2026-02-24 06:11:30.82756-05	2026-02-24 11:11:30.836926-05	\N
121	152	xafpay	mtn	3000.00	pending	e08c5145-c337-4553-a790-869266a363cf	2026-02-24 08:55:24.036363-05	\N	\N
122	153	cash	\N	4000.00	paid	\N	2026-02-24 09:06:14.652774-05	2026-02-24 14:06:14.660294-05	\N
123	154	xafpay	orange	6000.00	pending	f67f6417-d646-4d0a-95e2-de73c5d88bb4	2026-02-24 09:06:41.732229-05	\N	\N
124	155	xafpay	orange	11000.00	pending	045608e3-1706-42cd-b31f-6687ee2255b8	2026-02-24 09:51:08.222428-05	\N	\N
125	156	cash	\N	15000.00	paid	\N	2026-02-26 01:31:00.315623-05	2026-02-26 06:31:00.325391-05	\N
126	157	cash	\N	15000.00	paid	\N	2026-02-26 01:31:16.840907-05	2026-02-26 06:31:16.851774-05	\N
127	158	cash	\N	15000.00	paid	\N	2026-02-26 01:31:19.510201-05	2026-02-26 06:31:19.522975-05	\N
128	159	cash	\N	22000.00	paid	\N	2026-02-26 01:38:33.27353-05	2026-02-26 06:38:33.294024-05	\N
129	160	cash	\N	5000.00	paid	\N	2026-02-26 02:29:48.484325-05	2026-02-26 07:29:48.491129-05	\N
130	161	cash	\N	5000.00	paid	\N	2026-02-26 02:29:52.820147-05	2026-02-26 07:29:52.825156-05	\N
131	162	cash	\N	3000.00	paid	\N	2026-02-26 02:33:42.492476-05	2026-02-26 07:33:42.495527-05	\N
133	167	cash	\N	6500.00	paid	\N	2026-02-26 06:00:21.596531-05	2026-02-26 11:00:21.62574-05	\N
134	168	cash	\N	77500.00	paid	\N	2026-02-26 06:03:34.249314-05	2026-02-26 11:03:34.287244-05	\N
135	169	cash	\N	20000.00	paid	\N	2026-02-26 06:07:14.99217-05	2026-02-26 11:07:15.046134-05	\N
136	170	cash	\N	10000.00	paid	\N	2026-02-26 06:09:21.6991-05	2026-02-26 11:09:21.720369-05	\N
137	171	cash	\N	2500.00	paid	\N	2026-02-26 06:13:48.52898-05	2026-02-26 11:13:48.533296-05	\N
138	172	cash	\N	9000.00	paid	\N	2026-02-26 06:24:34.098083-05	2026-02-26 11:24:34.118605-05	\N
139	173	cash	\N	9000.00	paid	\N	2026-02-26 06:28:37.177758-05	2026-02-26 11:28:37.197559-05	\N
140	174	cash	\N	9000.00	paid	\N	2026-02-26 06:38:56.60496-05	2026-02-26 11:38:56.635888-05	\N
141	175	cash	\N	13000.00	paid	\N	2026-02-26 06:50:20.856752-05	2026-02-26 11:50:20.869434-05	\N
142	176	cash	\N	1500.00	paid	\N	2026-02-27 11:52:50.925675-05	2026-02-27 16:52:50.929571-05	\N
143	177	xafpay	orange	8000.00	paid	REQ26022716535FBTZH0	2026-02-27 11:53:14.696402-05	2026-02-27 16:53:43.02507-05	\N
144	179	xafpay	orange	10000.00	pending	2d7199a7-d798-4d91-b553-81e241886bfc	2026-02-28 09:02:50.492826-05	\N	\N
145	180	xafpay	orange	9000.00	pending	845090f4-37c3-47b2-adf9-c82d1703d1e9	2026-02-28 09:40:42.314386-05	\N	\N
146	181	xafpay	orange	2500.00	pending	6f937703-8745-4fe7-aa07-addaed93802e	2026-02-28 10:49:19.234021-05	\N	\N
147	184	cash	\N	10000.00	paid	\N	2026-02-28 11:58:56.039958-05	2026-02-28 16:58:56.043492-05	\N
148	199	cash	\N	6500.00	paid	\N	2026-03-02 04:31:18.98237-05	2026-03-02 09:31:18.988401-05	\N
149	207	cash	\N	7000.00	paid	\N	2026-03-02 06:02:21.866605-05	2026-03-02 11:02:21.874892-05	\N
150	208	cash	\N	11000.00	paid	\N	2026-03-02 11:46:21.651546-05	2026-03-02 16:46:21.660334-05	\N
151	209	cash	\N	5500.00	paid	\N	2026-03-02 11:59:49.676554-05	2026-03-02 16:59:49.681509-05	\N
152	210	cash	\N	3500.00	paid	\N	2026-03-02 12:03:40.321595-05	2026-03-02 17:03:40.323401-05	\N
153	211	cash	\N	10500.00	paid	\N	2026-03-02 12:13:17.20387-05	2026-03-02 17:13:17.210698-05	\N
154	212	cash	\N	12500.00	paid	\N	2026-03-02 12:18:36.265299-05	2026-03-02 17:18:36.277137-05	\N
155	213	cash	\N	6000.00	paid	\N	2026-03-02 13:10:37.854875-05	2026-03-02 18:10:37.860627-05	\N
156	214	cash	\N	8500.00	paid	\N	2026-03-02 14:08:46.458706-05	2026-03-02 19:08:46.463572-05	\N
157	215	cash	\N	5500.00	paid	\N	2026-03-02 14:17:31.05174-05	2026-03-02 19:17:31.058551-05	\N
158	216	cash	\N	10000.00	paid	\N	2026-03-02 17:59:15.227727-05	2026-03-02 22:59:15.240354-05	\N
159	217	cash	\N	9500.00	paid	\N	2026-03-02 18:01:04.567997-05	2026-03-02 23:01:04.57905-05	\N
160	218	cash	\N	22500.00	paid	\N	2026-03-02 18:05:05.927556-05	2026-03-02 23:05:05.945316-05	\N
161	219	cash	\N	5500.00	paid	\N	2026-03-03 01:46:31.449038-05	2026-03-03 06:46:31.453663-05	\N
162	220	cash	\N	5500.00	paid	\N	2026-03-03 01:49:20.901867-05	2026-03-03 06:49:20.907166-05	\N
\.


--
-- Data for Name: roles; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.roles (id, name, description, permissions, created_at, updated_at) FROM stdin;
6	kitchen	\N	["order.view", "order.update_status"]	2025-12-11 23:28:25.691828	\N
7	restaurant_manager	\N	["sale.create", "sale.edit", "sale.refund", "sale.view", "inventory.view", "inventory.edit", "inventory.adjust", "inventory.transfer", "report.view", "report.export", "report.financial", "report.sales", "report.finance.view", "report.financial.overview", "report.financial.export", "report.financial.audit", "hr.view", "hr.edit"]	2025-12-11 23:28:25.696197	\N
8	hostess	\N	["customer.view", "order.view"]	2025-12-11 23:28:25.699831	\N
9	payments_officer	\N	["payments.send", "payments.receive", "payments.reconcile", "transaction.view"]	2025-12-11 23:28:25.702232	\N
10	kyc_agent	\N	["hr.view", "customer.verify"]	2025-12-11 23:28:25.704746	\N
11	compliance_manager	\N	["payments.send", "payments.receive", "payments.reconcile"]	2025-12-11 23:28:25.707693	\N
12	treasury_analyst	\N	["wallet.balance.view", "report.finance.view"]	2025-12-11 23:28:25.709522	\N
13	reception	\N	["customer.view", "sale.create", "sale.view"]	2025-12-11 23:28:25.711499	\N
15	doctor	\N	["order.view", "customer.view"]	2025-12-11 23:28:25.71547	\N
16	clinic_manager	\N	["sale.create", "sale.edit", "sale.refund", "sale.view", "inventory.view", "inventory.edit", "inventory.adjust", "inventory.transfer", "report.view", "report.export", "report.financial", "report.sales", "report.finance.view", "report.financial.overview", "report.financial.export", "report.financial.audit", "hr.view", "hr.edit"]	2025-12-11 23:28:25.718345	\N
17	pharmacist	\N	["inventory.view", "inventory.edit", "inventory.adjust", "inventory.transfer"]	2025-12-11 23:28:25.72092	\N
18	hr_officer	\N	["hr.view", "hr.edit"]	2025-12-11 23:28:25.723537	\N
1	cashier	\N	["catalog.view", "customer.view", "inventory.view", "order.create", "order.view", "payments.receive", "sale.create", "sale.view", "taxonomy.view", "transaction.view", "wallet.balance.view", "wallet.transaction.view"]	2025-12-11 23:28:25.664822	2025-12-14 08:58:29.568138
2	inventory_clerk	\N	["catalog.view", "customer.view", "inventory.view", "order.create", "order.view", "payments.receive", "sale.create", "sale.view", "taxonomy.view", "transaction.view", "wallet.balance.view", "wallet.transaction.view"]	2025-12-11 23:28:25.67652	2025-12-14 08:58:29.568138
3	store_manager	\N	["catalog.create", "catalog.edit", "catalog.view", "customer.create", "customer.export", "customer.update", "customer.verify", "customer.view", "inventory.adjust", "inventory.edit", "inventory.view", "order.create", "order.export", "order.update", "order.update_status", "order.view", "payments.receive", "payments.send", "report.export", "report.sales", "report.view", "sale.create", "sale.edit", "sale.refund", "sale.view", "taxonomy.create", "taxonomy.edit", "taxonomy.view", "transaction.create", "transaction.export", "transaction.update", "transaction.view", "wallet.balance.view", "wallet.transaction.export", "wallet.transaction.view"]	2025-12-11 23:28:25.680634	2025-12-14 08:58:29.568138
4	accountant	\N	["catalog.create", "catalog.edit", "catalog.view", "customer.create", "customer.export", "customer.update", "customer.verify", "customer.view", "inventory.adjust", "inventory.edit", "inventory.view", "order.create", "order.export", "order.update", "order.update_status", "order.view", "payments.receive", "payments.send", "report.export", "report.sales", "report.view", "sale.create", "sale.edit", "sale.refund", "sale.view", "taxonomy.create", "taxonomy.edit", "taxonomy.view", "transaction.create", "transaction.export", "transaction.update", "transaction.view", "wallet.balance.view", "wallet.transaction.export", "wallet.transaction.view"]	2025-12-11 23:28:25.683593	2025-12-14 08:58:29.568138
5	waiter	\N	["catalog.view", "customer.view", "inventory.view", "order.create", "order.view", "payments.receive", "sale.create", "sale.view", "taxonomy.view", "transaction.view", "wallet.balance.view", "wallet.transaction.view"]	2025-12-11 23:28:25.68707	2025-12-14 08:58:29.568138
14	nurse	\N	["catalog.view", "customer.view", "inventory.view", "order.create", "order.view", "payments.receive", "sale.create", "sale.view", "taxonomy.view", "transaction.view", "wallet.balance.view", "wallet.transaction.view"]	2025-12-11 23:28:25.713348	2025-12-14 08:58:29.568138
19	finance_manager	\N	["catalog.create", "catalog.delete", "catalog.edit", "catalog.view", "customer.create", "customer.delete", "customer.export", "customer.update", "customer.verify", "customer.view", "inventory.adjust", "inventory.edit", "inventory.transfer", "inventory.view", "order.create", "order.delete", "order.export", "order.update", "order.update_status", "order.view", "payments.receive", "payments.reconcile", "payments.send", "report.export", "report.finance.view", "report.financial", "report.financial.audit", "report.financial.export", "report.financial.overview", "report.sales", "report.view", "sale.create", "sale.edit", "sale.refund", "sale.view", "taxonomy.create", "taxonomy.delete", "taxonomy.edit", "taxonomy.view", "transaction.create", "transaction.delete", "transaction.export", "transaction.update", "transaction.view", "wallet.balance.adjust", "wallet.balance.view", "wallet.freeze", "wallet.transaction.export", "wallet.transaction.view", "wallet.unfreeze"]	2025-12-11 23:28:25.725826	2025-12-14 08:58:29.568138
20	operations_manager	\N	["catalog.create", "catalog.edit", "catalog.view", "customer.create", "customer.export", "customer.update", "customer.verify", "customer.view", "inventory.adjust", "inventory.edit", "inventory.view", "order.create", "order.export", "order.update", "order.update_status", "order.view", "payments.receive", "payments.send", "report.export", "report.sales", "report.view", "sale.create", "sale.edit", "sale.refund", "sale.view", "taxonomy.create", "taxonomy.edit", "taxonomy.view", "transaction.create", "transaction.export", "transaction.update", "transaction.view", "wallet.balance.view", "wallet.transaction.export", "wallet.transaction.view"]	2025-12-11 23:28:25.728429	2025-12-14 08:58:29.568138
21	executive	\N	["catalog.create", "catalog.delete", "catalog.edit", "catalog.view", "customer.create", "customer.delete", "customer.export", "customer.update", "customer.verify", "customer.view", "inventory.adjust", "inventory.edit", "inventory.transfer", "inventory.view", "order.create", "order.delete", "order.export", "order.update", "order.update_status", "order.view", "payments.receive", "payments.reconcile", "payments.send", "report.export", "report.finance.view", "report.financial", "report.financial.audit", "report.financial.export", "report.financial.overview", "report.sales", "report.view", "sale.create", "sale.edit", "sale.refund", "sale.view", "taxonomy.create", "taxonomy.delete", "taxonomy.edit", "taxonomy.view", "transaction.create", "transaction.delete", "transaction.export", "transaction.update", "transaction.view", "wallet.balance.adjust", "wallet.balance.view", "wallet.freeze", "wallet.transaction.export", "wallet.transaction.view", "wallet.unfreeze"]	2025-12-11 23:28:25.731637	2025-12-14 08:58:29.568138
22	branch_manager	\N	["catalog.create", "catalog.edit", "catalog.view", "customer.create", "customer.export", "customer.update", "customer.verify", "customer.view", "inventory.adjust", "inventory.edit", "inventory.view", "order.create", "order.export", "order.update", "order.update_status", "order.view", "payments.receive", "payments.send", "report.export", "report.sales", "report.view", "sale.create", "sale.edit", "sale.refund", "sale.view", "taxonomy.create", "taxonomy.edit", "taxonomy.view", "transaction.create", "transaction.export", "transaction.update", "transaction.view", "wallet.balance.view", "wallet.transaction.export", "wallet.transaction.view"]	2025-12-14 08:58:29.554292	2025-12-14 08:58:29.568138
23	owner	\N	["catalog.create", "catalog.delete", "catalog.edit", "catalog.view", "customer.create", "customer.delete", "customer.export", "customer.update", "customer.verify", "customer.view", "inventory.adjust", "inventory.edit", "inventory.transfer", "inventory.view", "order.create", "order.delete", "order.export", "order.update", "order.update_status", "order.view", "payments.receive", "payments.reconcile", "payments.send", "report.export", "report.finance.view", "report.financial", "report.financial.audit", "report.financial.export", "report.financial.overview", "report.sales", "report.view", "sale.create", "sale.edit", "sale.refund", "sale.view", "taxonomy.create", "taxonomy.delete", "taxonomy.edit", "taxonomy.view", "transaction.create", "transaction.delete", "transaction.export", "transaction.update", "transaction.view", "wallet.balance.adjust", "wallet.balance.view", "wallet.freeze", "wallet.transaction.export", "wallet.transaction.view", "wallet.unfreeze"]	2025-12-14 08:58:29.554292	2025-12-14 08:58:29.568138
24	admin	\N	["catalog.create", "catalog.delete", "catalog.edit", "catalog.view", "customer.create", "customer.delete", "customer.export", "customer.update", "customer.verify", "customer.view", "inventory.adjust", "inventory.edit", "inventory.transfer", "inventory.view", "order.create", "order.delete", "order.export", "order.update", "order.update_status", "order.view", "payments.receive", "payments.reconcile", "payments.send", "report.export", "report.finance.view", "report.financial", "report.financial.audit", "report.financial.export", "report.financial.overview", "report.sales", "report.view", "sale.create", "sale.edit", "sale.refund", "sale.view", "taxonomy.create", "taxonomy.delete", "taxonomy.edit", "taxonomy.view", "transaction.create", "transaction.delete", "transaction.export", "transaction.update", "transaction.view", "wallet.balance.adjust", "wallet.balance.view", "wallet.freeze", "wallet.transaction.export", "wallet.transaction.view", "wallet.unfreeze"]	2025-12-14 08:58:29.554292	2025-12-14 08:58:29.568138
\.


--
-- Data for Name: sale_items; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.sale_items (id, sale_id, atomic_unit_id, name_snapshot, unit_price, quantity, line_total) FROM stdin;
3	3	26	Chicken	2500.00	1	2500.00
4	4	39	Gambas	7000.00	1	7000.00
5	5	32	Eru	2500.00	1	2500.00
6	5	40	Fish	3500.00	1	3500.00
7	5	66	BEAUFORT	1000.00	3	3000.00
8	5	55	BOOSTER	1000.00	2	2000.00
9	5	53	CASTEL	1000.00	1	1000.00
10	5	109	CALVET (RED)	10000.00	1	10000.00
11	6	39	Gambas	7000.00	1	7000.00
12	7	35	Cornchaff	1500.00	1	1500.00
13	7	40	Fish	3500.00	1	3500.00
14	8	26	Chicken	2500.00	1	2500.00
15	8	32	Eru	2500.00	1	2500.00
16	9	66	BEAUFORT	1000.00	1	1000.00
17	9	53	CASTEL	1000.00	1	1000.00
18	9	70	DOPPLE	1000.00	1	1000.00
19	9	58	G GUINNESS	2000.00	3	6000.00
20	10	26	Chicken	2500.00	1	2500.00
21	11	39	Gambas	7000.00	1	7000.00
22	11	122	BAILEYS	20000.00	1	20000.00
23	12	40	Fish	3500.00	1	3500.00
24	15	32	Eru	2500.00	1	2500.00
25	16	35	Cornchaff	1500.00	1	1500.00
26	16	66	BEAUFORT	1000.00	2	2000.00
27	17	39	Gambas	7000.00	1	7000.00
28	18	32	Eru	2500.00	1	2500.00
29	19	38	Achu	3000.00	1	3000.00
30	19	40	Fish	3500.00	1	3500.00
31	20	39	Gambas	7000.00	1	7000.00
32	21	121	RIGNAC	100000.00	1	100000.00
33	22	35	Cornchaff	1500.00	1	1500.00
34	23	26	Chicken	2500.00	1	2500.00
35	24	27	Goat	3500.00	1	3500.00
36	25	26	Chicken	2500.00	1	2500.00
37	26	38	Achu	3000.00	1	3000.00
38	27	40	Fish	3500.00	1	3500.00
39	27	39	Gambas	7000.00	1	7000.00
40	27	27	Goat	3500.00	1	3500.00
41	28	120	CRYSTAL	100000.00	1	100000.00
42	29	26	Chicken	2500.00	1	2500.00
43	29	32	Eru	2500.00	1	2500.00
44	29	39	Gambas	7000.00	1	7000.00
45	30	38	Achu	3000.00	1	3000.00
46	31	31	Ndole	2500.00	1	2500.00
47	32	40	Fish	3500.00	1	3500.00
48	32	27	Goat	3500.00	1	3500.00
49	32	37	Kati-Kati	3000.00	1	3000.00
50	33	27	Goat	3500.00	2	7000.00
51	34	35	Cornchaff	1500.00	1	1500.00
52	34	27	Goat	3500.00	1	3500.00
53	34	31	Ndole	2500.00	1	2500.00
54	35	35	Cornchaff	1500.00	1	1500.00
55	36	39	Gambas	7000.00	1	7000.00
56	36	36	Koki	1500.00	2	3000.00
57	36	33	Okro and Egussi	2500.00	2	5000.00
58	37	32	Eru	2500.00	1	2500.00
59	37	37	Kati-Kati	3000.00	1	3000.00
60	37	33	Okro and Egussi	2500.00	1	2500.00
61	38	31	Ndole	2500.00	1	2500.00
62	39	26	Chicken	2500.00	1	2500.00
63	39	35	Cornchaff	1500.00	1	1500.00
64	39	32	Eru	2500.00	1	2500.00
65	39	37	Kati-Kati	3000.00	1	3000.00
66	40	38	Achu	3000.00	1	3000.00
67	40	26	Chicken	2500.00	1	2500.00
68	40	35	Cornchaff	1500.00	1	1500.00
69	40	32	Eru	2500.00	1	2500.00
70	40	39	Gambas	7000.00	1	7000.00
71	41	120	CRYSTAL	100000.00	1	100000.00
72	41	114	MOET BRUT	55000.00	1	55000.00
73	41	121	RIGNAC	100000.00	1	100000.00
74	41	116	RUINART BRUT	75000.00	1	75000.00
75	42	26	Chicken	2500.00	1	2500.00
76	42	35	Cornchaff	1500.00	1	1500.00
77	42	40	Fish	3500.00	1	3500.00
78	42	32	Eru	2500.00	1	2500.00
79	43	26	Chicken	2500.00	1	2500.00
80	43	32	Eru	2500.00	1	2500.00
81	43	27	Goat	3500.00	1	3500.00
82	43	36	Koki	1500.00	1	1500.00
83	43	33	Okro and Egussi	2500.00	1	2500.00
84	43	55	BOOSTER	1000.00	1	1000.00
85	43	71	HEINEKEN	1500.00	1	1500.00
86	43	58	G GUINNESS	2000.00	1	2000.00
87	44	37	Kati-Kati	3000.00	5	15000.00
88	44	43	Poulet DG 1	10000.00	2	20000.00
89	44	34	White Beans	2500.00	1	2500.00
90	44	27	Goat	3500.00	1	3500.00
91	44	32	Eru	2500.00	2	5000.00
92	44	40	Fish	3500.00	1	3500.00
93	44	31	Ndole	2500.00	1	2500.00
94	44	39	Gambas	7000.00	1	7000.00
95	45	38	Achu	3000.00	1	3000.00
96	45	26	Chicken	2500.00	2	5000.00
97	46	26	Chicken	2500.00	3	7500.00
98	46	35	Cornchaff	1500.00	2	3000.00
99	46	32	Eru	2500.00	2	5000.00
100	46	40	Fish	3500.00	1	3500.00
101	46	18	Cigarettes	1000.00	2	2000.00
102	46	20	Charcoal	500.00	1	500.00
103	46	19	Shisha	3500.00	1	3500.00
104	46	38	Achu	3000.00	1	3000.00
105	46	57	BAVARIA	1500.00	1	1500.00
106	47	38	Achu	3000.00	1	3000.00
107	47	26	Chicken	2500.00	1	2500.00
108	47	35	Cornchaff	1500.00	1	1500.00
109	47	32	Eru	2500.00	1	2500.00
110	48	55	BOOSTER	1000.00	1	1000.00
111	48	58	G GUINNESS	2000.00	2	4000.00
112	48	67	KADJI	1000.00	1	1000.00
113	48	60	MALTA	1000.00	1	1000.00
114	48	63	SMOOTH	1500.00	1	1500.00
115	48	26	Chicken	2500.00	1	2500.00
116	48	36	Koki	1500.00	1	1500.00
117	48	28	Snails	5000.00	1	5000.00
118	49	31	Ndole	2500.00	1	2500.00
119	50	32	Eru	2500.00	1	2500.00
120	50	31	Ndole	2500.00	1	2500.00
121	50	33	Okro and Egussi	2500.00	1	2500.00
122	50	57	BAVARIA	1500.00	1	1500.00
123	50	70	DOPPLE	1000.00	1	1000.00
124	50	62	ICE PINEAPPLE	1000.00	1	1000.00
125	50	114	MOET BRUT	55000.00	1	55000.00
126	51	32	Eru	2500.00	1	2500.00
127	51	31	Ndole	2500.00	1	2500.00
128	51	33	Okro and Egussi	2500.00	1	2500.00
129	51	57	BAVARIA	1500.00	1	1500.00
130	51	70	DOPPLE	1000.00	1	1000.00
131	51	62	ICE PINEAPPLE	1000.00	1	1000.00
132	51	114	MOET BRUT	55000.00	1	55000.00
133	52	31	Ndole	2500.00	1	2500.00
134	52	28	Snails	5000.00	1	5000.00
135	52	41	Poulet DG 1/4	2500.00	1	2500.00
136	52	29	Pork	3000.00	1	3000.00
137	52	34	White Beans	2500.00	1	2500.00
145	55	32	Eru	2500.00	1	2500.00
146	55	31	Ndole	2500.00	1	2500.00
147	55	33	Okro and Egussi	2500.00	1	2500.00
148	55	30	Towel	2500.00	1	2500.00
149	56	34	White Beans	2500.00	1	2500.00
150	56	29	Pork	3000.00	1	3000.00
151	56	66	BEAUFORT	1000.00	1	1000.00
152	56	69	RED BULL	1500.00	1	1500.00
156	58	32	Eru	2500.00	1	2500.00
157	58	31	Ndole	2500.00	1	2500.00
158	58	28	Snails	5000.00	1	5000.00
159	58	66	BEAUFORT	1000.00	1	1000.00
160	58	51	ISENBECK	1000.00	1	1000.00
161	58	69	RED BULL	1500.00	1	1500.00
162	59	30	Towel	2500.00	1	2500.00
163	59	28	Snails	5000.00	1	5000.00
164	59	41	Poulet DG 1/4	2500.00	1	2500.00
165	59	42	Poulet DG 1/2	5000.00	1	5000.00
166	59	43	Poulet DG 1	10000.00	1	10000.00
167	60	32	Eru	2500.00	1	2500.00
168	60	65	HARP	1000.00	1	1000.00
169	60	71	HEINEKEN	1500.00	1	1500.00
170	60	54	MUTZIG	1000.00	1	1000.00
138	53	32	Eru	2500.00	1	2500.00
139	53	33	Okro and Egussi	2500.00	1	2500.00
140	53	34	White Beans	2500.00	1	2500.00
141	54	36	Koki	1500.00	1	1500.00
142	54	31	Ndole	2500.00	1	2500.00
143	54	30	Towel	2500.00	1	2500.00
144	54	34	White Beans	2500.00	1	2500.00
153	57	31	Ndole	2500.00	3	7500.00
154	57	28	Snails	5000.00	3	15000.00
155	57	41	Poulet DG 1/4	2500.00	3	7500.00
171	61	40	Fish	3500.00	1	3500.00
172	61	29	Pork	3000.00	1	3000.00
173	61	34	White Beans	2500.00	1	2500.00
174	61	30	Towel	2500.00	1	2500.00
175	62	19	Shisha	3500.00	1	3500.00
176	62	132	MONKEY SHOULDER	40000.00	1	40000.00
177	62	64	ORIGIN	1000.00	1	1000.00
178	62	59	P GUINNESS	1000.00	1	1000.00
179	62	69	RED BULL	1500.00	1	1500.00
180	62	73	SKOLL	1500.00	1	1500.00
181	62	63	SMOOTH	1500.00	1	1500.00
182	62	74	VK BLUE	1500.00	1	1500.00
183	63	35	Cornchaff	1500.00	1	1500.00
184	63	36	Koki	1500.00	1	1500.00
185	63	41	Poulet DG 1/4	2500.00	1	2500.00
186	63	32	Eru	2500.00	1	2500.00
187	63	31	Ndole	2500.00	1	2500.00
188	63	28	Snails	5000.00	1	5000.00
189	64	35	Cornchaff	1500.00	1	1500.00
190	64	36	Koki	1500.00	1	1500.00
191	64	41	Poulet DG 1/4	2500.00	1	2500.00
192	64	32	Eru	2500.00	1	2500.00
193	64	31	Ndole	2500.00	1	2500.00
194	64	28	Snails	5000.00	1	5000.00
195	65	32	Eru	2500.00	1	2500.00
196	65	31	Ndole	2500.00	1	2500.00
197	65	28	Snails	5000.00	1	5000.00
198	66	34	White Beans	2500.00	3	7500.00
199	66	29	Pork	3000.00	1	3000.00
200	66	33	Okro and Egussi	2500.00	1	2500.00
201	67	32	Eru	2500.00	1	2500.00
202	67	40	Fish	3500.00	1	3500.00
203	67	39	Gambas	7000.00	1	7000.00
204	67	55	BOOSTER	1000.00	1	1000.00
205	67	58	G GUINNESS	2000.00	1	2000.00
206	67	65	HARP	1000.00	1	1000.00
207	67	60	MALTA	1000.00	1	1000.00
208	67	63	SMOOTH	1500.00	1	1500.00
209	67	133	BLACK LABEL	35000.00	1	35000.00
210	68	32	Eru	2500.00	1	2500.00
211	68	33	Okro and Egussi	2500.00	1	2500.00
212	68	30	Towel	2500.00	1	2500.00
213	69	32	Eru	2500.00	1	2500.00
214	70	32	Eru	2500.00	2	5000.00
215	70	40	Fish	3500.00	1	3500.00
216	70	39	Gambas	7000.00	1	7000.00
217	71	39	Gambas	7000.00	1	7000.00
218	72	39	Gambas	7000.00	1	7000.00
219	73	32	Eru	2500.00	1	2500.00
220	74	40	Fish	3500.00	1	3500.00
221	75	30	Towel	2500.00	1	2500.00
222	76	31	Ndole	2500.00	1	2500.00
223	77	31	Ndole	2500.00	1	2500.00
224	78	36	Koki	1500.00	1	1500.00
225	79	37	Kati-Kati	3000.00	1	3000.00
226	80	65	HARP	1000.00	1	1000.00
227	80	66	BEAUFORT	1000.00	1	1000.00
228	81	28	Snails	5000.00	1	5000.00
229	81	34	White Beans	2500.00	1	2500.00
230	82	115	VEUVE CLICQUOT	70000.00	1	70000.00
231	82	114	MOET BRUT	55000.00	1	55000.00
232	82	119	DON PERIGNON	100000.00	1	100000.00
233	83	26	Chicken	2500.00	1	2500.00
234	83	42	Poulet DG 1/2	5000.00	1	5000.00
235	84	38	Achu	3000.00	1	3000.00
236	84	57	BAVARIA	1500.00	1	1500.00
237	84	66	BEAUFORT	1000.00	1	1000.00
238	84	19	Shisha	3500.00	1	3500.00
239	85	38	Achu	3000.00	1	3000.00
240	85	37	Kati-Kati	3000.00	1	3000.00
241	85	41	Poulet DG 1/4	2500.00	1	2500.00
242	85	28	Snails	5000.00	1	5000.00
243	86	35	Cornchaff	1500.00	1	1500.00
244	87	40	Fish	3500.00	1	3500.00
245	87	41	Poulet DG 1/4	2500.00	1	2500.00
246	88	32	Eru	2500.00	1	2500.00
247	89	40	Fish	3500.00	1	3500.00
248	90	31	Ndole	2500.00	1	2500.00
249	91	31	Ndole	2500.00	1	2500.00
250	92	30	Towel	2500.00	1	2500.00
251	93	37	Kati-Kati	3000.00	1	3000.00
252	94	37	Kati-Kati	3000.00	1	3000.00
253	95	35	Cornchaff	1500.00	1	1500.00
254	96	35	Cornchaff	1500.00	1	1500.00
255	97	34	White Beans	2500.00	1	2500.00
256	98	40	Fish	3500.00	1	3500.00
257	99	32	Eru	2500.00	1	2500.00
258	100	36	Koki	1500.00	1	1500.00
259	101	37	Kati-Kati	3000.00	1	3000.00
260	102	31	Ndole	2500.00	1	2500.00
261	103	26	Chicken	2500.00	1	2500.00
262	104	35	Cornchaff	1500.00	1	1500.00
263	105	28	Snails	5000.00	1	5000.00
264	106	40	Fish	3500.00	1	3500.00
265	107	32	Eru	2500.00	1	2500.00
266	108	32	Eru	2500.00	1	2500.00
267	109	30	Towel	2500.00	1	2500.00
268	110	38	Achu	3000.00	1	3000.00
269	111	26	Chicken	2500.00	1	2500.00
270	112	36	Koki	1500.00	1	1500.00
271	113	32	Eru	2500.00	1	2500.00
272	114	40	Fish	3500.00	1	3500.00
273	115	26	Chicken	2500.00	1	2500.00
274	116	32	Eru	2500.00	1	2500.00
275	117	30	Towel	2500.00	1	2500.00
276	118	30	Towel	2500.00	1	2500.00
277	119	37	Kati-Kati	3000.00	1	3000.00
278	120	32	Eru	2500.00	1	2500.00
279	121	30	Towel	2500.00	1	2500.00
280	122	33	Okro and Egussi	2500.00	1	2500.00
281	123	43	Poulet DG 1	10000.00	1	10000.00
282	124	43	Poulet DG 1	10000.00	1	10000.00
283	125	40	Fish	3500.00	1	3500.00
284	125	39	Gambas	7000.00	1	7000.00
285	125	33	Okro and Egussi	2500.00	1	2500.00
286	125	34	White Beans	2500.00	1	2500.00
287	125	36	Koki	1500.00	1	1500.00
288	125	66	BEAUFORT	1000.00	1	1000.00
289	125	58	G GUINNESS	2000.00	1	2000.00
290	125	127	VODKA BELVEDERE	50000.00	1	50000.00
291	126	36	Koki	1500.00	1	1500.00
292	127	35	Cornchaff	1500.00	1	1500.00
293	128	28	Snails	5000.00	1	5000.00
294	129	31	Ndole	2500.00	1	2500.00
295	130	29	Pork	3000.00	1	3000.00
296	131	27	Goat	3500.00	1	3500.00
297	132	33	Okro and Egussi	2500.00	1	2500.00
298	132	30	Towel	2500.00	2	5000.00
299	132	55	BOOSTER	1000.00	1	1000.00
300	132	58	G GUINNESS	2000.00	1	2000.00
301	132	125	BLUE CURACAO	20000.00	1	20000.00
302	132	138	HENNESSY	40000.00	1	40000.00
303	133	35	Cornchaff	1500.00	1	1500.00
304	134	34	White Beans	2500.00	1	2500.00
305	135	31	Ndole	2500.00	1	2500.00
306	136	28	Snails	5000.00	1	5000.00
307	137	41	Poulet DG 1/4	2500.00	1	2500.00
308	138	36	Koki	1500.00	1	1500.00
309	139	26	Chicken	2500.00	1	2500.00
310	139	37	Kati-Kati	3000.00	1	3000.00
311	139	42	Poulet DG 1/2	5000.00	1	5000.00
312	140	38	Achu	3000.00	3	9000.00
313	140	32	Eru	2500.00	1	2500.00
314	140	27	Goat	3500.00	1	3500.00
315	141	28	Snails	5000.00	1	5000.00
316	142	66	BEAUFORT	1000.00	1	1000.00
317	142	26	Chicken	2500.00	1	2500.00
318	142	44	Simple Complement	500.00	1	500.00
319	143	38	Achu	3000.00	1	3000.00
320	143	32	Eru	2500.00	1	2500.00
321	144	72	1664	1500.00	1	1500.00
322	144	57	BAVARIA	1500.00	1	1500.00
323	144	51	ISENBECK	1000.00	1	1000.00
324	144	69	RED BULL	1500.00	1	1500.00
325	145	35	Cornchaff	1500.00	1	1500.00
326	145	31	Ndole	2500.00	1	2500.00
327	146	35	Cornchaff	1500.00	2	3000.00
328	147	35	Cornchaff	1500.00	1	1500.00
329	147	32	Eru	2500.00	1	2500.00
330	147	31	Ndole	2500.00	1	2500.00
331	148	26	Chicken	2500.00	1	2500.00
332	149	41	Poulet DG 1/4	2500.00	1	2500.00
333	149	66	BEAUFORT	1000.00	1	1000.00
334	149	118	RUINART ROSE	100000.00	1	100000.00
335	150	35	Cornchaff	1500.00	1	1500.00
336	150	70	DOPPLE	1000.00	1	1000.00
337	150	111	JP CHENET (CHAMPAGNE)	15000.00	1	15000.00
338	151	40	Fish	3500.00	1	3500.00
339	151	33	Okro and Egussi	2500.00	1	2500.00
340	151	42	Poulet DG 1/2	5000.00	1	5000.00
341	152	37	Kati-Kati	3000.00	1	3000.00
342	153	26	Chicken	2500.00	1	2500.00
343	153	57	BAVARIA	1500.00	1	1500.00
344	154	40	Fish	3500.00	1	3500.00
345	154	31	Ndole	2500.00	1	2500.00
346	155	26	Chicken	2500.00	1	2500.00
347	155	37	Kati-Kati	3000.00	1	3000.00
348	155	29	Pork	3000.00	1	3000.00
349	155	41	Poulet DG 1/4	2500.00	1	2500.00
350	156	30	Towel	2500.00	1	2500.00
351	156	34	White Beans	2500.00	1	2500.00
352	156	29	Pork	3000.00	1	3000.00
353	156	39	Gambas	7000.00	1	7000.00
354	157	30	Towel	2500.00	1	2500.00
355	157	34	White Beans	2500.00	1	2500.00
356	157	29	Pork	3000.00	1	3000.00
357	157	39	Gambas	7000.00	1	7000.00
358	158	30	Towel	2500.00	1	2500.00
359	158	34	White Beans	2500.00	1	2500.00
360	158	29	Pork	3000.00	1	3000.00
361	158	39	Gambas	7000.00	1	7000.00
362	159	32	Eru	2500.00	1	2500.00
363	159	33	Okro and Egussi	2500.00	1	2500.00
364	159	29	Pork	3000.00	1	3000.00
365	159	72	1664	1500.00	1	1500.00
366	159	57	BAVARIA	1500.00	1	1500.00
367	159	70	DOPPLE	1000.00	1	1000.00
368	159	102	ROBINSON (RED)	10000.00	1	10000.00
369	160	31	Ndole	2500.00	1	2500.00
370	160	30	Towel	2500.00	1	2500.00
371	161	31	Ndole	2500.00	1	2500.00
372	161	30	Towel	2500.00	1	2500.00
373	162	37	Kati-Kati	3000.00	1	3000.00
374	167	35	Cornchaff	1500.00	1	1500.00
375	167	31	Ndole	2500.00	1	2500.00
376	167	34	White Beans	2500.00	1	2500.00
377	168	29	Pork	3000.00	1	3000.00
378	168	55	BOOSTER	1000.00	1	1000.00
379	168	114	MOET BRUT	55000.00	1	55000.00
380	168	99	DOMAINE OLIVER (WHITE)	7000.00	1	7000.00
381	168	102	ROBINSON (RED)	10000.00	1	10000.00
382	168	69	RED BULL	1500.00	1	1500.00
383	169	32	Eru	2500.00	1	2500.00
384	169	31	Ndole	2500.00	1	2500.00
385	169	33	Okro and Egussi	2500.00	1	2500.00
386	169	40	Fish	3500.00	1	3500.00
387	169	44	Simple Complement	500.00	1	500.00
388	169	55	BOOSTER	1000.00	1	1000.00
389	169	58	G GUINNESS	2000.00	1	2000.00
390	169	67	KADJI	1000.00	1	1000.00
391	169	73	SKOLL	1500.00	3	4500.00
392	170	31	Ndole	2500.00	1	2500.00
393	170	33	Okro and Egussi	2500.00	1	2500.00
394	170	34	White Beans	2500.00	1	2500.00
395	170	30	Towel	2500.00	1	2500.00
400	173	40	Fish	3500.00	1	3500.00
401	173	29	Pork	3000.00	1	3000.00
402	173	34	White Beans	2500.00	1	2500.00
396	171	30	Towel	2500.00	1	2500.00
397	172	40	Fish	3500.00	1	3500.00
398	172	29	Pork	3000.00	1	3000.00
399	172	34	White Beans	2500.00	1	2500.00
403	174	35	Cornchaff	1500.00	1	1500.00
404	174	31	Ndole	2500.00	1	2500.00
405	174	33	Okro and Egussi	2500.00	1	2500.00
406	174	34	White Beans	2500.00	1	2500.00
407	175	29	Pork	3000.00	1	3000.00
408	175	34	White Beans	2500.00	1	2500.00
409	175	30	Towel	2500.00	1	2500.00
410	175	28	Snails	5000.00	1	5000.00
411	176	35	Cornchaff	1500.00	1	1500.00
412	177	26	Chicken	2500.00	1	2500.00
413	177	37	Kati-Kati	3000.00	1	3000.00
414	177	41	Poulet DG 1/4	2500.00	1	2500.00
415	178	37	Kati-Kati	3000.00	1	3000.00
416	178	33	Okro and Egussi	2500.00	1	2500.00
417	179	37	Kati-Kati	3000.00	1	3000.00
418	179	29	Pork	3000.00	1	3000.00
419	179	41	Poulet DG 1/4	2500.00	1	2500.00
420	179	36	Koki	1500.00	1	1500.00
421	180	26	Chicken	2500.00	1	2500.00
422	180	40	Fish	3500.00	1	3500.00
423	180	29	Pork	3000.00	1	3000.00
424	181	26	Chicken	2500.00	1	2500.00
425	182	38	Achu	3000.00	1	3000.00
426	183	32	Eru	2500.00	1	2500.00
427	184	28	Snails	5000.00	2	10000.00
428	185	30	Towel	2500.00	1	2500.00
429	185	40	Fish	3500.00	1	3500.00
430	186	33	Okro and Egussi	2500.00	1	2500.00
431	186	31	Ndole	2500.00	1	2500.00
432	186	57	BAVARIA	1500.00	1	1500.00
433	186	61	ICE BLACK	1000.00	1	1000.00
434	186	64	ORIGIN	1000.00	1	1000.00
435	187	28	Snails	5000.00	1	5000.00
436	187	30	Towel	2500.00	1	2500.00
437	187	34	White Beans	2500.00	1	2500.00
438	188	36	Koki	1500.00	1	1500.00
439	188	35	Cornchaff	1500.00	1	1500.00
440	188	33	Okro and Egussi	2500.00	1	2500.00
441	188	34	White Beans	2500.00	1	2500.00
442	189	36	Koki	1500.00	1	1500.00
443	189	35	Cornchaff	1500.00	1	1500.00
444	189	33	Okro and Egussi	2500.00	1	2500.00
445	189	34	White Beans	2500.00	1	2500.00
446	190	36	Koki	1500.00	1	1500.00
447	190	31	Ndole	2500.00	1	2500.00
448	190	33	Okro and Egussi	2500.00	1	2500.00
449	190	30	Towel	2500.00	1	2500.00
450	191	40	Fish	3500.00	1	3500.00
451	191	33	Okro and Egussi	2500.00	1	2500.00
452	191	30	Towel	2500.00	1	2500.00
453	191	53	CASTEL	1000.00	1	1000.00
454	191	71	HEINEKEN	1500.00	1	1500.00
455	191	54	MUTZIG	1000.00	1	1000.00
456	191	74	VK BLUE	1500.00	1	1500.00
457	191	19	Shisha	3500.00	1	3500.00
458	192	40	Fish	3500.00	1	3500.00
459	192	33	Okro and Egussi	2500.00	1	2500.00
460	192	30	Towel	2500.00	1	2500.00
461	193	35	Cornchaff	1500.00	1	1500.00
462	194	34	White Beans	2500.00	1	2500.00
463	194	30	Towel	2500.00	1	2500.00
464	194	28	Snails	5000.00	1	5000.00
465	194	41	Poulet DG 1/4	2500.00	1	2500.00
466	194	42	Poulet DG 1/2	5000.00	1	5000.00
467	194	43	Poulet DG 1	10000.00	1	10000.00
468	195	34	White Beans	2500.00	1	2500.00
469	195	29	Pork	3000.00	1	3000.00
470	195	39	Gambas	7000.00	1	7000.00
471	195	53	CASTEL	1000.00	1	1000.00
472	195	71	HEINEKEN	1500.00	1	1500.00
473	195	74	VK BLUE	1500.00	1	1500.00
474	196	29	Pork	3000.00	1	3000.00
475	197	30	Towel	2500.00	1	2500.00
476	198	32	Eru	2500.00	1	2500.00
477	199	36	Koki	1500.00	1	1500.00
478	199	28	Snails	5000.00	1	5000.00
479	200	36	Koki	1500.00	1	1500.00
480	200	28	Snails	5000.00	1	5000.00
481	201	34	White Beans	2500.00	1	2500.00
482	202	26	Chicken	2500.00	1	2500.00
483	202	36	Koki	1500.00	1	1500.00
484	203	33	Okro and Egussi	2500.00	1	2500.00
485	203	29	Pork	3000.00	1	3000.00
486	204	40	Fish	3500.00	1	3500.00
487	204	32	Eru	2500.00	1	2500.00
488	204	35	Cornchaff	1500.00	1	1500.00
489	205	34	White Beans	2500.00	1	2500.00
490	206	33	Okro and Egussi	2500.00	1	2500.00
491	206	32	Eru	2500.00	1	2500.00
492	206	38	Achu	3000.00	1	3000.00
493	206	55	BOOSTER	1000.00	1	1000.00
494	206	56	BOOSTER CANNETTE	1500.00	1	1500.00
495	207	30	Towel	2500.00	1	2500.00
496	207	55	BOOSTER	1000.00	1	1000.00
497	207	19	Shisha	3500.00	1	3500.00
498	208	26	Chicken	2500.00	1	2500.00
499	208	39	Gambas	7000.00	1	7000.00
500	208	23	Salade Simple	1500.00	1	1500.00
501	209	32	Eru	2500.00	1	2500.00
502	209	37	Kati-Kati	3000.00	1	3000.00
503	210	40	Fish	3500.00	1	3500.00
504	211	26	Chicken	2500.00	1	2500.00
505	211	37	Kati-Kati	3000.00	1	3000.00
506	211	42	Poulet DG 1/2	5000.00	1	5000.00
507	212	38	Achu	3000.00	1	3000.00
508	212	32	Eru	2500.00	1	2500.00
509	212	27	Goat	3500.00	1	3500.00
510	212	72	1664	1500.00	1	1500.00
511	212	55	BOOSTER	1000.00	1	1000.00
512	212	68	CASTLE	1000.00	1	1000.00
513	213	27	Goat	3500.00	1	3500.00
514	213	31	Ndole	2500.00	1	2500.00
515	214	39	Gambas	7000.00	1	7000.00
516	214	35	Cornchaff	1500.00	1	1500.00
517	215	37	Kati-Kati	3000.00	1	3000.00
518	215	33	Okro and Egussi	2500.00	1	2500.00
519	216	32	Eru	2500.00	1	2500.00
520	216	28	Snails	5000.00	1	5000.00
521	216	30	Towel	2500.00	1	2500.00
522	217	35	Cornchaff	1500.00	1	1500.00
523	217	37	Kati-Kati	3000.00	1	3000.00
524	217	53	CASTEL	1000.00	1	1000.00
525	217	71	HEINEKEN	1500.00	1	1500.00
526	217	54	MUTZIG	1000.00	1	1000.00
527	217	74	VK BLUE	1500.00	1	1500.00
528	218	28	Snails	5000.00	1	5000.00
529	218	41	Poulet DG 1/4	2500.00	1	2500.00
530	218	42	Poulet DG 1/2	5000.00	1	5000.00
531	218	43	Poulet DG 1	10000.00	1	10000.00
532	219	33	Okro and Egussi	2500.00	1	2500.00
533	219	35	Cornchaff	1500.00	2	3000.00
534	220	33	Okro and Egussi	2500.00	1	2500.00
535	220	35	Cornchaff	1500.00	2	3000.00
536	221	32	Eru	2500.00	1	2500.00
537	221	40	Fish	3500.00	1	3500.00
538	221	34	White Beans	2500.00	1	2500.00
539	222	38	Achu	3000.00	1	3000.00
540	222	35	Cornchaff	1500.00	1	1500.00
541	222	36	Koki	1500.00	2	3000.00
542	223	31	Ndole	2500.00	1	2500.00
543	223	30	Towel	2500.00	1	2500.00
544	223	34	White Beans	2500.00	1	2500.00
545	224	33	Okro and Egussi	2500.00	1	2500.00
546	225	33	Okro and Egussi	2500.00	1	2500.00
547	225	30	Towel	2500.00	1	2500.00
548	226	37	Kati-Kati	3000.00	1	3000.00
549	226	42	Poulet DG 1/2	5000.00	1	5000.00
550	227	40	Fish	3500.00	1	3500.00
551	227	42	Poulet DG 1/2	5000.00	1	5000.00
552	227	41	Poulet DG 1/4	2500.00	1	2500.00
553	228	37	Kati-Kati	3000.00	1	3000.00
554	228	33	Okro and Egussi	2500.00	1	2500.00
555	229	37	Kati-Kati	3000.00	1	3000.00
556	229	33	Okro and Egussi	2500.00	1	2500.00
557	230	31	Ndole	2500.00	1	2500.00
558	230	43	Poulet DG 1	10000.00	1	10000.00
559	230	42	Poulet DG 1/2	5000.00	1	5000.00
560	230	40	Fish	3500.00	1	3500.00
561	230	57	BAVARIA	1500.00	1	1500.00
562	230	70	DOPPLE	1000.00	1	1000.00
563	230	65	HARP	1000.00	1	1000.00
564	230	62	ICE PINEAPPLE	1000.00	1	1000.00
565	231	32	Eru	2500.00	1	2500.00
566	231	31	Ndole	2500.00	1	2500.00
567	231	33	Okro and Egussi	2500.00	1	2500.00
568	231	34	White Beans	2500.00	1	2500.00
569	232	28	Snails	5000.00	1	5000.00
570	232	31	Ndole	2500.00	1	2500.00
571	232	33	Okro and Egussi	2500.00	1	2500.00
572	232	55	BOOSTER	1000.00	1	1000.00
573	232	56	BOOSTER CANNETTE	1500.00	1	1500.00
574	232	60	MALTA	1000.00	3	3000.00
575	233	33	Okro and Egussi	2500.00	1	2500.00
576	233	39	Gambas	7000.00	1	7000.00
577	233	66	BEAUFORT	1000.00	1	1000.00
578	233	70	DOPPLE	1000.00	1	1000.00
579	233	64	ORIGIN	1000.00	1	1000.00
580	234	53	CASTEL	1000.00	2	2000.00
581	234	71	HEINEKEN	1500.00	1	1500.00
582	234	54	MUTZIG	1000.00	2	2000.00
583	234	74	VK BLUE	1500.00	1	1500.00
584	235	31	Ndole	2500.00	1	2500.00
585	236	40	Fish	3500.00	1	3500.00
586	236	33	Okro and Egussi	2500.00	1	2500.00
587	237	27	Goat	3500.00	1	3500.00
588	237	37	Kati-Kati	3000.00	1	3000.00
589	237	33	Okro and Egussi	2500.00	1	2500.00
590	238	42	Poulet DG 1/2	5000.00	1	5000.00
591	238	37	Kati-Kati	3000.00	1	3000.00
592	238	72	1664	1500.00	1	1500.00
593	238	64	ORIGIN	1000.00	2	2000.00
594	239	33	Okro and Egussi	2500.00	1	2500.00
595	239	40	Fish	3500.00	1	3500.00
596	239	28	Snails	5000.00	1	5000.00
597	239	56	BOOSTER CANNETTE	1500.00	1	1500.00
598	239	65	HARP	1000.00	1	1000.00
599	239	60	MALTA	1000.00	1	1000.00
600	239	63	SMOOTH	1500.00	1	1500.00
601	239	88	BAOBA	2000.00	1	2000.00
602	239	89	CASSIMANGO	2000.00	1	2000.00
603	240	36	Koki	1500.00	1	1500.00
604	240	28	Snails	5000.00	1	5000.00
605	240	55	BOOSTER	1000.00	1	1000.00
606	240	65	HARP	1000.00	1	1000.00
607	240	54	MUTZIG	1000.00	1	1000.00
608	241	26	Chicken	2500.00	1	2500.00
609	241	66	BEAUFORT	1000.00	1	1000.00
610	241	52	EXPORT	1000.00	1	1000.00
611	241	51	ISENBECK	1000.00	1	1000.00
612	241	59	P GUINNESS	1000.00	1	1000.00
613	241	63	SMOOTH	1500.00	1	1500.00
614	242	26	Chicken	2500.00	1	2500.00
615	242	36	Koki	1500.00	1	1500.00
616	242	28	Snails	5000.00	1	5000.00
617	242	30	Towel	2500.00	1	2500.00
618	242	53	CASTEL	1000.00	2	2000.00
619	242	71	HEINEKEN	1500.00	1	1500.00
620	242	54	MUTZIG	1000.00	1	1000.00
621	242	74	VK BLUE	1500.00	1	1500.00
622	243	36	Koki	1500.00	1	1500.00
623	243	41	Poulet DG 1/4	2500.00	1	2500.00
624	243	28	Snails	5000.00	1	5000.00
625	243	30	Towel	2500.00	1	2500.00
626	243	55	BOOSTER	1000.00	1	1000.00
627	243	56	BOOSTER CANNETTE	1500.00	1	1500.00
628	243	65	HARP	1000.00	1	1000.00
629	243	54	MUTZIG	1000.00	1	1000.00
630	244	28	Snails	5000.00	1	5000.00
631	244	33	Okro and Egussi	2500.00	1	2500.00
632	244	66	BEAUFORT	1000.00	1	1000.00
633	244	55	BOOSTER	1000.00	1	1000.00
634	244	58	G GUINNESS	2000.00	1	2000.00
635	244	67	KADJI	1000.00	1	1000.00
636	245	28	Snails	5000.00	1	5000.00
637	245	33	Okro and Egussi	2500.00	1	2500.00
638	245	66	BEAUFORT	1000.00	1	1000.00
639	245	55	BOOSTER	1000.00	1	1000.00
640	245	58	G GUINNESS	2000.00	1	2000.00
641	245	67	KADJI	1000.00	1	1000.00
642	246	41	Poulet DG 1/4	2500.00	1	2500.00
643	246	28	Snails	5000.00	1	5000.00
644	246	30	Towel	2500.00	1	2500.00
645	246	34	White Beans	2500.00	1	2500.00
646	246	72	1664	1500.00	1	1500.00
647	246	68	CASTLE	1000.00	1	1000.00
648	246	61	ICE BLACK	1000.00	1	1000.00
649	246	64	ORIGIN	1000.00	1	1000.00
650	247	35	Cornchaff	1500.00	1	1500.00
651	247	32	Eru	2500.00	1	2500.00
652	247	39	Gambas	7000.00	1	7000.00
653	247	66	BEAUFORT	1000.00	1	1000.00
654	247	52	EXPORT	1000.00	1	1000.00
655	247	59	P GUINNESS	1000.00	1	1000.00
656	247	63	SMOOTH	1500.00	2	3000.00
657	248	39	Gambas	7000.00	1	7000.00
658	248	29	Pork	3000.00	1	3000.00
659	248	34	White Beans	2500.00	1	2500.00
660	248	53	CASTEL	1000.00	1	1000.00
661	248	71	HEINEKEN	1500.00	1	1500.00
662	248	74	VK BLUE	1500.00	1	1500.00
663	248	80	COCACOLA PM	500.00	1	500.00
664	248	78	WATER 0.5L	500.00	1	500.00
665	248	88	BAOBA	2000.00	1	2000.00
666	248	85	MANGUE	2000.00	1	2000.00
667	248	109	CALVET (RED)	10000.00	1	10000.00
668	248	99	DOMAINE OLIVER (WHITE)	7000.00	1	7000.00
669	249	36	Koki	1500.00	1	1500.00
670	250	40	Fish	3500.00	1	3500.00
671	250	39	Gambas	7000.00	1	7000.00
672	251	28	Snails	5000.00	1	5000.00
673	252	37	Kati-Kati	3000.00	1	3000.00
674	252	31	Ndole	2500.00	1	2500.00
675	253	40	Fish	3500.00	1	3500.00
676	253	29	Pork	3000.00	1	3000.00
677	254	40	Fish	3500.00	1	3500.00
678	254	36	Koki	1500.00	1	1500.00
679	254	66	BEAUFORT	1000.00	1	1000.00
680	254	56	BOOSTER CANNETTE	1500.00	1	1500.00
681	254	68	CASTLE	1000.00	1	1000.00
682	254	65	HARP	1000.00	1	1000.00
683	254	51	ISENBECK	1000.00	1	1000.00
684	255	40	Fish	3500.00	1	3500.00
685	255	36	Koki	1500.00	1	1500.00
686	255	66	BEAUFORT	1000.00	1	1000.00
687	255	56	BOOSTER CANNETTE	1500.00	1	1500.00
688	255	68	CASTLE	1000.00	1	1000.00
689	255	65	HARP	1000.00	1	1000.00
690	255	51	ISENBECK	1000.00	1	1000.00
691	256	26	Chicken	2500.00	1	2500.00
692	256	40	Fish	3500.00	1	3500.00
693	256	31	Ndole	2500.00	1	2500.00
694	256	57	BAVARIA	1500.00	1	1500.00
695	256	56	BOOSTER CANNETTE	1500.00	1	1500.00
696	256	70	DOPPLE	1000.00	1	1000.00
697	256	65	HARP	1000.00	1	1000.00
698	256	62	ICE PINEAPPLE	1000.00	1	1000.00
699	257	36	Koki	1500.00	1	1500.00
700	257	41	Poulet DG 1/4	2500.00	1	2500.00
701	257	28	Snails	5000.00	1	5000.00
702	258	37	Kati-Kati	3000.00	1	3000.00
703	258	42	Poulet DG 1/2	5000.00	1	5000.00
704	258	41	Poulet DG 1/4	2500.00	1	2500.00
705	258	28	Snails	5000.00	1	5000.00
706	259	37	Kati-Kati	3000.00	1	3000.00
707	259	42	Poulet DG 1/2	5000.00	1	5000.00
708	259	41	Poulet DG 1/4	2500.00	1	2500.00
709	259	28	Snails	5000.00	1	5000.00
710	260	37	Kati-Kati	3000.00	1	3000.00
711	260	42	Poulet DG 1/2	5000.00	1	5000.00
712	260	41	Poulet DG 1/4	2500.00	1	2500.00
713	260	28	Snails	5000.00	1	5000.00
714	261	37	Kati-Kati	3000.00	1	3000.00
715	261	42	Poulet DG 1/2	5000.00	1	5000.00
716	261	41	Poulet DG 1/4	2500.00	1	2500.00
717	261	28	Snails	5000.00	1	5000.00
718	262	32	Eru	2500.00	1	2500.00
719	262	40	Fish	3500.00	1	3500.00
720	262	36	Koki	1500.00	1	1500.00
721	263	32	Eru	2500.00	1	2500.00
722	263	40	Fish	3500.00	1	3500.00
723	263	36	Koki	1500.00	1	1500.00
724	264	32	Eru	2500.00	1	2500.00
725	264	40	Fish	3500.00	1	3500.00
726	264	36	Koki	1500.00	1	1500.00
727	265	32	Eru	2500.00	1	2500.00
728	265	40	Fish	3500.00	1	3500.00
729	265	36	Koki	1500.00	1	1500.00
730	266	32	Eru	2500.00	1	2500.00
731	266	40	Fish	3500.00	1	3500.00
732	266	36	Koki	1500.00	1	1500.00
733	267	32	Eru	2500.00	1	2500.00
734	267	40	Fish	3500.00	1	3500.00
735	267	36	Koki	1500.00	1	1500.00
736	268	32	Eru	2500.00	1	2500.00
737	268	40	Fish	3500.00	1	3500.00
738	268	36	Koki	1500.00	1	1500.00
739	269	32	Eru	2500.00	1	2500.00
740	269	40	Fish	3500.00	1	3500.00
741	269	36	Koki	1500.00	1	1500.00
742	270	32	Eru	2500.00	1	2500.00
743	270	40	Fish	3500.00	1	3500.00
744	270	36	Koki	1500.00	1	1500.00
745	271	32	Eru	2500.00	1	2500.00
746	271	40	Fish	3500.00	1	3500.00
747	271	36	Koki	1500.00	1	1500.00
748	272	32	Eru	2500.00	1	2500.00
749	272	40	Fish	3500.00	1	3500.00
750	272	36	Koki	1500.00	1	1500.00
751	273	37	Kati-Kati	3000.00	1	3000.00
752	273	42	Poulet DG 1/2	5000.00	1	5000.00
753	273	41	Poulet DG 1/4	2500.00	1	2500.00
754	273	28	Snails	5000.00	1	5000.00
755	274	37	Kati-Kati	3000.00	1	3000.00
756	274	42	Poulet DG 1/2	5000.00	1	5000.00
757	274	41	Poulet DG 1/4	2500.00	1	2500.00
758	274	28	Snails	5000.00	1	5000.00
759	275	37	Kati-Kati	3000.00	1	3000.00
760	275	42	Poulet DG 1/2	5000.00	1	5000.00
761	275	41	Poulet DG 1/4	2500.00	1	2500.00
762	275	28	Snails	5000.00	1	5000.00
763	276	37	Kati-Kati	3000.00	1	3000.00
764	276	42	Poulet DG 1/2	5000.00	1	5000.00
765	276	41	Poulet DG 1/4	2500.00	1	2500.00
766	276	28	Snails	5000.00	1	5000.00
767	277	37	Kati-Kati	3000.00	1	3000.00
768	277	42	Poulet DG 1/2	5000.00	1	5000.00
769	277	41	Poulet DG 1/4	2500.00	1	2500.00
770	277	28	Snails	5000.00	1	5000.00
771	278	38	Achu	3000.00	1	3000.00
772	278	40	Fish	3500.00	1	3500.00
773	278	41	Poulet DG 1/4	2500.00	1	2500.00
774	279	32	Eru	2500.00	1	2500.00
775	279	55	BOOSTER	1000.00	1	1000.00
776	279	56	BOOSTER CANNETTE	1500.00	1	1500.00
777	279	71	HEINEKEN	1500.00	1	1500.00
778	280	32	Eru	2500.00	1	2500.00
779	280	55	BOOSTER	1000.00	1	1000.00
780	280	56	BOOSTER CANNETTE	1500.00	1	1500.00
781	280	71	HEINEKEN	1500.00	1	1500.00
782	281	38	Achu	3000.00	1	3000.00
783	281	26	Chicken	2500.00	1	2500.00
784	281	39	Gambas	7000.00	1	7000.00
785	281	55	BOOSTER	1000.00	1	1000.00
786	281	68	CASTLE	1000.00	1	1000.00
787	281	58	G GUINNESS	2000.00	1	2000.00
788	281	61	ICE BLACK	1000.00	1	1000.00
789	281	83	GRENADINE	1000.00	1	1000.00
790	281	101	BALLART DE GUEST (RED)	12000.00	1	12000.00
791	281	126	ABSOLUT VODKA	20000.00	1	20000.00
792	281	87	ANANA PASSION	2000.00	1	2000.00
793	281	91	COCKTAIL	2000.00	1	2000.00
794	281	19	Shisha	3500.00	1	3500.00
795	283	56	BOOSTER CANNETTE	1500.00	1	1500.00
796	284	56	BOOSTER CANNETTE	1500.00	6	9000.00
797	285	66	BEAUFORT	1000.00	1	1000.00
798	286	52	EXPORT	1000.00	1	1000.00
799	287	52	EXPORT	1000.00	3	3000.00
800	288	66	BEAUFORT	1000.00	1	1000.00
801	288	52	EXPORT	1000.00	1	1000.00
802	288	51	ISENBECK	1000.00	1	1000.00
803	288	73	SKOLL	1500.00	1	1500.00
804	288	91	COCKTAIL	2000.00	1	2000.00
805	288	90	GOYAVE	2000.00	1	2000.00
806	288	39	Gambas	7000.00	1	7000.00
807	288	29	Pork	3000.00	1	3000.00
808	288	34	White Beans	2500.00	1	2500.00
809	289	66	BEAUFORT	1000.00	3	3000.00
810	289	52	EXPORT	1000.00	1	1000.00
811	289	51	ISENBECK	1000.00	1	1000.00
812	289	73	SKOLL	1500.00	1	1500.00
813	289	91	COCKTAIL	2000.00	1	2000.00
814	289	90	GOYAVE	2000.00	1	2000.00
815	289	39	Gambas	7000.00	1	7000.00
816	289	29	Pork	3000.00	1	3000.00
817	289	34	White Beans	2500.00	1	2500.00
818	290	65	HARP	1000.00	1	1000.00
819	290	60	MALTA	1000.00	1	1000.00
820	290	63	SMOOTH	1500.00	1	1500.00
821	291	57	BAVARIA	1500.00	1	1500.00
822	291	58	G GUINNESS	2000.00	1	2000.00
823	291	60	MALTA	1000.00	1	1000.00
824	292	53	CASTEL	1000.00	1	1000.00
825	292	54	MUTZIG	1000.00	1	1000.00
826	292	74	VK BLUE	1500.00	1	1500.00
827	293	56	BOOSTER CANNETTE	1500.00	1	1500.00
828	293	71	HEINEKEN	1500.00	1	1500.00
829	293	74	VK BLUE	1500.00	1	1500.00
830	294	55	BOOSTER	1000.00	1	1000.00
831	294	54	MUTZIG	1000.00	1	1000.00
832	295	55	BOOSTER	1000.00	1	1000.00
833	295	65	HARP	1000.00	1	1000.00
834	295	54	MUTZIG	1000.00	1	1000.00
835	296	67	KADJI	1000.00	1	1000.00
836	296	63	SMOOTH	1500.00	1	1500.00
837	297	58	G GUINNESS	2000.00	1	2000.00
838	297	60	MALTA	1000.00	1	1000.00
839	297	74	VK BLUE	1500.00	1	1500.00
840	298	58	G GUINNESS	2000.00	1	2000.00
841	298	60	MALTA	1000.00	1	1000.00
842	298	74	VK BLUE	1500.00	1	1500.00
843	299	58	G GUINNESS	2000.00	2	4000.00
844	299	60	MALTA	1000.00	1	1000.00
845	299	74	VK BLUE	1500.00	1	1500.00
846	299	55	BOOSTER	1000.00	1	1000.00
847	299	67	KADJI	1000.00	1	1000.00
848	299	73	SKOLL	1500.00	1	1500.00
849	299	69	RED BULL	1500.00	1	1500.00
850	299	59	P GUINNESS	1000.00	6	6000.00
851	300	58	G GUINNESS	2000.00	2	4000.00
852	300	60	MALTA	1000.00	1	1000.00
853	300	74	VK BLUE	1500.00	1	1500.00
854	300	55	BOOSTER	1000.00	1	1000.00
855	300	67	KADJI	1000.00	1	1000.00
856	300	73	SKOLL	1500.00	1	1500.00
857	300	69	RED BULL	1500.00	1	1500.00
858	300	59	P GUINNESS	1000.00	6	6000.00
859	301	58	G GUINNESS	2000.00	1	2000.00
860	301	63	SMOOTH	1500.00	1	1500.00
861	302	58	G GUINNESS	2000.00	1	2000.00
862	302	63	SMOOTH	1500.00	1	1500.00
863	303	58	G GUINNESS	2000.00	1	2000.00
864	303	63	SMOOTH	1500.00	1	1500.00
865	304	55	BOOSTER	1000.00	1	1000.00
867	306	55	BOOSTER	1000.00	1	1000.00
868	307	74	VK BLUE	1500.00	1	1500.00
870	309	53	CASTEL	1000.00	1	1000.00
871	309	71	HEINEKEN	1500.00	1	1500.00
872	309	54	MUTZIG	1000.00	1	1000.00
873	309	74	VK BLUE	1500.00	1	1500.00
876	312	72	1664	1500.00	1	1500.00
877	312	70	DOPPLE	1000.00	1	1000.00
878	312	51	ISENBECK	1000.00	1	1000.00
879	312	69	RED BULL	1500.00	1	1500.00
866	305	55	BOOSTER	1000.00	1	1000.00
869	308	74	VK BLUE	1500.00	1	1500.00
874	310	9999	Manual Payment	0.00	1	0.00
875	311	9999	Manual Payment	0.00	1	0.00
880	313	57	BAVARIA	1500.00	1	1500.00
881	314	9999	Manual Payment	0.00	1	0.00
882	315	9999	Manual Payment	0.00	1	0.00
\.


--
-- Data for Name: sales; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.sales (id, tenant_id, branch_id, cashier_id, status, payment_method, subtotal, total, payment_summary, created_at, paid_at, receipt_no, discount_total, discount_reason, complimentary_total, tendered_total, change_amount, unpaid_amount) FROM stdin;
3	2	1	1	pending_payment	xafpay	2500.00	2500.00	\N	2025-12-17 13:43:30.08617-05	\N	R-0201-1225-00001	0.00	\N	0.00	0.00	0.00	0.00
4	2	1	1	paid	cash	7000.00	7000.00	\N	2025-12-17 14:55:05.532247-05	\N	R-0201-1225-00002	0.00	\N	0.00	0.00	0.00	0.00
5	2	1	1	paid	cash	22000.00	22000.00	\N	2025-12-17 15:13:38.980842-05	\N	R-0201-1225-00003	0.00	\N	0.00	0.00	0.00	0.00
6	2	1	1	pending_payment	xafpay	7000.00	7000.00	\N	2025-12-17 15:14:25.491963-05	\N	R-0201-1225-00004	0.00	\N	0.00	0.00	0.00	0.00
7	2	1	1	pending_payment	xafpay	5000.00	5000.00	\N	2025-12-17 15:16:50.614066-05	\N	R-0201-1225-00005	0.00	\N	0.00	0.00	0.00	0.00
8	2	1	1	paid	cash	5000.00	5000.00	\N	2025-12-17 15:17:12.499307-05	\N	R-0201-1225-00006	0.00	\N	0.00	0.00	0.00	0.00
9	2	1	1	paid	cash	9000.00	9000.00	\N	2025-12-17 15:47:18.573308-05	\N	R-0201-1225-00007	0.00	\N	0.00	0.00	0.00	0.00
10	2	1	1	paid	cash	2500.00	2500.00	\N	2025-12-17 15:48:02.942366-05	\N	R-0201-1225-00008	0.00	\N	0.00	0.00	0.00	0.00
11	2	1	1	paid	cash	27000.00	27000.00	\N	2025-12-17 16:00:38.012971-05	\N	R-0201-1225-00009	0.00	\N	0.00	0.00	0.00	0.00
12	2	1	1	paid	cash	3500.00	3500.00	\N	2025-12-17 16:09:26.109199-05	\N	R-0201-1225-00010	0.00	\N	0.00	0.00	0.00	0.00
15	2	1	1	paid	cash	2500.00	2500.00	\N	2025-12-17 16:45:05.980013-05	\N	R-0201-1225-00011	0.00	\N	0.00	0.00	0.00	0.00
16	2	1	1	paid	cash	3500.00	3500.00	\N	2025-12-17 16:49:32.486255-05	\N	R-0201-1225-00012	0.00	\N	0.00	0.00	0.00	0.00
17	2	1	1	pending_payment	xafpay	7000.00	7000.00	\N	2025-12-17 16:56:44.10499-05	\N	R-0201-1225-00013	0.00	\N	0.00	0.00	0.00	0.00
18	2	1	1	paid	cash	2500.00	2500.00	\N	2025-12-17 19:04:19.550126-05	\N	R-0201-1225-00014	0.00	\N	0.00	0.00	0.00	0.00
19	2	1	1	paid	cash	6500.00	6500.00	\N	2025-12-17 19:10:26.457537-05	\N	R-0201-1225-00015	0.00	\N	0.00	0.00	0.00	0.00
20	2	1	1	paid	cash	7000.00	7000.00	\N	2025-12-17 19:13:35.465789-05	\N	R-0201-1225-00016	0.00	\N	0.00	0.00	0.00	0.00
21	2	1	1	paid	cash	100000.00	100000.00	\N	2025-12-17 19:19:50.49921-05	\N	R-0201-1225-00017	0.00	\N	0.00	0.00	0.00	0.00
22	2	1	1	paid	cash	1500.00	1500.00	\N	2025-12-17 19:30:23.117071-05	\N	R-0201-1225-00018	0.00	\N	0.00	0.00	0.00	0.00
23	2	1	1	paid	cash	2500.00	2500.00	\N	2025-12-17 19:34:03.150464-05	\N	R-0201-1225-00019	0.00	\N	0.00	0.00	0.00	0.00
24	2	1	1	paid	cash	3500.00	3500.00	\N	2025-12-17 19:35:51.862282-05	\N	R-0201-1225-00020	0.00	\N	0.00	0.00	0.00	0.00
25	2	1	1	paid	cash	2500.00	2500.00	\N	2025-12-17 19:38:04.137978-05	\N	R-0201-1225-00021	0.00	\N	0.00	0.00	0.00	0.00
26	2	1	1	paid	cash	3000.00	3000.00	\N	2025-12-17 19:50:49.688581-05	\N	R-0201-1225-00022	0.00	\N	0.00	0.00	0.00	0.00
27	2	1	1	paid	cash	14000.00	14000.00	\N	2025-12-18 01:53:07.224677-05	\N	R-0201-1225-00023	0.00	\N	0.00	0.00	0.00	0.00
28	2	1	1	paid	cash	100000.00	100000.00	\N	2025-12-18 02:08:25.083333-05	\N	R-0201-1225-00024	0.00	\N	0.00	0.00	0.00	0.00
29	2	1	1	paid	cash	12000.00	12000.00	\N	2025-12-18 02:23:34.21726-05	\N	R-0201-1225-00025	0.00	\N	0.00	0.00	0.00	0.00
30	2	1	1	paid	cash	3000.00	3000.00	\N	2025-12-18 02:32:00.306351-05	\N	R-0201-1225-00026	0.00	\N	0.00	0.00	0.00	0.00
31	2	1	1	paid	cash	2500.00	2500.00	\N	2025-12-18 03:00:22.841555-05	\N	R-0201-1225-00027	0.00	\N	0.00	0.00	0.00	0.00
32	2	1	1	paid	cash	10000.00	10000.00	\N	2025-12-18 03:01:34.022559-05	\N	R-0201-1225-00028	0.00	\N	0.00	0.00	0.00	0.00
33	2	1	1	paid	cash	7000.00	7000.00	\N	2025-12-18 03:23:26.619039-05	\N	R-0201-1225-00029	0.00	\N	0.00	0.00	0.00	0.00
34	2	1	1	paid	cash	7500.00	7500.00	\N	2025-12-18 12:42:31.073509-05	\N	R-0201-1225-00030	0.00	\N	0.00	0.00	0.00	0.00
35	2	1	1	paid	cash	1500.00	1500.00	\N	2025-12-18 12:47:09.178427-05	\N	R-0201-1225-00031	0.00	\N	0.00	0.00	0.00	0.00
36	2	1	1	paid	cash	15000.00	15000.00	\N	2025-12-18 12:51:36.945699-05	\N	R-0201-1225-00032	0.00	\N	0.00	0.00	0.00	0.00
37	2	1	1	paid	cash	8000.00	8000.00	\N	2025-12-18 13:21:34.698899-05	\N	R-0201-1225-00033	0.00	\N	0.00	0.00	0.00	0.00
38	2	1	1	paid	cash	2500.00	2500.00	\N	2025-12-18 13:24:42.405992-05	\N	R-0201-1225-00034	0.00	\N	0.00	0.00	0.00	0.00
39	2	1	1	paid	cash	9500.00	9500.00	\N	2025-12-19 04:23:39.886428-05	\N	R-0201-1225-00035	0.00	\N	0.00	0.00	0.00	0.00
40	2	1	1	paid	cash	16500.00	16500.00	\N	2025-12-19 04:28:48.677465-05	\N	R-0201-1225-00036	0.00	\N	0.00	0.00	0.00	0.00
41	2	1	1	paid	cash	330000.00	330000.00	\N	2025-12-20 13:51:12.559348-05	\N	R-0201-1225-00037	0.00	\N	0.00	0.00	0.00	0.00
42	2	1	1	paid	cash	10000.00	10000.00	\N	2025-12-21 15:06:43.460243-05	\N	R-0201-1225-00038	0.00	\N	0.00	0.00	0.00	0.00
43	2	1	1	paid	cash	17000.00	17000.00	\N	2025-12-21 15:18:35.375045-05	\N	R-0201-1225-00039	0.00	\N	0.00	0.00	0.00	0.00
44	2	1	1	paid	cash	59000.00	59000.00	\N	2025-12-21 18:30:02.505311-05	\N	R-0201-1225-00040	0.00	\N	0.00	0.00	0.00	0.00
45	2	1	1	paid	cash	8000.00	8000.00	\N	2025-12-22 02:59:22.425414-05	\N	R-0201-1225-00041	0.00	\N	0.00	0.00	0.00	0.00
46	2	1	1	paid	cash	29500.00	29500.00	\N	2025-12-22 05:49:08.956486-05	\N	R-0201-1225-00042	0.00	\N	0.00	0.00	0.00	0.00
47	2	1	1	paid	cash	9500.00	9500.00	\N	2025-12-22 06:04:57.084512-05	\N	R-0201-1225-00043	0.00	\N	0.00	0.00	0.00	0.00
48	2	1	1	paid	cash	17500.00	17500.00	\N	2025-12-25 03:05:05.851519-05	\N	R-0201-1225-00044	0.00	\N	0.00	0.00	0.00	0.00
49	2	1	1	paid	cash	2500.00	2500.00	\N	2025-12-25 18:43:18.871442-05	\N	R-0201-1225-00045	0.00	\N	0.00	0.00	0.00	0.00
50	2	1	1	paid	cash	66000.00	66000.00	\N	2025-12-25 18:44:04.581233-05	\N	R-0201-1225-00046	0.00	\N	0.00	0.00	0.00	0.00
51	2	1	1	paid	cash	66000.00	66000.00	\N	2025-12-25 18:44:31.860852-05	\N	R-0201-1225-00047	0.00	\N	0.00	0.00	0.00	0.00
52	2	1	1	paid	cash	15500.00	15500.00	\N	2025-12-25 19:35:35.717366-05	\N	R-0201-1225-00048	0.00	\N	0.00	0.00	0.00	0.00
53	2	1	1	paid	cash	7500.00	7500.00	\N	2025-12-25 19:35:54.71461-05	\N	R-0201-1225-00049	0.00	\N	0.00	0.00	0.00	0.00
54	2	1	1	paid	cash	9000.00	9000.00	\N	2025-12-25 19:55:02.916932-05	\N	R-0201-1225-00050	0.00	\N	0.00	0.00	0.00	0.00
55	2	1	1	paid	cash	10000.00	10000.00	\N	2025-12-25 19:55:17.627866-05	\N	R-0201-1225-00051	0.00	\N	0.00	0.00	0.00	0.00
56	2	1	1	paid	cash	8000.00	8000.00	\N	2025-12-25 20:02:04.529153-05	\N	R-0201-1225-00052	0.00	\N	0.00	0.00	0.00	0.00
57	2	1	1	paid	cash	30000.00	30000.00	\N	2025-12-25 20:27:16.330426-05	\N	R-0201-1225-00053	0.00	\N	0.00	0.00	0.00	0.00
58	2	1	1	paid	cash	13500.00	13500.00	\N	2025-12-25 20:40:02.494109-05	\N	R-0201-1225-00054	0.00	\N	0.00	0.00	0.00	0.00
59	2	1	1	paid	cash	25000.00	25000.00	\N	2025-12-25 21:10:18.177302-05	\N	R-0201-1225-00055	0.00	\N	0.00	0.00	0.00	0.00
60	2	1	1	paid	cash	6000.00	6000.00	\N	2025-12-25 22:07:15.326229-05	\N	R-0201-1225-00056	0.00	\N	0.00	0.00	0.00	0.00
61	2	1	1	paid	cash	11500.00	11500.00	\N	2025-12-25 22:07:55.327029-05	\N	R-0201-1225-00057	0.00	\N	0.00	0.00	0.00	0.00
62	2	1	1	paid	cash	51500.00	51500.00	\N	2025-12-25 22:18:40.271689-05	\N	R-0201-1225-00058	0.00	\N	0.00	0.00	0.00	0.00
63	2	1	1	paid	cash	15500.00	15500.00	\N	2025-12-25 22:20:47.625532-05	\N	R-0201-1225-00059	0.00	\N	0.00	0.00	0.00	0.00
64	2	1	1	paid	cash	15500.00	15500.00	\N	2025-12-25 22:38:48.721214-05	\N	R-0201-1225-00060	0.00	\N	0.00	0.00	0.00	0.00
65	2	1	1	paid	cash	10000.00	10000.00	\N	2025-12-25 22:39:04.320215-05	\N	R-0201-1225-00061	0.00	\N	0.00	0.00	0.00	0.00
66	2	1	1	paid	cash	13000.00	13000.00	\N	2025-12-25 22:43:10.98468-05	\N	R-0201-1225-00062	0.00	\N	0.00	0.00	0.00	0.00
67	2	1	1	paid	cash	54500.00	54500.00	\N	2025-12-25 23:06:15.90765-05	\N	R-0201-1225-00063	0.00	\N	0.00	0.00	0.00	0.00
68	2	1	1	paid	cash	7500.00	7500.00	\N	2025-12-25 23:20:50.739715-05	\N	R-0201-1225-00064	0.00	\N	0.00	0.00	0.00	0.00
69	2	1	1	paid	cash	2500.00	2500.00	\N	2025-12-25 23:24:59.268168-05	\N	R-0201-1225-00065	0.00	\N	0.00	0.00	0.00	0.00
70	2	1	1	paid	cash	15500.00	15500.00	\N	2025-12-25 23:50:35.095062-05	\N	R-0201-1225-00066	0.00	\N	0.00	0.00	0.00	0.00
71	2	1	1	paid	cash	7000.00	7000.00	\N	2025-12-25 23:51:00.885233-05	\N	R-0201-1225-00067	0.00	\N	0.00	0.00	0.00	0.00
72	2	1	1	paid	cash	7000.00	7000.00	\N	2025-12-25 23:54:45.290816-05	\N	R-0201-1225-00068	0.00	\N	0.00	0.00	0.00	0.00
73	2	1	1	paid	cash	2500.00	2500.00	\N	2025-12-26 00:27:27.615148-05	\N	R-0201-1225-00069	0.00	\N	0.00	0.00	0.00	0.00
74	2	1	1	paid	cash	3500.00	3500.00	\N	2025-12-26 00:42:24.482954-05	\N	R-0201-1225-00070	0.00	\N	0.00	0.00	0.00	0.00
75	2	1	1	paid	cash	2500.00	2500.00	\N	2025-12-26 05:20:38.945405-05	\N	R-0201-1225-00071	0.00	\N	0.00	0.00	0.00	0.00
77	2	1	1	paid	cash	2500.00	2500.00	\N	2025-12-26 05:38:12.577564-05	\N	R-0201-1225-00073	0.00	\N	0.00	0.00	0.00	0.00
78	2	1	1	paid	cash	1500.00	1500.00	\N	2025-12-26 05:41:59.814081-05	\N	R-0201-1225-00074	0.00	\N	0.00	0.00	0.00	0.00
79	2	1	1	paid	cash	3000.00	3000.00	\N	2025-12-26 05:43:25.569392-05	\N	R-0201-1225-00075	0.00	\N	0.00	0.00	0.00	0.00
80	2	1	1	paid	cash	2000.00	2000.00	\N	2025-12-28 15:34:36.126054-05	\N	R-0201-1225-00076	0.00	\N	0.00	0.00	0.00	0.00
84	2	1	1	paid	cash	9000.00	9000.00	\N	2026-01-04 15:49:38.506888-05	\N	R-0201-0126-00003	0.00	\N	0.00	0.00	0.00	0.00
76	2	1	1	paid	cash	2500.00	2500.00	\N	2025-12-26 05:27:12.204948-05	\N	R-0201-1225-00072	0.00	\N	0.00	0.00	0.00	0.00
81	2	1	1	paid	cash	7500.00	7500.00	\N	2025-12-28 15:36:38.019335-05	\N	R-0201-1225-00077	0.00	\N	0.00	0.00	0.00	0.00
82	2	1	1	paid	cash	225000.00	225000.00	\N	2026-01-02 15:47:07.232096-05	\N	R-0201-0126-00001	0.00	\N	0.00	0.00	0.00	0.00
83	2	1	1	paid	cash	7500.00	7500.00	\N	2026-01-02 15:47:29.36252-05	\N	R-0201-0126-00002	0.00	\N	0.00	0.00	0.00	0.00
85	2	1	1	paid	cash	13500.00	13500.00	\N	2026-01-05 10:52:24.703334-05	\N	R-0201-0126-00004	0.00	\N	0.00	0.00	0.00	0.00
86	2	1	1	paid	cash	1500.00	1500.00	\N	2026-02-19 06:27:12.060214-05	\N	R-0201-0226-00001	0.00	\N	0.00	0.00	0.00	0.00
87	2	1	1	paid	cash	6000.00	6000.00	\N	2026-02-19 08:30:59.239727-05	\N	R-0201-0226-00002	0.00	\N	0.00	0.00	0.00	0.00
88	2	1	1	paid	cash	2500.00	2500.00	\N	2026-02-19 09:03:32.197515-05	\N	R-0201-0226-00003	0.00	\N	0.00	0.00	0.00	0.00
89	2	1	1	pending_payment	xafpay	3500.00	3500.00	\N	2026-02-19 09:03:59.68755-05	\N	R-0201-0226-00004	0.00	\N	0.00	0.00	0.00	0.00
90	2	1	1	pending_payment	xafpay	2500.00	2500.00	\N	2026-02-19 10:48:08.502314-05	\N	R-0201-0226-00005	0.00	\N	0.00	0.00	0.00	0.00
91	2	1	1	pending_payment	xafpay	2500.00	2500.00	\N	2026-02-19 11:35:33.433281-05	\N	R-0201-0226-00006	0.00	\N	0.00	0.00	0.00	0.00
92	2	1	1	paid	cash	2500.00	2500.00	\N	2026-02-19 12:12:37.378164-05	\N	R-0201-0226-00007	0.00	\N	0.00	0.00	0.00	0.00
93	2	1	1	pending_payment	xafpay	3000.00	3000.00	\N	2026-02-19 12:12:49.998812-05	\N	R-0201-0226-00008	0.00	\N	0.00	0.00	0.00	0.00
94	2	1	1	pending_payment	xafpay	3000.00	3000.00	\N	2026-02-19 12:13:20.08065-05	\N	R-0201-0226-00009	0.00	\N	0.00	0.00	0.00	0.00
95	2	1	1	pending_payment	xafpay	1500.00	1500.00	\N	2026-02-19 12:25:48.748752-05	\N	R-0201-0226-00010	0.00	\N	0.00	0.00	0.00	0.00
96	2	1	1	pending_payment	xafpay	1500.00	1500.00	\N	2026-02-19 12:26:13.200934-05	\N	R-0201-0226-00011	0.00	\N	0.00	0.00	0.00	0.00
97	2	1	1	pending_payment	xafpay	2500.00	2500.00	\N	2026-02-19 12:31:11.008941-05	\N	R-0201-0226-00012	0.00	\N	0.00	0.00	0.00	0.00
98	2	1	1	pending_payment	xafpay	3500.00	3500.00	\N	2026-02-19 12:32:48.502124-05	\N	R-0201-0226-00013	0.00	\N	0.00	0.00	0.00	0.00
99	2	1	1	pending_payment	xafpay	2500.00	2500.00	\N	2026-02-19 13:06:27.580662-05	\N	R-0201-0226-00014	0.00	\N	0.00	0.00	0.00	0.00
100	2	1	1	paid	cash	1500.00	1500.00	\N	2026-02-19 13:23:49.520037-05	\N	R-0201-0226-00015	0.00	\N	0.00	0.00	0.00	0.00
101	2	1	1	pending_payment	xafpay	3000.00	3000.00	\N	2026-02-19 13:24:03.245272-05	\N	R-0201-0226-00016	0.00	\N	0.00	0.00	0.00	0.00
102	2	1	1	pending_payment	xafpay	2500.00	2500.00	\N	2026-02-19 13:30:45.90003-05	\N	R-0201-0226-00017	0.00	\N	0.00	0.00	0.00	0.00
103	2	1	1	pending_payment	xafpay	2500.00	2500.00	\N	2026-02-20 05:55:57.268488-05	\N	R-0201-0226-00018	0.00	\N	0.00	0.00	0.00	0.00
104	2	1	1	pending_payment	xafpay	1500.00	1500.00	\N	2026-02-20 06:07:27.073909-05	\N	R-0201-0226-00019	0.00	\N	0.00	0.00	0.00	0.00
105	2	1	1	pending_payment	xafpay	5000.00	5000.00	\N	2026-02-20 06:12:38.070243-05	\N	R-0201-0226-00020	0.00	\N	0.00	0.00	0.00	0.00
106	2	1	1	pending_payment	xafpay	3500.00	3500.00	\N	2026-02-20 08:35:20.988599-05	\N	R-0201-0226-00021	0.00	\N	0.00	0.00	0.00	0.00
107	2	1	1	pending_payment	xafpay	2500.00	2500.00	\N	2026-02-20 08:51:14.611631-05	\N	R-0201-0226-00022	0.00	\N	0.00	0.00	0.00	0.00
108	2	1	1	pending_payment	xafpay	2500.00	2500.00	\N	2026-02-20 09:03:39.255534-05	\N	R-0201-0226-00023	0.00	\N	0.00	0.00	0.00	0.00
109	2	1	1	pending_payment	xafpay	2500.00	2500.00	\N	2026-02-20 09:23:11.652722-05	\N	R-0201-0226-00024	0.00	\N	0.00	0.00	0.00	0.00
110	2	1	1	pending_payment	xafpay	3000.00	3000.00	\N	2026-02-20 09:43:15.921027-05	\N	R-0201-0226-00025	0.00	\N	0.00	0.00	0.00	0.00
111	2	1	1	pending_payment	xafpay	2500.00	2500.00	\N	2026-02-20 09:47:47.84721-05	\N	R-0201-0226-00026	0.00	\N	0.00	0.00	0.00	0.00
112	2	1	1	pending_payment	xafpay	1500.00	1500.00	\N	2026-02-20 09:54:33.554706-05	\N	R-0201-0226-00027	0.00	\N	0.00	0.00	0.00	0.00
113	2	1	1	pending_payment	xafpay	2500.00	2500.00	\N	2026-02-20 10:01:16.5761-05	\N	R-0201-0226-00028	0.00	\N	0.00	0.00	0.00	0.00
114	2	1	1	pending_payment	xafpay	3500.00	3500.00	\N	2026-02-20 10:02:27.789931-05	\N	R-0201-0226-00029	0.00	\N	0.00	0.00	0.00	0.00
115	2	1	1	pending_payment	xafpay	2500.00	2500.00	\N	2026-02-20 10:02:51.973259-05	\N	R-0201-0226-00030	0.00	\N	0.00	0.00	0.00	0.00
116	2	1	1	pending_payment	xafpay	2500.00	2500.00	\N	2026-02-20 10:15:09.105537-05	\N	R-0201-0226-00031	0.00	\N	0.00	0.00	0.00	0.00
117	2	1	1	pending_payment	xafpay	2500.00	2500.00	\N	2026-02-20 10:15:49.560922-05	\N	R-0201-0226-00032	0.00	\N	0.00	0.00	0.00	0.00
118	2	1	1	pending_payment	xafpay	2500.00	2500.00	\N	2026-02-20 10:19:39.171485-05	\N	R-0201-0226-00033	0.00	\N	0.00	0.00	0.00	0.00
119	2	1	1	pending_payment	xafpay	3000.00	3000.00	\N	2026-02-20 10:19:52.234339-05	\N	R-0201-0226-00034	0.00	\N	0.00	0.00	0.00	0.00
120	2	1	1	pending_payment	xafpay	2500.00	2500.00	\N	2026-02-20 11:01:54.304776-05	\N	R-0201-0226-00035	0.00	\N	0.00	0.00	0.00	0.00
121	2	1	1	pending_payment	xafpay	2500.00	2500.00	\N	2026-02-20 11:08:35.760285-05	\N	R-0201-0226-00036	0.00	\N	0.00	0.00	0.00	0.00
122	2	1	1	pending_payment	xafpay	2500.00	2500.00	\N	2026-02-20 11:13:33.824813-05	\N	R-0201-0226-00037	0.00	\N	0.00	0.00	0.00	0.00
123	2	1	1	pending_payment	xafpay	10000.00	10000.00	\N	2026-02-20 11:31:40.065078-05	\N	R-0201-0226-00038	0.00	\N	0.00	0.00	0.00	0.00
124	2	1	1	pending_payment	xafpay	10000.00	10000.00	\N	2026-02-20 11:55:54.846692-05	\N	R-0201-0226-00039	0.00	\N	0.00	0.00	0.00	0.00
125	2	1	1	pending_payment	xafpay	70000.00	70000.00	\N	2026-02-20 11:59:25.366032-05	\N	R-0201-0226-00040	0.00	\N	0.00	0.00	0.00	0.00
126	2	1	1	pending_payment	xafpay	1500.00	1500.00	\N	2026-02-20 12:53:43.895851-05	\N	R-0201-0226-00041	0.00	\N	0.00	0.00	0.00	0.00
127	2	1	1	pending_payment	xafpay	1500.00	1500.00	\N	2026-02-20 13:07:14.02427-05	\N	R-0201-0226-00042	0.00	\N	0.00	0.00	0.00	0.00
128	2	1	1	pending_payment	xafpay	5000.00	5000.00	\N	2026-02-20 16:26:17.360184-05	\N	R-0201-0226-00043	0.00	\N	0.00	0.00	0.00	0.00
129	2	1	1	pending_payment	xafpay	2500.00	2500.00	\N	2026-02-20 17:49:18.936796-05	\N	R-0201-0226-00044	0.00	\N	0.00	0.00	0.00	0.00
130	2	1	1	pending_payment	xafpay	3000.00	3000.00	\N	2026-02-20 18:00:27.013435-05	\N	R-0201-0226-00045	0.00	\N	0.00	0.00	0.00	0.00
131	2	1	1	pending_payment	xafpay	3500.00	3500.00	\N	2026-02-20 18:18:17.957918-05	\N	R-0201-0226-00046	0.00	\N	0.00	0.00	0.00	0.00
132	2	1	1	pending_payment	xafpay	70500.00	70500.00	\N	2026-02-20 18:42:53.036023-05	\N	R-0201-0226-00047	0.00	\N	0.00	0.00	0.00	0.00
133	2	1	1	pending_payment	xafpay	1500.00	1500.00	\N	2026-02-20 22:50:39.967448-05	\N	R-0201-0226-00048	0.00	\N	0.00	0.00	0.00	0.00
134	2	1	1	pending_payment	xafpay	2500.00	2500.00	\N	2026-02-20 23:12:17.838274-05	\N	R-0201-0226-00049	0.00	\N	0.00	0.00	0.00	0.00
135	2	1	1	pending_payment	xafpay	2500.00	2500.00	\N	2026-02-20 23:42:40.594752-05	\N	R-0201-0226-00050	0.00	\N	0.00	0.00	0.00	0.00
136	2	1	1	pending_payment	xafpay	5000.00	5000.00	\N	2026-02-20 23:52:32.368847-05	\N	R-0201-0226-00051	0.00	\N	0.00	0.00	0.00	0.00
137	2	1	1	paid	cash	2500.00	2500.00	\N	2026-02-20 23:54:37.215672-05	\N	R-0201-0226-00052	0.00	\N	0.00	0.00	0.00	0.00
138	2	1	1	pending_payment	xafpay	1500.00	1500.00	\N	2026-02-21 10:42:23.877647-05	\N	R-0201-0226-00053	0.00	\N	0.00	0.00	0.00	0.00
139	2	1	1	paid	cash	10500.00	10500.00	\N	2026-02-21 12:32:12.679966-05	\N	R-0201-0226-00054	0.00	\N	0.00	0.00	0.00	0.00
140	2	1	1	paid	cash	15000.00	15000.00	\N	2026-02-21 17:21:02.551404-05	\N	R-0201-0226-00055	0.00	\N	0.00	0.00	0.00	0.00
141	2	1	1	pending_payment	xafpay	5000.00	5000.00	\N	2026-02-21 19:03:28.274727-05	\N	R-0201-0226-00056	0.00	\N	0.00	0.00	0.00	0.00
142	2	1	1	pending_payment	xafpay	4000.00	4000.00	\N	2026-02-22 13:11:12.009386-05	\N	R-0201-0226-00057	0.00	\N	0.00	0.00	0.00	0.00
143	2	1	1	pending_payment	xafpay	5500.00	5500.00	\N	2026-02-23 09:28:25.875227-05	\N	R-0201-0226-00058	0.00	\N	0.00	0.00	0.00	0.00
144	2	1	1	pending_payment	xafpay	5500.00	5500.00	\N	2026-02-23 18:52:24.19282-05	\N	R-0201-0226-00059	0.00	\N	0.00	0.00	0.00	0.00
145	2	1	1	paid	cash	4000.00	4000.00	\N	2026-02-23 18:53:47.578031-05	\N	R-0201-0226-00060	0.00	\N	0.00	0.00	0.00	0.00
146	2	1	1	pending_payment	xafpay	3000.00	3000.00	\N	2026-02-24 08:29:00.113419-05	\N	R-0201-0226-00061	0.00	\N	0.00	0.00	0.00	0.00
147	2	1	1	pending_payment	xafpay	6500.00	6500.00	\N	2026-02-24 08:36:11.555349-05	\N	R-0201-0226-00062	0.00	\N	0.00	0.00	0.00	0.00
148	2	1	1	paid	cash	2500.00	2500.00	\N	2026-02-24 11:09:19.081514-05	\N	R-0201-0226-00063	0.00	\N	0.00	0.00	0.00	0.00
150	2	1	1	paid	cash	17500.00	17500.00	\N	2026-02-24 11:11:30.836926-05	\N	R-0201-0226-00065	0.00	\N	0.00	0.00	0.00	0.00
151	2	1	1	pending_payment	xafpay	11000.00	11000.00	\N	2026-02-24 12:43:17.856554-05	\N	R-0201-0226-00066	0.00	\N	0.00	0.00	0.00	0.00
154	2	1	1	pending_payment	xafpay	6000.00	6000.00	\N	2026-02-24 14:06:41.715242-05	\N	R-0201-0226-00069	0.00	\N	0.00	0.00	0.00	0.00
149	2	1	1	paid	cash	103500.00	103500.00	\N	2026-02-24 11:09:57.176493-05	\N	R-0201-0226-00064	0.00	\N	0.00	0.00	0.00	0.00
152	2	1	1	pending_payment	xafpay	3000.00	3000.00	\N	2026-02-24 13:55:24.013504-05	\N	R-0201-0226-00067	0.00	\N	0.00	0.00	0.00	0.00
153	2	1	1	paid	cash	4000.00	4000.00	\N	2026-02-24 14:06:14.660294-05	\N	R-0201-0226-00068	0.00	\N	0.00	0.00	0.00	0.00
155	2	1	1	pending_payment	xafpay	11000.00	11000.00	\N	2026-02-24 14:51:08.205712-05	\N	R-0201-0226-00070	0.00	\N	0.00	0.00	0.00	0.00
156	2	1	1	paid	cash	15000.00	15000.00	\N	2026-02-26 06:31:00.325391-05	\N	R-0201-0226-00071	0.00	\N	0.00	0.00	0.00	0.00
157	2	1	1	paid	cash	15000.00	15000.00	\N	2026-02-26 06:31:16.851774-05	\N	R-0201-0226-00072	0.00	\N	0.00	0.00	0.00	0.00
158	2	1	1	paid	cash	15000.00	15000.00	\N	2026-02-26 06:31:19.522975-05	\N	R-0201-0226-00073	0.00	\N	0.00	0.00	0.00	0.00
159	2	1	1	paid	cash	22000.00	22000.00	\N	2026-02-26 06:38:33.294024-05	\N	R-0201-0226-00074	0.00	\N	0.00	0.00	0.00	0.00
160	2	1	1	paid	cash	5000.00	5000.00	\N	2026-02-26 07:29:48.491129-05	\N	R-0201-0226-00075	0.00	\N	0.00	0.00	0.00	0.00
161	2	1	1	paid	cash	5000.00	5000.00	\N	2026-02-26 07:29:52.825156-05	\N	R-0201-0226-00076	0.00	\N	0.00	0.00	0.00	0.00
162	2	1	1	paid	cash	3000.00	3000.00	\N	2026-02-26 07:33:42.495527-05	\N	R-0201-0226-00077	0.00	\N	0.00	0.00	0.00	0.00
167	2	1	1	paid	cash	6500.00	6500.00	\N	2026-02-26 11:00:21.62574-05	2026-02-26 11:00:21.62574-05	R-0201-0226-00163	0.00	\N	0.00	6500.00	0.00	0.00
168	2	1	1	paid	cash	77500.00	77500.00	\N	2026-02-26 11:03:34.287244-05	2026-02-26 11:03:34.287244-05	R-0201-0226-00168	0.00	\N	0.00	77500.00	0.00	0.00
169	2	1	1	paid	cash	20000.00	20000.00	\N	2026-02-26 11:07:15.046134-05	2026-02-26 11:07:15.046134-05	R-0201-0226-00169	0.00	\N	0.00	20000.00	0.00	0.00
170	2	1	1	paid	cash	10000.00	10000.00	\N	2026-02-26 11:09:21.720369-05	2026-02-26 11:09:21.720369-05	R-0201-0226-00170	0.00	\N	0.00	10000.00	0.00	0.00
171	2	1	1	paid	cash	2500.00	2500.00	\N	2026-02-26 11:13:48.533296-05	2026-02-26 11:13:48.533296-05	R-0201-0226-00171	0.00	\N	0.00	2500.00	0.00	0.00
172	2	1	1	paid	cash	9000.00	9000.00	\N	2026-02-26 11:24:34.118605-05	2026-02-26 11:24:34.118605-05	R-0201-0226-00172	0.00	\N	0.00	9000.00	0.00	0.00
173	2	1	1	paid	cash	9000.00	9000.00	\N	2026-02-26 11:28:37.197559-05	2026-02-26 11:28:37.197559-05	R-0201-0226-00173	0.00	\N	0.00	9000.00	0.00	0.00
174	2	1	1	paid	cash	9000.00	9000.00	\N	2026-02-26 11:38:56.635888-05	2026-02-26 11:38:56.635888-05	R-0201-0226-00174	0.00	\N	0.00	9000.00	0.00	0.00
175	2	1	1	paid	cash	13000.00	13000.00	\N	2026-02-26 11:50:20.869434-05	2026-02-26 11:50:20.869434-05	R-0201-0226-00175	0.00	\N	0.00	13000.00	0.00	0.00
176	2	1	1	paid	cash	1500.00	1500.00	\N	2026-02-27 16:52:50.929571-05	2026-02-27 16:52:50.929571-05	R-0201-0226-00176	0.00	\N	0.00	1500.00	0.00	0.00
177	2	1	1	pending_payment	xafpay	8000.00	8000.00	\N	2026-02-27 16:53:14.680697-05	\N	R-0201-0226-00177	0.00	\N	0.00	0.00	0.00	0.00
178	2	1	1	pending_payment	xafpay	5500.00	5500.00	\N	2026-02-28 13:25:22.382737-05	\N	R-0201-0226-00178	0.00	\N	0.00	0.00	0.00	0.00
179	2	1	1	pending_payment	xafpay	10000.00	10000.00	\N	2026-02-28 14:02:50.44971-05	\N	R-0201-0226-00090	0.00	\N	0.00	0.00	0.00	0.00
180	2	1	1	pending_payment	xafpay	9000.00	9000.00	\N	2026-02-28 14:40:42.299391-05	\N	R-0201-0226-00091	0.00	\N	0.00	0.00	0.00	0.00
181	2	1	1	pending_payment	xafpay	2500.00	2500.00	\N	2026-02-28 15:49:19.199017-05	\N	R-0201-0226-00092	0.00	\N	0.00	0.00	0.00	0.00
182	2	1	1	pending_payment	xafpay	3000.00	3000.00	\N	2026-02-28 16:42:40.608646-05	\N	R-0201-0226-00093	0.00	\N	0.00	0.00	0.00	0.00
183	2	1	1	pending_payment	xafpay	2500.00	2500.00	\N	2026-02-28 16:53:46.093394-05	\N	R-0201-0226-00094	0.00	\N	0.00	0.00	0.00	0.00
184	2	1	1	paid	cash	10000.00	10000.00	\N	2026-02-28 16:58:56.043492-05	\N	R-0201-0226-00095	0.00	\N	0.00	0.00	0.00	0.00
185	2	1	1	pending_payment	xafpay	6000.00	6000.00	\N	2026-02-28 16:59:15.12072-05	\N	R-0201-0226-00096	0.00	\N	0.00	0.00	0.00	0.00
186	2	1	1	pending_payment	xafpay	8500.00	8500.00	\N	2026-02-28 17:18:42.836398-05	\N	R-0201-0226-00097	0.00	\N	0.00	0.00	0.00	0.00
187	2	1	1	pending_payment	xafpay	10000.00	10000.00	\N	2026-02-28 17:19:22.992708-05	\N	R-0201-0226-00098	0.00	\N	0.00	0.00	0.00	0.00
188	2	1	1	pending_payment	xafpay	8000.00	8000.00	\N	2026-02-28 17:26:55.596248-05	\N	R-0201-0226-00099	0.00	\N	0.00	0.00	0.00	0.00
189	2	1	1	pending_payment	xafpay	8000.00	8000.00	\N	2026-02-28 17:27:57.420052-05	\N	R-0201-0226-00100	0.00	\N	0.00	0.00	0.00	0.00
190	2	1	1	pending_payment	xafpay	9000.00	9000.00	\N	2026-02-28 17:34:46.708605-05	\N	R-0201-0226-00101	0.00	\N	0.00	0.00	0.00	0.00
191	2	1	1	pending_payment	xafpay	17000.00	17000.00	\N	2026-03-01 14:21:45.159879-05	\N	R-0201-0326-00001	0.00	\N	0.00	0.00	0.00	0.00
192	2	1	1	pending_payment	xafpay	8500.00	8500.00	\N	2026-03-01 14:28:26.681849-05	\N	R-0201-0326-00002	0.00	\N	0.00	0.00	0.00	0.00
193	2	1	1	pending_payment	xafpay	1500.00	1500.00	\N	2026-03-01 19:07:34.16602-05	\N	R-0201-0326-00003	0.00	\N	0.00	0.00	0.00	0.00
194	2	1	1	pending_payment	xafpay	27500.00	27500.00	\N	2026-03-01 19:37:17.201117-05	\N	R-0201-0326-00004	0.00	\N	0.00	0.00	0.00	0.00
195	2	1	1	pending_payment	xafpay	16500.00	16500.00	\N	2026-03-01 19:45:53.816605-05	\N	R-0201-0326-00005	0.00	\N	0.00	0.00	0.00	0.00
196	2	1	1	pending_payment	xafpay	3000.00	3000.00	\N	2026-03-01 19:52:51.153668-05	\N	R-0201-0326-00006	0.00	\N	0.00	0.00	0.00	0.00
197	2	1	1	pending_payment	xafpay	2500.00	2500.00	\N	2026-03-02 09:24:36.227052-05	\N	R-0201-0326-00007	0.00	\N	0.00	0.00	0.00	0.00
198	2	1	1	pending_payment	xafpay	2500.00	2500.00	\N	2026-03-02 09:29:42.333319-05	\N	R-0201-0326-00008	0.00	\N	0.00	0.00	0.00	0.00
199	2	1	1	paid	cash	6500.00	6500.00	\N	2026-03-02 09:31:18.988401-05	\N	R-0201-0326-00009	0.00	\N	0.00	0.00	0.00	0.00
200	2	1	1	pending_payment	xafpay	6500.00	6500.00	\N	2026-03-02 09:31:41.734791-05	\N	R-0201-0326-00010	0.00	\N	0.00	0.00	0.00	0.00
201	2	1	1	pending_payment	xafpay	2500.00	2500.00	\N	2026-03-02 09:38:11.14828-05	\N	R-0201-0326-00011	0.00	\N	0.00	0.00	0.00	0.00
202	2	1	1	pending_payment	xafpay	4000.00	4000.00	\N	2026-03-02 10:06:58.093927-05	\N	R-0201-0326-00012	0.00	\N	0.00	0.00	0.00	0.00
203	2	1	1	pending_payment	xafpay	5500.00	5500.00	\N	2026-03-02 10:12:08.839362-05	\N	R-0201-0326-00013	0.00	\N	0.00	0.00	0.00	0.00
204	2	1	1	pending_payment	xafpay	7500.00	7500.00	\N	2026-03-02 10:16:33.011542-05	\N	R-0201-0326-00014	0.00	\N	0.00	0.00	0.00	0.00
205	2	1	1	pending_payment	xafpay	2500.00	2500.00	\N	2026-03-02 10:30:28.529696-05	\N	R-0201-0326-00015	0.00	\N	0.00	0.00	0.00	0.00
206	2	1	1	pending_payment	xafpay	10500.00	10500.00	\N	2026-03-02 10:53:42.435101-05	\N	R-0201-0326-00016	0.00	\N	0.00	0.00	0.00	0.00
207	2	1	1	paid	cash	7000.00	7000.00	\N	2026-03-02 11:02:21.874892-05	\N	R-0201-0326-00017	0.00	\N	0.00	0.00	0.00	0.00
208	2	1	1	paid	cash	11000.00	11000.00	\N	2026-03-02 16:46:21.660334-05	\N	R-0201-0326-00018	0.00	\N	0.00	0.00	0.00	0.00
209	2	1	1	paid	cash	5500.00	5500.00	\N	2026-03-02 16:59:49.681509-05	\N	R-0201-0326-00019	0.00	\N	0.00	0.00	0.00	0.00
210	2	1	1	paid	cash	3500.00	3500.00	\N	2026-03-02 17:03:40.323401-05	\N	R-0201-0326-00020	0.00	\N	0.00	0.00	0.00	0.00
211	2	1	1	paid	cash	10500.00	10500.00	\N	2026-03-02 17:13:17.210698-05	\N	R-0201-0326-00021	0.00	\N	0.00	0.00	0.00	0.00
212	2	1	1	paid	cash	12500.00	12500.00	\N	2026-03-02 17:18:36.277137-05	\N	R-0201-0326-00022	0.00	\N	0.00	0.00	0.00	0.00
213	2	1	1	paid	cash	6000.00	6000.00	\N	2026-03-02 18:10:37.860627-05	\N	R-0201-0326-00023	0.00	\N	0.00	0.00	0.00	0.00
214	2	1	1	paid	cash	8500.00	8500.00	\N	2026-03-02 19:08:46.463572-05	\N	R-0201-0326-00024	0.00	\N	0.00	0.00	0.00	0.00
215	2	1	1	paid	cash	5500.00	5500.00	\N	2026-03-02 19:17:31.058551-05	\N	R-0201-0326-00025	0.00	\N	0.00	0.00	0.00	0.00
216	2	1	1	paid	cash	10000.00	10000.00	\N	2026-03-02 22:59:15.240354-05	\N	R-0201-0326-00026	0.00	\N	0.00	0.00	0.00	0.00
217	2	1	1	paid	cash	9500.00	9500.00	\N	2026-03-02 23:01:04.57905-05	\N	R-0201-0326-00027	0.00	\N	0.00	0.00	0.00	0.00
218	2	1	1	paid	cash	22500.00	22500.00	\N	2026-03-02 23:05:05.945316-05	\N	R-0201-0326-00028	0.00	\N	0.00	0.00	0.00	0.00
219	2	1	1	paid	cash	5500.00	5500.00	\N	2026-03-03 06:46:31.453663-05	\N	R-0201-0326-00029	0.00	\N	0.00	0.00	0.00	0.00
220	2	1	1	paid	cash	5500.00	5500.00	\N	2026-03-03 06:49:20.907166-05	\N	R-0201-0326-00030	0.00	\N	0.00	0.00	0.00	0.00
221	2	1	1	pending_payment	xafpay	8500.00	8500.00	\N	2026-03-03 06:59:17.795908-05	\N	R-0201-0326-00031	0.00	\N	0.00	0.00	0.00	0.00
222	2	1	1	pending_payment	xafpay	7500.00	7500.00	\N	2026-03-03 07:02:33.574085-05	\N	R-0201-0326-00032	0.00	\N	0.00	0.00	0.00	0.00
223	2	1	1	pending_payment	cash	7500.00	7500.00	\N	2026-03-03 07:24:06.574285-05	\N	R-0201-0326-00033	0.00	\N	0.00	0.00	0.00	0.00
224	2	1	1	pending_payment	cash	2500.00	2500.00	\N	2026-03-03 08:02:18.465127-05	\N	R-0201-0326-00034	0.00	\N	0.00	0.00	0.00	0.00
225	2	1	1	pending_payment	cash	5000.00	5000.00	\N	2026-03-03 08:04:01.518744-05	\N	R-0201-0326-00035	0.00	\N	0.00	0.00	0.00	0.00
226	2	1	1	pending_payment	cash	8000.00	8000.00	\N	2026-03-03 09:39:29.211413-05	\N	R-0201-0326-00036	0.00	\N	0.00	0.00	0.00	0.00
227	2	1	1	pending_payment	cash	11000.00	11000.00	\N	2026-03-03 10:29:26.552896-05	\N	R-0201-0326-00037	0.00	\N	0.00	0.00	0.00	0.00
228	2	1	1	pending_payment	cash	5500.00	5500.00	\N	2026-03-03 10:31:48.578758-05	\N	R-0201-0326-00038	0.00	\N	0.00	0.00	0.00	0.00
229	2	1	1	pending_payment	cash	5500.00	5500.00	\N	2026-03-03 10:34:35.196794-05	\N	R-0201-0326-00039	0.00	\N	0.00	0.00	0.00	0.00
230	2	1	1	pending_payment	cash	25500.00	25500.00	\N	2026-03-03 10:37:46.645581-05	\N	R-0201-0326-00040	0.00	\N	0.00	0.00	0.00	0.00
231	2	1	1	pending_payment	cash	10000.00	10000.00	\N	2026-03-03 11:50:10.090437-05	\N	R-0201-0326-00041	0.00	\N	0.00	0.00	0.00	0.00
232	2	1	1	pending_payment	cash	15500.00	15500.00	\N	2026-03-03 11:52:09.94436-05	\N	R-0201-0326-00042	0.00	\N	0.00	0.00	0.00	0.00
233	2	1	1	pending_payment	cash	12500.00	12500.00	\N	2026-03-03 11:58:17.122384-05	\N	R-0201-0326-00043	0.00	\N	0.00	0.00	0.00	0.00
234	2	1	1	pending_payment	cash	7000.00	7000.00	\N	2026-03-03 12:00:23.355306-05	\N	R-0201-0326-00044	0.00	\N	0.00	0.00	0.00	0.00
235	2	1	1	pending_payment	cash	2500.00	2500.00	\N	2026-03-03 12:27:55.699967-05	\N	R-0201-0326-00045	0.00	\N	0.00	0.00	0.00	0.00
236	2	1	1	pending_payment	cash	6000.00	6000.00	\N	2026-03-03 12:33:20.724472-05	\N	R-0201-0326-00046	0.00	\N	0.00	0.00	0.00	0.00
237	2	1	1	pending_payment	cash	9000.00	9000.00	\N	2026-03-03 13:37:06.235986-05	\N	R-0201-0326-00047	0.00	\N	0.00	0.00	0.00	0.00
238	2	1	1	pending_payment	cash	11500.00	11500.00	\N	2026-03-03 13:50:54.542739-05	\N	R-0201-0326-00048	0.00	\N	0.00	0.00	0.00	0.00
239	2	1	1	pending_payment	cash	20000.00	20000.00	\N	2026-03-03 13:59:26.220882-05	\N	R-0201-0326-00049	0.00	\N	0.00	0.00	0.00	0.00
240	2	1	1	pending_payment	cash	9500.00	9500.00	\N	2026-03-03 16:35:36.025053-05	\N	R-0201-0326-00050	0.00	\N	0.00	0.00	0.00	0.00
241	2	1	1	pending_payment	cash	8000.00	8000.00	\N	2026-03-03 16:54:25.733656-05	\N	R-0201-0326-00051	0.00	\N	0.00	0.00	0.00	0.00
242	2	1	1	pending_payment	cash	17500.00	17500.00	\N	2026-03-03 17:14:01.836872-05	\N	R-0201-0326-00052	0.00	\N	0.00	0.00	0.00	0.00
243	2	1	1	pending_payment	cash	16000.00	16000.00	\N	2026-03-03 17:34:56.800709-05	\N	R-0201-0326-00053	0.00	\N	0.00	0.00	0.00	0.00
244	2	1	1	pending_payment	cash	12500.00	12500.00	\N	2026-03-04 07:34:44.999182-05	\N	R-0201-0326-00054	0.00	\N	0.00	0.00	0.00	0.00
245	2	1	1	pending_payment	cash	12500.00	12500.00	\N	2026-03-04 07:45:55.21554-05	\N	R-0201-0326-00055	0.00	\N	0.00	0.00	0.00	0.00
246	2	1	1	pending_payment	cash	17000.00	17000.00	\N	2026-03-04 07:51:13.881967-05	\N	R-0201-0326-00056	0.00	\N	0.00	0.00	0.00	0.00
247	2	1	1	pending_payment	cash	17000.00	17000.00	\N	2026-03-04 11:05:37.196301-05	\N	R-0201-0326-00057	0.00	\N	0.00	0.00	0.00	0.00
248	2	1	1	pending_payment	cash	38500.00	38500.00	\N	2026-03-04 11:43:08.698224-05	\N	R-0201-0326-00058	0.00	\N	0.00	0.00	0.00	0.00
249	2	1	1	paid	cash	1500.00	1500.00	\N	2026-03-04 12:37:25.474315-05	2026-03-04 12:37:25.622444-05	R-0201-0326-00059	0.00	\N	0.00	0.00	0.00	0.00
250	2	1	1	paid	cash	10500.00	10500.00	\N	2026-03-04 12:42:20.708748-05	2026-03-04 12:42:20.756849-05	R-0201-0326-00060	0.00	\N	0.00	0.00	0.00	0.00
251	2	1	1	paid	cash	5000.00	5000.00	\N	2026-03-04 12:47:03.028172-05	2026-03-04 12:47:03.084262-05	R-0201-0326-00061	0.00	\N	0.00	0.00	0.00	0.00
252	2	1	1	paid	cash	5500.00	5500.00	\N	2026-03-04 14:13:09.396038-05	2026-03-04 14:13:09.447643-05	R-0201-0326-00062	0.00	\N	0.00	0.00	0.00	0.00
253	2	1	1	pending_payment	cash	6500.00	6500.00	\N	2026-03-04 14:24:40.344336-05	\N	R-0201-0326-00063	0.00	\N	0.00	0.00	0.00	0.00
254	2	1	1	paid	cash	10500.00	10500.00	\N	2026-03-04 14:32:28.010096-05	2026-03-04 14:32:28.181495-05	R-0201-0326-00064	0.00	\N	0.00	0.00	0.00	0.00
255	2	1	1	paid	cash	10500.00	10500.00	\N	2026-03-04 14:33:31.465856-05	2026-03-04 14:33:31.520657-05	R-0201-0326-00065	0.00	\N	0.00	0.00	0.00	0.00
256	2	1	1	paid	cash	14500.00	14500.00	\N	2026-03-04 14:35:21.30001-05	2026-03-04 14:35:21.355614-05	R-0201-0326-00066	0.00	\N	0.00	0.00	0.00	0.00
257	2	1	1	pending_payment	cash	9000.00	9000.00	\N	2026-03-05 07:44:01.518632-05	\N	R-0201-0326-00067	0.00	\N	0.00	0.00	0.00	0.00
258	2	1	1	pending_payment	cash	15500.00	15500.00	\N	2026-03-05 07:47:38.728907-05	\N	R-0201-0326-00068	0.00	\N	0.00	0.00	0.00	0.00
259	2	1	1	paid	cash	15500.00	15500.00	\N	2026-03-05 07:48:40.306596-05	2026-03-05 07:48:40.366152-05	R-0201-0326-00069	0.00	\N	0.00	0.00	0.00	0.00
260	2	1	1	pending_payment	cash	15500.00	15500.00	\N	2026-03-05 07:49:40.149564-05	\N	R-0201-0326-00070	0.00	\N	0.00	0.00	0.00	0.00
261	2	1	1	paid	cash	15500.00	15500.00	\N	2026-03-05 07:57:23.08852-05	2026-03-05 07:57:23.139863-05	R-0201-0326-00071	0.00	\N	0.00	0.00	0.00	0.00
262	2	1	1	pending_payment	cash	7500.00	7500.00	\N	2026-03-05 08:18:01.884832-05	\N	R-0201-0326-00072	0.00	\N	0.00	0.00	0.00	0.00
263	2	1	1	pending_payment	cash	7500.00	7500.00	\N	2026-03-05 08:19:10.026313-05	\N	R-0201-0326-00073	0.00	\N	0.00	0.00	0.00	0.00
264	2	1	1	paid	cash	7500.00	7500.00	\N	2026-03-05 08:20:10.434059-05	2026-03-05 08:20:10.454817-05	R-0201-0326-00074	0.00	\N	0.00	0.00	0.00	0.00
265	2	1	1	pending_payment	cash	7500.00	7500.00	\N	2026-03-05 08:21:40.140188-05	\N	R-0201-0326-00075	0.00	\N	0.00	0.00	0.00	0.00
266	2	1	1	paid	cash	7500.00	7500.00	\N	2026-03-05 08:22:24.039044-05	2026-03-05 08:22:24.059492-05	R-0201-0326-00076	0.00	\N	0.00	0.00	0.00	0.00
267	2	1	1	paid	cash	7500.00	7500.00	\N	2026-03-05 08:26:21.689231-05	2026-03-05 08:26:21.708675-05	R-0201-0326-00077	0.00	\N	0.00	0.00	0.00	0.00
268	2	1	1	paid	cash	7500.00	7500.00	\N	2026-03-05 08:27:52.011968-05	2026-03-05 08:27:52.033453-05	R-0201-0326-00078	0.00	\N	0.00	0.00	0.00	0.00
269	2	1	1	pending_payment	cash	7500.00	7500.00	\N	2026-03-05 08:28:09.590628-05	\N	R-0201-0326-00079	0.00	\N	0.00	0.00	0.00	0.00
270	2	1	1	paid	cash	7500.00	7500.00	\N	2026-03-05 08:29:10.09327-05	2026-03-05 08:29:10.112716-05	R-0201-0326-00080	0.00	\N	0.00	0.00	0.00	0.00
271	2	1	1	paid	cash	7500.00	7500.00	\N	2026-03-05 08:39:40.104387-05	2026-03-05 08:39:40.129026-05	R-0201-0326-00081	0.00	\N	0.00	0.00	0.00	0.00
272	2	1	1	pending_payment	cash	7500.00	7500.00	\N	2026-03-05 08:40:04.451968-05	\N	R-0201-0326-00082	0.00	\N	0.00	0.00	0.00	0.00
273	2	1	1	paid	cash	15500.00	15500.00	\N	2026-03-05 10:13:03.235918-05	2026-03-05 10:13:03.446861-05	R-0201-0326-00083	0.00	\N	0.00	0.00	0.00	0.00
274	2	1	1	pending_payment	cash	15500.00	15500.00	\N	2026-03-05 10:14:54.743605-05	\N	R-0201-0326-00084	0.00	\N	0.00	0.00	0.00	0.00
275	2	1	1	pending_payment	cash	15500.00	15500.00	\N	2026-03-05 10:16:11.993356-05	\N	R-0201-0326-00085	0.00	\N	0.00	0.00	0.00	0.00
276	2	1	1	pending_payment	cash	15500.00	15500.00	\N	2026-03-05 10:20:38.633559-05	\N	R-0201-0326-00086	0.00	\N	0.00	0.00	0.00	0.00
277	2	1	1	paid	cash	15500.00	15500.00	\N	2026-03-05 10:37:41.388517-05	2026-03-05 10:37:41.446816-05	R-0201-0326-00087	0.00	\N	0.00	0.00	0.00	0.00
278	2	1	1	pending_payment	cash	9000.00	9000.00	\N	2026-03-05 18:14:17.036369-05	\N	R-0201-0326-00088	0.00	\N	0.00	0.00	0.00	0.00
279	2	1	1	pending_payment	cash	6500.00	6500.00	\N	2026-03-05 18:32:09.445908-05	\N	R-0201-0326-00089	0.00	\N	0.00	0.00	0.00	0.00
280	2	1	1	paid	cash	6500.00	6500.00	\N	2026-03-05 18:36:03.435405-05	2026-03-05 18:36:03.468469-05	R-0201-0326-00090	0.00	\N	0.00	0.00	0.00	0.00
281	2	1	1	pending_payment	cash	58000.00	58000.00	\N	2026-03-06 06:30:15.445253-05	\N	R-0201-0326-00091	0.00	\N	0.00	0.00	0.00	0.00
283	2	1	1	paid	cash	1500.00	1500.00	\N	2026-03-06 21:33:33.669-05	2026-03-06 21:33:33.800177-05	R-0201-0326-00092	0.00	\N	0.00	0.00	0.00	0.00
284	2	1	1	pending_payment	cash	9000.00	9000.00	\N	2026-03-06 21:35:03.072214-05	\N	R-0201-0326-00093	0.00	\N	0.00	0.00	0.00	0.00
285	2	1	1	paid	cash	1000.00	1000.00	\N	2026-03-06 22:23:05.705626-05	2026-03-06 22:23:05.735087-05	R-0201-0326-00094	0.00	\N	0.00	0.00	0.00	0.00
286	2	1	1	paid	cash	1000.00	1000.00	\N	2026-03-07 07:07:50.697293-05	2026-03-07 07:07:50.742316-05	R-0201-0326-00095	0.00	\N	0.00	0.00	0.00	0.00
287	2	1	1	paid	cash	3000.00	3000.00	\N	2026-03-07 07:13:18.192175-05	2026-03-07 07:13:18.222338-05	R-0201-0326-00096	0.00	\N	0.00	0.00	0.00	0.00
288	2	1	1	paid	cash	21000.00	21000.00	\N	2026-03-07 07:28:19.927168-05	2026-03-07 07:28:19.962148-05	R-0201-0326-00097	0.00	\N	0.00	0.00	0.00	0.00
289	2	1	1	paid	cash	23000.00	23000.00	\N	2026-03-07 07:28:55.033776-05	2026-03-07 07:28:55.075596-05	R-0201-0326-00098	0.00	\N	0.00	0.00	0.00	0.00
290	2	1	1	pending_payment	cash	3500.00	3500.00	\N	2026-03-07 08:00:22.278267-05	\N	R-0201-0326-00099	0.00	\N	0.00	0.00	0.00	0.00
291	2	1	1	paid	cash	4500.00	4500.00	\N	2026-03-07 10:13:58.04103-05	2026-03-07 10:13:58.071838-05	R-0201-0326-00100	0.00	\N	0.00	0.00	0.00	0.00
292	2	1	1	pending_payment	cash	3500.00	3500.00	\N	2026-03-08 07:48:34.337711-04	\N	R-0201-0326-00101	0.00	\N	0.00	0.00	0.00	0.00
293	2	1	1	paid	cash	4500.00	4500.00	\N	2026-03-08 10:28:02.925096-04	2026-03-08 10:28:03.028424-04	R-0201-0326-00102	0.00	\N	0.00	0.00	0.00	0.00
294	2	1	1	pending_payment	cash	2000.00	2000.00	\N	2026-03-08 10:28:54.534918-04	\N	R-0201-0326-00103	0.00	\N	0.00	0.00	0.00	0.00
295	2	1	1	pending_payment	cash	3000.00	3000.00	\N	2026-03-08 10:33:41.136408-04	\N	R-0201-0326-00104	0.00	\N	0.00	0.00	0.00	0.00
296	2	1	1	pending_payment	cash	2500.00	2500.00	\N	2026-03-08 10:40:28.736462-04	\N	R-0201-0326-00105	0.00	\N	0.00	0.00	0.00	0.00
297	2	1	1	pending_payment	cash	4500.00	4500.00	\N	2026-03-08 10:58:24.890383-04	\N	R-0201-0326-00106	0.00	\N	0.00	0.00	0.00	0.00
298	2	1	1	paid	cash	4500.00	4500.00	\N	2026-03-08 11:00:07.466643-04	2026-03-08 11:00:07.554681-04	R-0201-0326-00107	0.00	\N	0.00	0.00	0.00	0.00
299	2	1	1	pending_payment	cash	17500.00	17500.00	\N	2026-03-08 11:02:34.749032-04	\N	R-0201-0326-00108	0.00	\N	0.00	0.00	0.00	0.00
300	2	1	1	paid	cash	17500.00	17500.00	\N	2026-03-08 11:10:03.352493-04	2026-03-08 11:10:03.490683-04	R-0201-0326-00109	0.00	\N	0.00	0.00	0.00	0.00
301	2	1	1	pending_payment	cash	3500.00	3500.00	\N	2026-03-08 12:11:16.53134-04	\N	R-0201-0326-00110	0.00	\N	0.00	0.00	0.00	0.00
302	2	1	1	pending_payment	cash	3500.00	3500.00	\N	2026-03-08 12:25:24.976433-04	\N	R-0201-0326-00111	0.00	\N	0.00	0.00	0.00	0.00
303	2	1	1	pending_payment	cash	3500.00	3500.00	\N	2026-03-08 13:00:34.556506-04	\N	R-0201-0326-00112	0.00	\N	0.00	0.00	0.00	0.00
304	2	1	1	pending_payment	cash	1000.00	1000.00	\N	2026-03-08 13:08:50.892916-04	\N	R-0201-0326-00113	0.00	\N	0.00	0.00	0.00	0.00
305	2	1	1	pending_payment	cash	1000.00	1000.00	\N	2026-03-08 13:09:17.726765-04	\N	R-0201-0326-00114	0.00	\N	0.00	0.00	0.00	0.00
306	2	1	1	pending_payment	cash	1000.00	1000.00	\N	2026-03-08 13:09:47.824909-04	\N	R-0201-0326-00115	0.00	\N	0.00	0.00	0.00	0.00
307	2	1	1	pending_payment	cash	1500.00	1500.00	\N	2026-03-08 13:34:36.266231-04	\N	R-0201-0326-00116	0.00	\N	0.00	0.00	0.00	0.00
308	2	1	1	pending_payment	cash	1500.00	1500.00	\N	2026-03-08 13:35:59.7245-04	\N	R-0201-0326-00117	0.00	\N	0.00	0.00	0.00	0.00
309	2	1	1	pending_payment	cash	5000.00	5000.00	\N	2026-03-08 17:09:16.411468-04	\N	R-0201-0326-00118	0.00	\N	0.00	0.00	0.00	0.00
310	2	1	1	paid	cash	0.00	0.00	\N	2026-03-09 17:25:44.233843-04	2026-03-09 17:25:44.387285-04	R-0201-0326-00119	0.00	\N	0.00	0.00	0.00	0.00
311	2	1	1	paid	cash	0.00	0.00	\N	2026-03-09 17:28:55.922359-04	2026-03-09 17:28:55.978836-04	R-0201-0326-00120	0.00	\N	0.00	0.00	0.00	0.00
312	2	1	1	paid	cash	5000.00	5000.00	\N	2026-03-10 08:21:38.055145-04	2026-03-10 08:21:38.184313-04	R-0201-0326-00121	0.00	\N	0.00	0.00	0.00	0.00
313	2	1	1	pending_payment	cash	1500.00	1500.00	\N	2026-03-10 13:35:28.793499-04	\N	R-0201-0326-00122	0.00	\N	0.00	0.00	0.00	0.00
314	2	1	1	paid	cash	0.00	0.00	\N	2026-03-10 14:41:46.868604-04	2026-03-10 14:41:46.949768-04	R-0201-0326-00123	0.00	\N	0.00	0.00	0.00	0.00
315	2	1	1	paid	cash	0.00	0.00	\N	2026-03-10 14:46:31.495383-04	2026-03-10 14:46:31.535264-04	R-0201-0326-00124	0.00	\N	0.00	0.00	0.00	0.00
\.


--
-- Data for Name: taxonomy_nodes; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.taxonomy_nodes (id, tenant_id, parent_id, name, semantic_level, sort_order, is_active, taxonomy_type, meta) FROM stdin;
43	2	\N	Others	category	3	t	inventory	\N
44	2	41	Main Dish	subcategory	1	t	inventory	\N
45	2	41	Breakfast	subcategory	2	t	inventory	\N
46	2	41	Dessert	subcategory	3	t	inventory	\N
47	2	41	Complement	subcategory	4	t	inventory	\N
48	2	42	Beer	subcategory	1	t	inventory	\N
49	2	42	Soft Drinks	subcategory	2	t	inventory	\N
50	2	42	Hot Drinks	subcategory	3	t	inventory	\N
51	2	42	Wine	subcategory	4	t	inventory	\N
52	2	42	Whiskey	subcategory	5	t	inventory	\N
53	2	42	Champagne	subcategory	6	t	inventory	\N
54	2	42	Juice	subcategory	7	t	inventory	\N
41	2	\N	Food	category	2	t	inventory	\N
42	2	\N	Drinks	category	1	t	inventory	\N
\.


--
-- Data for Name: tenants; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.tenants (id, code, name, country_code, country_name, currency, locale, timezone, settings, extra_metadata, created_at, updated_at) FROM stdin;
3	CM002	Test Tenant	CM	\N	XAF	en_CM	Africa/Douala	{}	{}	2025-12-10 14:07:50.372926	\N
4	CM003	XafPay	CM	\N	XAF	en_CM	Africa/Douala	{}	{}	2025-12-10 14:10:34.348438	\N
2	CM001	Wine & Dine	CM	Cameroon	XAF	en_CM	Africa/Douala	{}	{}	2025-12-10 13:15:49.947708	\N
\.


--
-- Data for Name: treasury_logs; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.treasury_logs (id, tenant_id, branch_id, event_type, sale_id, payment_attempt_id, amount, currency, channel, meta, created_at, direction, reference_type, reference_id, taxonomy_node_id, idempotency_key, occurred_at) FROM stdin;
1	2	1	PAYMENT_RECEIVED	\N	\N	500.00	XAF	cash	{"provider": null, "mode": "manual", "sale_id": 279}	2026-03-05 13:32:09.483989-05	credit	payment_attempt	134	\N	pay_attempt:134	2026-03-05 18:32:09.506369-05
2	2	1	PAYMENT_RECEIVED	\N	\N	4000.00	XAF	mtn	{"provider": null, "mode": "manual", "sale_id": 279}	2026-03-05 13:32:09.483989-05	credit	payment_attempt	135	\N	pay_attempt:135	2026-03-05 18:32:09.510104-05
3	2	1	PAYMENT_RECEIVED	\N	\N	1000.00	XAF	orange	{"provider": null, "mode": "manual", "sale_id": 279}	2026-03-05 13:32:09.483989-05	credit	payment_attempt	136	\N	pay_attempt:136	2026-03-05 18:32:09.513452-05
4	2	1	SALE_REVENUE_GROSS	\N	\N	6500.00	XAF	\N	{"receipt_no": "R-0201-0326-00089"}	2026-03-05 13:32:09.483989-05	credit	sale	279	\N	sale_revenue:279	2026-03-05 18:32:09.51473-05
5	2	1	DEBT_CREATED	\N	\N	1000.00	XAF	\N	{"unpaid_notes": []}	2026-03-05 13:32:09.483989-05	debit	sale	279	\N	debt_created:279	2026-03-05 18:32:09.515591-05
6	2	1	PAYMENT_RECEIVED	\N	\N	6500.00	XAF	cash	{"provider": null, "mode": "manual", "sale_id": 280}	2026-03-05 13:36:03.457993-05	credit	payment_attempt	137	\N	pay_attempt:137	2026-03-05 18:36:03.465856-05
7	2	1	SALE_REVENUE_GROSS	\N	\N	6500.00	XAF	\N	{"receipt_no": "R-0201-0326-00090"}	2026-03-05 13:36:03.457993-05	credit	sale	280	\N	sale_revenue:280	2026-03-05 18:36:03.466398-05
8	2	1	PAYMENT_RECEIVED	\N	\N	50000.00	XAF	cash	{"provider": null, "mode": "manual", "sale_id": 281}	2026-03-06 01:30:15.582521-05	credit	payment_attempt	138	\N	pay_attempt:138	2026-03-06 06:30:15.629031-05
9	2	1	PAYMENT_RECEIVED	\N	\N	2000.00	XAF	mtn	{"provider": null, "mode": "manual", "sale_id": 281}	2026-03-06 01:30:15.582521-05	credit	payment_attempt	139	\N	pay_attempt:139	2026-03-06 06:30:15.632932-05
10	2	1	PAYMENT_RECEIVED	\N	\N	1000.00	XAF	orange	{"provider": null, "mode": "manual", "sale_id": 281}	2026-03-06 01:30:15.582521-05	credit	payment_attempt	140	\N	pay_attempt:140	2026-03-06 06:30:15.635044-05
11	2	1	SALE_REVENUE_GROSS	\N	\N	58000.00	XAF	\N	{"receipt_no": "R-0201-0326-00091"}	2026-03-06 01:30:15.582521-05	credit	sale	281	\N	sale_revenue:281	2026-03-06 06:30:15.635449-05
12	2	1	DISCOUNT_APPLIED	\N	\N	1500.00	XAF	\N	{"reason": "Manager override"}	2026-03-06 01:30:15.582521-05	debit	sale	281	\N	sale_discount:281	2026-03-06 06:30:15.635984-05
13	2	1	COMPLIMENTARY_APPLIED	\N	\N	1000.00	XAF	\N	{"items": []}	2026-03-06 01:30:15.582521-05	debit	sale	281	\N	sale_comp:281	2026-03-06 06:30:15.63638-05
14	2	1	DEBT_CREATED	\N	\N	2500.00	XAF	\N	{"unpaid_notes": []}	2026-03-06 01:30:15.582521-05	debit	sale	281	\N	debt_created:281	2026-03-06 06:30:15.636886-05
15	2	1	PAYMENT_RECEIVED	\N	\N	1500.00	XAF	cash	{"provider": null, "mode": "manual", "sale_id": 283}	2026-03-06 16:33:33.729941-05	credit	payment_attempt	141	\N	pay_attempt:141	2026-03-06 21:33:33.792641-05
16	2	1	SALE_REVENUE_GROSS	\N	\N	1500.00	XAF	\N	{"receipt_no": "R-0201-0326-00092"}	2026-03-06 16:33:33.729941-05	credit	sale	283	\N	sale_revenue:283	2026-03-06 21:33:33.794903-05
17	2	1	SALE_REVENUE_GROSS	\N	\N	9000.00	XAF	\N	{"receipt_no": "R-0201-0326-00093"}	2026-03-06 16:35:03.106284-05	credit	sale	284	\N	sale_revenue:284	2026-03-06 21:35:03.110022-05
18	2	1	COMPLIMENTARY_APPLIED	\N	\N	1500.00	XAF	\N	{"items": []}	2026-03-06 16:35:03.106284-05	debit	sale	284	\N	sale_comp:284	2026-03-06 21:35:03.110464-05
19	2	1	DEBT_CREATED	\N	\N	7500.00	XAF	\N	{"unpaid_notes": []}	2026-03-06 16:35:03.106284-05	debit	sale	284	\N	debt_created:284	2026-03-06 21:35:03.110858-05
20	2	1	PAYMENT_RECEIVED	\N	\N	1000.00	XAF	mtn	{"provider": null, "mode": "manual", "sale_id": 285}	2026-03-06 17:23:05.726605-05	credit	payment_attempt	142	\N	pay_attempt:142	2026-03-06 22:23:05.733102-05
21	2	1	SALE_REVENUE_GROSS	\N	\N	1000.00	XAF	\N	{"receipt_no": "R-0201-0326-00094"}	2026-03-06 17:23:05.726605-05	credit	sale	285	\N	sale_revenue:285	2026-03-06 22:23:05.733599-05
22	2	1	PAYMENT_RECEIVED	\N	\N	1000.00	XAF	cash	{"provider": null, "mode": "manual", "sale_id": 286}	2026-03-07 02:07:50.728478-05	credit	payment_attempt	143	\N	pay_attempt:143	2026-03-07 07:07:50.740154-05
23	2	1	SALE_REVENUE_GROSS	\N	\N	1000.00	XAF	\N	{"receipt_no": "R-0201-0326-00095"}	2026-03-07 02:07:50.728478-05	credit	sale	286	\N	sale_revenue:286	2026-03-07 07:07:50.740821-05
24	2	1	PAYMENT_RECEIVED	\N	\N	3000.00	XAF	mtn	{"provider": null, "mode": "manual", "sale_id": 287}	2026-03-07 02:13:18.214149-05	credit	payment_attempt	144	\N	pay_attempt:144	2026-03-07 07:13:18.220546-05
25	2	1	SALE_REVENUE_GROSS	\N	\N	3000.00	XAF	\N	{"receipt_no": "R-0201-0326-00096"}	2026-03-07 02:13:18.214149-05	credit	sale	287	\N	sale_revenue:287	2026-03-07 07:13:18.22098-05
26	2	1	PAYMENT_RECEIVED	\N	\N	21000.00	XAF	mtn	{"provider": null, "mode": "manual", "sale_id": 288}	2026-03-07 02:28:19.952711-05	credit	payment_attempt	145	\N	pay_attempt:145	2026-03-07 07:28:19.959549-05
27	2	1	SALE_REVENUE_GROSS	\N	\N	21000.00	XAF	\N	{"receipt_no": "R-0201-0326-00097"}	2026-03-07 02:28:19.952711-05	credit	sale	288	\N	sale_revenue:288	2026-03-07 07:28:19.960241-05
28	2	1	PAYMENT_RECEIVED	\N	\N	22000.00	XAF	cash	{"provider": null, "mode": "manual", "sale_id": 289}	2026-03-07 02:28:55.062551-05	credit	payment_attempt	146	\N	pay_attempt:146	2026-03-07 07:28:55.072808-05
29	2	1	SALE_REVENUE_GROSS	\N	\N	23000.00	XAF	\N	{"receipt_no": "R-0201-0326-00098"}	2026-03-07 02:28:55.062551-05	credit	sale	289	\N	sale_revenue:289	2026-03-07 07:28:55.073446-05
30	2	1	COMPLIMENTARY_APPLIED	\N	\N	1000.00	XAF	\N	{"items": []}	2026-03-07 02:28:55.062551-05	debit	sale	289	\N	sale_comp:289	2026-03-07 07:28:55.073873-05
31	2	1	PAYMENT_RECEIVED	\N	\N	5.00	XAF	cash	{"provider": null, "mode": "manual", "sale_id": 290}	2026-03-07 03:00:22.311197-05	credit	payment_attempt	147	\N	pay_attempt:147	2026-03-07 08:00:22.317042-05
32	2	1	SALE_REVENUE_GROSS	\N	\N	3500.00	XAF	\N	{"receipt_no": "R-0201-0326-00099"}	2026-03-07 03:00:22.311197-05	credit	sale	290	\N	sale_revenue:290	2026-03-07 08:00:22.317567-05
33	2	1	DEBT_CREATED	\N	\N	3495.00	XAF	\N	{"unpaid_notes": []}	2026-03-07 03:00:22.311197-05	debit	sale	290	\N	debt_created:290	2026-03-07 08:00:22.317986-05
34	2	1	PAYMENT_RECEIVED	\N	\N	4500.00	XAF	cash	{"provider": null, "mode": "manual", "sale_id": 291}	2026-03-07 05:13:58.063568-05	credit	payment_attempt	148	\N	pay_attempt:148	2026-03-07 10:13:58.069777-05
35	2	1	SALE_REVENUE_GROSS	\N	\N	4500.00	XAF	\N	{"receipt_no": "R-0201-0326-00100"}	2026-03-07 05:13:58.063568-05	credit	sale	291	\N	sale_revenue:291	2026-03-07 10:13:58.070318-05
36	2	1	SALE_REVENUE_GROSS	\N	\N	3500.00	XAF	\N	{"receipt_no": "R-0201-0326-00101"}	2026-03-08 03:48:34.454527-04	credit	sale	292	\N	sale_revenue:292	2026-03-08 07:48:34.468661-04
37	2	1	DEBT_CREATED	\N	\N	3500.00	XAF	\N	{"unpaid_notes": []}	2026-03-08 03:48:34.454527-04	debit	sale	292	\N	debt_created:292	2026-03-08 07:48:34.471373-04
38	2	1	PAYMENT_RECEIVED	\N	\N	4500.00	XAF	cash	{"provider": null, "mode": "manual", "sale_id": 293}	2026-03-08 06:28:02.989548-04	credit	payment_attempt	149	\N	pay_attempt:149	2026-03-08 10:28:03.019971-04
39	2	1	SALE_REVENUE_GROSS	\N	\N	4500.00	XAF	\N	{"receipt_no": "R-0201-0326-00102"}	2026-03-08 06:28:02.989548-04	credit	sale	293	\N	sale_revenue:293	2026-03-08 10:28:03.02188-04
40	2	1	PAYMENT_RECEIVED	\N	\N	500.00	XAF	cash	{"provider": null, "mode": "manual", "sale_id": 294}	2026-03-08 06:28:54.58625-04	credit	payment_attempt	150	\N	pay_attempt:150	2026-03-08 10:28:54.600207-04
41	2	1	SALE_REVENUE_GROSS	\N	\N	2000.00	XAF	\N	{"receipt_no": "R-0201-0326-00103"}	2026-03-08 06:28:54.58625-04	credit	sale	294	\N	sale_revenue:294	2026-03-08 10:28:54.601543-04
42	2	1	DEBT_CREATED	\N	\N	1500.00	XAF	\N	{"unpaid_notes": []}	2026-03-08 06:28:54.58625-04	debit	sale	294	\N	debt_created:294	2026-03-08 10:28:54.602836-04
43	2	1	PAYMENT_RECEIVED	\N	\N	2000.00	XAF	cash	{"provider": null, "mode": "manual", "sale_id": 295}	2026-03-08 06:33:41.18152-04	credit	payment_attempt	151	\N	pay_attempt:151	2026-03-08 10:33:41.196052-04
44	2	1	SALE_REVENUE_GROSS	\N	\N	3000.00	XAF	\N	{"receipt_no": "R-0201-0326-00104"}	2026-03-08 06:33:41.18152-04	credit	sale	295	\N	sale_revenue:295	2026-03-08 10:33:41.197437-04
45	2	1	DEBT_CREATED	\N	\N	1000.00	XAF	\N	{"unpaid_notes": []}	2026-03-08 06:33:41.18152-04	debit	sale	295	\N	debt_created:295	2026-03-08 10:33:41.198971-04
46	2	1	PAYMENT_RECEIVED	\N	\N	1000.00	XAF	cash	{"provider": null, "mode": "manual", "sale_id": 296}	2026-03-08 06:40:28.773793-04	credit	payment_attempt	152	\N	pay_attempt:152	2026-03-08 10:40:28.789281-04
47	2	1	SALE_REVENUE_GROSS	\N	\N	2500.00	XAF	\N	{"receipt_no": "R-0201-0326-00105"}	2026-03-08 06:40:28.773793-04	credit	sale	296	\N	sale_revenue:296	2026-03-08 10:40:28.791016-04
48	2	1	DEBT_CREATED	\N	\N	1500.00	XAF	\N	{"unpaid_notes": []}	2026-03-08 06:40:28.773793-04	debit	sale	296	\N	debt_created:296	2026-03-08 10:40:28.792608-04
49	2	1	PAYMENT_RECEIVED	\N	\N	1000.00	XAF	cash	{"provider": null, "mode": "manual", "sale_id": 297}	2026-03-08 06:58:24.958103-04	credit	payment_attempt	153	\N	pay_attempt:153	2026-03-08 10:58:24.978307-04
50	2	1	PAYMENT_RECEIVED	\N	\N	1500.00	XAF	mtn	{"provider": null, "mode": "manual", "sale_id": 297}	2026-03-08 06:58:24.958103-04	credit	payment_attempt	154	\N	pay_attempt:154	2026-03-08 10:58:24.991207-04
51	2	1	PAYMENT_RECEIVED	\N	\N	500.00	XAF	orange	{"provider": null, "mode": "manual", "sale_id": 297}	2026-03-08 06:58:24.958103-04	credit	payment_attempt	155	\N	pay_attempt:155	2026-03-08 10:58:24.996842-04
52	2	1	SALE_REVENUE_GROSS	\N	\N	4500.00	XAF	\N	{"receipt_no": "R-0201-0326-00106"}	2026-03-08 06:58:24.958103-04	credit	sale	297	\N	sale_revenue:297	2026-03-08 10:58:24.998121-04
53	2	1	DISCOUNT_APPLIED	\N	\N	500.00	XAF	\N	{"reason": "Manager override"}	2026-03-08 06:58:24.958103-04	debit	sale	297	\N	sale_discount:297	2026-03-08 10:58:24.999351-04
54	2	1	DEBT_CREATED	\N	\N	1000.00	XAF	\N	{"unpaid_notes": []}	2026-03-08 06:58:24.958103-04	debit	sale	297	\N	debt_created:297	2026-03-08 10:58:25.000662-04
55	2	1	PAYMENT_RECEIVED	\N	\N	4500.00	XAF	cash	{"provider": null, "mode": "manual", "sale_id": 298}	2026-03-08 07:00:07.511788-04	credit	payment_attempt	156	\N	pay_attempt:156	2026-03-08 11:00:07.543892-04
56	2	1	SALE_REVENUE_GROSS	\N	\N	4500.00	XAF	\N	{"receipt_no": "R-0201-0326-00107"}	2026-03-08 07:00:07.511788-04	credit	sale	298	\N	sale_revenue:298	2026-03-08 11:00:07.546647-04
57	2	1	PAYMENT_RECEIVED	\N	\N	2000.00	XAF	cash	{"provider": null, "mode": "manual", "sale_id": 299}	2026-03-08 07:02:34.809979-04	credit	payment_attempt	157	\N	pay_attempt:157	2026-03-08 11:02:34.848078-04
58	2	1	PAYMENT_RECEIVED	\N	\N	3000.00	XAF	mtn	{"provider": null, "mode": "manual", "sale_id": 299}	2026-03-08 07:02:34.809979-04	credit	payment_attempt	158	\N	pay_attempt:158	2026-03-08 11:02:34.860011-04
59	2	1	PAYMENT_RECEIVED	\N	\N	1000.00	XAF	orange	{"provider": null, "mode": "manual", "sale_id": 299}	2026-03-08 07:02:34.809979-04	credit	payment_attempt	159	\N	pay_attempt:159	2026-03-08 11:02:34.868383-04
60	2	1	SALE_REVENUE_GROSS	\N	\N	17500.00	XAF	\N	{"receipt_no": "R-0201-0326-00108"}	2026-03-08 07:02:34.809979-04	credit	sale	299	\N	sale_revenue:299	2026-03-08 11:02:34.870648-04
61	2	1	DISCOUNT_APPLIED	\N	\N	4000.00	XAF	\N	{"reason": "Manager override"}	2026-03-08 07:02:34.809979-04	debit	sale	299	\N	sale_discount:299	2026-03-08 11:02:34.872965-04
62	2	1	COMPLIMENTARY_APPLIED	\N	\N	3000.00	XAF	\N	{"items": []}	2026-03-08 07:02:34.809979-04	debit	sale	299	\N	sale_comp:299	2026-03-08 11:02:34.874995-04
63	2	1	DEBT_CREATED	\N	\N	4500.00	XAF	\N	{"unpaid_notes": []}	2026-03-08 07:02:34.809979-04	debit	sale	299	\N	debt_created:299	2026-03-08 11:02:34.877003-04
64	2	1	PAYMENT_RECEIVED	\N	\N	17500.00	XAF	xafpay	{"provider": "mtn", "mode": "manual", "sale_id": 300}	2026-03-08 07:10:03.408749-04	credit	payment_attempt	160	\N	pay_attempt:160	2026-03-08 11:10:03.481226-04
65	2	1	SALE_REVENUE_GROSS	\N	\N	17500.00	XAF	\N	{"receipt_no": "R-0201-0326-00109"}	2026-03-08 07:10:03.408749-04	credit	sale	300	\N	sale_revenue:300	2026-03-08 11:10:03.48364-04
66	2	1	PAYMENT_RECEIVED	\N	\N	8000.00	XAF	cash	{"provider": null, "mode": "manual", "sale_id": 310}	2026-03-09 13:25:44.319684-04	credit	payment_attempt	161	\N	pay_attempt:161	2026-03-09 17:25:44.380613-04
67	2	1	SALE_REVENUE_GROSS	\N	\N	8000.00	XAF	\N	{"receipt_no": "R-0201-0326-00119"}	2026-03-09 13:25:44.319684-04	credit	sale	310	\N	sale_revenue:310	2026-03-09 17:25:44.384346-04
68	2	1	PAYMENT_RECEIVED	\N	\N	10000.00	XAF	cash	{"provider": null, "mode": "manual", "sale_id": 311}	2026-03-09 13:28:55.964266-04	credit	payment_attempt	162	\N	pay_attempt:162	2026-03-09 17:28:55.973928-04
69	2	1	SALE_REVENUE_GROSS	\N	\N	10000.00	XAF	\N	{"receipt_no": "R-0201-0326-00120"}	2026-03-09 13:28:55.964266-04	credit	sale	311	\N	sale_revenue:311	2026-03-09 17:28:55.975115-04
70	2	1	PAYMENT_RECEIVED	\N	\N	5000.00	XAF	mtn	{"provider": null, "mode": "manual", "sale_id": 312}	2026-03-10 04:21:38.146946-04	credit	payment_attempt	163	\N	pay_attempt:163	2026-03-10 08:21:38.177811-04
71	2	1	SALE_REVENUE_GROSS	\N	\N	5000.00	XAF	\N	{"receipt_no": "R-0201-0326-00121"}	2026-03-10 04:21:38.146946-04	credit	sale	312	\N	sale_revenue:312	2026-03-10 08:21:38.179355-04
72	2	1	PAYMENT_RECEIVED	\N	\N	5000.00	XAF	cash	{"provider": null, "mode": "manual", "sale_id": 314}	2026-03-10 10:41:46.892175-04	credit	payment_attempt	164	\N	pay_attempt:164	2026-03-10 14:41:46.946876-04
73	2	1	SALE_REVENUE_GROSS	\N	\N	5000.00	XAF	\N	{"receipt_no": "R-0201-0326-00123"}	2026-03-10 10:41:46.892175-04	credit	sale	314	\N	sale_revenue:314	2026-03-10 14:41:46.947517-04
74	2	1	PAYMENT_RECEIVED	\N	\N	5000.00	XAF	cash	{"provider": null, "mode": "manual", "sale_id": 315}	2026-03-10 10:46:31.520115-04	credit	payment_attempt	165	\N	pay_attempt:165	2026-03-10 14:46:31.532851-04
75	2	1	SALE_REVENUE_GROSS	\N	\N	5000.00	XAF	\N	{"receipt_no": "R-0201-0326-00124"}	2026-03-10 10:46:31.520115-04	credit	sale	315	\N	sale_revenue:315	2026-03-10 14:46:31.533374-04
\.


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.users (id, username, password_hash, full_name, phone, role, tenant_id, branch_id, is_active, created_at) FROM stdin;
2	cashier	$2b$12$Q97CGkz3Fy1AHxqc.0zZbONWk3YR4lQwbgQDYtVE8AmdyszqiuKXm	\N	\N	cashier	2	1	t	\N
1	admin	$2b$12$htgUsjeOv0lOHZlgASo3IeeLgGvHV7yIPrKbY5DgBQH/e004d7ugu	\N	\N	admin	2	1	t	\N
\.


--
-- Name: billable_units_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.billable_units_id_seq', 138, true);


--
-- Name: branches_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.branches_id_seq', 4, true);


--
-- Name: inventory_items_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.inventory_items_id_seq', 1, false);


--
-- Name: inventory_movements_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.inventory_movements_id_seq', 1, false);


--
-- Name: payment_attempts_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.payment_attempts_id_seq', 165, true);


--
-- Name: payment_intents_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.payment_intents_id_seq', 121, true);


--
-- Name: payments_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.payments_id_seq', 162, true);


--
-- Name: roles_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.roles_id_seq', 24, true);


--
-- Name: sale_items_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.sale_items_id_seq', 882, true);


--
-- Name: sales_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.sales_id_seq', 315, true);


--
-- Name: taxonomy_nodes_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.taxonomy_nodes_id_seq', 55, true);


--
-- Name: tenants_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.tenants_id_seq', 4, true);


--
-- Name: treasury_logs_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.treasury_logs_id_seq', 75, true);


--
-- Name: users_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.users_id_seq', 2, true);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: atomic_unit_taxonomy billable_unit_taxonomy_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.atomic_unit_taxonomy
    ADD CONSTRAINT billable_unit_taxonomy_pkey PRIMARY KEY (atomic_unit_id, taxonomy_node_id);


--
-- Name: billable_unit_taxonomy billable_unit_taxonomy_pkey1; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.billable_unit_taxonomy
    ADD CONSTRAINT billable_unit_taxonomy_pkey1 PRIMARY KEY (atomic_unit_id, taxonomy_node_id);


--
-- Name: atomic_units billable_units_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.atomic_units
    ADD CONSTRAINT billable_units_pkey PRIMARY KEY (id);


--
-- Name: branches branches_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.branches
    ADD CONSTRAINT branches_pkey PRIMARY KEY (id);


--
-- Name: inventory_items inventory_items_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.inventory_items
    ADD CONSTRAINT inventory_items_pkey PRIMARY KEY (id);


--
-- Name: inventory_movements inventory_movements_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.inventory_movements
    ADD CONSTRAINT inventory_movements_pkey PRIMARY KEY (id);


--
-- Name: payment_attempts payment_attempts_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payment_attempts
    ADD CONSTRAINT payment_attempts_pkey PRIMARY KEY (id);


--
-- Name: payment_intents payment_intents_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payment_intents
    ADD CONSTRAINT payment_intents_pkey PRIMARY KEY (id);


--
-- Name: payments payments_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payments
    ADD CONSTRAINT payments_pkey PRIMARY KEY (id);


--
-- Name: roles roles_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_name_key UNIQUE (name);


--
-- Name: roles roles_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (id);


--
-- Name: sale_items sale_items_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sale_items
    ADD CONSTRAINT sale_items_pkey PRIMARY KEY (id);


--
-- Name: sales sales_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sales
    ADD CONSTRAINT sales_pkey PRIMARY KEY (id);


--
-- Name: taxonomy_nodes taxonomy_nodes_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.taxonomy_nodes
    ADD CONSTRAINT taxonomy_nodes_pkey PRIMARY KEY (id);


--
-- Name: tenants tenants_code_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenants
    ADD CONSTRAINT tenants_code_key UNIQUE (code);


--
-- Name: tenants tenants_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenants
    ADD CONSTRAINT tenants_pkey PRIMARY KEY (id);


--
-- Name: treasury_logs treasury_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.treasury_logs
    ADD CONSTRAINT treasury_logs_pkey PRIMARY KEY (id);


--
-- Name: atomic_units uq_billable_unit_sku_per_tenant; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.atomic_units
    ADD CONSTRAINT uq_billable_unit_sku_per_tenant UNIQUE (tenant_id, sku);


--
-- Name: taxonomy_nodes uq_taxonomy_node_name_per_parent; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.taxonomy_nodes
    ADD CONSTRAINT uq_taxonomy_node_name_per_parent UNIQUE (tenant_id, parent_id, name);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: users users_username_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_username_key UNIQUE (username);


--
-- Name: payment_attempts ux_pa_callback_reference; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payment_attempts
    ADD CONSTRAINT ux_pa_callback_reference UNIQUE (callback_reference);


--
-- Name: payment_attempts ux_pa_client_reference; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payment_attempts
    ADD CONSTRAINT ux_pa_client_reference UNIQUE (client_reference);


--
-- Name: idx_payment_intents_gateway_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_payment_intents_gateway_id ON public.payment_intents USING btree (gateway_intent_id);


--
-- Name: idx_payment_intents_meta_gin; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_payment_intents_meta_gin ON public.payment_intents USING gin (meta);


--
-- Name: ix_billable_unit_tenant_active; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_billable_unit_tenant_active ON public.atomic_units USING btree (tenant_id, is_active);


--
-- Name: ix_billable_units_tenant_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_billable_units_tenant_id ON public.atomic_units USING btree (tenant_id);


--
-- Name: ix_branches_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_branches_id ON public.branches USING btree (id);


--
-- Name: ix_inventory_item_tenant_branch; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_inventory_item_tenant_branch ON public.inventory_items USING btree (tenant_id, branch_id);


--
-- Name: ix_inventory_items_billable_unit_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_inventory_items_billable_unit_id ON public.inventory_items USING btree (atomic_unit_id);


--
-- Name: ix_inventory_items_branch_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_inventory_items_branch_id ON public.inventory_items USING btree (branch_id);


--
-- Name: ix_inventory_items_tenant_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_inventory_items_tenant_id ON public.inventory_items USING btree (tenant_id);


--
-- Name: ix_inventory_movement_branch_unit_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_inventory_movement_branch_unit_time ON public.inventory_movements USING btree (branch_id, atomic_unit_id, created_at);


--
-- Name: ix_inventory_movements_billable_unit_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_inventory_movements_billable_unit_id ON public.inventory_movements USING btree (atomic_unit_id);


--
-- Name: ix_inventory_movements_branch_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_inventory_movements_branch_id ON public.inventory_movements USING btree (branch_id);


--
-- Name: ix_inventory_movements_inventory_item_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_inventory_movements_inventory_item_id ON public.inventory_movements USING btree (inventory_item_id);


--
-- Name: ix_inventory_movements_movement_type; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_inventory_movements_movement_type ON public.inventory_movements USING btree (movement_type);


--
-- Name: ix_inventory_movements_reference_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_inventory_movements_reference_id ON public.inventory_movements USING btree (reference_id);


--
-- Name: ix_inventory_movements_tenant_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_inventory_movements_tenant_id ON public.inventory_movements USING btree (tenant_id);


--
-- Name: ix_pa_intent_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_pa_intent_status ON public.payment_attempts USING btree (payment_intent_id, status);


--
-- Name: ix_payment_attempts_cashier_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_payment_attempts_cashier_id ON public.payment_attempts USING btree (cashier_id);


--
-- Name: ix_payment_attempts_gateway_reference; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_payment_attempts_gateway_reference ON public.payment_attempts USING btree (gateway_reference);


--
-- Name: ix_payment_attempts_method; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_payment_attempts_method ON public.payment_attempts USING btree (method);


--
-- Name: ix_payment_attempts_payment_intent_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_payment_attempts_payment_intent_id ON public.payment_attempts USING btree (payment_intent_id);


--
-- Name: ix_payment_attempts_provider; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_payment_attempts_provider ON public.payment_attempts USING btree (provider);


--
-- Name: ix_payment_attempts_provider_reference; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_payment_attempts_provider_reference ON public.payment_attempts USING btree (provider_reference);


--
-- Name: ix_payment_attempts_sale_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_payment_attempts_sale_id ON public.payment_attempts USING btree (sale_id);


--
-- Name: ix_payment_attempts_settlement_mode; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_payment_attempts_settlement_mode ON public.payment_attempts USING btree (settlement_mode);


--
-- Name: ix_payment_attempts_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_payment_attempts_status ON public.payment_attempts USING btree (status);


--
-- Name: ix_payment_gateway_intent; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_payment_gateway_intent ON public.payments USING btree (gateway_intent_id);


--
-- Name: ix_payment_intents_branch_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_payment_intents_branch_id ON public.payment_intents USING btree (branch_id);


--
-- Name: ix_payment_intents_created_by_user_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_payment_intents_created_by_user_id ON public.payment_intents USING btree (created_by_user_id);


--
-- Name: ix_payment_intents_payable_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_payment_intents_payable_id ON public.payment_intents USING btree (payable_id);


--
-- Name: ix_payment_intents_payable_type; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_payment_intents_payable_type ON public.payment_intents USING btree (payable_type);


--
-- Name: ix_payment_intents_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_payment_intents_status ON public.payment_intents USING btree (status);


--
-- Name: ix_payment_intents_tenant_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_payment_intents_tenant_id ON public.payment_intents USING btree (tenant_id);


--
-- Name: ix_payment_sale_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_payment_sale_status ON public.payments USING btree (sale_id, status);


--
-- Name: ix_payments_method; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_payments_method ON public.payments USING btree (method);


--
-- Name: ix_payments_provider; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_payments_provider ON public.payments USING btree (provider);


--
-- Name: ix_payments_reference; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_payments_reference ON public.payments USING btree (reference);


--
-- Name: ix_payments_sale_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_payments_sale_id ON public.payments USING btree (sale_id);


--
-- Name: ix_payments_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_payments_status ON public.payments USING btree (status);


--
-- Name: ix_pi_payable_lookup; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_pi_payable_lookup ON public.payment_intents USING btree (payable_type, payable_id);


--
-- Name: ix_pi_tenant_branch_created; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_pi_tenant_branch_created ON public.payment_intents USING btree (tenant_id, branch_id, created_at);


--
-- Name: ix_sale_item_sale; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_sale_item_sale ON public.sale_items USING btree (sale_id);


--
-- Name: ix_sale_items_billable_unit_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_sale_items_billable_unit_id ON public.sale_items USING btree (atomic_unit_id);


--
-- Name: ix_sale_items_sale_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_sale_items_sale_id ON public.sale_items USING btree (sale_id);


--
-- Name: ix_sale_tenant_branch_created; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_sale_tenant_branch_created ON public.sales USING btree (tenant_id, branch_id, created_at);


--
-- Name: ix_sales_branch_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_sales_branch_id ON public.sales USING btree (branch_id);


--
-- Name: ix_sales_cashier_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_sales_cashier_id ON public.sales USING btree (cashier_id);


--
-- Name: ix_sales_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_sales_status ON public.sales USING btree (status);


--
-- Name: ix_sales_tenant_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_sales_tenant_id ON public.sales USING btree (tenant_id);


--
-- Name: ix_taxonomy_nodes_parent_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_taxonomy_nodes_parent_id ON public.taxonomy_nodes USING btree (parent_id);


--
-- Name: ix_taxonomy_nodes_tenant_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_taxonomy_nodes_tenant_id ON public.taxonomy_nodes USING btree (tenant_id);


--
-- Name: ix_taxonomy_tenant_parent; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_taxonomy_tenant_parent ON public.taxonomy_nodes USING btree (tenant_id, parent_id);


--
-- Name: ix_tenants_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_tenants_id ON public.tenants USING btree (id);


--
-- Name: ix_treasury_logs_attempt; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_treasury_logs_attempt ON public.treasury_logs USING btree (payment_attempt_id);


--
-- Name: ix_treasury_logs_occurred; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_treasury_logs_occurred ON public.treasury_logs USING btree (tenant_id, occurred_at DESC);


--
-- Name: ix_treasury_logs_reference; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_treasury_logs_reference ON public.treasury_logs USING btree (reference_type, reference_id);


--
-- Name: ix_treasury_logs_sale; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_treasury_logs_sale ON public.treasury_logs USING btree (sale_id);


--
-- Name: ix_treasury_logs_tenant_created; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_treasury_logs_tenant_created ON public.treasury_logs USING btree (tenant_id, created_at);


--
-- Name: ix_users_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_users_id ON public.users USING btree (id);


--
-- Name: treasury_logs_idempotency_key_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX treasury_logs_idempotency_key_idx ON public.treasury_logs USING btree (tenant_id, idempotency_key);


--
-- Name: uq_inventory_item_branch_unit; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX uq_inventory_item_branch_unit ON public.inventory_items USING btree (branch_id, atomic_unit_id);


--
-- Name: ux_pa_callback_reference_not_null; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX ux_pa_callback_reference_not_null ON public.payment_attempts USING btree (callback_reference) WHERE (callback_reference IS NOT NULL);


--
-- Name: ux_sales_receipt_no; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX ux_sales_receipt_no ON public.sales USING btree (tenant_id, branch_id, receipt_no);


--
-- Name: billable_unit_taxonomy billable_unit_taxonomy_atomic_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.billable_unit_taxonomy
    ADD CONSTRAINT billable_unit_taxonomy_atomic_unit_id_fkey FOREIGN KEY (atomic_unit_id) REFERENCES public.atomic_units(id) ON DELETE CASCADE;


--
-- Name: atomic_unit_taxonomy billable_unit_taxonomy_billable_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.atomic_unit_taxonomy
    ADD CONSTRAINT billable_unit_taxonomy_billable_unit_id_fkey FOREIGN KEY (atomic_unit_id) REFERENCES public.atomic_units(id) ON DELETE CASCADE;


--
-- Name: atomic_unit_taxonomy billable_unit_taxonomy_taxonomy_node_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.atomic_unit_taxonomy
    ADD CONSTRAINT billable_unit_taxonomy_taxonomy_node_id_fkey FOREIGN KEY (taxonomy_node_id) REFERENCES public.taxonomy_nodes(id) ON DELETE CASCADE;


--
-- Name: billable_unit_taxonomy billable_unit_taxonomy_taxonomy_node_id_fkey1; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.billable_unit_taxonomy
    ADD CONSTRAINT billable_unit_taxonomy_taxonomy_node_id_fkey1 FOREIGN KEY (taxonomy_node_id) REFERENCES public.taxonomy_nodes(id) ON DELETE CASCADE;


--
-- Name: atomic_units billable_units_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.atomic_units
    ADD CONSTRAINT billable_units_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: branches branches_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.branches
    ADD CONSTRAINT branches_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id);


--
-- Name: inventory_items inventory_items_billable_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.inventory_items
    ADD CONSTRAINT inventory_items_billable_unit_id_fkey FOREIGN KEY (atomic_unit_id) REFERENCES public.atomic_units(id);


--
-- Name: inventory_movements inventory_movements_billable_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.inventory_movements
    ADD CONSTRAINT inventory_movements_billable_unit_id_fkey FOREIGN KEY (atomic_unit_id) REFERENCES public.atomic_units(id);


--
-- Name: inventory_movements inventory_movements_inventory_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.inventory_movements
    ADD CONSTRAINT inventory_movements_inventory_item_id_fkey FOREIGN KEY (inventory_item_id) REFERENCES public.inventory_items(id) ON DELETE CASCADE;


--
-- Name: payment_attempts payment_attempts_cashier_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payment_attempts
    ADD CONSTRAINT payment_attempts_cashier_id_fkey FOREIGN KEY (cashier_id) REFERENCES public.users(id);


--
-- Name: payment_attempts payment_attempts_payment_intent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payment_attempts
    ADD CONSTRAINT payment_attempts_payment_intent_id_fkey FOREIGN KEY (payment_intent_id) REFERENCES public.payment_intents(id) ON DELETE CASCADE;


--
-- Name: payment_attempts payment_attempts_sale_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payment_attempts
    ADD CONSTRAINT payment_attempts_sale_id_fkey FOREIGN KEY (sale_id) REFERENCES public.sales(id) ON DELETE SET NULL;


--
-- Name: payment_intents payment_intents_branch_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payment_intents
    ADD CONSTRAINT payment_intents_branch_id_fkey FOREIGN KEY (branch_id) REFERENCES public.branches(id) ON DELETE CASCADE;


--
-- Name: payment_intents payment_intents_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payment_intents
    ADD CONSTRAINT payment_intents_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


--
-- Name: payment_intents payment_intents_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payment_intents
    ADD CONSTRAINT payment_intents_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: payments payments_sale_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payments
    ADD CONSTRAINT payments_sale_id_fkey FOREIGN KEY (sale_id) REFERENCES public.sales(id) ON DELETE CASCADE;


--
-- Name: sale_items sale_items_billable_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sale_items
    ADD CONSTRAINT sale_items_billable_unit_id_fkey FOREIGN KEY (atomic_unit_id) REFERENCES public.atomic_units(id);


--
-- Name: sale_items sale_items_sale_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sale_items
    ADD CONSTRAINT sale_items_sale_id_fkey FOREIGN KEY (sale_id) REFERENCES public.sales(id) ON DELETE CASCADE;


--
-- Name: sales sales_branch_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sales
    ADD CONSTRAINT sales_branch_id_fkey FOREIGN KEY (branch_id) REFERENCES public.branches(id) ON DELETE CASCADE;


--
-- Name: sales sales_cashier_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sales
    ADD CONSTRAINT sales_cashier_id_fkey FOREIGN KEY (cashier_id) REFERENCES public.users(id);


--
-- Name: sales sales_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sales
    ADD CONSTRAINT sales_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: taxonomy_nodes taxonomy_nodes_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.taxonomy_nodes
    ADD CONSTRAINT taxonomy_nodes_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.taxonomy_nodes(id) ON DELETE CASCADE;


--
-- Name: taxonomy_nodes taxonomy_nodes_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.taxonomy_nodes
    ADD CONSTRAINT taxonomy_nodes_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: users users_branch_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_branch_id_fkey FOREIGN KEY (branch_id) REFERENCES public.branches(id);


--
-- Name: users users_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id);


--
-- PostgreSQL database dump complete
--

