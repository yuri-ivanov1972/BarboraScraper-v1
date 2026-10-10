---
name: Enrichment availability meaning
description: User's definition of available for scraping in the Nutrition Data Enrichment tab.
---

In the Nutrition Data Enrichment tab, "available for scraping" means latest scraped product availability, not whether a page was successfully fetched in the one-time reload.

**Why:** The user explicitly selected latest scraped availability when requesting an available-only Needs Enrichment list.

**How to apply:** Restrict the visible enrichment queue and its counts consistently. Hiding an unavailable product must not imply that its nutrition was enriched or manually reviewed.
