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

### Approved production application

The user explicitly approved **“Apply 18 updates”**. Because the original
preview had expired, all three categories were fetched again into a separate
manifest. A comparison of the entire approved and refreshed manifests, excluding
only fetch timestamps and checksums, found no differences.

At **2026-10-30 20:52:09 UTC**, the scoped Apply transaction inserted **18**
`redesign_catchup` price-history rows for exactly the approved existing popcorn
products, with explicit exclusion approval. Read-back verified **all 52**
observed existing products against the approved values with **zero mismatches**.
The complete product-row fingerprints for the 52 observed products before and
after were identical. No new
products were inserted; the biscuit and pastry categories received no updates.

- Approved manifest checksum: `ce3833c7ab75b812f03719618c8061f19a2a5f34e2718132ef38b1b71a945f00`
- Applied fresh manifest checksum: `0a206459fd211658007e80272c02486f3e8f698fb75acc7b117286f502ea3bf1`
- Machine-readable receipt: `generated-artifacts/barbora-three-category-refreshed/application-verification.json`

The original preview files remain unchanged as approval evidence. They describe
the state **before** application, not the final write result. Unobserved-product
reports now distinguish incomplete, verified-empty, complete and unrequested
categories explicitly; none of these reasons infers unavailability.
The corrected derived report is
`generated-artifacts/barbora-three-category-refreshed/not-seen-corrected.csv`:
73 products belong to the incomplete pastry category, 29 to the verified-empty
biscuit category, and 16 were not observed in the complete popcorn listing.

## Verification

```sh
python -B -m unittest test_barbora_category_recovery test_barbora_redesign test_product_refresh \
  test_photo_maintenance test_brand_producer test_nutrition_reload -q
```

Database regression tests use a temporary isolated PostgreSQL instance, not the
project's development or production database.
