---
name: Account secret visibility
description: Secret existence metadata can miss an account-linked connection available to running code.
---

Do not treat secret-existence metadata alone as proof that an account-linked database connection is unavailable.

**Why:** The user identified an account-linked `RIMI_DATABASE_URL`. Secret-existence metadata reported it absent, but running code could use it successfully for a read-only Rimi database connection.

**How to apply:** Verify runtime presence without printing the value and, when authorized, attempt a read-only connection before requesting duplicate credentials. Never expose connection strings or unsanitized connection errors.
