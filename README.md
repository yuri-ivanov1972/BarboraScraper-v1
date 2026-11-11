# BarboraScraper-v1

Crawls [Barbora.lv](https://www.barbora.lv), the online store of Maxima Latvia, and parses product data into PostgreSQL. It supplies the Maxima products shown on [abcde.lv](https://abcde.lv).

This repository is a fork of [RimiScraper-v2](https://github.com/yuri-ivanov1972/RimiScraper-v2), and the two share their early history. Many generic modules and docs, including `WORKER_USAGE.md` and parts of `replit.md`, still refer to Rimi. The Barbora-specific code is in the `barbora_*` files.

## What it does

- **Scrapes products** from Barbora: name, SKU, price, photos, quantity, country of origin, ingredients, allergens and nutrition (`barbora_parser.py`, `barbora_site_data.py`).
- **Tracks prices**: each price or availability change is inserted as a new row in `product_price_history`. The `products` table holds product metadata only. The full schema is in `barbora_schema.sql`.
- **Updates prices daily** with a lightweight updater (`barbora_lightweight_updater.py`).
- **Links Barbora products to Rimi data**:
  - Rimi category codes (`sync_rimi_nova_categories.py`)
  - Rimi nutrition imports (`import_rimi_nutrition.py`, `rimi_nutrition_import_*.py`)
  - Fresh produce matching (`produce_*.py`, `rimi_produce_reader.py`)
- **Scores products**:
  - Nutri-Score (`nutriscore_calculator.py`; the algorithm is described in `NUTRISCORE_ALGORITHM.md`)
  - NOVA processing level (`nova_calculator.py`, `populate_nova.py`)
  - Fiber estimates (`fiber_estimator.py`)
  - USDA enrichment (`usda_enrichment.py`)
  - Nutrition validation (`nutrition_validation.py`)
- **Analyzes ingredients**: finds E-number additives and makes one AI pass to classify and flag ingredients (`combined_ingredient_analyzer.py`).
- **Provides maintenance tools**:
  - Photo maintenance (`photo_maintenance*.py`, `fix_broken_photos.py`)
  - Product card refreshes (`product_refresh_*.py`)
  - Nutrition reloads (`nutrition_reload_*.py`)
  - Poultry category recovery (`poultry_*.py`)
  - Brand and producer backfill (`backfill_brand_producer.py`)

## Architecture

| Component | Entry point | Role |
|---|---|---|
| Streamlit UI | `main.py` | Browsing, reports, maintenance tools, job queueing |
| Barbora worker | `barbora_worker.py` | Processes queued Barbora jobs from the PostgreSQL job queue |
| Daily updater | `barbora_lightweight_updater.py` | Price and availability refresh |
| Combined startup | `combined_startup.sh` | Starts the daily scheduler (`lightweight_scheduler.py --enable`) and the UI. It doesn't start the worker. |

The project was built on Replit and is configured there by `.replit` and `replit.nix`.

## Setup

Requires Python 3.11 or newer and PostgreSQL. Dependencies are managed with [uv](https://github.com/astral-sh/uv):

```bash
uv sync
```

Environment variables used by the code:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Main Barbora/Maxima PostgreSQL connection |
| `RIMI_DATABASE_URL`, `OTHER_DATABASE_URL` | Read access to the Rimi database for cross-store matching |
| `PRODUCTS_DB_URL`, `CATEGORIES_DB_URL` | Additional database connections used by some modules |
| `AI_INTEGRATIONS_GEMINI_API_KEY`, `AI_INTEGRATIONS_GEMINI_BASE_URL` | Gemini access for ingredient analysis |
| `USDA_API_KEY` | USDA nutrition enrichment |
| `GOOGLE_TRANSLATE_API_KEY` | Food name translation |

## Running

```bash
# UI
streamlit run main.py --server.port 5000

# Barbora worker (one job, or until the queue is empty)
python barbora_worker.py --single-run
python barbora_worker.py --exit-when-empty

# Daily price/availability update (preview first)
python barbora_lightweight_updater.py --dry-run --limit 5
python barbora_lightweight_updater.py

# UI plus the 02:00 daily scheduler
./combined_startup.sh
```

## Tests

The tests are the `test_*.py` files in the repository root, with fixtures in `fixtures/`:

```bash
uv run pytest
```

Some of them use a real database, so check what a test touches before pointing it at production.

## Further documentation

- `ARCHITECTURE.md`: components, update paths, data model, NOVA rules
- `replit.md`: architecture notes and verified schema facts
- `docs/`: feature write-ups covering nutrition reload, photo formats and maintenance, enrichment availability, product card refresh, Rimi nutrition import, Rimi produce report and poultry recovery
- `BARBORA_RECOVERY.md`, `BRAND_PRODUCER_BACKFILL.md`: operational notes
- `DAILY_UPDATES_GUIDE.md`, `RESERVED_VM_SETUP.md`, `MIGRATION_GUIDE.md`: operations and deployment
