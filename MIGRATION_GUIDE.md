# Database Migration Guide

This guide explains how to copy data between your development database (heliumdb) and your production database (Neon) in either direction.

## Overview

The `migrate_to_production.py` script copies all 12 tables between databases in the correct order to respect foreign key constraints. Direction is controlled by a required `--direction` flag:

| Flag | What it does |
|------|-------------|
| `--direction prod-to-dev` | Copy production → development (refresh dev with live data) |
| `--direction dev-to-prod` | Copy development → production (**destructive** — wipes prod tables) |

### Tables Migrated (in dependency order)

**CRITICAL**: Parent tables are migrated BEFORE child tables to prevent CASCADE deletions.

1. **Base tables** (no dependencies):
   - `normalized_categories` - Your 75 level2 categories
   - `ingredient_analysis` - E-number and ingredient data

2. **Products table** (depends on categories):
   - `products` - All product information

3. **Job table** (parent of workers and other job-related tables):
   - `category_processing_jobs` - Job queue with processing history

4. **Worker table** (depends on jobs):
   - `processing_workers` - Worker registration data (has FK to category_processing_jobs)

5. **Product-related tables** (depend on products):
   - `nutritionfacts` - Nutritional information
   - `productphotos` - Product photos from Rimi CDN
   - `product_price_history` - Historical pricing data

6. **Job-related tables** (depend on jobs):
   - `job_events` - Job lifecycle event logs
   - `product_processing_log` - Per-product processing logs
   - `update_statistics` - Category update statistics

7. **Mapping tables**:
   - `ingredient_product_mapping` - Links ingredients to products

## Prerequisites

### 1. Get Your Production Database Connection String

You need the production database connection URL from Replit:

1. Open your **Reserved VM deployment** in Replit
2. Go to the **Database** pane
3. Click on **"Production"** tab
4. Copy the connection string (format: `postgresql://user:password@host:port/database`)

### 2. Database URLs

Two connection strings are needed:

| Variable | Always points to | How to provide |
|----------|-----------------|----------------|
| `DATABASE_URL` | Development DB (heliumdb) | Replit injects this automatically — no action needed |
| `OTHER_DATABASE_URL` | Production DB (Neon) | Set this to your production Neon connection string, or leave it unset and the script will prompt you interactively |

To set the production URL in advance:

```bash
export OTHER_DATABASE_URL='your_production_neon_connection_string'
python migrate_to_production.py --direction prod-to-dev
```

Or simply run the script without setting it and paste the URL when prompted.

## Running the Migration

### Step 1: Verify Development Database

First, check that your development database has data to migrate:

```bash
python -c "
import os
import psycopg2
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cursor = conn.cursor()
cursor.execute('SELECT COUNT(*) FROM normalized_categories')
print(f'Categories: {cursor.fetchone()[0]}')
cursor.execute('SELECT COUNT(*) FROM products')
print(f'Products: {cursor.fetchone()[0]}')
cursor.close()
conn.close()
"
```

### Step 2: Run the Script

**To refresh dev with production data (most common):**

```bash
export OTHER_DATABASE_URL='your_production_neon_connection_string'
python migrate_to_production.py --direction prod-to-dev
```

**To push dev data up to production:**

```bash
export OTHER_DATABASE_URL='your_production_neon_connection_string'
python migrate_to_production.py --direction dev-to-prod
```

The `dev-to-prod` direction requires two confirmations before proceeding.

### Step 3: Review Output

The script will:
- ✅ Connect to both databases
- ✅ Show progress for each table
- ✅ Display record counts (source → destination)
- ✅ Verify all data was copied correctly
- ✅ Reset auto-increment sequences

**Example output (prod-to-dev):**

