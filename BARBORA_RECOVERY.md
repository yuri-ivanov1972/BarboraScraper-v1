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

## Three-category recovery

The three user-confirmed paths use canonical `/c/{shortId}/{fullPath}` routes.
Every response must still agree with the current tree and inventory query.
An empty listing with blank metadata is accepted only when its zero-item response,
query identity, pagination and exact current-tree path agree. It never makes
previously stored products unavailable merely because they were not listed.

```sh
python barbora_catchup.py --production --confirm-production --recover-three \
  --output generated-artifacts/barbora-three-category-preview
```

This is a complete **explicit three-category scope**, not a sample of all
categories. Its manifest binds the exact selected paths and only includes
observations from categories with complete listings. New products are reported
but never created. The usual approval, freshness, baseline and exclusion guards
apply; `--recover-three` is only a preview option, not an Apply option.

The pastry listing was observed advertising 50 items while returning 49 on page
one and none on page two. That is an inconsistent retailer response, not evidence
that the missing product is unavailable. Keep this category incomplete unless a
complete listing is recovered; never lower the expected count silently.

## Verification

```sh
python -B -m unittest test_barbora_redesign test_product_refresh \
  test_photo_maintenance test_brand_producer test_nutrition_reload -q
```

Database regression tests use a temporary isolated PostgreSQL instance, not the
project's development or production database.
