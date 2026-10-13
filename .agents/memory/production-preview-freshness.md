---
name: Production preview freshness
description: Safe comparison of a refreshed production preview when approval arrives after expiry.
---

Expired production previews must be genuinely fetched again, not given a newer
timestamp to bypass their expiry guard. Compare the entire fresh manifest with
the approved one, not just product counts, names or rendered change summaries.

**Why:** Approval can arrive after the preview's safety window. Identical visible
changes alone do not prove database snapshots, ingredient context or processing
rules stayed unchanged.

**How to apply:** Check target identity, policy, category hierarchy, every product
candidate, snapshot and context. If anything beyond fetch timestamp/checksum
differs, obtain approval for the changed preview before writing. Keep the approved
and refreshed manifests separate, and retain serializable baseline checks at Apply.
