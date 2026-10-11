# Approved one-time Rimi nutrition import

This operation uses only the 190 reviewed **rank-one** pairs in the October 11,
2026 report. The user approved both suggested and review-only pairs and confirmed
that USDA-enriched values stored in Rimi are **per 100 g of edible food**. There
is no pack-weight scaling, new matching, live USDA request, scraping or schema
change. Review warnings remain in the audit; missing data is not silently guessed.

## Safety and scope

- Destination is the existing external `PROD_DATABASE_URL`; Rimi is read-only
  through the account-linked `RIMI_DATABASE_URL`. No credentials appear in files
  or commands. These databases must be distinct.
- The original CSV is reconciled field by field with its original fingerprinted
  database snapshots before producing the import manifest. Do not rerank the
  report or substitute other source products.
- Preview and apply check full product/nutrition before-images. Apply locks each
  target product and nutrition row and checks current source data, manual flags,
  enrichment/review status, latest scraped availability and category policy.
- Only core nutrient fields, USDA reference ID, nutrition source, completeness
  flag and recalculated score may change, plus corresponding update timestamps.
  Product names, ingredients, brands, producer, categories, prices, availability,
  NOVA, review/skipped flags and manual flags are not written.
- **Target fiber and `is_fiber_correct` are never written.** The existing fiber
  estimator may supply an effective value for scoring, without storing it or
  copying Rimi fiber.
- Missing source nutrients do not clear known target values and do not become
  zero. Valid recorded zeros remain zero. Incomplete source records retain
  `needs_enrichment`; unsupported scores are cleared rather than left stale.
- Origin remains `usda_api`, not `rimi_scraped`. The audit records the Rimi
  product ID/SKU, accepted warnings and confirmed basis. A missing source USDA
  ID clears an unrelated old target USDA ID.
- Each product is its own transaction. A full before-image backup and a durable
  prepared/committed receipt allow interrupted commits to be reconciled.
  Repeating the same apply detects matching post-images without another write.
- Cross-database reads are not distributed transactions: source data is checked
  in a fresh read-only transaction immediately before each target apply, then
  rechecked after the operation. A concurrently changed source is reported.

## Commands

All output belongs under `generated-artifacts/`, excluded from Git and publishing.
The original raw reviewed snapshots must match the SHA-256 hashes in summary.json.
The completed operation has a self-contained manifest and before-images, so
rerun/restore do not depend on temporary original files.

```sh
python import_rimi_nutrition.py preview --production \
  --basis-per-100g-confirmed \
  --target-baseline /tmp/produce-barbora.json \
  --source-baseline /tmp/produce-rimi.json \
  --output generated-artifacts/rimi-nutrition-import-2026-10-11
```

Review `field-preview.csv`, `manifest.json` and `before-images.json`. The manifest
contains all 190 pairs, original reviewed values, current before-images, policy
and database fingerprints. Production approval for these unchanged pairs has
already been given. Materially changed records are skipped, not silently approved.

```sh
python import_rimi_nutrition.py apply --production --confirm-production \
  --manifest generated-artifacts/rimi-nutrition-import-2026-10-11/manifest.json \
  --output generated-artifacts/rimi-nutrition-import-2026-10-11
```

Results: `apply-results.json`, `verification.json`, `import-audit.csv`,
`remaining-enrichment.csv`, and individual `receipts/*.json`. Verification
reconciles every pair, full target post-images, source data, preserved fields,
and server-side fingerprints of all unrelated product/nutrition rows.

## Guarded restoration (only if separately authorized)

Restoration changes production. Do not execute merely to test it. Each target
must still exactly match its recorded full post-image; subsequent edits cause
a skip. Only this operation's allowlisted fields and timestamps are restored.
Availability history and source data remain unchanged.

```sh
python import_rimi_nutrition.py restore --production --confirm-production \
  --manifest generated-artifacts/rimi-nutrition-import-2026-10-11/manifest.json \
  --output generated-artifacts/rimi-nutrition-import-2026-10-11
```

Results are recorded in `restore-results.json`. The CLI refuses a different
database, manifest/output directory mismatch or altered manifest/policy.

## Isolated tests

```sh
python -m unittest test_rimi_nutrition_import test_produce_nutrition_matches \
  test_rimi_produce_reader
```

PostgreSQL fixtures run on private temporary Unix sockets and never read project
credentials. Do not run broad legacy test discovery against production.
