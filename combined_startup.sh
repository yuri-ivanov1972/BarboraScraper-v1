#!/bin/bash
# Combined Startup Script for Reserved VM
# Runs both Streamlit UI and background worker

set -e

echo "=========================================="
echo "Rimi Product Scraper - Combined Startup"
echo "=========================================="
echo "Started at: $(date)"
echo ""

# Create logs directory
mkdir -p logs

# Start Streamlit in background
echo "Starting Streamlit UI on port 5000..."
streamlit run main.py --server.port 5000 > logs/streamlit.log 2>&1 &
STREAMLIT_PID=$!
echo "Streamlit started (PID: $STREAMLIT_PID)"

# Wait for Streamlit to initialize
sleep 5

# Check if Streamlit is running
if kill -0 $STREAMLIT_PID 2>/dev/null; then
    echo "✓ Streamlit is running"
else
    echo "✗ Streamlit failed to start, check logs/streamlit.log"
    exit 1
fi

echo ""
echo "Starting worker with built-in scheduler..."
echo "Worker will:"
echo "  - Process any queued jobs immediately"
echo "  - Queue all categories daily at 2:00 AM Latvia time"
echo "  - Generate reports at 6:00 AM Latvia time"
echo ""

# Run the worker with scheduler
# The worker runs in foreground so the container stays alive
python worker_with_scheduler.py --production --chunk-size 15 --max-workers 3 --heartbeat-interval 30

# If worker exits, log it
echo "Worker exited at: $(date)"
