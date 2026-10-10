# Maxima / Barbora Database Schema Reference

## Source and scope

Captured at 2026-10-10 09:14 UTC.

This package is a point-in-time export of the **development** PostgreSQL `public` schema. It is not a production-schema verification or a data backup. The SQL dump and catalogue inventory were collected from the same read-only, repeatable-read snapshot.

- Source PostgreSQL version: **16.10**; export tool: **pg_dump 16.10**.
- **20 tables**, **207 table columns**, **1 materialized view** with **10 columns**, **16 sequences**.
- **44 constraints**, including **16 foreign keys**; **65 indexes**, including constraint-backed indexes.
- No public user-defined functions, custom enum/domain types, or non-internal triggers were found.
- No rows, materialized-view contents, current sequence values, database credentials, owner assignments, or grants are included.
- Defaults and CHECK constraints contain schema-defined literals, not exported catalogue rows.

## Files and import prerequisites

- `schema.sql`: complete public-schema DDL in dependency order.
- `SCHEMA_REFERENCE.md`: this reference, including exact column definitions and declared relationships.
- `database-schema-share.zip`: downloadable bundle of the two files (checksums shown below).

Use an **empty target database**, PostgreSQL **16 or newer**, UTF-8 encoding, and a role permitted to create objects in `public`. Only the standard `plpgsql` extension is installed on the source; the exported public objects need no extra extension. No `pg_trgm` extension or trigram indexes exist in this snapshot. Core JSONB, array, aggregate, and built-in PostgreSQL functions are used by the materialized view.

The dump includes psql `\restrict` / `\unrestrict` safety directives. Use **psql 16.10+ or a newer supported psql release** that understands these directives, not a generic SQL editor. The generated safety token is not a database credential. Only `CREATE SCHEMA public` was changed to `CREATE SCHEMA IF NOT EXISTS public` so the default empty public schema is supported. No tables are dropped or overwritten; existing objects will cause the import to fail and roll back.

```bash
psql -X --single-transaction --set=ON_ERROR_STOP=1 \
  --dbname=TARGET_DATABASE --file=schema.sql
```

Replace `TARGET_DATABASE` with the destination database name and configure authentication securely through your normal PostgreSQL tooling. Do not put passwords in the SQL files. Ownership belongs to the importing role; destination permissions must be configured separately.

After importing and loading any separately supplied data, refresh the materialized view:

```sql
REFRESH MATERIALIZED VIEW public.product_ingredient_cards;
```

The view is exported `WITH NO DATA` and cannot be queried until refreshed. No data-loading step is included. Categories, NOVA defaults, brand/producer records, and ingredient records must be populated separately; Nutri-Score algorithms and mappings in Python are application logic, not SQL schema.

## Tables at a glance

| Table | Columns | Primary key |
|---|---:|---|
| `brand_producers` | 3 | `PRIMARY KEY (brand_id, producer_id)` |
| `brands` | 6 | `PRIMARY KEY (id)` |
| `category_processing_jobs` | 20 | `PRIMARY KEY (id)` |
| `daily_update_logs` | 20 | `PRIMARY KEY (id)` |
| `ingredient_analysis` | 10 | `PRIMARY KEY (id)` |
| `ingredient_product_mapping` | 3 | `PRIMARY KEY (ingredient_id, product_sku)` |
| `job_events` | 6 | `PRIMARY KEY (id)` |
| `lightweight_update_runs` | 14 | `PRIMARY KEY (run_id)` |
| `normalized_categories` | 7 | `PRIMARY KEY (category_id)` |
| `nutrition_validation` | 6 | `PRIMARY KEY (id)` |
| `nutritionfacts` | 18 | `PRIMARY KEY (nutrition_id)` |
| `processing_workers` | 10 | `PRIMARY KEY (id)` |
| `producers` | 6 | `PRIMARY KEY (id)` |
| `product_price_history` | 12 | `PRIMARY KEY (price_history_id)` |
| `product_processing_log` | 13 | `PRIMARY KEY (id)` |
| `productphotos` | 5 | `PRIMARY KEY (photo_id)` |
| `products` | 26 | `PRIMARY KEY (product_id)` |
| `rimi_nova_categories` | 3 | `PRIMARY KEY (rimi_category_code)` |
| `translation_cache` | 8 | `PRIMARY KEY (cache_id)` |
| `update_statistics` | 11 | `PRIMARY KEY (id)` |

## Declared foreign-key relationships

These relationships are enforced by database constraints; nullability and uniqueness are listed in the detailed definitions below. All unspecified delete/update actions use PostgreSQL’s default NO ACTION.

