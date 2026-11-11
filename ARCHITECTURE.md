# BarboraScraper-v1 Architecture

BarboraScraper-v1 collects products from [Barbora.lv](https://barbora.lv), the online store of Maxima Latvia, and stores them in PostgreSQL. The [abcde.lv](https://abcde.lv) website reads this database as its Maxima source, through the website's `MAXIMA_DATABASE_URL`.

The repository is a fork of [RimiScraper-v2](https://github.com/yuri-ivanov1972/RimiScraper-v2), and the two share their root commit. A lot of generic code is still shared with the Rimi scraper, sometimes unused: `worker.py`, `core_parser.py`, `batch_processor.py` and others. The Barbora-specific path is described below.

## Components

```mermaid
flowchart LR
    subgraph Barbora["barbora.lv"]
        LIST["Category pages<br/>window.b_productList JSON"]
        PDP["Product pages<br/>window.__remixContext"]
    end

    subgraph App["BarboraScraper-v1"]
        UI["Streamlit UI<br/>main.py"]
        LS["Scheduler<br/>lightweight_scheduler.py"]
        LU["Lightweight updater<br/>barbora_lightweight_updater.py"]
        BW["Worker<br/>barbora_worker.py"]
        BPAR["BarboraParser<br/>barbora_parser.py + barbora_site_data.py"]
        ENR["Enrichment<br/>nutriscore · nova · fiber · ingredients"]
        MAINT["Maintenance tools<br/>photos · refresh · reload · recovery"]
        XR["Rimi cross-link tools"]
    end

    PG[("Barbora / Maxima PostgreSQL<br/>DATABASE_URL · PROD_DATABASE_URL")]
    RIMI[("Rimi PostgreSQL<br/>RIMI_DATABASE_URL (read-only)")]
    GEM["Gemini"]
    SITE["abcde.lv API server"]

    LS -- "02:00 Riga" --> LU
    UI --> LU
    UI -- queue jobs --> PG
    LU --> BPAR --> LIST
    LU -- "price rows · new-SKU jobs" --> PG
    BW -- "claim job (SKIP LOCKED)" --> PG
    BW --> BPAR --> PDP
    BW --> ENR --> PG
    ENR --> GEM
    UI --> MAINT --> PG
    XR -- read --> RIMI
    XR -- write --> PG
    PG -- read only --> SITE
```

Barbora pages embed their data as JSON, so the parser decodes JavaScript objects with `json.JSONDecoder().raw_decode` instead of scraping HTML text:

- Category pages carry the product list in `window.b_productList`.
- Product pages carry their data in `window.__remixContext`.

## Two update paths

```mermaid
sequenceDiagram
    autonumber
    participant S as lightweight_scheduler
    participant L as LightweightUpdater
    participant B as barbora.lv
    participant DB as PostgreSQL
    participant W as barbora_worker

    Note over S,L: Daily, 02:00 Europe/Riga
    S->>L: run
    loop each category
        L->>B: GET category pages
        B-->>L: b_productList JSON (sku, price, availability)
        L->>DB: compare with latest product_price_history
        alt known SKU, values changed
            L->>DB: INSERT product_price_history (data_source = barbora_listing)
        else unknown SKU
            L->>DB: INSERT category_processing_jobs (queued)
        end
    end
    L->>DB: INSERT lightweight_update_runs (summary)

    Note over W,DB: Separately, the worker drains the queue
    W->>DB: claim job (priority DESC, scheduled_for ASC, SKIP LOCKED)
    loop each pending SKU
        W->>B: GET product page
        W->>DB: save product, nutrition, photos
        W->>DB: price history, fiber estimate, ingredients → NOVA
    end
    W->>DB: fix missing photos, refresh product_ingredient_cards
```

- **Lightweight path** (daily): reads only listing JSON, roughly 10–50× faster than full scraping. It inserts a price row only when a price field changes beyond a tolerance of €0.01, and it queues jobs for SKUs it hasn't seen before.
- **Full path** (worker): `barbora_worker.py` claims queued jobs and scrapes each product page. It can run once (`--single-run`) or until the queue is empty (`--exit-when-empty`).

`combined_startup.sh` starts the Streamlit UI and the lightweight scheduler. It doesn't start the worker. `ENABLED = False` in `lightweight_scheduler.py`, and the startup script passes `--enable` to override it.

## Data model

The schema is in `barbora_schema.sql`, generated from the live database on 2026-04-27. It closely follows Rimi's schema with these differences:

| Difference | Purpose |
|---|---|
| `products.barbora_url` replaces `rimi_url` | Source link |
| `products.ingredients`, `allergens` and `description` | Raw text stored on the product |
| `products.rimi_category_code` (integer) | Points to a Rimi `normalized_categories.category_id`. The website uses it to place Maxima products in Rimi's category tree. |
| `products.has_confirmed_match` | A Barbora product has been matched to a Rimi product. |
| `products.name_manual_edit` | Keeps a manually edited name from being overwritten by the scraper. |
| `rimi_nova_categories` | Local cache of Rimi category NOVA scores, filled by `sync_rimi_nova_categories.py` |
| `lightweight_update_runs` | History of daily listing-only runs |
| `translation_cache` | Product name translations to English (Gemini, manual or rule-based) |

```mermaid
erDiagram
    products ||--|| nutritionfacts : has
    products ||--o{ product_price_history : "append-only"
    products ||--o{ productphotos : has
    products ||--o{ ingredient_product_mapping : "by sku"
    ingredient_analysis ||--o{ ingredient_product_mapping : ""
    products }o--|| normalized_categories : "category_id (Barbora tree)"
    products }o--o| rimi_nova_categories : rimi_category_code
    brands ||--o{ products : ""
    producers ||--o{ products : ""
    category_processing_jobs ||--o{ product_processing_log : ""
    lightweight_update_runs {
        int run_id PK
        int price_changes
        int new_product_jobs_created
    }
```

As in the Rimi scraper, `product_price_history` is append-only, and the current price is the latest row.

## Links to Rimi data

The Rimi database is opened read-only through `RIMI_DATABASE_URL`. Several approved, audited one-time operations copy data from it:

```mermaid
flowchart LR
    R[("Rimi DB")] -->|category NOVA scores| A["sync_rimi_nova_categories.py"] --> T1["rimi_nova_categories"]
    R -->|"reviewed rank-one matches"| B["rimi_nutrition_import_*.py"] --> T2["nutritionfacts<br/>(core nutrients only)"]
    R -->|"fresh produce"| C["produce_nutrition_matches.py<br/>rimi_produce_reader.py"] --> T3["CSV report<br/>(read-only)"]
    R -->|"category defaults"| D["fiber_estimation_config.json"] --> T4["fiber estimates"]
```

The rules for these operations are described in `docs/rimi-nutrition-import.md` and `docs/rimi-produce-report.md`:

- The source and destination databases must be different.
- Import only from the reviewed manifest.
- Before writing, check the full before-image of each product and nutrition row and lock the target rows.
- Never write fiber or `is_fiber_correct`.
- Never overwrite fields that were set manually.

## Scoring

Nutri-Score and fiber estimation follow the same algorithm as RimiScraper-v2. The formulas are in that repository's `ARCHITECTURE.md` and in `NUTRISCORE_ALGORITHM.md` here. Fiber defaults are looked up by `rimi_category_code`.

### NOVA rules

The Barbora version is stricter than the Rimi version. If the analysis is missing or contradictory, the product's NOVA stays unknown instead of being treated as unprocessed:

```mermaid
flowchart TD
    M{"manual_override?"} -- yes --> KEEP["keep"]
    M -- no --> A{"any ingredient<br/>suspicion ∈ {avoid, limit}?"}
    A -- yes --> N4a["4 · additive_override"]
    A -- no --> F{"explicit flavouring<br/>(aromatizētāji) marked caution?"}
    F -- yes --> N4b["4 · additive_override<br/>(flavouring_marker)"]
    F -- no --> U{"every ingredient has<br/>a consistent analysis?"}
    U -- no --> P["NULL · pending_analysis"]
    U -- yes --> G{"category says 1, but salt or<br/>flavouring was added?"}
    G -- yes --> X["NULL · unsupported_preparation_default"]
    G -- no --> C{"category score in 1–4?"}
    C -- yes --> INH["category score · category_inherited"]
    C -- no --> NC["NULL · no_category"]
```

`_assign_nova_score` locks the product row with `FOR UPDATE` and re-reads the ingredient mappings before writing. This prevents a race with refresh jobs running at the same time.

## Maintenance tools

Most of the code added since the fork is careful repair tooling. Each tool comes as a *plan → preview → apply* set of modules, with a Streamlit UI and a write-up in `docs/`:

| Tool | Modules | Doc |
|---|---|---|
| Photo maintenance | `photo_maintenance*.py`, `photo_sources.py`, `fix_broken_photos.py` | `docs/photo-maintenance.md`, `docs/barbora-photo-formats.md` |
| Product card refresh | `product_refresh_{plan,source,store,ui}.py` | `docs/product-card-refresh.md` |
| Nutrition reload | `nutrition_reload_{plan,source,store}.py`, `reload_barbora_nutrition.py` | `docs/barbora-nutrition-reload.md` |
| Enrichment availability | `enrichment_availability.py` | `docs/enrichment-availability.md` |
| Poultry recovery and scoring | `poultry_*.py`, `recover_poultry_category.py` | `docs/poultry-*.md` |
| Brand and producer backfill | `backfill_brand_producer.py`, `migrate_brand_producer.py` | `BRAND_PRODUCER_BACKFILL.md` |

## Notes

- `replit.md` is still titled "Maxima Product Scraper" and describes Rimi in several places. `WORKER_USAGE.md` documents the Rimi `worker.py`, not `barbora_worker.py`.
- The Barbora worker's `claim_job` sets `status = 'processing'`. The Rimi worker uses `in_progress` with heartbeat leases. The Barbora worker doesn't reclaim stale jobs.
