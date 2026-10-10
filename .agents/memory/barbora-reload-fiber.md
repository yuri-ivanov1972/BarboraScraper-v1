---
name: Barbora reload fiber policy
description: User's required fiber handling when reloading nutrition from Barbora.
---

For Barbora nutrition reloads, keep the current category-based fiber estimation approach to calculate Nutri-Score when website fiber is absent.

**Why:** The user stated that Barbora has no fiber information and explicitly rejected a preview that would clear fiber and leave Nutri-Score unknown.

**How to apply:** A missing website fiber field is not permission to discard existing fiber handling. Use the existing estimator and its precedence/provenance rules, preserve manual nutrition protections, and show resulting fiber and score changes in the revised preview before production apply.
