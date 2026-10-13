---
name: NOVA completion concurrency
description: Why ingredient analysis completion and product refresh need whole-transaction conflict handling.
---

Keep ingredient-analysis persistence and affected automatic NOVA updates atomic.
Retry the whole save on a deadlock or serialization conflict, not only the scoring
portion. Do not reuse a captured mapping list after waiting for a product lock.

**Why:** Product refresh locks the product before replacing ingredient mappings
and updating shared ingredient frequencies; analysis completion writes shared
ingredients before finding affected products. Their opposite lock order can
conflict legitimately. Separating commits would leave completed analysis with
stale scores after a conflict, and stale mapping snapshots can score products
that no longer contain the analyzed ingredient.

**How to apply:** Maintain explicit bounded retries and rollback on exhausted
conflicts. Test with isolated PostgreSQL and real competing transactions, not only
mocked conflicts. Refresh must retain its serializable transaction and fresh-preview
requirement so newly linked ingredients cannot silently race an analysis save.
