# Targeted minced-poultry category recovery

The category at
`https://barbora.lv/gala-zivs-un-gatava-kulinarija/svaiga-putnu-gala/malta-putnu-gala`
has website UUID `8a626638-f481-4299-a438-eb24495c3fb1`.
It was absent from the stored category tree, which is the daily scraper's source
of level-3 categories. Website listings initially showed two absent SKUs:
`000000000001315297` and `000000000001286881`.

## Prepare and review

```sh
python recover_poultry_category.py preview --production
```

This reads the existing external database through `PROD_DATABASE_URL` in a
server-enforced read-only transaction and fetches the exact category and full
product pages. It does not instantiate a worker, initialize schema, create jobs,
save ingredients, or update a product. Category pagination is bounded to six
pages and product identity/category checks reject wrong or partial discovery.

The manifest in `generated-artifacts/poultry-recovery-preview.json` contains the
category proposal, full product comparisons, manual protections, scoring results,
context and approval checksum. Generated manifests/results are ignored by Git
and deployment. Review the manifest and obtain explicit approval before Apply.

Complete website nutrition does not imply a Nutri-Score can be computed: Barbora
does not normally publish fiber. This new category may lack an existing fiber
estimate or Rimi NOVA default. Retain the established estimation policy and leave
unsupported grades unassigned; never invent mappings or interpret unknown fiber
as zero. Ingredient analysis uses the existing pending-analysis workflow.

## Apply the exact approved preview

```sh
python recover_poultry_category.py apply --production \
  --approve-sha THE_EXACT_CHECKSUM_FROM_THE_APPROVED_PREVIEW
```

Approval, database identity, policy fingerprints and expiry (one hour) are checked
before connecting for writes. Changed taxonomy, active jobs, products or ingredient
context require a fresh preview, not an automatic overwrite.

One serializable transaction:
- Verifies the exact root and poultry parent by website UUID and hierarchy.
- Adds or reuses the category; a short category-table lock makes `MAX+1` ID
  allocation safe for this manually keyed tree. Existing IDs/rows are retained.
- Runs the **same full-information planning and persistence pipeline as the
  Product Browser refresh**, including brands/producers, nutrition, description,
  ingredients, allergens, origin, units, photos, market history and validations.
- Preserves existing manual inputs/overrides and shared master metadata.
- Records a completed audit job and per-SKU outcomes, not an executable queue job.

No network request is made during Apply. A failure rolls back the category,
all products and their dependent data together. No unrelated job is claimed or
processed. The result file records every SKU as not applied, identifying the
failed SKU when a product save caused rollback. The application does not need a schema change or a broad category
reimport; **do not run `import_categories.py`**, which deletes the current tree.

A fresh repeat preview yields no changes when stored values match, with no new
jobs or history rows. Reapplying the old approved manifest safely fails its stale
baseline checks rather than duplicating records.

## Verify recovery

Check the inserted/reused UUID, its parent and reconstructed URL; inspect every
listed SKU's full fields, photos, latest availability/price and enrichment state.
Check the completed audit job, Product Browser category/product queries and the
daily updater's level-3 selection. Selection proves eligibility for subsequent
scheduled runs, not that a future nightly run has already executed.

```sh
python -m unittest test_poultry_category_recovery test_product_refresh \
  test_nova_analysis_completion
```

Tests use private temporary PostgreSQL databases and HTTP fixtures. They cover
actual full persistence, Browser queries, daily eligibility, repeated recovery,
collision-safe category allocation, manual edits, stale/concurrent changes,
malformed/mismatched website identity and whole-operation rollback.
