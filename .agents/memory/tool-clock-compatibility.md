---
name: Tool clock compatibility
description: Date handling for read-only log requests in this project's execution sandbox.
---

Do not assume `Date.now()` is available in the durable execution scope here.
For known absolute log windows, use `Date.parse()` on an explicit ISO timestamp;
omit the upper bound when the request should include all newer logs.

**Why:** The runtime rejected `Date.now()` with “disabled in durableptc v1”
before the deployment-log callback could run, despite examples allowing it.

**How to apply:** Prefer absolute timestamps when querying incident logs.
If a genuinely current clock is required, follow the documented impure-function
boundary rather than repeating the failing durable-scope expression.
