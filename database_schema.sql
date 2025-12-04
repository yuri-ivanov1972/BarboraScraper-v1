-- ============================================
-- Rimi Product Scraper Database Schema
-- ============================================
-- This schema defines all tables, constraints, indexes, and relationships
-- for the Rimi product scraper application.
-- 
-- Prerequisites:
-- - PostgreSQL 14+ with pg_trgm extension
-- ============================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================
-- CORE TABLES
-- ============================================

-- Normalized product categories (hierarchical)
CREATE TABLE normalized_categories (
    category_id INTEGER NOT NULL PRIMARY KEY,
    rimi_category_code TEXT UNIQUE,
    name_lv TEXT NOT NULL,
    name_en TEXT,
    parent_category_id INTEGER REFERENCES normalized_categories(category_id),
    level INTEGER NOT NULL
);

-- Products table (core product information)
CREATE TABLE products (
    product_id SERIAL PRIMARY KEY,
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    name_norm TEXT,
    rimi_url TEXT UNIQUE,
    category_id INTEGER NOT NULL REFERENCES normalized_categories(category_id),
    quantity_value NUMERIC(10,2),
    quantity_unit VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    country_of_origin VARCHAR(255) DEFAULT 'Unknown',
    nutrition_source VARCHAR(50),
    needs_enrichment BOOLEAN DEFAULT false,
    enrichment_reviewed BOOLEAN DEFAULT false,
    enrichment_skipped BOOLEAN DEFAULT false
);

