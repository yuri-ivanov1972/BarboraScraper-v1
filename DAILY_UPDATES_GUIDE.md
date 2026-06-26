# Daily Automated Updates - Production Guide

## System Overview

The Rimi product scraper now features a fully automated daily update system that:
- Processes all 75 level2 categories automatically
- Runs daily at 2am Latvia time (Europe/Riga timezone)
- Tracks product changes, price updates, and availability
- Generates comprehensive daily reports
- Handles failures gracefully with per-category isolation

## Architecture

**Dual Component System:**
1. **auto_update.py** - Orchestrates daily updates (queue creation + reporting)
2. **worker.py** - Background daemon that processes queued jobs 24/7

**Database Tables:**
- `category_processing_jobs` - Job queue with status tracking
- `processing_workers` - Worker registration and heartbeat monitoring
- `job_events` - Event log for debugging
- `daily_update_logs` - Historical update reports

## Production Commands

### 1. Start Worker Daemon (24/7 Background Processing)

```bash
python worker.py --daemon --heartbeat-interval 30 --chunk-size 15 --max-workers 3
```

**Parameters:**
- `--daemon` - Keep running 24/7, polling for jobs
- `--heartbeat-interval 30` - Send heartbeat every 30 seconds
- `--chunk-size 15` - Process 15 products per chunk
- `--max-workers 3` - Use 3 parallel workers per category

**Worker Features:**
- Automatic heartbeat monitoring
- Stale job reassignment (if worker dies)
- Graceful shutdown on SIGTERM/SIGINT
- Memory usage tracking
- Continuous job polling with 10-second sleep when idle

### 2. Queue Daily Update Jobs

```bash
python auto_update.py --queue-all
```

**What it does:**
- Queues jobs for all 75 level2 categories
- Sets priority based on product count (high priority = more products)
- Worker daemon automatically picks up and processes jobs
- Each category commits independently (failures don't cascade)

### 3. Generate Daily Report

```bash
python auto_update.py --report
```

**Report includes:**
- Categories processed (count)
- Jobs completed/failed/stuck
- New products discovered
- Products updated
- Price changes (top 5 largest changes)
- Availability changes (back in stock / out of stock)
- Duration and timestamp

**Exit codes:**
- `0` - Success (all jobs completed, no stuck jobs)
- `1` - Failure (stuck or failed jobs detected)

## Cron Setup (2am Daily Updates)

### Install Cron Job

```bash
bash cron_setup.sh
```

**What it does:**
1. Creates `/var/log/rimi_daily_update.log` for logging
2. Configures cron job: `0 2 * * * /path/to/cron_job.sh`
3. Runs at 2am Latvia time (Europe/Riga)
4. Queues all categories, waits for completion, generates report

### Manual Cron Job (if cron_setup.sh fails)

Add to crontab:
```cron
TZ=Europe/Riga
0 2 * * * cd /path/to/project && python auto_update.py --queue-all --wait && python auto_update.py --report >> /var/log/rimi_daily_update.log 2>&1
```

## Monitoring

### Check Worker Status

```bash
# View worker registration
psql $DATABASE_URL -c "SELECT * FROM processing_workers ORDER BY last_heartbeat DESC;"

# Check active jobs
psql $DATABASE_URL -c "SELECT * FROM category_processing_jobs WHERE status = 'in_progress';"

# View job events (last 50)
psql $DATABASE_URL -c "SELECT * FROM job_events ORDER BY created_at DESC LIMIT 50;"
```

### View Reports

```bash
# Last 24 hours
python auto_update.py --report --report-hours 24

# Last 7 days
python auto_update.py --report --report-hours 168

# View all historical reports
psql $DATABASE_URL -c "SELECT * FROM daily_update_logs ORDER BY created_at DESC;"
```

### Check Cron Logs

```bash
tail -f /var/log/rimi_daily_update.log
```

## Stuck Job Detection

**A job is flagged as stuck if:**
1. In progress for > 30 minutes (grace period for new jobs)
2. Worker heartbeat is stale (> 30 minutes)
3. Worker heartbeat is dead (> 60 minutes for assigned workers)

**Why this works:**
- Workers send heartbeat after EACH chunk (~every 1-3 minutes)
- Even 15-product chunks complete in ~15 minutes
- 60-minute stale heartbeat = truly stuck, not false positive

**False positive prevention:**
- 30-minute grace period for newly started jobs
- 60-minute threshold (4x typical chunk time)
- Only flags jobs with dead worker heartbeats

## Failure Handling

### Per-Category Isolation
- Each category processes in isolated transaction
- One category failure doesn't abort remaining categories
- Failed categories logged but queue continues

### Worker Failure Recovery
- Worker heartbeat monitoring detects dead workers
- Stale jobs automatically reassigned to healthy workers
- Job events logged for debugging

### Database Transaction Safety
- Each category commits independently
- Skip paths commit immediately to release locks
- Rollback on category-level exceptions

## Performance

**Typical metrics:**
- ~9000 products across 75 categories
- ~15 products per chunk
- ~1 minute per product (scraping + processing)
- Total processing time: ~6-8 hours for full update

**Resource usage:**
- Memory: ~58 MB per chunk (3 workers = ~200 MB total)
- CPU: Moderate (network I/O bound)
- Database: Connection pooling with retry logic

## Deployment Options

### Option 1: Reserved VM (Recommended - $20/month)
- 24/7 worker daemon running
- Flat-rate pricing (0.5 vCPU / 2GB RAM)
- Ideal for continuous background processing
- No timeout limits

### Option 2: Autoscale (Current - Higher cost)
- Worker runs on-demand
- 90-second timeout for background processes
- Requires smaller chunks (`--chunk-size 3`)
- More expensive for 24/7 operation

## Troubleshooting

### Worker not processing jobs
```bash
# Check worker status
python worker.py --status

# Restart worker daemon
pkill -f "worker.py"
python worker.py --daemon --heartbeat-interval 30 --chunk-size 15 --max-workers 3 &
```

### Jobs stuck in queue
```bash
# Check for stuck jobs
python auto_update.py --report

# Reset stuck jobs
psql $DATABASE_URL -c "UPDATE category_processing_jobs SET status = 'pending', worker_id = NULL WHERE status = 'in_progress' AND last_updated < NOW() - INTERVAL '2 hours';"
```

### Database connection errors
```bash
# Test database connection
python -c "import psycopg2; conn = psycopg2.connect('$DATABASE_URL'); print('OK')"

# Check connection pooling
psql $DATABASE_URL -c "SELECT * FROM pg_stat_activity WHERE datname = current_database();"
```

## Production Checklist

Before enabling daily cron job:

- [ ] Worker daemon running: `python worker.py --daemon`
- [ ] Test single category: `python auto_update.py --category piens-olas`
- [ ] Verify report generation: `python auto_update.py --report`
- [ ] Check cron logs: `tail -f /var/log/rimi_daily_update.log`
- [ ] Monitor first full run (queue all categories and watch worker)
- [ ] Verify stuck job detection doesn't produce false positives

## Exit Codes

All commands follow Unix exit code conventions for cron monitoring:

- `0` - Success
- `1` - Failure (stuck/failed jobs, database errors, etc.)

## Support

For issues or questions:
1. Check worker status and logs
2. Review job events table for debugging
3. Check stuck job detection thresholds
4. Verify database connection and schema
