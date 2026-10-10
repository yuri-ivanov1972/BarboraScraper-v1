-- Development public schema only; no rows, ownership, or grants.
-- Import into an empty PostgreSQL 16+ database using psql 16.10+ or newer.
-- public schema creation is made idempotent; table creation is intentionally strict.

--
-- PostgreSQL database dump
--

\restrict hHnEZgujDo2KtoILNprBssWG26pjp0daTD4sgucTgk32wndFzdlJ3yZn6dNvSbk

-- Dumped from database version 16.10
-- Dumped by pg_dump version 16.10

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA IF NOT EXISTS public;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: brand_producers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.brand_producers (
    brand_id integer NOT NULL,
    producer_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: brands; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.brands (
    id integer NOT NULL,
    name text NOT NULL,
    normalized_name text NOT NULL,
    website_url text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: brands_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.brands_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: brands_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.brands_id_seq OWNED BY public.brands.id;


--
-- Name: category_processing_jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.category_processing_jobs (
    id integer NOT NULL,
    category_code character varying(50) NOT NULL,
    category_id integer,
    total_products integer NOT NULL,
    processed_count integer DEFAULT 0,
    status character varying(30) DEFAULT 'in_progress'::character varying NOT NULL,
    started_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    last_updated timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    completed_at timestamp without time zone,
    priority integer DEFAULT 5,
    scheduled_for timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    current_worker_id character varying(100),
    last_heartbeat timestamp without time zone,
    retry_count integer DEFAULT 0,
    max_retries integer DEFAULT 3,
    lock_version integer DEFAULT 0,
    log_path text,
    notes text,
    requested_by character varying(100) DEFAULT 'streamlit_ui'::character varying,
    update_mode character varying(20) DEFAULT 'full'::character varying NOT NULL
);


--
-- Name: category_processing_jobs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.category_processing_jobs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: category_processing_jobs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.category_processing_jobs_id_seq OWNED BY public.category_processing_jobs.id;


--
-- Name: daily_update_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.daily_update_logs (
    id integer NOT NULL,
    update_type character varying(50) DEFAULT 'daily'::character varying NOT NULL,
    start_time timestamp without time zone NOT NULL,
    end_time timestamp without time zone NOT NULL,
    duration_minutes numeric,
    categories_processed integer DEFAULT 0,
    jobs_completed integer DEFAULT 0,
    jobs_failed integer DEFAULT 0,
    products_added integer DEFAULT 0,
    products_updated integer DEFAULT 0,
    products_removed integer DEFAULT 0,
    price_changes_count integer DEFAULT 0,
    availability_changes jsonb,
    ingredient_changes_count integer DEFAULT 0,
    nutrition_changes_count integer DEFAULT 0,
    photo_changes_count integer DEFAULT 0,
    errors_count integer DEFAULT 0,
    error_details jsonb,
    summary text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: daily_update_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.daily_update_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: daily_update_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.daily_update_logs_id_seq OWNED BY public.daily_update_logs.id;


--
-- Name: ingredient_analysis; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ingredient_analysis (
    id integer NOT NULL,
    ingredient text NOT NULL,
    frequency integer NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    clean_name text,
    category character varying(20) DEFAULT 'uncategorized'::character varying,
    is_processed boolean,
    suspicion_level text,
    suspicion_category text,
    health_note text
);


--
-- Name: ingredient_analysis_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ingredient_analysis_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ingredient_analysis_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ingredient_analysis_id_seq OWNED BY public.ingredient_analysis.id;


--
-- Name: ingredient_product_mapping; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ingredient_product_mapping (
    ingredient_id integer NOT NULL,
    product_sku text NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: job_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.job_events (
    id integer NOT NULL,
    job_id integer NOT NULL,
    event_type character varying(50) NOT NULL,
    message text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    metadata jsonb
);


--
-- Name: job_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.job_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: job_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.job_events_id_seq OWNED BY public.job_events.id;


--
-- Name: lightweight_update_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.lightweight_update_runs (
    run_id integer NOT NULL,
    started_at timestamp without time zone,
    ended_at timestamp without time zone,
    duration_seconds double precision,
    categories_processed integer DEFAULT 0,
    products_checked integer DEFAULT 0,
    products_updated integer DEFAULT 0,
    price_changes integer DEFAULT 0,
    availability_changes integer DEFAULT 0,
    new_products_found integer DEFAULT 0,
    new_product_jobs_created integer DEFAULT 0,
    errors_count integer DEFAULT 0,
    status character varying(50) DEFAULT 'running'::character varying,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: lightweight_update_runs_run_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.lightweight_update_runs_run_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: lightweight_update_runs_run_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.lightweight_update_runs_run_id_seq OWNED BY public.lightweight_update_runs.run_id;


--
-- Name: normalized_categories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.normalized_categories (
    category_id integer NOT NULL,
    barbora_category_code text,
    name_lv text NOT NULL,
    name_en text,
    parent_category_id integer,
    level integer NOT NULL,
    normalized_category text
);


--
-- Name: nutrition_validation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.nutrition_validation (
    id integer NOT NULL,
    product_id integer NOT NULL,
    suspicion_level character varying(10) NOT NULL,
    suspicion_score numeric DEFAULT 0 NOT NULL,
    reasons jsonb DEFAULT '[]'::jsonb NOT NULL,
    checked_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT nutrition_validation_suspicion_level_check CHECK (((suspicion_level)::text = ANY ((ARRAY['none'::character varying, 'low'::character varying, 'medium'::character varying, 'high'::character varying])::text[])))
);


--
-- Name: nutrition_validation_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.nutrition_validation_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: nutrition_validation_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.nutrition_validation_id_seq OWNED BY public.nutrition_validation.id;


--
-- Name: nutritionfacts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.nutritionfacts (
    nutrition_id integer NOT NULL,
    product_id integer NOT NULL,
    ingredients_text text,
    energy_kcal integer,
    energy_kj integer,
    fat_total numeric,
    fat_saturated numeric,
    carbs_total numeric,
    carbs_sugars numeric,
    protein numeric,
    salt numeric,
    fiber numeric,
    nutri_score_grade character(1),
    nutri_score_points integer,
    data_source_date timestamp with time zone,
    usda_fdc_id integer,
    is_fiber_correct boolean DEFAULT false,
    nutrition_manual_edit boolean DEFAULT false
);


--
-- Name: nutritionfacts_nutrition_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.nutritionfacts_nutrition_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: nutritionfacts_nutrition_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.nutritionfacts_nutrition_id_seq OWNED BY public.nutritionfacts.nutrition_id;


--
-- Name: processing_workers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.processing_workers (
    id integer NOT NULL,
    worker_id character varying(100) NOT NULL,
    hostname character varying(255),
    pid integer,
    status character varying(20) DEFAULT 'idle'::character varying NOT NULL,
    current_job_id integer,
    last_heartbeat timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    started_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    stopped_at timestamp without time zone,
    error_message text
);


--
-- Name: processing_workers_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.processing_workers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: processing_workers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.processing_workers_id_seq OWNED BY public.processing_workers.id;


--
-- Name: producers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.producers (
    id integer NOT NULL,
    name text NOT NULL,
    normalized_name text NOT NULL,
    website_url text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: producers_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.producers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: producers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.producers_id_seq OWNED BY public.producers.id;


--
-- Name: products; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.products (
    product_id integer NOT NULL,
    sku text NOT NULL,
    name text NOT NULL,
    name_norm text,
    barbora_url text,
    category_id integer NOT NULL,
    quantity_value numeric,
    quantity_unit character varying(50),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    country_of_origin character varying(255) DEFAULT 'Unknown'::character varying,
    nutrition_source character varying(50),
    needs_enrichment boolean DEFAULT false,
    enrichment_reviewed boolean DEFAULT false,
    enrichment_skipped boolean DEFAULT false,
    ingredients text,
    allergens text,
    description text,
    rimi_category_code integer,
    has_confirmed_match boolean DEFAULT false,
    nova_score integer,
    nova_source character varying(30),
    name_manual_edit boolean DEFAULT false,
    is_hidden boolean DEFAULT false,
    brand_id integer,
    producer_id integer
);


--
-- Name: product_ingredient_cards; Type: MATERIALIZED VIEW; Schema: public; Owner: -
--

CREATE MATERIALIZED VIEW public.product_ingredient_cards AS
 SELECT p.sku,
    p.name,
    p.category_id,
    nc.name_lv AS category_name,
    COALESCE(jsonb_agg(jsonb_build_object('id', ia.id, 'name', COALESCE(ia.clean_name, ia.ingredient), 'category', ia.category, 'is_processed', ia.is_processed, 'suspicion_level', ia.suspicion_level, 'suspicion_category', ia.suspicion_category, 'health_note', ia.health_note) ORDER BY ia.frequency DESC) FILTER (WHERE (ia.id IS NOT NULL)), '[]'::jsonb) AS ingredients,
    count(ia.id) FILTER (WHERE ((ia.category)::text = 'natural'::text)) AS natural_count,
    count(ia.id) FILTER (WHERE ((ia.category)::text = 'processed'::text)) AS processed_count,
    count(ia.id) FILTER (WHERE (ia.suspicion_level = 'avoid'::text)) AS avoid_count,
    count(ia.id) FILTER (WHERE (ia.suspicion_level = 'limit'::text)) AS limit_count,
    count(ia.id) FILTER (WHERE (ia.suspicion_level = 'caution'::text)) AS caution_count
   FROM (((public.products p
     LEFT JOIN public.normalized_categories nc ON ((p.category_id = nc.category_id)))
     LEFT JOIN public.ingredient_product_mapping ipm ON ((p.sku = ipm.product_sku)))
     LEFT JOIN public.ingredient_analysis ia ON ((ipm.ingredient_id = ia.id)))
  GROUP BY p.sku, p.name, p.category_id, nc.name_lv
  WITH NO DATA;


--
-- Name: product_price_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.product_price_history (
    price_history_id integer NOT NULL,
    product_id integer NOT NULL,
    price numeric NOT NULL,
    currency character varying(3) DEFAULT 'EUR'::character varying NOT NULL,
    is_available boolean NOT NULL,
    recorded_at timestamp with time zone NOT NULL,
    data_source character varying(100),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    price_per_unit numeric,
    price_per_unit_type character varying(20),
    discount_price numeric,
    discount_price_per_unit numeric
);


--
-- Name: product_price_history_price_history_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.product_price_history_price_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: product_price_history_price_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.product_price_history_price_history_id_seq OWNED BY public.product_price_history.price_history_id;


--
-- Name: product_processing_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.product_processing_log (
    id integer NOT NULL,
    job_id integer NOT NULL,
    sku character varying(50) NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    error_message text,
    processed_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    product_url text,
    price numeric(10,2),
    retail_price numeric(10,2),
    price_per_unit numeric(10,4),
    price_per_unit_type character varying(20),
    is_available boolean DEFAULT true,
    promotion_data jsonb
);


--
-- Name: product_processing_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.product_processing_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: product_processing_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.product_processing_log_id_seq OWNED BY public.product_processing_log.id;


--
-- Name: productphotos; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.productphotos (
    photo_id integer NOT NULL,
    product_id integer NOT NULL,
    photo_url text NOT NULL,
    alt_text text,
    is_primary boolean DEFAULT false
);


--
-- Name: productphotos_photo_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.productphotos_photo_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: productphotos_photo_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.productphotos_photo_id_seq OWNED BY public.productphotos.photo_id;


--
-- Name: products_product_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.products_product_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: products_product_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.products_product_id_seq OWNED BY public.products.product_id;


--
-- Name: rimi_nova_categories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rimi_nova_categories (
    rimi_category_code integer NOT NULL,
    nova_score integer,
    synced_at timestamp with time zone DEFAULT now()
);


--
-- Name: translation_cache; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.translation_cache (
    cache_id integer NOT NULL,
    product_name_hash character varying(64) NOT NULL,
    product_name text NOT NULL,
    category_name text,
    english_translation text NOT NULL,
    translation_method character varying(50),
    confidence numeric(3,2),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: translation_cache_cache_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.translation_cache_cache_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: translation_cache_cache_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.translation_cache_cache_id_seq OWNED BY public.translation_cache.cache_id;


--
-- Name: update_statistics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.update_statistics (
    id integer NOT NULL,
    job_id integer NOT NULL,
    category_code character varying(50) NOT NULL,
    total_checked integer DEFAULT 0,
    new_products integer DEFAULT 0,
    price_changed integer DEFAULT 0,
    availability_changed integer DEFAULT 0,
    data_updated integer DEFAULT 0,
    unchanged integer DEFAULT 0,
    failed integer DEFAULT 0,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: update_statistics_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.update_statistics_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: update_statistics_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.update_statistics_id_seq OWNED BY public.update_statistics.id;


--
-- Name: brands id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.brands ALTER COLUMN id SET DEFAULT nextval('public.brands_id_seq'::regclass);


--
-- Name: category_processing_jobs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.category_processing_jobs ALTER COLUMN id SET DEFAULT nextval('public.category_processing_jobs_id_seq'::regclass);


--
-- Name: daily_update_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_update_logs ALTER COLUMN id SET DEFAULT nextval('public.daily_update_logs_id_seq'::regclass);


--
-- Name: ingredient_analysis id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ingredient_analysis ALTER COLUMN id SET DEFAULT nextval('public.ingredient_analysis_id_seq'::regclass);


--
-- Name: job_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_events ALTER COLUMN id SET DEFAULT nextval('public.job_events_id_seq'::regclass);


--
-- Name: lightweight_update_runs run_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lightweight_update_runs ALTER COLUMN run_id SET DEFAULT nextval('public.lightweight_update_runs_run_id_seq'::regclass);


--
-- Name: nutrition_validation id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nutrition_validation ALTER COLUMN id SET DEFAULT nextval('public.nutrition_validation_id_seq'::regclass);


--
-- Name: nutritionfacts nutrition_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nutritionfacts ALTER COLUMN nutrition_id SET DEFAULT nextval('public.nutritionfacts_nutrition_id_seq'::regclass);


--
-- Name: processing_workers id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.processing_workers ALTER COLUMN id SET DEFAULT nextval('public.processing_workers_id_seq'::regclass);


--
-- Name: producers id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.producers ALTER COLUMN id SET DEFAULT nextval('public.producers_id_seq'::regclass);


--
-- Name: product_price_history price_history_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.product_price_history ALTER COLUMN price_history_id SET DEFAULT nextval('public.product_price_history_price_history_id_seq'::regclass);


--
-- Name: product_processing_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.product_processing_log ALTER COLUMN id SET DEFAULT nextval('public.product_processing_log_id_seq'::regclass);


--
-- Name: productphotos photo_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.productphotos ALTER COLUMN photo_id SET DEFAULT nextval('public.productphotos_photo_id_seq'::regclass);


--
-- Name: products product_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.products ALTER COLUMN product_id SET DEFAULT nextval('public.products_product_id_seq'::regclass);


--
-- Name: translation_cache cache_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.translation_cache ALTER COLUMN cache_id SET DEFAULT nextval('public.translation_cache_cache_id_seq'::regclass);


--
-- Name: update_statistics id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.update_statistics ALTER COLUMN id SET DEFAULT nextval('public.update_statistics_id_seq'::regclass);


--
-- Name: brand_producers brand_producers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.brand_producers
    ADD CONSTRAINT brand_producers_pkey PRIMARY KEY (brand_id, producer_id);


--
-- Name: brands brands_normalized_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.brands
    ADD CONSTRAINT brands_normalized_name_key UNIQUE (normalized_name);


--
-- Name: brands brands_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.brands
    ADD CONSTRAINT brands_pkey PRIMARY KEY (id);


--
-- Name: category_processing_jobs category_processing_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.category_processing_jobs
    ADD CONSTRAINT category_processing_jobs_pkey PRIMARY KEY (id);


--
-- Name: daily_update_logs daily_update_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_update_logs
    ADD CONSTRAINT daily_update_logs_pkey PRIMARY KEY (id);


--
-- Name: ingredient_analysis ingredient_analysis_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ingredient_analysis
    ADD CONSTRAINT ingredient_analysis_pkey PRIMARY KEY (id);


--
-- Name: ingredient_product_mapping ingredient_product_mapping_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ingredient_product_mapping
    ADD CONSTRAINT ingredient_product_mapping_pkey PRIMARY KEY (ingredient_id, product_sku);


--
-- Name: job_events job_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_events
    ADD CONSTRAINT job_events_pkey PRIMARY KEY (id);


--
-- Name: lightweight_update_runs lightweight_update_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lightweight_update_runs
    ADD CONSTRAINT lightweight_update_runs_pkey PRIMARY KEY (run_id);


--
-- Name: normalized_categories normalized_categories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.normalized_categories
    ADD CONSTRAINT normalized_categories_pkey PRIMARY KEY (category_id);


--
-- Name: nutrition_validation nutrition_validation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nutrition_validation
    ADD CONSTRAINT nutrition_validation_pkey PRIMARY KEY (id);


--
-- Name: nutrition_validation nutrition_validation_product_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nutrition_validation
    ADD CONSTRAINT nutrition_validation_product_id_key UNIQUE (product_id);


--
-- Name: nutritionfacts nutritionfacts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nutritionfacts
    ADD CONSTRAINT nutritionfacts_pkey PRIMARY KEY (nutrition_id);


--
-- Name: nutritionfacts nutritionfacts_product_id_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nutritionfacts
    ADD CONSTRAINT nutritionfacts_product_id_unique UNIQUE (product_id);


--
-- Name: processing_workers processing_workers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.processing_workers
    ADD CONSTRAINT processing_workers_pkey PRIMARY KEY (id);


--
-- Name: processing_workers processing_workers_worker_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.processing_workers
    ADD CONSTRAINT processing_workers_worker_id_key UNIQUE (worker_id);


--
-- Name: producers producers_normalized_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.producers
    ADD CONSTRAINT producers_normalized_name_key UNIQUE (normalized_name);


--
-- Name: producers producers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.producers
    ADD CONSTRAINT producers_pkey PRIMARY KEY (id);


--
-- Name: product_price_history product_price_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.product_price_history
    ADD CONSTRAINT product_price_history_pkey PRIMARY KEY (price_history_id);


--
-- Name: product_processing_log product_processing_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.product_processing_log
    ADD CONSTRAINT product_processing_log_pkey PRIMARY KEY (id);


--
-- Name: productphotos productphotos_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.productphotos
    ADD CONSTRAINT productphotos_pkey PRIMARY KEY (photo_id);


--
-- Name: products products_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.products
    ADD CONSTRAINT products_pkey PRIMARY KEY (product_id);


--
-- Name: products products_sku_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.products
    ADD CONSTRAINT products_sku_key UNIQUE (sku);


--
-- Name: rimi_nova_categories rimi_nova_categories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rimi_nova_categories
    ADD CONSTRAINT rimi_nova_categories_pkey PRIMARY KEY (rimi_category_code);


--
-- Name: translation_cache translation_cache_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.translation_cache
    ADD CONSTRAINT translation_cache_pkey PRIMARY KEY (cache_id);


--
-- Name: translation_cache translation_cache_product_name_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.translation_cache
    ADD CONSTRAINT translation_cache_product_name_hash_key UNIQUE (product_name_hash);


--
-- Name: update_statistics update_statistics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.update_statistics
    ADD CONSTRAINT update_statistics_pkey PRIMARY KEY (id);


--
-- Name: idx_brand_producers_producer; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_brand_producers_producer ON public.brand_producers USING btree (producer_id);


--
-- Name: idx_daily_logs_start; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_daily_logs_start ON public.daily_update_logs USING btree (start_time);


--
-- Name: idx_daily_logs_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_daily_logs_type ON public.daily_update_logs USING btree (update_type);


--
-- Name: idx_ingredient_analysis_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ingredient_analysis_category ON public.ingredient_analysis USING btree (category);


--
-- Name: idx_ingredient_analysis_processed; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ingredient_analysis_processed ON public.ingredient_analysis USING btree (is_processed);


--
-- Name: idx_ingredient_analysis_suspicion; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ingredient_analysis_suspicion ON public.ingredient_analysis USING btree (suspicion_level);


--
-- Name: idx_ingredient_product_mapping_sku; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ingredient_product_mapping_sku ON public.ingredient_product_mapping USING btree (product_sku);


--
-- Name: idx_job_events_job; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_job_events_job ON public.job_events USING btree (job_id);


--
-- Name: idx_job_events_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_job_events_type ON public.job_events USING btree (event_type);


--
-- Name: idx_jobs_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jobs_category ON public.category_processing_jobs USING btree (category_code);


--
-- Name: idx_jobs_priority; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jobs_priority ON public.category_processing_jobs USING btree (priority DESC, scheduled_for);


--
-- Name: idx_jobs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jobs_status ON public.category_processing_jobs USING btree (status);


--
-- Name: idx_jobs_worker; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jobs_worker ON public.category_processing_jobs USING btree (current_worker_id);


--
-- Name: idx_normalized_categories_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_normalized_categories_code ON public.normalized_categories USING btree (barbora_category_code);


--
-- Name: idx_normalized_categories_level; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_normalized_categories_level ON public.normalized_categories USING btree (level);


--
-- Name: idx_normalized_categories_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_normalized_categories_parent ON public.normalized_categories USING btree (parent_category_id);


--
-- Name: idx_nutrition_validation_level_score; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_nutrition_validation_level_score ON public.nutrition_validation USING btree (suspicion_level, suspicion_score DESC);


--
-- Name: idx_nutritionfacts_nutriscore; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_nutritionfacts_nutriscore ON public.nutritionfacts USING btree (nutri_score_grade);


--
-- Name: idx_nutritionfacts_product; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_nutritionfacts_product ON public.nutritionfacts USING btree (product_id);


--
-- Name: idx_price_history_product; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_price_history_product ON public.product_price_history USING btree (product_id);


--
-- Name: idx_price_history_product_recorded; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_price_history_product_recorded ON public.product_price_history USING btree (product_id, recorded_at DESC);


--
-- Name: idx_price_history_recorded; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_price_history_recorded ON public.product_price_history USING btree (recorded_at);


--
-- Name: idx_processing_log_job; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_processing_log_job ON public.product_processing_log USING btree (job_id);


--
-- Name: idx_processing_log_sku; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_processing_log_sku ON public.product_processing_log USING btree (sku);


--
-- Name: idx_product_ingredient_cards_sku; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_product_ingredient_cards_sku ON public.product_ingredient_cards USING btree (sku);


--
-- Name: idx_productphotos_product; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_productphotos_product ON public.productphotos USING btree (product_id);


--
-- Name: idx_products_brand; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_products_brand ON public.products USING btree (brand_id);


--
-- Name: idx_products_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_products_category ON public.products USING btree (category_id);


--
-- Name: idx_products_name_norm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_products_name_norm ON public.products USING btree (name_norm);


--
-- Name: idx_products_needs_enrichment; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_products_needs_enrichment ON public.products USING btree (needs_enrichment);


--
-- Name: idx_products_producer; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_products_producer ON public.products USING btree (producer_id);


--
-- Name: idx_products_sku; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_products_sku ON public.products USING btree (sku);


--
-- Name: idx_translation_cache_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_translation_cache_hash ON public.translation_cache USING btree (product_name_hash);


--
-- Name: idx_update_stats_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_update_stats_category ON public.update_statistics USING btree (category_code);


--
-- Name: idx_update_stats_job; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_update_stats_job ON public.update_statistics USING btree (job_id);


--
-- Name: idx_workers_heartbeat; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workers_heartbeat ON public.processing_workers USING btree (last_heartbeat);


--
-- Name: idx_workers_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workers_status ON public.processing_workers USING btree (status);


--
-- Name: ingredient_analysis_ingredient_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ingredient_analysis_ingredient_idx ON public.ingredient_analysis USING btree (ingredient);


--
-- Name: brand_producers brand_producers_brand_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.brand_producers
    ADD CONSTRAINT brand_producers_brand_id_fkey FOREIGN KEY (brand_id) REFERENCES public.brands(id) ON DELETE CASCADE;


--
-- Name: brand_producers brand_producers_producer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.brand_producers
    ADD CONSTRAINT brand_producers_producer_id_fkey FOREIGN KEY (producer_id) REFERENCES public.producers(id) ON DELETE CASCADE;


--
-- Name: category_processing_jobs category_processing_jobs_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.category_processing_jobs
    ADD CONSTRAINT category_processing_jobs_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.normalized_categories(category_id);


--
-- Name: ingredient_product_mapping ingredient_product_mapping_ingredient_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ingredient_product_mapping
    ADD CONSTRAINT ingredient_product_mapping_ingredient_id_fkey FOREIGN KEY (ingredient_id) REFERENCES public.ingredient_analysis(id);


--
-- Name: job_events job_events_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_events
    ADD CONSTRAINT job_events_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.category_processing_jobs(id);


--
-- Name: normalized_categories normalized_categories_parent_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.normalized_categories
    ADD CONSTRAINT normalized_categories_parent_category_id_fkey FOREIGN KEY (parent_category_id) REFERENCES public.normalized_categories(category_id);


--
-- Name: nutrition_validation nutrition_validation_product_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nutrition_validation
    ADD CONSTRAINT nutrition_validation_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(product_id) ON DELETE CASCADE;


--
-- Name: nutritionfacts nutritionfacts_product_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nutritionfacts
    ADD CONSTRAINT nutritionfacts_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(product_id);


--
-- Name: processing_workers processing_workers_current_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.processing_workers
    ADD CONSTRAINT processing_workers_current_job_id_fkey FOREIGN KEY (current_job_id) REFERENCES public.category_processing_jobs(id);


--
-- Name: product_price_history product_price_history_product_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.product_price_history
    ADD CONSTRAINT product_price_history_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(product_id);


--
-- Name: product_processing_log product_processing_log_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.product_processing_log
    ADD CONSTRAINT product_processing_log_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.category_processing_jobs(id);


--
-- Name: productphotos productphotos_product_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.productphotos
    ADD CONSTRAINT productphotos_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(product_id);


--
-- Name: products products_brand_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.products
    ADD CONSTRAINT products_brand_id_fkey FOREIGN KEY (brand_id) REFERENCES public.brands(id);


--
-- Name: products products_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.products
    ADD CONSTRAINT products_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.normalized_categories(category_id);


--
-- Name: products products_producer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.products
    ADD CONSTRAINT products_producer_id_fkey FOREIGN KEY (producer_id) REFERENCES public.producers(id);


--
-- Name: update_statistics update_statistics_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.update_statistics
    ADD CONSTRAINT update_statistics_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.category_processing_jobs(id);


--
-- PostgreSQL database dump complete
--

\unrestrict hHnEZgujDo2KtoILNprBssWG26pjp0daTD4sgucTgk32wndFzdlJ3yZn6dNvSbk

