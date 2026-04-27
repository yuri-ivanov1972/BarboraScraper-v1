-- =============================================================================
-- Barbora Grocery Price Tracker — Complete Database Schema
-- PostgreSQL 16
-- Generated from live database: 2026-04-27
-- =============================================================================

-- ============================================================
-- EXTENSIONS (enable if not already present)
-- ============================================================
-- CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- for fuzzy name search


-- ============================================================
-- 1. NORMALIZED_CATEGORIES
--    Hierarchical category tree (self-referencing parent).
--    Must be created before products and jobs.
-- ============================================================
CREATE TABLE IF NOT EXISTS normalized_categories (
    category_id           INTEGER         PRIMARY KEY,
    barbora_category_code TEXT,
    name_lv               TEXT            NOT NULL,
    name_en               TEXT,
    parent_category_id    INTEGER         REFERENCES normalized_categories(category_id),
    level                 INTEGER         NOT NULL,
    normalized_category   TEXT
);

CREATE INDEX IF NOT EXISTS idx_normalized_categories_code   ON normalized_categories (barbora_category_code);
CREATE INDEX IF NOT EXISTS idx_normalized_categories_level  ON normalized_categories (level);
CREATE INDEX IF NOT EXISTS idx_normalized_categories_parent ON normalized_categories (parent_category_id);


