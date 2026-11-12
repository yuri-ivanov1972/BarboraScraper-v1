---
name: Nutri-Score classification scope
description: User-approved category source for bounded Nutri-Score scoring corrections.
---

For the Nutri-Score boundary and fats-category corrections, keep the existing saved-category mapping rather than adding a dedicated saved Nutri-Score category field.

**Why:** The user explicitly chose “Keep existing saved-category mapping” when the distinction between saved catalogue categories and a dedicated scoring-classification field was explained.

**How to apply:** Preserve the current category source during scoring-rule corrections. A request to correct grade boundaries or protein rules does not also authorize a new classification scheme, per-product overrides or database fields; agree that scope separately if needed.
