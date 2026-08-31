# Brand and producer backfill

The backfill re-fetches stored Barbora product URLs and updates only the
normalized brand and producer links. It is explicit, rate-limited, resumable,
and is never started automatically by the app or deployment.

## Development

Development uses Replit's runtime-managed `DATABASE_URL`:

```bash
PYTHONUNBUFFERED=1 python backfill_brand_producer.py \
  --start-id 0 \
  --batch-size 25 \
  --limit 10 \
  --delay 0.5
```

Remove `--limit 10` after reviewing the bounded result.
Development dry runs require the brand/producer schema to exist already; they
perform the same read-only schema preflight as production and never run DDL.

## Production prerequisites

1. Publish the latest development schema through Replit's Publish flow.
2. Confirm the production database contains `brands`, `producers`, and
   `brand_producers`, and that `products` has `brand_id` and `producer_id`.
3. Store the production connection string as the `PROD_DATABASE_URL` secret.
   Never paste the value into a command, source file, or log.
4. Ensure `logs/` exists before using `tee`.

Production execution performs a read-only schema preflight. It does not create
or alter tables. Both production flags are mandatory, and execution is refused
if `PROD_DATABASE_URL` is missing or exactly matches the development
`DATABASE_URL`.

## Production verification

Start with a dry run or bounded write:

```bash
PYTHONUNBUFFERED=1 python backfill_brand_producer.py \
  --production \
  --confirm-production \
  --start-id 0 \
  --batch-size 25 \
  --limit 10 \
  --delay 0.5 \
  --dry-run \
  2>&1 | tee logs/brand_producer_backfill_prod_dry_run.log
```

`--dry-run` performs the Barbora requests and database operations but rolls
back every batch. Its durable `resume_after_product_id` remains at the supplied
start ID because no writes were committed; `simulated_resume_after_product_id`
shows how far a successful real run could advance. Remove `--dry-run` to
perform the bounded production write.

## Full production run

```bash
PYTHONUNBUFFERED=1 python backfill_brand_producer.py \
  --production \
  --confirm-production \
  --start-id 0 \
  --batch-size 25 \
  --delay 0.5 \
  2>&1 | tee logs/brand_producer_backfill_prod.log
```

The final JSON summary includes `errors`, `failed_product_ids`, and
`resume_after_product_id`. A run with failures exits non-zero.

Resume from the reported safe cursor:

```bash
PYTHONUNBUFFERED=1 python backfill_brand_producer.py \
  --production \
  --confirm-production \
  --start-id REPORT_RESUME_ID_HERE \
  --batch-size 25 \
  --delay 0.5 \
  2>&1 | tee -a logs/brand_producer_backfill_prod.log
```

The older `--after-product-id` spelling remains available as an alias for
`--start-id`.