| Source table | Constraint | Relationship |
|---|---|---|
| `brand_producers` | `brand_producers_brand_id_fkey` | `FOREIGN KEY (brand_id) REFERENCES brands(id) ON DELETE CASCADE` |
| `brand_producers` | `brand_producers_producer_id_fkey` | `FOREIGN KEY (producer_id) REFERENCES producers(id) ON DELETE CASCADE` |
| `category_processing_jobs` | `category_processing_jobs_category_id_fkey` | `FOREIGN KEY (category_id) REFERENCES normalized_categories(category_id)` |
| `ingredient_product_mapping` | `ingredient_product_mapping_ingredient_id_fkey` | `FOREIGN KEY (ingredient_id) REFERENCES ingredient_analysis(id)` |
| `job_events` | `job_events_job_id_fkey` | `FOREIGN KEY (job_id) REFERENCES category_processing_jobs(id)` |
| `normalized_categories` | `normalized_categories_parent_category_id_fkey` | `FOREIGN KEY (parent_category_id) REFERENCES normalized_categories(category_id)` |
| `nutrition_validation` | `nutrition_validation_product_id_fkey` | `FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE CASCADE` |
| `nutritionfacts` | `nutritionfacts_product_id_fkey` | `FOREIGN KEY (product_id) REFERENCES products(product_id)` |
| `processing_workers` | `processing_workers_current_job_id_fkey` | `FOREIGN KEY (current_job_id) REFERENCES category_processing_jobs(id)` |
| `product_price_history` | `product_price_history_product_id_fkey` | `FOREIGN KEY (product_id) REFERENCES products(product_id)` |
| `product_processing_log` | `product_processing_log_job_id_fkey` | `FOREIGN KEY (job_id) REFERENCES category_processing_jobs(id)` |
| `productphotos` | `productphotos_product_id_fkey` | `FOREIGN KEY (product_id) REFERENCES products(product_id)` |
| `products` | `products_brand_id_fkey` | `FOREIGN KEY (brand_id) REFERENCES brands(id)` |
| `products` | `products_category_id_fkey` | `FOREIGN KEY (category_id) REFERENCES normalized_categories(category_id)` |
| `products` | `products_producer_id_fkey` | `FOREIGN KEY (producer_id) REFERENCES producers(id)` |
| `update_statistics` | `update_statistics_job_id_fkey` | `FOREIGN KEY (job_id) REFERENCES category_processing_jobs(id)` |

### Application relationships without a foreign key

- `ingredient_product_mapping.product_sku = products.sku` is used by the materialized view but is **not** protected by a product foreign key. Do not assume referential integrity from this join.
- `product_processing_log.sku = products.sku` is an application join, not a declared foreign key; queued products may not yet exist in `products`.
- `processing_workers.worker_id` and job worker identifier strings are application identifiers; no worker-identifier foreign key is declared.

### Key catalogue conventions

- `products.brand_id` joins **`brands.id`**, and `products.producer_id` joins **`producers.id`**. The master tables do not have `brand_id` / `producer_id` primary-key columns.
- `brand_producers` links brands and producers many-to-many; a product has at most one current brand and producer link.
- `normalized_categories.category_id` is an integer local key. `barbora_category_code` is text for the stable external category code/UUID. Parent categories use `parent_category_id`.
- `nutritionfacts.product_id` has a UNIQUE constraint and a product foreign key; a product may have zero or one nutrition row.
- `nutrition_validation` holds separate validation findings and has a UNIQUE product link. Findings are not replacements for nutrition values.
- Prices and availability are in `product_price_history`, not `products`. Use the latest `recorded_at` row with a deterministic ID tie-breaker.

## Example joins

### Recently created products with brands and producers

```sql
SELECT p.product_id, p.sku, p.name, p.created_at, p.updated_at,
       b.name AS brand, pr.name AS producer,
       CASE
           WHEN b.id IS NULL AND pr.id IS NULL THEN 'Missing brand and producer'
           WHEN b.id IS NULL THEN 'Missing brand'
           WHEN pr.id IS NULL THEN 'Missing producer'
           ELSE 'Complete'
       END AS metadata_status
FROM public.products p
LEFT JOIN public.brands b ON b.id = p.brand_id
LEFT JOIN public.producers pr ON pr.id = p.producer_id
WHERE p.created_at >= CURRENT_TIMESTAMP - INTERVAL '7 days'
ORDER BY p.created_at DESC, p.product_id DESC;
```

### Product, category, nutrition, and current price

```sql
SELECT p.product_id, p.sku, p.name,
       nc.name_lv AS category_name, nc.barbora_category_code,
       nf.nutri_score_grade, nf.nutri_score_points,
       latest.price, latest.discount_price, latest.is_available,
       latest.recorded_at
FROM public.products p
LEFT JOIN public.normalized_categories nc ON nc.category_id = p.category_id
LEFT JOIN public.nutritionfacts nf ON nf.product_id = p.product_id
LEFT JOIN LATERAL (
    SELECT ph.price, ph.discount_price, ph.is_available, ph.recorded_at
    FROM public.product_price_history ph
    WHERE ph.product_id = p.product_id
    ORDER BY ph.recorded_at DESC NULLS LAST, ph.price_history_id DESC
    LIMIT 1
) latest ON true
ORDER BY p.product_id;
```

## Detailed table definitions

### brand_producers

| Column | PostgreSQL type | Nullable | Default / generation |
|---|---|---|---|
| `brand_id` | `integer` | No | `—` |
| `producer_id` | `integer` | No | `—` |
| `created_at` | `timestamp with time zone` | No | `CURRENT_TIMESTAMP` |

**Constraints**

- `brand_producers_brand_id_fkey`: `FOREIGN KEY (brand_id) REFERENCES brands(id) ON DELETE CASCADE`
- `brand_producers_pkey`: `PRIMARY KEY (brand_id, producer_id)`
- `brand_producers_producer_id_fkey`: `FOREIGN KEY (producer_id) REFERENCES producers(id) ON DELETE CASCADE`

**Indexes** (including primary/unique constraint indexes)

- `brand_producers_pkey`: `CREATE UNIQUE INDEX brand_producers_pkey ON public.brand_producers USING btree (brand_id, producer_id)`
- `idx_brand_producers_producer`: `CREATE INDEX idx_brand_producers_producer ON public.brand_producers USING btree (producer_id)`