```
==============================================================
        DATABASE COPY: PRODUCTION → DEVELOPMENT
==============================================================

ℹ This will REPLACE all data in your dev (heliumdb) database
ℹ with a fresh copy from production.

Type YES to continue: YES

ℹ Connecting to production (Neon) ...
✓ Connected to production (Neon)
ℹ Connecting to development (heliumdb) ...
✓ Connected to development (heliumdb)

==============================================================
                      STARTING COPY
==============================================================

ℹ Migrating table: normalized_categories
ℹ   Source records: 75
ℹ   Truncating destination table...
ℹ   Inserted 75/75 records...
✓   Done: 75 records

ℹ Migrating table: products
ℹ   Source records: 9034
ℹ   Truncating destination table...
ℹ   Inserted 1000/9034 records...
...
✓   Done: 9034 records

...

==============================================================
                        SUMMARY
==============================================================

✓ normalized_categories                  75 →       75
✓ ingredient_analysis                   450 →      450
✓ products                             9034 →     9034
...

ℹ Total records copied:   63060
ℹ Total tables processed: 12
ℹ Completed in 45.32 seconds
✓ All tables copied successfully!
```

## Important Notes

### Data Safety

- ⚠️ **The script TRUNCATES (deletes all data) in production tables before copying**
- This ensures a clean migration without duplicates
- If you need to preserve existing production data, modify the script to use `UPSERT` logic instead

### Foreign Key Handling

- The script temporarily disables foreign key constraints during migration
- This allows faster bulk inserts without constraint checking overhead
- Constraints are re-enabled after migration completes

### Sequence Reset

- Auto-increment sequences are automatically reset to match the maximum ID values
- This ensures new records get correct IDs after migration

### Error Handling

If migration fails:

1. **Check error message** - The script shows detailed error information
2. **Verify connection strings** - Ensure DATABASE_URL is set correctly for both source and destination
3. **Check permissions** - Production database user must have CREATE, INSERT, DELETE permissions
4. **Review logs** - Look for network issues or timeout errors

The script is **safe to re-run** - it will truncate and re-migrate all data.

## Post-Migration Verification

After migration completes, verify your production database by running this from your **production** deployment (where `DATABASE_URL` already points to production):

```bash
# Check record counts
python -c "
import os
import psycopg2
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cursor = conn.cursor()

tables = [
    'normalized_categories',
    'products',
    'category_processing_jobs',
    'nutritionfacts'
]

for table in tables:
    cursor.execute(f'SELECT COUNT(*) FROM {table}')
    count = cursor.fetchone()[0]
    print(f'{table}: {count} records')

cursor.close()
conn.close()
"
```

## Starting Worker on Production

After successful migration, you can start the worker on your Reserved VM:

```bash
python worker.py --resume-all --heartbeat-interval 30 --chunk-size 15 --max-workers 3
```

The worker will:
- ✅ Find all your migrated jobs in `category_processing_jobs`
- ✅ Resume processing from where it left off
- ✅ Use optimal settings for Reserved VM (no timeout limits)

## Troubleshooting

### Problem: "DATABASE_URL not set"

**Solution**: Replit injects `DATABASE_URL` automatically in the dev environment. If running locally for testing, export it manually:

```bash
export DATABASE_URL='your_dev_connection_string'
export OTHER_DATABASE_URL='your_production_neon_connection_string'
python migrate_to_production.py --direction prod-to-dev
```

### Problem: Script prompts for the production URL

**Solution**: Set `OTHER_DATABASE_URL` before running to skip the interactive prompt:

```bash
export OTHER_DATABASE_URL='your_production_neon_connection_string'
python migrate_to_production.py --direction prod-to-dev
```

### Problem: "Permission denied on table"

**Solution**: Ensure your production database user has proper permissions:

```sql
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO your_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO your_user;
```

### Problem: "Connection timeout"

**Solution**: Check that:
- Your production database is accessible
- Firewall rules allow connections
- Connection string is correct (host, port, credentials)

### Problem: Record count mismatch

**Solution**: 
- Re-run the migration (script is idempotent)
- Check for schema differences between dev and prod
- Verify all tables exist in production database

## Next Steps

After successful migration:

1. ✅ Verify production database has all data
2. ✅ Test Streamlit UI on production deployment
3. ✅ Start worker with Reserved VM settings
4. ✅ Monitor job processing and logs
5. ✅ Set up daily auto-updates at 2am Latvia time

---

**Questions or issues?** Check the migration output for detailed error messages or review the script source code in `migrate_to_production.py`.
