#!/bin/bash
# Combined Startup Script for Barbora Product Scraper
# Runs Streamlit UI and lightweight update scheduler at 2am Latvia time

set -e

echo "=========================================="
echo "Barbora Product Scraper - Combined Startup"
echo "=========================================="
echo "Started at: $(date)"
echo ""

mkdir -p logs

echo "Starting Streamlit UI on port 5000..."
streamlit run main.py --server.port 5000 > logs/streamlit.log 2>&1 &
STREAMLIT_PID=$!
echo "Streamlit started (PID: $STREAMLIT_PID)"

sleep 5

if kill -0 $STREAMLIT_PID 2>/dev/null; then
    echo "✓ Streamlit is running"
else
    echo "✗ Streamlit failed to start, check logs/streamlit.log"
    exit 1
fi

echo ""
echo "Starting lightweight update scheduler..."
echo "Schedule: 2:00 AM Latvia time (Europe/Riga)"
echo "  - Fast price/availability updates from category listings"
echo "  - New products queued for full scraping"
echo ""

set +e

while true; do
    echo "[$(date)] Starting scheduler with --enable flag..."
    python lightweight_scheduler.py --enable > logs/scheduler.log 2>&1
    EXIT_CODE=$?
    echo "[$(date)] Scheduler exited with code $EXIT_CODE"
    
    if [ $EXIT_CODE -ne 0 ]; then
        echo "Scheduler crashed, restarting in 60s..."
        sleep 60
    fi
done