### brands

| Column | PostgreSQL type | Nullable | Default / generation |
|---|---|---|---|
| `id` | `integer` | No | `nextval('brands_id_seq'::regclass)` |
| `name` | `text` | No | `—` |
| `normalized_name` | `text` | No | `—` |
| `website_url` | `text` | Yes | `—` |
| `created_at` | `timestamp with time zone` | No | `CURRENT_TIMESTAMP` |
| `updated_at` | `timestamp with time zone` | No | `CURRENT_TIMESTAMP` |

**Constraints**

- `brands_normalized_name_key`: `UNIQUE (normalized_name)`
- `brands_pkey`: `PRIMARY KEY (id)`

**Indexes** (including primary/unique constraint indexes)

- `brands_normalized_name_key`: `CREATE UNIQUE INDEX brands_normalized_name_key ON public.brands USING btree (normalized_name)`
- `brands_pkey`: `CREATE UNIQUE INDEX brands_pkey ON public.brands USING btree (id)`

### category_processing_jobs

| Column | PostgreSQL type | Nullable | Default / generation |
|---|---|---|---|
| `id` | `integer` | No | `nextval('category_processing_jobs_id_seq'::regclass)` |
| `category_code` | `character varying(50)` | No | `—` |
| `category_id` | `integer` | Yes | `—` |
| `total_products` | `integer` | No | `—` |
| `processed_count` | `integer` | Yes | `0` |
| `status` | `character varying(30)` | No | `'in_progress'::character varying` |
| `started_at` | `timestamp without time zone` | Yes | `CURRENT_TIMESTAMP` |
| `last_updated` | `timestamp without time zone` | Yes | `CURRENT_TIMESTAMP` |
| `completed_at` | `timestamp without time zone` | Yes | `—` |
| `priority` | `integer` | Yes | `5` |
| `scheduled_for` | `timestamp without time zone` | Yes | `CURRENT_TIMESTAMP` |
| `current_worker_id` | `character varying(100)` | Yes | `—` |
| `last_heartbeat` | `timestamp without time zone` | Yes | `—` |
| `retry_count` | `integer` | Yes | `0` |
| `max_retries` | `integer` | Yes | `3` |
| `lock_version` | `integer` | Yes | `0` |
| `log_path` | `text` | Yes | `—` |
| `notes` | `text` | Yes | `—` |
| `requested_by` | `character varying(100)` | Yes | `'streamlit_ui'::character varying` |
| `update_mode` | `character varying(20)` | No | `'full'::character varying` |

**Constraints**

- `category_processing_jobs_category_id_fkey`: `FOREIGN KEY (category_id) REFERENCES normalized_categories(category_id)`
- `category_processing_jobs_pkey`: `PRIMARY KEY (id)`

**Indexes** (including primary/unique constraint indexes)

- `category_processing_jobs_pkey`: `CREATE UNIQUE INDEX category_processing_jobs_pkey ON public.category_processing_jobs USING btree (id)`
- `idx_jobs_category`: `CREATE INDEX idx_jobs_category ON public.category_processing_jobs USING btree (category_code)`
- `idx_jobs_priority`: `CREATE INDEX idx_jobs_priority ON public.category_processing_jobs USING btree (priority DESC, scheduled_for)`
- `idx_jobs_status`: `CREATE INDEX idx_jobs_status ON public.category_processing_jobs USING btree (status)`
- `idx_jobs_worker`: `CREATE INDEX idx_jobs_worker ON public.category_processing_jobs USING btree (current_worker_id)`

### daily_update_logs

| Column | PostgreSQL type | Nullable | Default / generation |
|---|---|---|---|
| `id` | `integer` | No | `nextval('daily_update_logs_id_seq'::regclass)` |
| `update_type` | `character varying(50)` | No | `'daily'::character varying` |
| `start_time` | `timestamp without time zone` | No | `—` |
| `end_time` | `timestamp without time zone` | No | `—` |
| `duration_minutes` | `numeric` | Yes | `—` |
| `categories_processed` | `integer` | Yes | `0` |
| `jobs_completed` | `integer` | Yes | `0` |
| `jobs_failed` | `integer` | Yes | `0` |
| `products_added` | `integer` | Yes | `0` |
| `products_updated` | `integer` | Yes | `0` |
| `products_removed` | `integer` | Yes | `0` |
| `price_changes_count` | `integer` | Yes | `0` |
| `availability_changes` | `jsonb` | Yes | `—` |
| `ingredient_changes_count` | `integer` | Yes | `0` |
| `nutrition_changes_count` | `integer` | Yes | `0` |
| `photo_changes_count` | `integer` | Yes | `0` |
| `errors_count` | `integer` | Yes | `0` |
| `error_details` | `jsonb` | Yes | `—` |
| `summary` | `text` | Yes | `—` |
| `created_at` | `timestamp without time zone` | Yes | `CURRENT_TIMESTAMP` |

**Constraints**

- `daily_update_logs_pkey`: `PRIMARY KEY (id)`

**Indexes** (including primary/unique constraint indexes)

- `daily_update_logs_pkey`: `CREATE UNIQUE INDEX daily_update_logs_pkey ON public.daily_update_logs USING btree (id)`
- `idx_daily_logs_start`: `CREATE INDEX idx_daily_logs_start ON public.daily_update_logs USING btree (start_time)`
- `idx_daily_logs_type`: `CREATE INDEX idx_daily_logs_type ON public.daily_update_logs USING btree (update_type)`