-- Product price history (tracks all price/availability changes)
CREATE TABLE product_price_history (
    price_history_id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    price NUMERIC(10,2) NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'EUR',
    is_available BOOLEAN NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    data_source VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Product photos
CREATE TABLE productphotos (
    photo_id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    photo_url TEXT NOT NULL,
    alt_text TEXT,
    is_primary BOOLEAN DEFAULT false
);

-- Nutrition facts (one per product)
CREATE TABLE nutritionfacts (
    nutrition_id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL UNIQUE REFERENCES products(product_id),
    ingredients_text TEXT,
    energy_kcal INTEGER,
    energy_kj INTEGER,
    fat_total NUMERIC(10,2),
    fat_saturated NUMERIC(10,2),
    carbs_total NUMERIC(10,2),
    carbs_sugars NUMERIC(10,2),
    protein NUMERIC(10,2),
    salt NUMERIC(10,2),
    fiber NUMERIC(10,2),
    nutri_score_grade CHAR(1),
    nutri_score_points INTEGER,
    data_source_date TIMESTAMPTZ,
    usda_fdc_id INTEGER
);

-- ============================================
-- INGREDIENT ANALYSIS TABLES
-- ============================================

-- Unique ingredients with frequency
CREATE TABLE ingredient_analysis (
    id SERIAL PRIMARY KEY,
    ingredient TEXT NOT NULL UNIQUE,
    frequency INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Mapping of ingredients to products
CREATE TABLE ingredient_product_mapping (
    ingredient_id INTEGER NOT NULL REFERENCES ingredient_analysis(id),
    product_sku TEXT NOT NULL REFERENCES products(sku),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ingredient_id, product_sku)
);

-- ============================================
-- JOB QUEUE & PROCESSING TABLES
-- ============================================

-- Category processing jobs (job queue)
CREATE TABLE category_processing_jobs (
    id SERIAL PRIMARY KEY,
    category_code VARCHAR(50) NOT NULL,
    category_id INTEGER REFERENCES normalized_categories(category_id),
    total_products INTEGER NOT NULL,
    processed_count INTEGER DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'in_progress',
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    priority INTEGER DEFAULT 5,
    scheduled_for TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    current_worker_id VARCHAR(100),
    last_heartbeat TIMESTAMP,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    lock_version INTEGER DEFAULT 0,
    log_path TEXT,
    notes TEXT,
    requested_by VARCHAR(100) DEFAULT 'streamlit_ui',
    update_mode VARCHAR(20) NOT NULL DEFAULT 'full'
);

-- Job events (lifecycle tracking)
CREATE TABLE job_events (
    id SERIAL PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES category_processing_jobs(id),
    event_type VARCHAR(50) NOT NULL,
    message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB
);

-- Product processing log (per-product status within a job)
CREATE TABLE product_processing_log (
    id SERIAL PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES category_processing_jobs(id),
    sku VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    error_message TEXT,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Processing workers (worker registration and heartbeat)
CREATE TABLE processing_workers (
    id SERIAL PRIMARY KEY,
    worker_id VARCHAR(100) NOT NULL UNIQUE,
    hostname VARCHAR(255),
    pid INTEGER,
    status VARCHAR(20) NOT NULL DEFAULT 'idle',
    current_job_id INTEGER REFERENCES category_processing_jobs(id),
    last_heartbeat TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    stopped_at TIMESTAMP,
    error_message TEXT
);

-- ============================================
-- STATISTICS & LOGGING TABLES
-- ============================================

-- Update statistics per category per job
CREATE TABLE update_statistics (
    id SERIAL PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES category_processing_jobs(id),
    category_code VARCHAR(50) NOT NULL,
    total_checked INTEGER DEFAULT 0,
    new_products INTEGER DEFAULT 0,
    price_changed INTEGER DEFAULT 0,
    availability_changed INTEGER DEFAULT 0,
    data_updated INTEGER DEFAULT 0,
    unchanged INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Daily update logs (summary of daily processing runs)
CREATE TABLE daily_update_logs (
    id SERIAL PRIMARY KEY,
    update_type VARCHAR(50) NOT NULL DEFAULT 'daily',
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    duration_minutes NUMERIC(10,2),
    categories_processed INTEGER DEFAULT 0,
    jobs_completed INTEGER DEFAULT 0,
    jobs_failed INTEGER DEFAULT 0,
    products_added INTEGER DEFAULT 0,
    products_updated INTEGER DEFAULT 0,
    products_removed INTEGER DEFAULT 0,
    price_changes_count INTEGER DEFAULT 0,
    availability_changes JSONB,
    ingredient_changes_count INTEGER DEFAULT 0,
    nutrition_changes_count INTEGER DEFAULT 0,
    photo_changes_count INTEGER DEFAULT 0,
    errors_count INTEGER DEFAULT 0,
    error_details JSONB,
    summary TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- INDEXES
-- ============================================

-- Products indexes
CREATE INDEX idx_products_category_id ON products(category_id);
CREATE INDEX idx_products_sku ON products(sku);
CREATE INDEX idx_products_name ON products USING gin(name gin_trgm_ops);

-- Product price history indexes
CREATE INDEX idx_price_history_product_id ON product_price_history(product_id);
CREATE INDEX idx_price_history_recorded_at ON product_price_history(recorded_at);
CREATE INDEX idx_price_history_product_recorded ON product_price_history(product_id, recorded_at);
CREATE INDEX idx_price_history_availability ON product_price_history(is_available);
CREATE INDEX idx_price_history_data_source ON product_price_history(data_source);

-- Product photos indexes
CREATE INDEX idx_photos_product_id ON productphotos(product_id);

-- Nutrition indexes
CREATE INDEX idx_nutrition_product_id ON nutritionfacts(product_id);
CREATE INDEX idx_nutrition_nutri_score ON nutritionfacts(nutri_score_grade);
CREATE INDEX idx_nutrition_protein ON nutritionfacts(protein);
CREATE INDEX idx_nutrition_carbs_sugars ON nutritionfacts(carbs_sugars);

-- Ingredient analysis indexes
CREATE INDEX idx_ingredient_analysis_freq ON ingredient_analysis(frequency DESC);
CREATE INDEX idx_ingredient_product_mapping_ingredient ON ingredient_product_mapping(ingredient_id);

-- Category processing jobs indexes
CREATE INDEX idx_category_jobs_code ON category_processing_jobs(category_code);
CREATE INDEX idx_category_jobs_status ON category_processing_jobs(status);
CREATE INDEX idx_jobs_queue_poll ON category_processing_jobs(status, priority DESC, scheduled_for) 
    WHERE status IN ('queued', 'in_progress');
CREATE UNIQUE INDEX idx_unique_active_category ON category_processing_jobs(category_code) 
    WHERE status IN ('queued', 'in_progress');

-- Job events indexes
CREATE INDEX idx_job_events_job ON job_events(job_id, created_at DESC);
CREATE INDEX idx_job_events_type ON job_events(event_type, created_at DESC);

-- Product processing log indexes
CREATE INDEX idx_product_log_job ON product_processing_log(job_id);
CREATE INDEX idx_product_log_sku ON product_processing_log(sku);
CREATE INDEX idx_product_log_status ON product_processing_log(job_id, status);

-- Processing workers indexes
CREATE INDEX idx_workers_status ON processing_workers(status, last_heartbeat DESC);
CREATE INDEX idx_workers_current_job ON processing_workers(current_job_id) 
    WHERE current_job_id IS NOT NULL;

-- Update statistics indexes
CREATE INDEX idx_update_statistics_job_id ON update_statistics(job_id);
CREATE INDEX idx_update_statistics_category_code ON update_statistics(category_code);

-- Daily update logs indexes
CREATE INDEX idx_daily_update_logs_created_at ON daily_update_logs(created_at DESC);
CREATE INDEX idx_daily_update_logs_start_time ON daily_update_logs(start_time DESC);
CREATE INDEX idx_daily_update_logs_update_type ON daily_update_logs(update_type);

-- ============================================
-- USEFUL QUERIES (COMMENTS)
-- ============================================

-- Get current price and availability for a product:
-- SELECT p.*, pph.price, pph.is_available, pph.recorded_at
-- FROM products p
-- LEFT JOIN LATERAL (
--     SELECT price, is_available, recorded_at
--     FROM product_price_history
--     WHERE product_id = p.product_id
--     ORDER BY recorded_at DESC
--     LIMIT 1
-- ) pph ON true
-- WHERE p.sku = 'YOUR_SKU';

-- Get products with price history count:
-- SELECT p.product_id, p.name, COUNT(pph.price_history_id) as price_records
-- FROM products p
-- LEFT JOIN product_price_history pph ON p.product_id = pph.product_id
-- GROUP BY p.product_id, p.name
-- ORDER BY price_records DESC;
