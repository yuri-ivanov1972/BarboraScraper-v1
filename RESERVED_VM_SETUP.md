# Reserved VM Deployment Setup Guide

This guide explains how to set up the Reserved VM deployment for the Rimi Product Scraper worker system.

## Overview

The worker system runs on a **Reserved VM** deployment to optimize costs and provide 24/7 background processing. This separates the heavy scraping workload from the Streamlit UI (which stays on Autoscale).

## Why Reserved VM?

**Cost Comparison:**
- **Autoscale**: Billed per compute unit (18 CU/CPU-second + 2 CU/GB-second)
  - 24/7 worker = ~$60-100+/month in compute units
- **Reserved VM**: Flat $20/month for 0.5 vCPU / 2GB RAM
  - Predictable cost for always-on workloads

**Best For:**
- Background workers that run continuously
- Scheduled jobs (daily auto-updates)
- Long-running scraping tasks
- Jobs that don't need to scale with traffic

## Deployment Configuration

### 1. Machine Size

**Recommended:** Shared VM - 0.5 vCPU / 2GB RAM ($20/month)

This is sufficient for:
- Processing 9000+ products overnight
- Running worker.py with 15-product chunks
- Daily auto-update scheduling
- Log storage and monitoring

### 2. App Type

**Background Worker** (does not listen on a port)

The worker processes jobs from the database queue and doesn't serve HTTP requests.

### 3. Run Command

```bash
./worker_startup.sh
```

This script:
- Runs `worker.py --resume-all --heartbeat-interval 30 --chunk-size 15`
- Auto-restarts on failure (up to 5 attempts)
- Logs all activity to `logs/` directory

### 4. Environment Variables

**Required Secrets** (copy from current deployment):
```
DATABASE_URL
PGHOST
PGPORT
PGUSER
PGPASSWORD
PGDATABASE
```

These are automatically available in the Replit environment - the Reserved VM will inherit them from your project secrets.

### 5. Build Command

```bash
pip install -r requirements.txt
```

Installs all Python dependencies before the worker starts.

## Setup Steps

### Step 1: Open Publishing Tool

1. Click "All tools" in left sidebar
2. Select "Publishing"
3. Click "Reserved VM"

### Step 2: Configure Deployment

1. **Machine size**: Shared VM - 0.5 vCPU / 2GB RAM
2. **Subdomain**: Choose a name (e.g., `rimi-scraper-worker`)
3. **Build command**: `pip install -r requirements.txt`
4. **Run command**: `./worker_startup.sh`
5. **App type**: Select "Background worker"

### Step 3: Add Environment Variables

The database environment variables should already be available from your Replit project. If not:

1. Click "Add published app secret"
2. Add each variable from your project secrets:
   - `DATABASE_URL`
   - `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE`

### Step 4: Deploy

1. Click "Deploy"
2. Wait for deployment to complete (~2-3 minutes)
3. Check logs to verify worker started successfully

## Daily Auto-Update Schedule

### Using Cron (Recommended for Reserved VM)

Create a crontab entry to run daily at 2am Latvia time:

```bash
# Run daily at 2am EET/EEST (Latvia timezone)
0 2 * * * /home/runner/workspace/daily_scheduler.sh
```

**Important:** Schedule at 2am to avoid Rimi's maintenance window (midnight-1am).

### Setup Instructions

1. SSH into Reserved VM or use Replit Shell
2. Edit crontab: `crontab -e`
3. Add the line above
4. Save and exit
5. Verify: `crontab -l`

Logs will be saved to `logs/auto_update_YYYYMMDD.log`

## Monitoring

### Check Worker Status

```bash
# View worker logs
tail -f logs/worker_*.log

# Check if worker is running
ps aux | grep worker.py

# View recent auto-update logs
ls -lt logs/auto_update_*.log | head -5
```

### Database Queries

```sql
-- Check job queue status
SELECT status, COUNT(*) as jobs, SUM(total_products) as products
FROM category_processing_jobs
GROUP BY status;

-- Check worker status
SELECT worker_id, status, last_heartbeat
FROM processing_workers
WHERE status != 'stopped'
ORDER BY last_heartbeat DESC;

-- View recent update statistics
SELECT category_code, new_products, price_changed, unchanged, created_at::date
FROM update_statistics
ORDER BY created_at DESC
LIMIT 10;
```

## Dual Deployment Architecture

After setting up Reserved VM:

| Component | Deployment Type | Purpose | Cost |
|-----------|----------------|---------|------|
| **Worker System** | Reserved VM | 24/7 background processing, daily auto-updates | $20/month flat |
| **Streamlit UI** | Autoscale | User interface, on-demand access | ~$2-5/month (scales to zero) |

### Autoscale Optimization

After migrating worker to Reserved VM, optimize your Autoscale deployment:

1. **Remove worker workflow** from Streamlit app
2. **Set max machines to 1-2** (prevents over-scaling)
3. **Keep only Streamlit UI** workflow

This reduces Autoscale compute unit consumption to near-zero when no users are active.

## Troubleshooting

### Worker Not Starting

1. Check logs: `tail -f logs/worker_*.log`
2. Verify database connection:
   ```bash
   python -c "import os; import psycopg2; psycopg2.connect(os.environ['DATABASE_URL'])"
   ```
3. Test worker manually:
   ```bash
   python worker.py --resume-all --chunk-size 15
   ```

### Jobs Not Processing

1. Check queue:
   ```bash
   python auto_update.py --status
   ```
2. Verify worker is registered:
   ```sql
   SELECT * FROM processing_workers WHERE status = 'active';
   ```
3. Check for stale jobs:
   ```sql
   SELECT * FROM category_processing_jobs 
   WHERE status = 'in_progress' 
   AND last_heartbeat < NOW() - INTERVAL '5 minutes';
   ```

### Daily Schedule Not Running

1. Verify crontab: `crontab -l`
2. Check cron logs: `grep CRON /var/log/syslog`
3. Test scheduler manually:
   ```bash
   ./daily_scheduler.sh
   ```
4. Ensure script is executable: `chmod +x daily_scheduler.sh`

## Cost Monitoring

### Expected Monthly Costs

**Reserved VM:**
- Base cost: $20/month (0.5 vCPU / 2GB RAM)
- Includes: Unlimited CPU/RAM within machine limits
- No compute unit charges

**Autoscale (UI only):**
- Base fee: $1/month
- Compute units: ~$2-5/month (scales to zero when idle)
- Requests: $1.20 per million requests

**Total:** ~$23-26/month (vs. $60-100+ with all on Autoscale)

### Setting Alerts

1. Go to Replit Account Settings
2. Navigate to Billing → Usage Alerts
3. Set alert at $30/month
4. Add budget limit at $40/month

## Next Steps

After deployment:

1. ✅ Verify worker processes existing queued jobs
2. ✅ Test daily scheduler with manual run
3. ✅ Monitor for 48 hours to ensure stability
4. ✅ Remove worker from Autoscale deployment
5. ✅ Set up usage alerts and budget limits
6. ✅ Document any adjustments needed

## Support

For issues or questions:
- Check worker logs in `logs/` directory
- Review database job queue and statistics
- Consult `WORKER_USAGE.md` for worker system details
- Review Replit docs: https://docs.replit.com/hosting/deployments/reserved-vm