### ingredient_analysis

| Column | PostgreSQL type | Nullable | Default / generation |
|---|---|---|---|
| `id` | `integer` | No | `nextval('ingredient_analysis_id_seq'::regclass)` |
| `ingredient` | `text` | No | `—` |
| `frequency` | `integer` | No | `—` |
| `created_at` | `timestamp with time zone` | Yes | `CURRENT_TIMESTAMP` |
| `clean_name` | `text` | Yes | `—` |
| `category` | `character varying(20)` | Yes | `'uncategorized'::character varying` |
| `is_processed` | `boolean` | Yes | `—` |
| `suspicion_level` | `text` | Yes | `—` |
| `suspicion_category` | `text` | Yes | `—` |
| `health_note` | `text` | Yes | `—` |

**Constraints**

- `ingredient_analysis_pkey`: `PRIMARY KEY (id)`

**Indexes** (including primary/unique constraint indexes)

- `idx_ingredient_analysis_category`: `CREATE INDEX idx_ingredient_analysis_category ON public.ingredient_analysis USING btree (category)`
- `idx_ingredient_analysis_processed`: `CREATE INDEX idx_ingredient_analysis_processed ON public.ingredient_analysis USING btree (is_processed)`
- `idx_ingredient_analysis_suspicion`: `CREATE INDEX idx_ingredient_analysis_suspicion ON public.ingredient_analysis USING btree (suspicion_level)`
- `ingredient_analysis_ingredient_idx`: `CREATE UNIQUE INDEX ingredient_analysis_ingredient_idx ON public.ingredient_analysis USING btree (ingredient)`
- `ingredient_analysis_pkey`: `CREATE UNIQUE INDEX ingredient_analysis_pkey ON public.ingredient_analysis USING btree (id)`

### ingredient_product_mapping

| Column | PostgreSQL type | Nullable | Default / generation |
|---|---|---|---|
| `ingredient_id` | `integer` | No | `—` |
| `product_sku` | `text` | No | `—` |
| `created_at` | `timestamp with time zone` | Yes | `CURRENT_TIMESTAMP` |

**Constraints**

- `ingredient_product_mapping_ingredient_id_fkey`: `FOREIGN KEY (ingredient_id) REFERENCES ingredient_analysis(id)`
- `ingredient_product_mapping_pkey`: `PRIMARY KEY (ingredient_id, product_sku)`

**Indexes** (including primary/unique constraint indexes)

- `idx_ingredient_product_mapping_sku`: `CREATE INDEX idx_ingredient_product_mapping_sku ON public.ingredient_product_mapping USING btree (product_sku)`
- `ingredient_product_mapping_pkey`: `CREATE UNIQUE INDEX ingredient_product_mapping_pkey ON public.ingredient_product_mapping USING btree (ingredient_id, product_sku)`

### job_events

| Column | PostgreSQL type | Nullable | Default / generation |
|---|---|---|---|
| `id` | `integer` | No | `nextval('job_events_id_seq'::regclass)` |
| `job_id` | `integer` | No | `—` |
| `event_type` | `character varying(50)` | No | `—` |
| `message` | `text` | Yes | `—` |
| `created_at` | `timestamp without time zone` | Yes | `CURRENT_TIMESTAMP` |
| `metadata` | `jsonb` | Yes | `—` |

**Constraints**

- `job_events_job_id_fkey`: `FOREIGN KEY (job_id) REFERENCES category_processing_jobs(id)`
- `job_events_pkey`: `PRIMARY KEY (id)`

**Indexes** (including primary/unique constraint indexes)

- `idx_job_events_job`: `CREATE INDEX idx_job_events_job ON public.job_events USING btree (job_id)`
- `idx_job_events_type`: `CREATE INDEX idx_job_events_type ON public.job_events USING btree (event_type)`
- `job_events_pkey`: `CREATE UNIQUE INDEX job_events_pkey ON public.job_events USING btree (id)`

### lightweight_update_runs

| Column | PostgreSQL type | Nullable | Default / generation |
|---|---|---|---|
| `run_id` | `integer` | No | `nextval('lightweight_update_runs_run_id_seq'::regclass)` |
| `started_at` | `timestamp without time zone` | Yes | `—` |
| `ended_at` | `timestamp without time zone` | Yes | `—` |
| `duration_seconds` | `double precision` | Yes | `—` |
| `categories_processed` | `integer` | Yes | `0` |
| `products_checked` | `integer` | Yes | `0` |
| `products_updated` | `integer` | Yes | `0` |
| `price_changes` | `integer` | Yes | `0` |
| `availability_changes` | `integer` | Yes | `0` |
| `new_products_found` | `integer` | Yes | `0` |
| `new_product_jobs_created` | `integer` | Yes | `0` |
| `errors_count` | `integer` | Yes | `0` |
| `status` | `character varying(50)` | Yes | `'running'::character varying` |
| `created_at` | `timestamp without time zone` | Yes | `CURRENT_TIMESTAMP` |

**Constraints**

- `lightweight_update_runs_pkey`: `PRIMARY KEY (run_id)`

**Indexes** (including primary/unique constraint indexes)

- `lightweight_update_runs_pkey`: `CREATE UNIQUE INDEX lightweight_update_runs_pkey ON public.lightweight_update_runs USING btree (run_id)`

