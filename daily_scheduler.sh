#!/bin/bash
# Daily Scheduler for Auto-Update
# Runs auto_update.py daily at 2am Latvia time (EET/EEST UTC+2/+3)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
AUTO_UPDATE_LOG="$LOG_DIR/auto_update_$(date +%Y%m%d).log"

mkdir -p "$LOG_DIR"

echo "========================================"
echo "Daily Auto-Update Scheduler"
echo "========================================"
echo "Started at: $(date)"
echo "Timezone: $(date +%Z)"
echo "Log file: $AUTO_UPDATE_LOG"
echo "========================================"

cd "$SCRIPT_DIR"

{
    echo ""
    echo "========================================" 
    echo "Auto-Update Started: $(date)"
    echo "========================================"
    echo ""
    
    python auto_update.py --queue-all --priority 5
    
    exit_code=$?
    
    echo ""
    echo "========================================"
    echo "Auto-Update Finished: $(date)"
    echo "Exit code: $exit_code"
    echo "========================================"
    echo ""
    
    exit $exit_code
    
} 2>&1 | tee -a "$AUTO_UPDATE_LOG"
