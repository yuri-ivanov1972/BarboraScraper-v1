---
name: Photo maintenance policy
description: User-approved scope for regular photo maintenance and the consuming website data flow.
---

The consuming website reads this project's database directly.

**Why:** The user explicitly confirmed this data flow when discussing photo maintenance.

**How to apply:** Do not introduce an export or synchronization service just to publish photo URL changes. Do not assume that separate website caches or image proxies refresh automatically; verify them when their code/runtime is available.

Regular photo maintenance should automatically update retailer photos while preserving manual photos, prioritize daily URL changes, rotate unchanged links weekly, and cover only latest-scraped-available products.

**Why:** The user selected these scope and replacement policies.

**How to apply:** Preserve uncertain/manual ownership, distinguish access restrictions from missing images, and defer host-blocked checks rather than sacrificing these protections to meet the weekly target.