### normalized_categories

| Column | PostgreSQL type | Nullable | Default / generation |
|---|---|---|---|
| `category_id` | `integer` | No | `—` |
| `barbora_category_code` | `text` | Yes | `—` |
| `name_lv` | `text` | No | `—` |
| `name_en` | `text` | Yes | `—` |
| `parent_category_id` | `integer` | Yes | `—` |
| `level` | `integer` | No | `—` |
| `normalized_category` | `text` | Yes | `—` |

**Constraints**

- `normalized_categories_parent_category_id_fkey`: `FOREIGN KEY (parent_category_id) REFERENCES normalized_categories(category_id)`
- `normalized_categories_pkey`: `PRIMARY KEY (category_id)`

**Indexes** (including primary/unique constraint indexes)

- `idx_normalized_categories_code`: `CREATE INDEX idx_normalized_categories_code ON public.normalized_categories USING btree (barbora_category_code)`
- `idx_normalized_categories_level`: `CREATE INDEX idx_normalized_categories_level ON public.normalized_categories USING btree (level)`
- `idx_normalized_categories_parent`: `CREATE INDEX idx_normalized_categories_parent ON public.normalized_categories USING btree (parent_category_id)`
- `normalized_categories_pkey`: `CREATE UNIQUE INDEX normalized_categories_pkey ON public.normalized_categories USING btree (category_id)`

### nutrition_validation

| Column | PostgreSQL type | Nullable | Default / generation |
|---|---|---|---|
| `id` | `integer` | No | `nextval('nutrition_validation_id_seq'::regclass)` |
| `product_id` | `integer` | No | `—` |
| `suspicion_level` | `character varying(10)` | No | `—` |
| `suspicion_score` | `numeric` | No | `0` |
| `reasons` | `jsonb` | No | `'[]'::jsonb` |
| `checked_at` | `timestamp with time zone` | No | `CURRENT_TIMESTAMP` |

**Constraints**

- `nutrition_validation_pkey`: `PRIMARY KEY (id)`
- `nutrition_validation_product_id_fkey`: `FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE CASCADE`
- `nutrition_validation_product_id_key`: `UNIQUE (product_id)`
- `nutrition_validation_suspicion_level_check`: `CHECK (suspicion_level::text = ANY (ARRAY['none'::character varying, 'low'::character varying, 'medium'::character varying, 'high'::character varying]::text[]))`

**Indexes** (including primary/unique constraint indexes)

- `idx_nutrition_validation_level_score`: `CREATE INDEX idx_nutrition_validation_level_score ON public.nutrition_validation USING btree (suspicion_level, suspicion_score DESC)`
- `nutrition_validation_pkey`: `CREATE UNIQUE INDEX nutrition_validation_pkey ON public.nutrition_validation USING btree (id)`
- `nutrition_validation_product_id_key`: `CREATE UNIQUE INDEX nutrition_validation_product_id_key ON public.nutrition_validation USING btree (product_id)`

### nutritionfacts

| Column | PostgreSQL type | Nullable | Default / generation |
|---|---|---|---|
| `nutrition_id` | `integer` | No | `nextval('nutritionfacts_nutrition_id_seq'::regclass)` |
| `product_id` | `integer` | No | `—` |
| `ingredients_text` | `text` | Yes | `—` |
| `energy_kcal` | `integer` | Yes | `—` |
| `energy_kj` | `integer` | Yes | `—` |
| `fat_total` | `numeric` | Yes | `—` |
| `fat_saturated` | `numeric` | Yes | `—` |
| `carbs_total` | `numeric` | Yes | `—` |
| `carbs_sugars` | `numeric` | Yes | `—` |
| `protein` | `numeric` | Yes | `—` |
| `salt` | `numeric` | Yes | `—` |
| `fiber` | `numeric` | Yes | `—` |
| `nutri_score_grade` | `character(1)` | Yes | `—` |
| `nutri_score_points` | `integer` | Yes | `—` |
| `data_source_date` | `timestamp with time zone` | Yes | `—` |
| `usda_fdc_id` | `integer` | Yes | `—` |
| `is_fiber_correct` | `boolean` | Yes | `false` |
| `nutrition_manual_edit` | `boolean` | Yes | `false` |

**Constraints**

- `nutritionfacts_pkey`: `PRIMARY KEY (nutrition_id)`
- `nutritionfacts_product_id_fkey`: `FOREIGN KEY (product_id) REFERENCES products(product_id)`
- `nutritionfacts_product_id_unique`: `UNIQUE (product_id)`

**Indexes** (including primary/unique constraint indexes)

- `idx_nutritionfacts_nutriscore`: `CREATE INDEX idx_nutritionfacts_nutriscore ON public.nutritionfacts USING btree (nutri_score_grade)`
- `idx_nutritionfacts_product`: `CREATE INDEX idx_nutritionfacts_product ON public.nutritionfacts USING btree (product_id)`
- `nutritionfacts_pkey`: `CREATE UNIQUE INDEX nutritionfacts_pkey ON public.nutritionfacts USING btree (nutrition_id)`
- `nutritionfacts_product_id_unique`: `CREATE UNIQUE INDEX nutritionfacts_product_id_unique ON public.nutritionfacts USING btree (product_id)`

### processing_workers

