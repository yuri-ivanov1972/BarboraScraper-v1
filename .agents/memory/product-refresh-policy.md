---
name: Manual Barbora refresh protections
description: User-selected behavior for manually refreshing an individual product from its Product Browser card.
---

For a manually triggered full Barbora product-card refresh, preview changes before Apply, always preserve manual edits, and prefer complete valid website nutrition over enriched nutrition. Missing/incomplete website information must not erase existing values.

**Why:** The user explicitly selected these protections and nutrition precedence when requesting a full refresh for a renamed product.

**How to apply:** Keep the refresh scoped to the selected product and retain the established fiber-estimation approach. Do not introduce a manual-edit overwrite option or make a preview save changes automatically.

Unknown ingredient analysis must not be represented as a confident automatic NOVA classification. Remove mappings for ingredients no longer accepted; retain shared analysis, and leave NOVA pending when newly encountered ingredients are not yet analyzed.

**Why:** A refreshed ingredient list can invalidate an old additive-based grade. The safe preview must not make paid/live AI calls or treat missing analysis as evidence that ingredients are harmless.

**How to apply:** Recompute from accepted inputs and available analysis, preserve manual NOVA overrides, and use the existing pending-analysis workflow for new ingredients.
