# Barbora recovery

The redesigned pages are read through the shared structured-data adapter. Missing,
unrecognized or incomplete category pages are errors, not evidence that products
are unavailable. Existing category paths must match exactly. Retailer category
UUIDs are not rewritten automatically.

## Prices/availability catch-up

These preview commands use read-only database transactions. They do not initialize
schema, create products/jobs, update photos, enrich nutrition or backdate prices.

```sh
# Bounded production preview
python barbora_catchup.py --production --confirm-production --limit 3 \
  --output generated-artifacts/barbora-catchup-bounded

# Full production preview
python barbora_catchup.py --production --confirm-production \
  --output generated-artifacts/barbora-catchup-full

# One bounded retry of failed categories, retaining successful observations
python barbora_catchup.py --production --confirm-production \
  --retry-failed generated-artifacts/barbora-catchup-full/preview.json \
  --output generated-artifacts/barbora-catchup-retried
```

Review `changes.csv`, `coverage.csv`, `new-products-excluded.csv` and `not-seen.csv`.
An unobserved product is not automatically made unavailable. Conflicting
observations are never eligible for application.

Only after explicit approval of the exact preview:

```sh
python barbora_catchup.py --production --confirm-production \
  --apply generated-artifacts/barbora-catchup-full/preview.json
```

A full preview with failed categories is blocked unless the user explicitly
approves applying verified products while excluding every listed failed category.
Only then add `--accept-exclusions` and use that approved manifest's path.
Bounded previews cannot be applied even with this flag.

Preview expiry and changed database baselines stop the apply operation. Generate a
fresh preview and obtain renewed approval if the proposed data or coverage changes.
All applied observations use the actual application time; repeat application does
not duplicate unchanged price history.

Publishing the parser repair and approving catch-up data are separate decisions.
Do not run the normal writing updater as a substitute for a catch-up preview.

## Verification

```sh
python -B -m unittest test_barbora_redesign test_product_refresh \
  test_photo_maintenance test_brand_producer test_nutrition_reload -q
```

Database regression tests use a temporary isolated PostgreSQL instance, not the
project's development or production database.