| Column | PostgreSQL type | Nullable | Default / generation |
|---|---|---|---|
| `id` | `integer` | No | `nextval('processing_workers_id_seq'::regclass)` |
| `worker_id` | `character varying(100)` | No | `—` |
| `hostname` | `character varying(255)` | Yes | `—` |
| `pid` | `integer` | Yes | `—` |
| `status` | `character varying(20)` | No | `'idle'::character varying` |
| `current_job_id` | `integer` | Yes | `—` |
| `last_heartbeat` | `timestamp without time zone` | Yes | `CURRENT_TIMESTAMP` |
| `started_at` | `timestamp without time zone` | Yes | `CURRENT_TIMESTAMP` |
| `stopped_at` | `timestamp without time zone` | Yes | `—` |
| `error_message` | `text` | Yes | `—` |

**Constraints**

- `processing_workers_current_job_id_fkey`: `FOREIGN KEY (current_job_id) REFERENCES category_processing_jobs(id)`
- `processing_workers_pkey`: `PRIMARY KEY (id)`
- `processing_workers_worker_id_key`: `UNIQUE (worker_id)`

**Indexes** (including primary/unique constraint indexes)

- `idx_workers_heartbeat`: `CREATE INDEX idx_workers_heartbeat ON public.processing_workers USING btree (last_heartbeat)`
- `idx_workers_status`: `CREATE INDEX idx_workers_status ON public.processing_workers USING btree (status)`
- `processing_workers_pkey`: `CREATE UNIQUE INDEX processing_workers_pkey ON public.processing_workers USING btree (id)`
- `processing_workers_worker_id_key`: `CREATE UNIQUE INDEX processing_workers_worker_id_key ON public.processing_workers USING btree (worker_id)`

### producers

| Column | PostgreSQL type | Nullable | Default / generation |
|---|---|---|---|
| `id` | `integer` | No | `nextval('producers_id_seq'::regclass)` |
| `name` | `text` | No | `—` |
| `normalized_name` | `text` | No | `—` |
| `website_url` | `text` | Yes | `—` |
| `created_at` | `timestamp with time zone` | No | `CURRENT_TIMESTAMP` |
| `updated_at` | `timestamp with time zone` | No | `CURRENT_TIMESTAMP` |

**Constraints**

- `producers_normalized_name_key`: `UNIQUE (normalized_name)`
- `producers_pkey`: `PRIMARY KEY (id)`

**Indexes** (including primary/unique constraint indexes)

- `producers_normalized_name_key`: `CREATE UNIQUE INDEX producers_normalized_name_key ON public.producers USING btree (normalized_name)`
- `producers_pkey`: `CREATE UNIQUE INDEX producers_pkey ON public.producers USING btree (id)`

### product_price_history

| Column | PostgreSQL type | Nullable | Default / generation |
|---|---|---|---|
| `price_history_id` | `integer` | No | `nextval('product_price_history_price_history_id_seq'::regclass)` |
| `product_id` | `integer` | No | `—` |
| `price` | `numeric` | No | `—` |
| `currency` | `character varying(3)` | No | `'EUR'::character varying` |
| `is_available` | `boolean` | No | `—` |
| `recorded_at` | `timestamp with time zone` | No | `—` |
| `data_source` | `character varying(100)` | Yes | `—` |
| `created_at` | `timestamp with time zone` | Yes | `CURRENT_TIMESTAMP` |
| `price_per_unit` | `numeric` | Yes | `—` |
| `price_per_unit_type` | `character varying(20)` | Yes | `—` |
| `discount_price` | `numeric` | Yes | `—` |
| `discount_price_per_unit` | `numeric` | Yes | `—` |

**Constraints**

- `product_price_history_pkey`: `PRIMARY KEY (price_history_id)`
- `product_price_history_product_id_fkey`: `FOREIGN KEY (product_id) REFERENCES products(product_id)`

**Indexes** (including primary/unique constraint indexes)

- `idx_price_history_product`: `CREATE INDEX idx_price_history_product ON public.product_price_history USING btree (product_id)`
- `idx_price_history_product_recorded`: `CREATE INDEX idx_price_history_product_recorded ON public.product_price_history USING btree (product_id, recorded_at DESC)`
- `idx_price_history_recorded`: `CREATE INDEX idx_price_history_recorded ON public.product_price_history USING btree (recorded_at)`
- `product_price_history_pkey`: `CREATE UNIQUE INDEX product_price_history_pkey ON public.product_price_history USING btree (price_history_id)`

### product_processing_log

| Column | PostgreSQL type | Nullable | Default / generation |
|---|---|---|---|
| `id` | `integer` | No | `nextval('product_processing_log_id_seq'::regclass)` |
| `job_id` | `integer` | No | `—` |
| `sku` | `character varying(50)` | No | `—` |
| `status` | `character varying(20)` | No | `'pending'::character varying` |
| `error_message` | `text` | Yes | `—` |
| `processed_at` | `timestamp without time zone` | Yes | `CURRENT_TIMESTAMP` |
| `product_url` | `text` | Yes | `—` |
| `price` | `numeric(10,2)` | Yes | `—` |
| `retail_price` | `numeric(10,2)` | Yes | `—` |
| `price_per_unit` | `numeric(10,4)` | Yes | `—` |
| `price_per_unit_type` | `character varying(20)` | Yes | `—` |
| `is_available` | `boolean` | Yes | `true` |
| `promotion_data` | `jsonb` | Yes | `—` |

**Constraints**

- `product_processing_log_job_id_fkey`: `FOREIGN KEY (job_id) REFERENCES category_processing_jobs(id)`
- `product_processing_log_pkey`: `PRIMARY KEY (id)`

