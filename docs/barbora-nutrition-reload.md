# One-time Barbora nutrition/name reload

This command does not run through the normal scraper worker, queue jobs, change
daily scraping, or create database schema. Preview is the default. Production
apply requires a separate explicit approval of the completed preview.

## Production preview

Run from the project root:

```bash
python reload_barbora_nutrition.py \
  --production --confirm-production --dry-run \
  --delay 0.5 --workers 3 \
  --manifest generated-artifacts/production-nutrition-reload.json
```

The existing production database secret is used internally. Connection strings,
passwords and raw connection exceptions are never printed. There is no automatic
fallback to development.

The exact selection is `needs_enrichment IS TRUE` and
`COALESCE(enrichment_reviewed, FALSE) = FALSE`. Skipped and unavailable products
are included. The operation never scans for or flags additional products.

The first invocation captures the entire selected scope and baseline values in a
read-only PostgreSQL transaction. `--limit 10` can bound a **new** preview for
testing. An existing manifest always retains its original scope; use a different
filename to create a different selection.

All requests share a rate limiter; worker threads hide network latency without
increasing the configured request rate. Workers are limited to 1–4, retries to
0–3, and delay to at least 0.25 seconds. Redirects are checked before following
them. Only HTTPS Barbora hosts are allowed. Fallback category listings are cached,
bounded by `--max-category-pages` (default 30), and used only to locate an exact,
unique SKU. A changed name never establishes product identity.

No database connection remains open while pages are being downloaded.

## Preview files and restart

- `production-nutrition-reload.json`: frozen scope, baseline values, parsed
  candidates and allowlisted proposals. It contains catalogue records, not
  credentials or raw HTML; keep it with the report for apply/reconciliation.
- `.json.csv`: reviewable per-product before/after report, including nutrition,
  names, protections, missing pages, unknown values and proposed score changes.
- `.json.summary.json`: counts, error categories, completion status and final
  approval SHA-256.
- `.json.lock`: process lock preventing simultaneous preview/apply of one manifest.

Reports and manifests are generated under `generated-artifacts/`, which is
excluded from Git and deployment. Keep a downloaded copy if moving environments.
Preview checkpoints are saved atomically every 25 products. Rerun the **same**
command and filename to continue after interruption; at most the last uncheckpointed
batch will be fetched again. Successfully previewed products and recorded source
failures are skipped on ordinary resume.

To retry only failed page checks within the same frozen scope, add
`--retry-source-errors` to the preview command. This generates a new preview digest
requiring renewed approval; it never adds newly eligible products.

## What proposals can change

- Non-manually corrected product `name` and `name_norm`.
- Complete, valid per-100 g/ml nutrition. Energy units may be converted using
  1 kcal = 4.184 kJ; integer energy columns are rounded explicitly.
- Nutrition provenance/date, obsolete USDA link, fiber provenance, Nutri-Score,
  `needs_enrichment`, and the product change timestamp.

Name and nutrition manual flags are independent. `enrichment_reviewed` and
`enrichment_skipped` are preserved. Prices, availability, ingredients (including
`nutritionfacts.ingredients_text`), allergens, description, category, quantity,
photos, NOVA, brand, producer, SKU, product ID and stored URL stay unchanged.

Required source values are energy (at least one unit), fat, saturated fat,
carbohydrates, sugars, protein and salt. Values must have recognized units and
be finite/non-negative. A real numeric zero is accepted, including all-zero
nutrition for water. Partial or empty nutrition is only reported and does not
replace existing measurements or clear the enrichment flag.

Fiber is optional in the Barbora response. When absent, use the existing
`FiberEstimator` and configuration: retain positive existing fiber and its
correctness flag, otherwise apply the configured category/keyword exception
estimate using the stored `rimi_category_code` and effective product name.
Estimates have `is_fiber_correct=false`; they are never represented as scraped
Barbora measurements. The report includes fiber origin, value and reason.
A configured zero is a valid estimate. Unmapped categories do not become
fabricated zeros; a verified existing zero can be retained, otherwise fiber
and score remain unknown. Explicit website fiber takes precedence if supplied.
No AI or USDA lookup is performed and no global estimation rules are changed.

With explicit, retained or estimated fiber, the existing calculator is used with
stored ingredients, the effective product name, and the production category
mapping, including beverage/sweetener rules. A failed calculation clears the old
score instead of retaining a stale grade. A name-only change also refreshes or
clears a name-dependent score where nutrition is not manually protected. If the
stored core scoring inputs are complete but fiber needs estimation, a name-only
update can also estimate fiber with the same policy; it leaves other nutrition,
the core source/date, and the enrichment flag unchanged.

## Rebuild the saved preview with category fiber estimation

The original preview that proposed clearing missing fiber must not be applied.
Rebuild from the completed saved candidates into a **new** manifest:

```bash
python reload_barbora_nutrition.py \
  --production --confirm-production --dry-run \
  --rebuild-from generated-artifacts/production-nutrition-reload.json \
  --manifest generated-artifacts/production-nutrition-reload-fiber.json
```

This reads the production category mapping in a read-only transaction, but makes
no HTTP requests and does not recapture or extend the original product scope.
The original file remains unchanged. The new manifest records the source digest,
fiber configuration digest, revised proposal policy and its own approval digest.
Rebuild requires a completed source preview, no apply checkpoint for that source,
and a new output filename. It cannot be combined with source retries or a limit.
Old fiber-clearing manifests are explicitly blocked by apply, even if their old
digest is supplied. Review and approve the **revised** report before production writes.

## Apply only after preview approval

First verify that `preview_complete` is true in the summary, review the CSV and
approve the proposed changes. Then use the exact `approval_sha256` from that
completed preview:

```bash
python reload_barbora_nutrition.py \
  --production --confirm-production --apply \
  --manifest generated-artifacts/production-nutrition-reload-fiber.json \
  --approved-sha256 APPROVED_PREVIEW_SHA256
```

`APPROVED_PREVIEW_SHA256` is a placeholder, not a credential. Apply refuses an
incomplete preview, an altered manifest, a mismatched database, or scope-changing
options. It makes no HTTP requests and applies the reviewed proposals rather
than refetching different page contents.

Each product is applied in its own transaction. Product/nutrition rows are locked
and compared with the complete captured baseline. A product changed by scraping
or manual editing since preview is skipped as `baseline_changed`, even if the
changed field is outside this operation's write scope. Manual protections and
eligibility are checked again; no products are created.

The `.json.apply.json` checkpoint is recorded only after commit/rollback. Rerun
the same approved apply command to resume. If interrupted after a commit but
before checkpointing, matching approved state is detected without a second
write and reported as `already_applied_or_matches_approved_state`.
`apply_failed` outcomes are retried; stale or protected records are not.
Unexpected post-commit states require reconciliation, not automatic overwriting.

The final summary contains proposed outcomes separately from actual apply
outcomes, the actual update count and the remaining flagged count within the
original manifest. Any source/apply failures remain explicit report entries;
inspect the report even if the process exits normally.

## Tests

```bash
python -m unittest test_nutrition_reload -v
python -m py_compile reload_barbora_nutrition.py nutrition_reload_source.py \
  nutrition_reload_plan.py nutrition_reload_store.py
```

`test_nutrition_reload_postgres.py` additionally verifies real SQL writes and
read-only enforcement against an empty isolated local PostgreSQL instance at
port 55441 with a restored schema. It accepts only a socket directory starting
with `/tmp/nutrition-reload-db.` and never reads application database secrets.
Do not run legacy repository-wide tests indiscriminately; some existing test
scripts directly mutate catalogue databases.
