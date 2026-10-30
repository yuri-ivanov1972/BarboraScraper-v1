---
name: Barbora redesign identity
description: Category identity and nutrition-basis evidence when adapting to retailer redesigns.
---

Do not assume Barbora category UUIDs survive a website redesign. Reconcile existing categories only through their exact full hierarchy path and validated current category metadata; do not guess by a translated name or overwrite stored mappings automatically.

**Why:** During the October 2026 redesign, the live category tree replaced UUIDs, while product inventory exposed all-zero category UUID placeholders. Existing paths continued to redirect to equivalent categories.

**How to apply:** Verify the resolved full path before accepting an existing category's observations. Report genuinely changed/unmapped paths separately; leave broad category discovery to its own work.

A valid category can return zero inventory with blank category metadata while still appearing in the current category tree. Missing inventory metadata is not proof that the category was retired.

**Why:** The user supplied working current category links after earlier exclusions; the weighted-biscuit listing had an explicit matching inventory-query short ID and current-tree path despite blank response metadata.

**How to apply:** Confirm empty listings only through agreement between the query identity, pagination, exact expected hierarchy and current tree. Never turn products missing from such a listing into unavailable products automatically.

The redesigned product page's nutrient accordion is client-rendered, so missing per-100-g text in server HTML is not proof of missing nutrition.

**Why:** The public product route displayed the product nutrient values under the per-100-g translation, but the initial server-rendered HTML omitted the accordion content. Values and GDA percentages are separate fields.

**How to apply:** Validate the current retailer rendering contract before adapting nutrient fields. Never substitute GDA percentages for grams or infer a new basis solely from absent SSR text.