**Indexes** (including primary/unique constraint indexes)

- `idx_processing_log_job`: `CREATE INDEX idx_processing_log_job ON public.product_processing_log USING btree (job_id)`
- `idx_processing_log_sku`: `CREATE INDEX idx_processing_log_sku ON public.product_processing_log USING btree (sku)`
- `product_processing_log_pkey`: `CREATE UNIQUE INDEX product_processing_log_pkey ON public.product_processing_log USING btree (id)`

### productphotos

| Column | PostgreSQL type | Nullable | Default / generation |
|---|---|---|---|
| `photo_id` | `integer` | No | `nextval('productphotos_photo_id_seq'::regclass)` |
| `product_id` | `integer` | No | `—` |
| `photo_url` | `text` | No | `—` |
| `alt_text` | `text` | Yes | `—` |
| `is_primary` | `boolean` | Yes | `false` |

**Constraints**

- `productphotos_pkey`: `PRIMARY KEY (photo_id)`
- `productphotos_product_id_fkey`: `FOREIGN KEY (product_id) REFERENCES products(product_id)`

**Indexes** (including primary/unique constraint indexes)

- `idx_productphotos_product`: `CREATE INDEX idx_productphotos_product ON public.productphotos USING btree (product_id)`
- `productphotos_pkey`: `CREATE UNIQUE INDEX productphotos_pkey ON public.productphotos USING btree (photo_id)`

### products

| Column | PostgreSQL type | Nullable | Default / generation |
|---|---|---|---|
| `product_id` | `integer` | No | `nextval('products_product_id_seq'::regclass)` |
| `sku` | `text` | No | `—` |
| `name` | `text` | No | `—` |
| `name_norm` | `text` | Yes | `—` |
| `barbora_url` | `text` | Yes | `—` |
| `category_id` | `integer` | No | `—` |
| `quantity_value` | `numeric` | Yes | `—` |
| `quantity_unit` | `character varying(50)` | Yes | `—` |
| `created_at` | `timestamp with time zone` | Yes | `CURRENT_TIMESTAMP` |
| `updated_at` | `timestamp with time zone` | Yes | `CURRENT_TIMESTAMP` |
| `country_of_origin` | `character varying(255)` | Yes | `'Unknown'::character varying` |
| `nutrition_source` | `character varying(50)` | Yes | `—` |
| `needs_enrichment` | `boolean` | Yes | `false` |
| `enrichment_reviewed` | `boolean` | Yes | `false` |
| `enrichment_skipped` | `boolean` | Yes | `false` |
| `ingredients` | `text` | Yes | `—` |
| `allergens` | `text` | Yes | `—` |
| `description` | `text` | Yes | `—` |
| `rimi_category_code` | `integer` | Yes | `—` |
| `has_confirmed_match` | `boolean` | Yes | `false` |
| `nova_score` | `integer` | Yes | `—` |
| `nova_source` | `character varying(30)` | Yes | `—` |
| `name_manual_edit` | `boolean` | Yes | `false` |
| `is_hidden` | `boolean` | Yes | `false` |
| `brand_id` | `integer` | Yes | `—` |
| `producer_id` | `integer` | Yes | `—` |

**Constraints**

- `products_brand_id_fkey`: `FOREIGN KEY (brand_id) REFERENCES brands(id)`
- `products_category_id_fkey`: `FOREIGN KEY (category_id) REFERENCES normalized_categories(category_id)`
- `products_pkey`: `PRIMARY KEY (product_id)`
- `products_producer_id_fkey`: `FOREIGN KEY (producer_id) REFERENCES producers(id)`
- `products_sku_key`: `UNIQUE (sku)`

**Indexes** (including primary/unique constraint indexes)

- `idx_products_brand`: `CREATE INDEX idx_products_brand ON public.products USING btree (brand_id)`
- `idx_products_category`: `CREATE INDEX idx_products_category ON public.products USING btree (category_id)`
- `idx_products_name_norm`: `CREATE INDEX idx_products_name_norm ON public.products USING btree (name_norm)`
- `idx_products_needs_enrichment`: `CREATE INDEX idx_products_needs_enrichment ON public.products USING btree (needs_enrichment)`
- `idx_products_producer`: `CREATE INDEX idx_products_producer ON public.products USING btree (producer_id)`
- `idx_products_sku`: `CREATE INDEX idx_products_sku ON public.products USING btree (sku)`
- `products_pkey`: `CREATE UNIQUE INDEX products_pkey ON public.products USING btree (product_id)`
- `products_sku_key`: `CREATE UNIQUE INDEX products_sku_key ON public.products USING btree (sku)`

### rimi_nova_categories

| Column | PostgreSQL type | Nullable | Default / generation |
|---|---|---|---|
| `rimi_category_code` | `integer` | No | `—` |
| `nova_score` | `integer` | Yes | `—` |
| `synced_at` | `timestamp with time zone` | Yes | `now()` |

**Constraints**

- `rimi_nova_categories_pkey`: `PRIMARY KEY (rimi_category_code)`

**Indexes** (including primary/unique constraint indexes)

- `rimi_nova_categories_pkey`: `CREATE UNIQUE INDEX rimi_nova_categories_pkey ON public.rimi_nova_categories USING btree (rimi_category_code)`

### translation_cache

