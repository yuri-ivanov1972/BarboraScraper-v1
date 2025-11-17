#!/bin/bash
# Worker Startup Script for Reserved VM Deployment
# This script runs the worker in a loop with automatic restart on failure

set -e

WORKER_LOG_DIR="logs"
HEARTBEAT_INTERVAL=30
CHUNK_SIZE=15
MAX_RESTART_ATTEMPTS=5
RESTART_DELAY=10

mkdir -p "$WORKER_LOG_DIR"

echo "========================================"
echo "Rimi Product Scraper - Worker Startup"
echo "========================================"
echo "Starting at: $(date)"
echo "Log directory: $WORKER_LOG_DIR"
echo "Heartbeat interval: ${HEARTBEAT_INTERVAL}s"
echo "Chunk size: $CHUNK_SIZE products"
echo "========================================"

restart_count=0

while true; do
    echo ""
    echo "[$(date)] Starting worker (attempt $((restart_count + 1))/$MAX_RESTART_ATTEMPTS)..."
    
    if python worker.py --resume-all --heartbeat-interval $HEARTBEAT_INTERVAL --chunk-size $CHUNK_SIZE; then
        echo "[$(date)] Worker completed successfully"
        restart_count=0
        
        echo "[$(date)] Waiting ${RESTART_DELAY}s before checking for new jobs..."
        sleep $RESTART_DELAY
    else
        exit_code=$?
        restart_count=$((restart_count + 1))
        
        echo "[$(date)] ERROR: Worker exited with code $exit_code"
        
        if [ $restart_count -ge $MAX_RESTART_ATTEMPTS ]; then
            echo "[$(date)] FATAL: Maximum restart attempts ($MAX_RESTART_ATTEMPTS) reached"
            echo "[$(date)] Worker stopped. Manual intervention required."
            exit 1
        fi
        
        echo "[$(date)] Restarting in ${RESTART_DELAY}s..."
        sleep $RESTART_DELAY
    fi
done
