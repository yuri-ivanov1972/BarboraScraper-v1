# One-time Rimi produce nutrition comparison

This tool only reads the two existing PostgreSQL databases. It does not load the
app's database initialization, scraping, translation or enrichment services.
There is no apply/import mode.

## Run

The runtime needs the existing `PROD_DATABASE_URL` and account-linked
`RIMI_DATABASE_URL`. Do not paste either connection string into commands, output
or reports.

```sh
python produce_nutrition_matches.py --production-read-only \
  --output generated-artifacts/rimi-produce-matches-new
```

Choose a new/empty output directory. Existing reports are never overwritten.
Generated output is excluded from Git and deployment.

Files:
- `matches.csv`: every target, including excluded/unmatched targets, with up to
  three comparable source candidates, nutrient values, provenance and warnings.
- `source-audit.csv`: every scoped Rimi record, including unknown-origin and
  invalid nutrition. Those records are not recommended replacements.
- `summary.md` / `summary.json`: reconciled product counts, snapshots and limits.

Import SKU columns as **text** when opening CSV in a spreadsheet to retain
leading zeros. Cells that could become spreadsheet formulas are escaped.

## What the counts mean

Targets are production products below Barbora's verified produce root, flagged
for enrichment, unreviewed, and available in their latest price-history record.
Timestamp ties use descending history ID; no availability history means excluded.
Rimi's separate category tree is traversed independently, including products
assigned directly to a parent category. Rimi availability is displayed, not used
as an exclusion.

`suggested` means the best candidate has compatible observed identity/form and
passed basic numeric/completeness checks. It does **not** mean the underlying
USDA food match has been independently verified. `review_only` means candidates
exist but specificity, composition, provenance details or nutrient quality need
review. `unmatched` has no acceptable known-origin candidate; `unresolved` has an
ambiguous identity/composition without candidates. Non-fresh/non-food entries are
`excluded`. Manually edited target nutrition is `manual_protected`.

Different explicit varieties, species, colors, edible portions and growth stages
are not interchangeable. Missing specificity requires review. Blend labels alone
do not prove equivalent ingredient proportions.

Amounts are shown **as recorded**. USDA documentation specifies per-100-g edible
food nutrient amounts, and the local importer follows that convention. However,
the external Rimi importer has not been inspected and its rows have no explicit
basis field. Confirm its convention and original USDA matches before any future
import. Neither pack weights nor target fiber estimates are used to transform
nutrients. All existing fiber, manual edits, flags, timestamps and scores remain
unchanged.

Both readers use server-enforced read-only repeatable-read transactions. Separate
databases have separate snapshot timestamps, not a shared atomic snapshot.
Connection errors are sanitized to avoid disclosing connection credentials.

## Verification

```sh
python -m unittest test_produce_nutrition_matches test_rimi_produce_reader -v
```

Matching tests run offline. Reader tests create a private temporary PostgreSQL
instance with no TCP listener, demonstrate write rejection inside the actual
reader session, and delete that fixture afterward. They never use project secrets.