| Column | PostgreSQL type | Nullable | Default / generation |
|---|---|---|---|
| `cache_id` | `integer` | No | `nextval('translation_cache_cache_id_seq'::regclass)` |
| `product_name_hash` | `character varying(64)` | No | `—` |
| `product_name` | `text` | No | `—` |
| `category_name` | `text` | Yes | `—` |
| `english_translation` | `text` | No | `—` |
| `translation_method` | `character varying(50)` | Yes | `—` |
| `confidence` | `numeric(3,2)` | Yes | `—` |
| `created_at` | `timestamp without time zone` | Yes | `CURRENT_TIMESTAMP` |

**Constraints**

- `translation_cache_pkey`: `PRIMARY KEY (cache_id)`
- `translation_cache_product_name_hash_key`: `UNIQUE (product_name_hash)`

**Indexes** (including primary/unique constraint indexes)

- `idx_translation_cache_hash`: `CREATE INDEX idx_translation_cache_hash ON public.translation_cache USING btree (product_name_hash)`
- `translation_cache_pkey`: `CREATE UNIQUE INDEX translation_cache_pkey ON public.translation_cache USING btree (cache_id)`
- `translation_cache_product_name_hash_key`: `CREATE UNIQUE INDEX translation_cache_product_name_hash_key ON public.translation_cache USING btree (product_name_hash)`

### update_statistics

| Column | PostgreSQL type | Nullable | Default / generation |
|---|---|---|---|
| `id` | `integer` | No | `nextval('update_statistics_id_seq'::regclass)` |
| `job_id` | `integer` | No | `—` |
| `category_code` | `character varying(50)` | No | `—` |
| `total_checked` | `integer` | Yes | `0` |
| `new_products` | `integer` | Yes | `0` |
| `price_changed` | `integer` | Yes | `0` |
| `availability_changed` | `integer` | Yes | `0` |
| `data_updated` | `integer` | Yes | `0` |
| `unchanged` | `integer` | Yes | `0` |
| `failed` | `integer` | Yes | `0` |
| `created_at` | `timestamp without time zone` | Yes | `CURRENT_TIMESTAMP` |

**Constraints**

- `update_statistics_job_id_fkey`: `FOREIGN KEY (job_id) REFERENCES category_processing_jobs(id)`
- `update_statistics_pkey`: `PRIMARY KEY (id)`

**Indexes** (including primary/unique constraint indexes)

- `idx_update_stats_category`: `CREATE INDEX idx_update_stats_category ON public.update_statistics USING btree (category_code)`
- `idx_update_stats_job`: `CREATE INDEX idx_update_stats_job ON public.update_statistics USING btree (job_id)`
- `update_statistics_pkey`: `CREATE UNIQUE INDEX update_statistics_pkey ON public.update_statistics USING btree (id)`

## Materialized view: product_ingredient_cards

Aggregates ingredient cards and category counts per product, joining products, categories, ingredient mappings, and ingredient analysis. Its join from mappings to product SKU is an application relationship, not a declared foreign key. Column nullability below is PostgreSQL catalogue metadata for a view, not a guarantee about the SELECT output.

| Column | PostgreSQL type | Catalogue nullable |
|---|---|---|
| `sku` | `text` | Yes |
| `name` | `text` | Yes |
| `category_id` | `integer` | Yes |
| `category_name` | `text` | Yes |
| `ingredients` | `jsonb` | Yes |
| `natural_count` | `bigint` | Yes |
| `processed_count` | `bigint` | Yes |
| `avoid_count` | `bigint` | Yes |
| `limit_count` | `bigint` | Yes |
| `caution_count` | `bigint` | Yes |

**Definition**

```sql
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
```

**Indexes**

- `CREATE UNIQUE INDEX idx_product_ingredient_cards_sku ON public.product_ingredient_cards USING btree (sku)`

## Sequences

The SQL preserves sequence data types, start/increment/bounds/cache, column ownership dependencies, and nextval defaults. It deliberately does not copy current sequence counters. Sequence `OWNED BY table.column` means a schema dependency, not an environment-specific database role assignment.

- `brands_id_seq`
- `category_processing_jobs_id_seq`
- `daily_update_logs_id_seq`
- `ingredient_analysis_id_seq`
- `job_events_id_seq`
- `lightweight_update_runs_run_id_seq`
- `nutrition_validation_id_seq`
- `nutritionfacts_nutrition_id_seq`
- `processing_workers_id_seq`
- `producers_id_seq`
- `product_price_history_price_history_id_seq`
- `product_processing_log_id_seq`
- `productphotos_photo_id_seq`
- `products_product_id_seq`
- `translation_cache_cache_id_seq`
- `update_statistics_id_seq`

## Verification and package checksum

The export inventory was compared against the same live read-only snapshot. The SQL is schema-only: no INSERT/COPY rows, sequence setval calls, owner-role assignments, grants, or materialized-view refresh data are included. A restore into an isolated temporary PostgreSQL 16 database is checked against the captured catalogue; the source development database and production database are not modified.

SHA-256 for `schema.sql`:

```text
fb76f20c82c391012eeae5879c916f6657efc5291aa94992b606759ec95b8e9a
```

Restore verification passed: the isolated database contains 20 tables, 65 indexes, 16 sequences, and 1 materialized view. All exported object DDL matches the source snapshot after excluding generated psql safety tokens and normalizing PostgreSQL’s equivalent array-cast rewrite in the nutrition-validation CHECK constraint. No other DDL differences were accepted.
