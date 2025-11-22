#!/bin/bash
# Cron Setup Script for Daily Automated Updates
# Sets up cron jobs to run at 2am Latvia time (Europe/Riga timezone)
# Avoids Rimi's midnight maintenance window

set -e

echo "=========================================="
echo "Rimi Product Scraper - Cron Setup"
echo "=========================================="
echo ""

# Configuration
PROJECT_DIR="/home/runner/$(basename $(pwd))"
CRON_LOG_DIR="/home/runner/$(basename $(pwd))/logs/cron"
TIMEZONE="Europe/Riga"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Configuration:${NC}"
echo "  Project Directory: $PROJECT_DIR"
echo "  Cron Log Directory: $CRON_LOG_DIR"
echo "  Timezone: $TIMEZONE"
echo ""

# Create cron log directory
mkdir -p "$CRON_LOG_DIR"
echo -e "${GREEN}✓${NC} Created cron log directory: $CRON_LOG_DIR"

# Define cron jobs
CRON_JOBS=$(cat <<'CRONEOF'
# Rimi Product Scraper - Daily Automated Updates
# Runs at 2:00 AM Latvia time (Europe/Riga)
# Avoids Rimi's midnight maintenance window

# Set timezone for cron jobs
TZ=Europe/Riga

# Daily Update - Queue all categories at 2:00 AM
0 2 * * * cd PROJECT_DIR && /home/runner/.nix-profile/bin/python3 auto_update.py --production --queue-all --priority 10 >> CRON_LOG_DIR/daily_queue_$(date +\%Y\%m\%d).log 2>&1

# Daily Report - Generate report at 6:00 AM (after updates complete)
0 6 * * * cd PROJECT_DIR && /home/runner/.nix-profile/bin/python3 auto_update.py --production --report --report-hours 12 >> CRON_LOG_DIR/daily_report_$(date +\%Y\%m\%d).log 2>&1

# Weekly cleanup - Remove old logs (keep last 30 days)
0 3 * * 0 find CRON_LOG_DIR -name "*.log" -mtime +30 -delete >> CRON_LOG_DIR/cleanup.log 2>&1
CRONEOF
)

# Replace placeholders
CRON_JOBS="${CRON_JOBS//PROJECT_DIR/$PROJECT_DIR}"
CRON_JOBS="${CRON_JOBS//CRON_LOG_DIR/$CRON_LOG_DIR}"

echo ""
echo -e "${YELLOW}Cron Jobs to be installed:${NC}"
echo "----------------------------------------"
echo "$CRON_JOBS"
echo "----------------------------------------"
echo ""

# Check if running in interactive mode
if [ -t 0 ]; then
    read -p "Install these cron jobs? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Installation cancelled."
        exit 1
    fi
fi

# Install cron jobs
echo ""
echo "Installing cron jobs..."

# Get current crontab (ignore errors if no crontab exists)
CURRENT_CRON=$(crontab -l 2>/dev/null || echo "")

# Remove old Rimi scraper cron jobs if they exist
FILTERED_CRON=$(echo "$CURRENT_CRON" | grep -v "Rimi Product Scraper" || true)

# Combine filtered cron with new jobs
NEW_CRON=$(cat <<EOF
$FILTERED_CRON

$CRON_JOBS
EOF
)

# Install new crontab
echo "$NEW_CRON" | crontab -

echo -e "${GREEN}✓${NC} Cron jobs installed successfully!"
echo ""

# Display installed crontab
echo -e "${YELLOW}Installed crontab:${NC}"
echo "----------------------------------------"
crontab -l
echo "----------------------------------------"
echo ""

# Setup instructions for worker daemon
echo -e "${YELLOW}Worker Daemon Setup:${NC}"
echo "To run the worker in daemon mode on Reserved VM, use:"
echo ""
echo "  nohup python worker.py --production --daemon --chunk-size 15 --max-workers 3 --heartbeat-interval 30 > logs/worker_daemon.log 2>&1 &"
echo ""
echo "This will:"
echo "  - Run the worker in background (daemon mode)"
echo "  - Process production database"
echo "  - Keep running and wait for new jobs (24/7)"
echo "  - Automatically pick up jobs queued by cron at 2am"
echo ""

# Verify cron service
echo -e "${YELLOW}Verifying cron service:${NC}"
if command -v systemctl &> /dev/null; then
    systemctl status cron 2>/dev/null || systemctl status crond 2>/dev/null || echo "Note: Unable to check cron service status"
else
    echo "Note: systemctl not available, assuming cron is running"
fi

echo ""
echo -e "${GREEN}=========================================="
echo "Setup Complete!"
echo "==========================================${NC}"
echo ""
echo "Next steps:"
echo "1. Start worker in daemon mode (see command above)"
echo "2. Monitor logs in: $CRON_LOG_DIR"
echo "3. Check worker logs in: logs/worker_daemon.log"
echo ""
echo "Daily update schedule:"
echo "  2:00 AM - Queue all categories for update"
echo "  2:01 AM - Worker automatically picks up jobs"
echo "  6:00 AM - Generate and save daily report"
echo ""
echo "Useful commands:"
echo "  crontab -l                                  # View installed cron jobs"
echo "  crontab -e                                  # Edit cron jobs"
echo "  tail -f $CRON_LOG_DIR/daily_queue_*.log     # Monitor queue logs"
echo "  tail -f logs/worker_daemon.log              # Monitor worker logs"
echo "  python auto_update.py --production --status # Check job queue status"
echo "  python auto_update.py --production --report # Generate manual report"
echo ""
