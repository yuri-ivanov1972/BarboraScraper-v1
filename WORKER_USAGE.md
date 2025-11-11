# Worker System Usage Guide

## Overview
The standalone worker system processes Rimi product categories in the background, independent of Streamlit sessions. This solves the SessionInfo crash issue and enables reliable overnight processing of 9000+ products.

## Quick Start

### 1. Queue a Job (via Streamlit UI)
1. Open the Streamlit app
2. Go to "Category Processing" section
3. Enter category code (e.g., `SH-11-9-26`)
4. Set priority (1-10, higher = more urgent)
5. Click "Queue Job"

### 2. Run the Worker

**Process all queued jobs:**
```bash
python worker.py --resume-all --heartbeat-interval 30 --chunk-size 15
```

**Process specific category:**
```bash
python worker.py --category SH-11-9-26 --priority 10
```

**Process multiple categories:**
```bash
python worker.py --categories SH-11-9-26,SH-11-6-19 --chunk-size 20
```

## Command Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--category` | Process single category code | None |
| `--categories` | Process multiple categories (comma-separated) | None |
| `--resume-all` | Resume all incomplete jobs in queue | False |
| `--priority` | Job priority (1-10, higher = more urgent) | 5 |
| `--chunk-size` | Products per chunk | 15 |
| `--heartbeat-interval` | Heartbeat update interval (seconds) | 30 |
| `--log-dir` | Log file directory | `logs/` |
| `--worker-id` | Custom worker ID | Auto-generated |

## Architecture

### Job States
- **queued**: Job waiting to be processed
- **in_progress**: Worker actively processing
- **completed**: All products processed successfully
- **failed**: Job exceeded max retry attempts

### Worker Lifecycle
1. **Registration**: Worker registers in `processing_workers` table with hostname, PID
2. **Job Acquisition**: Uses `SELECT FOR UPDATE SKIP LOCKED` to grab next job
3. **Heartbeat**: Updates every chunk to signal it's alive
4. **Processing**: Processes products in chunks using `BatchProcessor`
5. **Completion**: Marks job complete or queues for retry on failure
6. **Shutdown**: Graceful shutdown via SIGTERM/SIGINT signals

### Fault Tolerance
- **Stale Job Detection**: Jobs with heartbeat older than `2 × heartbeat_interval` are reassigned
- **Retry Logic**: Failed jobs retry up to `max_retries` times
- **Event Logging**: All job lifecycle events logged to `job_events` table

## Monitoring

### Check Job Status
```sql
SELECT id, category_code, status, processed_count, total_products, current_worker_id
FROM category_processing_jobs
WHERE status IN ('queued', 'in_progress')
ORDER BY priority DESC, scheduled_for ASC;
```

### Check Worker Status
```sql
SELECT worker_id, hostname, status, current_job_id, last_heartbeat
FROM processing_workers
WHERE status != 'stopped'
ORDER BY last_heartbeat DESC;
```

### View Job Events
```sql
SELECT job_id, event_type, message, created_at
FROM job_events
WHERE job_id = 4
ORDER BY created_at DESC;
```

### View Processing Progress
```sql
SELECT 
    status,
    COUNT(*) as count
FROM product_processing_log
WHERE job_id = 4
GROUP BY status;
```

## Log Files
Worker logs are saved to: `logs/worker_{worker_id}_{timestamp}.log`

Example:
```
logs/worker_hostname_1234_20251111_171947.log
```

## Overnight Processing Example

**Recommended command for overnight runs:**
```bash
nohup python worker.py --resume-all --heartbeat-interval 30 --chunk-size 15 > worker_overnight.log 2>&1 &
```

**Monitor progress:**
```bash
# View live logs
tail -f logs/worker_*.log

# Check job status
psql $DATABASE_URL -c "SELECT category_code, status, processed_count, total_products FROM category_processing_jobs ORDER BY id DESC LIMIT 10;"
```

**Stop worker gracefully:**
```bash
# Find worker PID
ps aux | grep worker.py

# Send SIGTERM for graceful shutdown
kill -TERM <PID>
```

## Database Schema

### Tables
- `category_processing_jobs`: Job queue with status, priority, heartbeat
- `processing_workers`: Worker registration and heartbeat tracking
- `job_events`: Job lifecycle event log
- `product_processing_log`: Per-product processing status

### Key Constraints
- Unique constraint on `(category_code, status)` prevents duplicate queued jobs
- Foreign key from `job_events.job_id` to `category_processing_jobs.id`
- Foreign key from `processing_workers.current_job_id` to `category_processing_jobs.id`

## Troubleshooting

### Worker not picking up jobs
1. Check job is in 'queued' status
2. Verify `scheduled_for` is not in the future
3. Check `retry_count < max_retries`

### Stale jobs
Jobs stuck in 'in_progress' will be reassigned after `2 × heartbeat_interval` seconds.

### Worker crashes
- Check log files in `logs/` directory
- Review `job_events` table for error messages
- Failed jobs will retry up to `max_retries` times

### BrokenPipe errors
Some products may fail with "Broken pipe" errors during processing. These are logged and counted as failures. The worker continues processing remaining products.

## Best Practices

1. **Chunk Size**: Use 10-20 for balance between progress tracking and performance
2. **Heartbeat Interval**: 30 seconds recommended for overnight runs
3. **Priority**: Reserve 8-10 for urgent jobs, use 5 for normal processing
4. **Monitoring**: Check logs periodically during long runs
5. **Recovery**: Use `--resume-all` to continue after interruptions
