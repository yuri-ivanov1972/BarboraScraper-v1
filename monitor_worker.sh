#!/bin/bash
# Worker Health Monitoring Script
# Checks worker status, queue health, and recent statistics

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "========================================"
echo "Rimi Scraper - Worker Health Monitor"
echo "========================================"
echo "Timestamp: $(date)"
echo "========================================"
echo ""

echo "📊 JOB QUEUE STATUS"
echo "----------------------------------------"
python -c "
import os, psycopg2
from psycopg2.extras import RealDictCursor

db_url = os.environ['DATABASE_URL']
conn = psycopg2.connect(db_url, cursor_factory=RealDictCursor)
cur = conn.cursor()

# Queue summary
cur.execute('''
    SELECT 
        status,
        COUNT(*) as jobs,
        SUM(total_products) as products,
        SUM(processed_count) as processed
    FROM category_processing_jobs
    GROUP BY status
    ORDER BY 
        CASE status 
            WHEN 'in_progress' THEN 1
            WHEN 'queued' THEN 2
            WHEN 'completed' THEN 3
            ELSE 4
        END
''')

results = cur.fetchall()
for row in results:
    print(f\"  {row['status']:15} {row['jobs']:3} jobs  ({row['processed'] or 0}/{row['products'] or 0} products)\")

conn.close()
"
echo ""

echo "👷 ACTIVE WORKERS"
echo "----------------------------------------"
python -c "
import os, psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

db_url = os.environ['DATABASE_URL']
conn = psycopg2.connect(db_url, cursor_factory=RealDictCursor)
cur = conn.cursor()

cur.execute('''
    SELECT 
        worker_id,
        hostname,
        status,
        current_job_id,
        last_heartbeat
    FROM processing_workers
    WHERE status != 'stopped'
    ORDER BY last_heartbeat DESC
''')

workers = cur.fetchall()
if workers:
    for w in workers:
        age = (datetime.now() - w['last_heartbeat']).total_seconds() if w['last_heartbeat'] else 'N/A'
        print(f\"  Worker: {w['worker_id'][:20]}...\")
        print(f\"    Status: {w['status']}, Job: {w['current_job_id']}, Last heartbeat: {age:.0f}s ago\")
else:
    print('  No active workers')

conn.close()
"
echo ""

echo "📈 RECENT UPDATE STATISTICS (Last 5)"
echo "----------------------------------------"
python -c "
import os, psycopg2
from psycopg2.extras import RealDictCursor

db_url = os.environ['DATABASE_URL']
conn = psycopg2.connect(db_url, cursor_factory=RealDictCursor)
cur = conn.cursor()

cur.execute('''
    SELECT 
        us.category_code,
        us.total_checked,
        us.new_products,
        us.price_changed,
        us.unchanged,
        us.created_at::date as date
    FROM update_statistics us
    JOIN category_processing_jobs j ON us.job_id = j.id
    ORDER BY us.created_at DESC
    LIMIT 5
''')

stats = cur.fetchall()
if stats:
    for s in stats:
        print(f\"  {s['category_code']:15} {s['date']}  New:{s['new_products']:3}  Price∆:{s['price_changed']:3}  Same:{s['unchanged']:3}\")
else:
    print('  No statistics available')

conn.close()
"
echo ""

echo "⚠️  STALE JOBS (heartbeat >5min old)"
echo "----------------------------------------"
python -c "
import os, psycopg2
from psycopg2.extras import RealDictCursor

db_url = os.environ['DATABASE_URL']
conn = psycopg2.connect(db_url, cursor_factory=RealDictCursor)
cur = conn.cursor()

cur.execute('''
    SELECT 
        id,
        category_code,
        processed_count,
        total_products,
        last_heartbeat
    FROM category_processing_jobs
    WHERE status = 'in_progress'
    AND last_heartbeat < NOW() - INTERVAL '5 minutes'
''')

stale = cur.fetchall()
if stale:
    for job in stale:
        print(f\"  Job #{job['id']:3} {job['category_code']:15} {job['processed_count']}/{job['total_products']}  (stale: {job['last_heartbeat']})\")
else:
    print('  No stale jobs')

conn.close()
"
echo ""

echo "💾 DISK USAGE"
echo "----------------------------------------"
du -sh logs/ 2>/dev/null && echo "  Log directory: $(du -sh logs/ | cut -f1)" || echo "  No logs directory"
echo ""

echo "📝 RECENT LOGS"
echo "----------------------------------------"
if [ -d "logs" ]; then
    echo "  Latest worker log:"
    LATEST_LOG=$(ls -t logs/worker_*.log 2>/dev/null | head -1)
    if [ -n "$LATEST_LOG" ]; then
        echo "    $LATEST_LOG ($(wc -l < "$LATEST_LOG") lines)"
        echo "  Last 3 lines:"
        tail -3 "$LATEST_LOG" | sed 's/^/    /'
    else
        echo "    No worker logs found"
    fi
    echo ""
    echo "  Latest auto-update log:"
    LATEST_AUTO=$(ls -t logs/auto_update_*.log 2>/dev/null | head -1)
    if [ -n "$LATEST_AUTO" ]; then
        echo "    $LATEST_AUTO ($(wc -l < "$LATEST_AUTO") lines)"
    else
        echo "    No auto-update logs found"
    fi
else
    echo "  No logs directory"
fi
echo ""

echo "========================================"
echo "Monitor completed at: $(date)"
echo "========================================"
