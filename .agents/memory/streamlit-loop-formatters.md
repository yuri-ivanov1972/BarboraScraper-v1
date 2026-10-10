---
name: Streamlit loop formatter timing
description: A delayed widget formatter can read the wrong loop iteration's labels.
---

Bind per-product label data when creating a widget formatter inside a loop.

**Why:** Streamlit's interactive test runner evaluates saved formatters after the script has finished. A callback closing over a reassigned loop variable then reads the last product's labels, causing an option lookup error before the next interaction.

**How to apply:** Capture each iteration's labels eagerly rather than relying on the loop variable's later value. Also use stable product identity for widget keys when batches can be pruned or reordered.
