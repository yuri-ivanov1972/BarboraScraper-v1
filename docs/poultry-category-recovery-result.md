# Production minced-poultry recovery — 2026-10-13

## Approved and completed

The user approved adding the missing category and its two missing products.
The initial preview expired before approval arrived. A genuine fresh website and
read-only database preview matched **every** previously approved field except the
fetch timestamp and resulting checksum; the same approved changes were applied
using the fresh manifest, without bypassing expiry or changing its timestamp.

- Category: **352 — Malta putnu gaļa**
- Website UUID: `8a626638-f481-4299-a438-eb24495c3fb1`
- Existing parent: **233 — Svaiga putnu gaļa**, under root **204**
- Website path:
  `gala-zivs-un-gatava-kulinarija/svaiga-putnu-gala/malta-putnu-gala`
- Completed audit job: **3994**, processed **2/2**, with both SKU logs completed.
- Failed product saves: **none**. Active jobs for the recovered category: **zero**.

| SKU | Product ID | Product | Outcome | Photos | Current price |
| --- | --- | --- | --- | --- | --- |
| `000000000001315297` | 12984 | Cāļa filejas maltās gaļas masa ĶEKAVA 450g | Created | 1 | €2.39 |
| `000000000001286881` | 12985 | Tītara maltās gaļas masa WELL DONE 400g | Created | 2 | €2.89 |

Both products have linked brands and producers, complete valid core nutrition
from Barbora (`nutrition_source=barbora_scraped`), accepted ingredients and full
available metadata. Both are available, visible and **`needs_enrichment=false`**.
Each gallery has exactly one primary photo.

Fiber, Nutri-Score and NOVA remain unassigned where supported inputs or mappings
are missing. No fiber policy was changed, no Rimi mapping was guessed, and no
unknown analysis was treated as a confident NOVA result.

The subsequent scoring investigation, separate explicit approval, applied results
and verification are in [poultry-scoring-result.md](poultry-scoring-result.md).
Both products now have supported estimated fiber, Nutri-Score C and NOVA 4;
recovery itself did not authorize those later scoring/mapping updates.

## Verification

- Server-enforced read-only checks matched every approved product/nutrition
  update, gallery URL and market value to the actual production records.
- The stored hierarchy/path matches the exact website UUID and requested URL.
- All pre-existing category rows are identical to the preview baseline.
- The actual Product Browser tree, listing and detail reader methods return
  the new category and both products when supplied read-only production connections.
- The actual daily updater methods return the category in **293** level-3
  categories and both SKUs in the existing-SKU set. This verifies eligibility for
  future scheduled runs, not execution of a future run.
- No broad worker or unrelated queued job was run.
- **11** scoped recovery tests passed, including unrelated queued-job preservation.
  Related product-refresh and NOVA regression suites also passed before Apply.

Generated approval manifests, transaction outcomes and detailed verification
are in the ignored `generated-artifacts/` directory. The durable job/SKU audit
is also stored in production; no credentials are included in this report.