-- ============================================================
-- 2. PRODUCTS
--    Core product catalogue. Prices live in product_price_history.
--    Nutrition lives in nutritionfacts (1-to-1 via UNIQUE FK).
-- ============================================================
CREATE TABLE IF NOT EXISTS products (
    product_id          SERIAL          PRIMARY KEY,
    sku                 TEXT            NOT NULL UNIQUE,
    name                TEXT            NOT NULL,
    name_norm           TEXT,                                  -- normalised/lowercased for search
    barbora_url         TEXT,
    category_id         INTEGER         NOT NULL REFERENCES normalized_categories(category_id),
    quantity_value      NUMERIC,                               -- e.g. 500  (grams, ml, pieces …)
    quantity_unit       VARCHAR(50),                           -- g | kg | ml | l | gab
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    country_of_origin   VARCHAR(255)    DEFAULT 'Unknown',
    -- nutrition enrichment tracking
    nutrition_source    VARCHAR(50),                           -- 'rimi_scraped' | 'ai_generated' | 'manual_entry'
    needs_enrichment    BOOLEAN         DEFAULT FALSE,
    enrichment_reviewed BOOLEAN         DEFAULT FALSE,
    enrichment_skipped  BOOLEAN         DEFAULT FALSE,
    -- raw text fields stored directly on the product
    ingredients         TEXT,
    allergens           TEXT,
    description         TEXT,
    -- legacy / cross-system reference
    rimi_category_code  INTEGER,
    has_confirmed_match BOOLEAN         DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_products_sku              ON products (sku);
CREATE INDEX IF NOT EXISTS idx_products_category         ON products (category_id);
CREATE INDEX IF NOT EXISTS idx_products_name_norm        ON products (name_norm);
CREATE INDEX IF NOT EXISTS idx_products_needs_enrichment ON products (needs_enrichment);


-- ============================================================
-- 3. PRODUCT_PRICE_HISTORY
--    Append-only price/availability log. Never UPDATE rows —
--    always INSERT a new record. Current price = latest row.
-- ============================================================
CREATE TABLE IF NOT EXISTS product_price_history (
    price_history_id        SERIAL          PRIMARY KEY,
    product_id              INTEGER         NOT NULL REFERENCES products(product_id),
    price                   NUMERIC         NOT NULL,
    currency                VARCHAR(3)      NOT NULL DEFAULT 'EUR',
    is_available            BOOLEAN         NOT NULL,
    recorded_at             TIMESTAMPTZ     NOT NULL,
    data_source             VARCHAR(100),                      -- e.g. 'barbora_listing' | 'barbora_product_page'
    created_at              TIMESTAMPTZ     DEFAULT CURRENT_TIMESTAMP,
    price_per_unit          NUMERIC,                           -- e.g. 2.99
    price_per_unit_type     VARCHAR(20),                       -- 'kg' | 'l' | '100g' etc.
    discount_price          NUMERIC,                           -- MansRimi / loyalty card price
    discount_price_per_unit NUMERIC
);

CREATE INDEX IF NOT EXISTS idx_price_history_product          ON product_price_history (product_id);
CREATE INDEX IF NOT EXISTS idx_price_history_recorded         ON product_price_history (recorded_at);
CREATE INDEX IF NOT EXISTS idx_price_history_product_recorded ON product_price_history (product_id, recorded_at DESC);

-- Convenience: get current price with a LATERAL JOIN
-- SELECT p.product_id, p.name, ph.price, ph.discount_price, ph.is_available
-- FROM products p
-- LEFT JOIN LATERAL (
--     SELECT price, discount_price, is_available, recorded_at
--     FROM product_price_history
--     WHERE product_id = p.product_id
--     ORDER BY recorded_at DESC LIMIT 1
-- ) ph ON TRUE;


-- ============================================================
-- 4. NUTRITIONFACTS
--    One row per product (enforced by UNIQUE on product_id).
--    Nutri-Score 2.0 (2024) fields included.
-- ============================================================
CREATE TABLE IF NOT EXISTS nutritionfacts (
    nutrition_id            SERIAL          PRIMARY KEY,
    product_id              INTEGER         NOT NULL UNIQUE REFERENCES products(product_id),
    ingredients_text        TEXT,
    energy_kcal             INTEGER,
    energy_kj               INTEGER,
    fat_total               NUMERIC,
    fat_saturated           NUMERIC,
    carbs_total             NUMERIC,
    carbs_sugars            NUMERIC,
    protein                 NUMERIC,
    salt                    NUMERIC,
    fiber                   NUMERIC,
    nutri_score_grade       CHAR(1),                           -- A | B | C | D | E
    nutri_score_points      INTEGER,
    data_source_date        TIMESTAMPTZ,
    usda_fdc_id             INTEGER,                           -- USDA FoodData Central reference
    is_fiber_correct        BOOLEAN         DEFAULT FALSE,     -- TRUE = scraped/USDA; FALSE = estimated
    nutrition_manual_edit   BOOLEAN         DEFAULT FALSE      -- if TRUE, skip auto-overwrite
);

CREATE INDEX IF NOT EXISTS idx_nutritionfacts_product    ON nutritionfacts (product_id);
CREATE INDEX IF NOT EXISTS idx_nutritionfacts_nutriscore ON nutritionfacts (nutri_score_grade);


-- ============================================================
-- 5. PRODUCTPHOTOS
--    CDN photo URLs for each product (primary + extras).
-- ============================================================
CREATE TABLE IF NOT EXISTS productphotos (
    photo_id    SERIAL      PRIMARY KEY,
    product_id  INTEGER     NOT NULL REFERENCES products(product_id),
    photo_url   TEXT        NOT NULL,
    alt_text    TEXT,
    is_primary  BOOLEAN     DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_productphotos_product ON productphotos (product_id);


-- ============================================================
-- 6. INGREDIENT_ANALYSIS
--    Catalogue of unique ingredient strings with AI analysis.
-- ============================================================
CREATE TABLE IF NOT EXISTS ingredient_analysis (
    id                  SERIAL          PRIMARY KEY,
    ingredient          TEXT            NOT NULL,
    frequency           INTEGER         NOT NULL,
    created_at          TIMESTAMPTZ     DEFAULT CURRENT_TIMESTAMP,
    clean_name          TEXT,
    category            VARCHAR(20)     DEFAULT 'uncategorized',
    is_processed        BOOLEAN,
    suspicion_level     TEXT,
    suspicion_category  TEXT,
    health_note         TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS ingredient_analysis_ingredient_idx ON ingredient_analysis (ingredient);
CREATE INDEX IF NOT EXISTS idx_ingredient_analysis_category   ON ingredient_analysis (category);
CREATE INDEX IF NOT EXISTS idx_ingredient_analysis_processed  ON ingredient_analysis (is_processed);
CREATE INDEX IF NOT EXISTS idx_ingredient_analysis_suspicion  ON ingredient_analysis (suspicion_level);


-- ============================================================
-- 7. INGREDIENT_PRODUCT_MAPPING
--    Many-to-many: which products contain which ingredients.
-- ============================================================
CREATE TABLE IF NOT EXISTS ingredient_product_mapping (
    ingredient_id   INTEGER     NOT NULL REFERENCES ingredient_analysis(id),
    product_sku     TEXT        NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ingredient_id, product_sku)
);

CREATE INDEX IF NOT EXISTS idx_ingredient_product_mapping_sku ON ingredient_product_mapping (product_sku);


-- ============================================================
-- 8. CATEGORY_PROCESSING_JOBS
--    Job queue for background scraping workers.
-- ============================================================
CREATE TABLE IF NOT EXISTS category_processing_jobs (
    id                  SERIAL          PRIMARY KEY,
    category_code       VARCHAR(50)     NOT NULL,
    category_id         INTEGER         REFERENCES normalized_categories(category_id),
    total_products      INTEGER         NOT NULL,
    processed_count     INTEGER         DEFAULT 0,
    status              VARCHAR(30)     NOT NULL DEFAULT 'in_progress',
    started_at          TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,
    last_updated        TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,
    completed_at        TIMESTAMP,
    priority            INTEGER         DEFAULT 5,
    scheduled_for       TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,
    current_worker_id   VARCHAR(100),
    last_heartbeat      TIMESTAMP,
    retry_count         INTEGER         DEFAULT 0,
    max_retries         INTEGER         DEFAULT 3,
    lock_version        INTEGER         DEFAULT 0,
    log_path            TEXT,
    notes               TEXT,
    requested_by        VARCHAR(100)    DEFAULT 'streamlit_ui',
    update_mode         VARCHAR(20)     NOT NULL DEFAULT 'full' -- 'full' | 'incremental'
);

CREATE INDEX IF NOT EXISTS idx_jobs_status   ON category_processing_jobs (status);
CREATE INDEX IF NOT EXISTS idx_jobs_category ON category_processing_jobs (category_code);
CREATE INDEX IF NOT EXISTS idx_jobs_priority ON category_processing_jobs (priority DESC, scheduled_for);
CREATE INDEX IF NOT EXISTS idx_jobs_worker   ON category_processing_jobs (current_worker_id);


-- ============================================================
-- 9. PROCESSING_WORKERS
--    Worker process registration and heartbeat tracking.
-- ============================================================
CREATE TABLE IF NOT EXISTS processing_workers (
    id              SERIAL          PRIMARY KEY,
    worker_id       VARCHAR(100)    NOT NULL UNIQUE,
    hostname        VARCHAR(255),
    pid             INTEGER,
    status          VARCHAR(20)     NOT NULL DEFAULT 'idle',
    current_job_id  INTEGER         REFERENCES category_processing_jobs(id),
    last_heartbeat  TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,
    started_at      TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,
    stopped_at      TIMESTAMP,
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_workers_status    ON processing_workers (status);
CREATE INDEX IF NOT EXISTS idx_workers_heartbeat ON processing_workers (last_heartbeat);


-- ============================================================
-- 10. JOB_EVENTS
--     Audit log of state transitions per job.
-- ============================================================
CREATE TABLE IF NOT EXISTS job_events (
    id          SERIAL          PRIMARY KEY,
    job_id      INTEGER         NOT NULL REFERENCES category_processing_jobs(id),
    event_type  VARCHAR(50)     NOT NULL,
    message     TEXT,
    created_at  TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,
    metadata    JSONB
);

CREATE INDEX IF NOT EXISTS idx_job_events_job  ON job_events (job_id);
CREATE INDEX IF NOT EXISTS idx_job_events_type ON job_events (event_type);


-- ============================================================
-- 11. PRODUCT_PROCESSING_LOG
--     Per-product scraping results within a job.
-- ============================================================
CREATE TABLE IF NOT EXISTS product_processing_log (
    id                  SERIAL          PRIMARY KEY,
    job_id              INTEGER         NOT NULL REFERENCES category_processing_jobs(id),
    sku                 VARCHAR(50)     NOT NULL,
    status              VARCHAR(20)     NOT NULL DEFAULT 'pending',
    error_message       TEXT,
    processed_at        TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,
    product_url         TEXT,
    price               NUMERIC(10, 2),
    retail_price        NUMERIC(10, 2),
    price_per_unit      NUMERIC(10, 4),
    price_per_unit_type VARCHAR(20),
    is_available        BOOLEAN         DEFAULT TRUE,
    promotion_data      JSONB
);

CREATE INDEX IF NOT EXISTS idx_processing_log_job ON product_processing_log (job_id);
CREATE INDEX IF NOT EXISTS idx_processing_log_sku ON product_processing_log (sku);


-- ============================================================
-- 12. UPDATE_STATISTICS
--     Per-job, per-category change counters.
-- ============================================================
CREATE TABLE IF NOT EXISTS update_statistics (
    id                    SERIAL          PRIMARY KEY,
    job_id                INTEGER         NOT NULL REFERENCES category_processing_jobs(id),
    category_code         VARCHAR(50)     NOT NULL,
    total_checked         INTEGER         DEFAULT 0,
    new_products          INTEGER         DEFAULT 0,
    price_changed         INTEGER         DEFAULT 0,
    availability_changed  INTEGER         DEFAULT 0,
    data_updated          INTEGER         DEFAULT 0,
    unchanged             INTEGER         DEFAULT 0,
    failed                INTEGER         DEFAULT 0,
    created_at            TIMESTAMP       DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_update_stats_job      ON update_statistics (job_id);
CREATE INDEX IF NOT EXISTS idx_update_stats_category ON update_statistics (category_code);


-- ============================================================
-- 13. LIGHTWEIGHT_UPDATE_RUNS
--     History of daily incremental price-only update runs.
--     These runs read prices directly from category listing pages
--     without visiting individual product pages (10-50x faster).
-- ============================================================
CREATE TABLE IF NOT EXISTS lightweight_update_runs (
    run_id                   SERIAL           PRIMARY KEY,
    started_at               TIMESTAMP,
    ended_at                 TIMESTAMP,
    duration_seconds         DOUBLE PRECISION,
    categories_processed     INTEGER          DEFAULT 0,
    products_checked         INTEGER          DEFAULT 0,
    products_updated         INTEGER          DEFAULT 0,
    price_changes            INTEGER          DEFAULT 0,
    availability_changes     INTEGER          DEFAULT 0,
    new_products_found       INTEGER          DEFAULT 0,
    new_product_jobs_created INTEGER          DEFAULT 0,
    errors_count             INTEGER          DEFAULT 0,
    status                   VARCHAR(50)      DEFAULT 'running',
    created_at               TIMESTAMP        DEFAULT CURRENT_TIMESTAMP
);


-- ============================================================
-- 14. DAILY_UPDATE_LOGS
--     High-level summary of each full daily update cycle.
-- ============================================================
CREATE TABLE IF NOT EXISTS daily_update_logs (
    id                       SERIAL          PRIMARY KEY,
    update_type              VARCHAR(50)     NOT NULL DEFAULT 'daily',
    start_time               TIMESTAMP       NOT NULL,
    end_time                 TIMESTAMP       NOT NULL,
    duration_minutes         NUMERIC,
    categories_processed     INTEGER         DEFAULT 0,
    jobs_completed           INTEGER         DEFAULT 0,
    jobs_failed              INTEGER         DEFAULT 0,
    products_added           INTEGER         DEFAULT 0,
    products_updated         INTEGER         DEFAULT 0,
    products_removed         INTEGER         DEFAULT 0,
    price_changes_count      INTEGER         DEFAULT 0,
    availability_changes     JSONB,
    ingredient_changes_count INTEGER         DEFAULT 0,
    nutrition_changes_count  INTEGER         DEFAULT 0,
    photo_changes_count      INTEGER         DEFAULT 0,
    errors_count             INTEGER         DEFAULT 0,
    error_details            JSONB,
    summary                  TEXT,
    created_at               TIMESTAMP       DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_daily_logs_start ON daily_update_logs (start_time);
CREATE INDEX IF NOT EXISTS idx_daily_logs_type  ON daily_update_logs (update_type);


-- ============================================================
-- 15. TRANSLATION_CACHE
--     Stores AI/manual translations of product names to English.
-- ============================================================
CREATE TABLE IF NOT EXISTS translation_cache (
    cache_id            SERIAL          PRIMARY KEY,
    product_name_hash   VARCHAR(64)     NOT NULL UNIQUE,
    product_name        TEXT            NOT NULL,
    category_name       TEXT,
    english_translation TEXT            NOT NULL,
    translation_method  VARCHAR(50),                          -- 'gemini' | 'manual' | 'rule'
    confidence          NUMERIC(3, 2),
    created_at          TIMESTAMP       DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_translation_cache_hash ON translation_cache (product_name_hash);


-- =============================================================================
-- END OF SCHEMA
-- =============================================================================
--
-- KEY DESIGN NOTES
-- ----------------
-- 1. Prices are NEVER stored on the products table.
--    Always INSERT into product_price_history; never UPDATE it.
--    Query current price via LATERAL JOIN (see comment above).
--
-- 2. nutritionfacts is 1-to-1 with products (UNIQUE product_id FK).
--    Products with nutrition_manual_edit = TRUE are skipped during
--    automated enrichment passes.
--
-- 3. normalized_categories is a self-referencing tree.
--    Root nodes have parent_category_id = NULL, level = 0.
--
-- 4. Nutri-Score grades: A (best) → E (worst).
--    Algorithm: Nutri-Score 2.0 (2024 revision).
--    Product categories: general | beverage | cheese | red_meat | fat_oil
--
-- 5. Worker heartbeat timeout: 2 × heartbeat_interval.
--    Stale jobs are reassigned automatically on worker startup.
--
-- 6. quantity_unit values in use: g | kg | ml | l | gab (pieces)
--    quantity_value = NULL for loose/variable-weight products (sold as "sver.")
--
-- TABLE DEPENDENCY ORDER (for clean drop):
--   update_statistics → category_processing_jobs
--   product_processing_log → category_processing_jobs
--   job_events → category_processing_jobs
--   processing_workers → category_processing_jobs
--   category_processing_jobs → normalized_categories
--   nutritionfacts → products
--   product_price_history → products
--   productphotos → products
--   ingredient_product_mapping → ingredient_analysis
--   products → normalized_categories
-- =============================================================================
