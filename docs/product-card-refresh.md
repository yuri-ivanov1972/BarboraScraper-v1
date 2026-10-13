# Refresh a single product from Barbora

In **Product Browser**, use **Refresh from Barbora** on a grid card, or open
the product and expand **Refresh from Barbora**. Click **Fetch refresh preview**,
review the old/new values and protected/unavailable fields, then choose
**Apply changes** or **Cancel preview**.

Fetching does not save anything. Apply affects the selected existing SKU only,
uses the same `DATABASE_URL` as the Browser, and requires a fresh preview if
product data, related records, categories or ingredient analysis have changed.
Previews expire after ten minutes. Database/network errors do not expose secrets.

## What is refreshed

- Name, description, ingredients, allergens, origin, pack quantity/unit, product
  URL, uniquely mapped category, brand and producer.
- Valid product gallery photos; absent/placeholder galleries retain old photos.
- Regular/discount and comparative prices, current availability and price history.
  History is appended only when values change. Hidden products remain unavailable.
- Complete, valid per-100-g/ml website nutrition takes precedence over non-manual
  enriched nutrition. Missing/incomplete website nutrition retains stored values;
  incomplete stored data cannot be falsely marked fully enriched.
- Nutri-Score, automatic NOVA and nutrition-consistency findings are recalculated
  from accepted values. New ingredient mappings replace this SKU's old mappings;
  shared existing analysis and manually managed brand/producer websites are retained.

Manual name/ingredient and nutrition flags protect their inputs. Manual NOVA
overrides are retained. Computed scores can still reflect accepted/protected
post-update inputs; protection does not turn a previously computed score into
a manually editable score.

Fiber follows the existing estimation policy, retaining existing positive values
and using configured category/exception estimates when necessary. No missing
website field becomes a guessed zero. Unsupported scoring inputs produce no
grade rather than a stale, apparently valid score.

New ingredients enter the existing pending-analysis catalogue. If classification
depends on analysis not yet available, the automatic NOVA score is cleared with
a preview explanation; no live AI analysis or external enrichment is run by a
preview. Saving single or batch ingredient analysis automatically recalculates
NOVA for currently linked products in the same transaction, using their current
category and mappings. Manual NOVA overrides are retained. Remaining unknown
ingredients keep category-based scores pending; a confirmed avoid/limit additive
can establish NOVA 4 even while other ingredients remain unknown. Completed natural
ingredient analysis is usable even though it has no suspicion marker. Reprocessing
the same analysis does not rewrite unchanged product scores.

Promotion prices are stored using existing history columns. Promotion type/card
requirements are displayed in the preview, but the current schema has no column
for those metadata. Storage conditions also have no product-storage column.
Missing or ambiguous category mappings are explicitly reported and not guessed.

## Safety and verification

Fetch validates HTTPS Barbora hosts and redirects before following them, checks
the exact SKU including leading zeros, and can recover an old URL through an
exact-SKU lookup in at most six pages of the current category. It never substitutes
a name-matched product or treats a failed fetch as proof of unavailability.

Preview reads use server-enforced read-only transactions and no worker, cache or
schema initializers. Apply uses one serializable transaction with locked target
rows, allowlisted fields, a complete baseline comparison and rollback on failure.
The detail-view database reader skips startup migration statements.

```sh
python -m unittest test_nova_analysis_completion test_product_refresh test_brand_producer \
  test_nutrition_reload test_nutrition_reload_postgres test_nutrition_validation
```

Tests use private temporary PostgreSQL fixtures and Streamlit's application
testing tools. Do not execute production Apply merely to test this feature.
