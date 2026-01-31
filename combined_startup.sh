#!/bin/bash
# Combined Startup Script for Barbora Product Scraper
# Runs Streamlit UI on port 5000

set -e

echo "=========================================="
echo "Barbora Product Scraper - Combined Startup"
echo "=========================================="
echo "Started at: $(date)"
echo ""

mkdir -p logs

echo "Starting lightweight update scheduler in background..."
python -u lightweight_scheduler.py --enable > logs/scheduler.log 2>&1 &
SCHEDULER_PID=$!
echo "Scheduler started (PID: $SCHEDULER_PID)"
echo "Schedule: 2:00 AM Latvia time (Europe/Riga)"
echo ""

echo "Starting Streamlit UI on port 5000 (foreground)..."
exec streamlit run main.py --server.port 5000 --server.address 0.0.0.0
