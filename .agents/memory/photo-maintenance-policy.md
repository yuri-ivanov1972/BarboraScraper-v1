---
name: Photo maintenance policy
description: User-approved scope for regular photo maintenance and the consuming website data flow.
---

The consuming website reads this project's database directly.

**Why:** The user explicitly confirmed this data flow when discussing photo maintenance.

**How to apply:** Do not introduce an export or synchronization service just to publish photo URL changes. Do not assume that separate website caches or image proxies refresh automatically; verify them when their code/runtime is available.

The consuming website is abcde.lv; the user reports that it does not recognize AVIF product photos.

**Why:** The user identified incompatible stored AVIF URLs after Barbora's UI redesign and supplied HTML showing PNG alternatives for the same images.

**How to apply:** Prefer supported image alternatives advertised by Barbora, particularly PNG. Do not assume a guessed extension replacement exists or infer that the consumer supports AVIF merely because an image URL returns HTTP 200.

Regular photo maintenance should automatically update retailer photos while preserving manual photos, prioritize daily URL changes, rotate unchanged links weekly, and cover only latest-scraped-available products.

**Why:** The user selected these scope and replacement policies.

**How to apply:** Preserve uncertain/manual ownership, distinguish access restrictions from missing images, and defer host-blocked checks rather than sacrificing these protections to meet the weekly target.

Do not infer that an existing photo is retailer-managed solely because its URL is on the retailer CDN. Unknown ownership needs explicit classification, and external changes to a previously managed primary require renewed review.

**Why:** Existing photo records do not establish whether a human selected the image; guessing would violate the user's requirement to preserve manual photos.

**How to apply:** Keep safe automatic replacements opt-in until a bounded preview is reviewed on the intended database. Preserve unclassified photos instead of bulk-adopting them from the supplied report.
