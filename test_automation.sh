#!/bin/bash
# Test script for automated update cycle
# Tests: job queueing → worker processing → report generation

set -e

echo "=========================================="
echo "Testing Automated Update Cycle"
echo "=========================================="
echo ""

# Test 1: Queue status
echo "Test 1: Checking production queue status..."
python auto_update.py --production --status
echo ""

# Test 2: Queue a small test category (if not already queued)
echo "Test 2: Queue test category..."
echo "Note: This will queue ONE random category for testing"
read -p "Press Enter to continue or Ctrl+C to cancel..."
python auto_update.py --production --queue-all --priority 10 --skip-recent-days 0 | head -50
echo ""

# Test 3: Check worker daemon mode (instructions only)
echo "Test 3: Worker Daemon Mode"
echo "To test worker in daemon mode, run in a separate terminal:"
echo ""
echo "  python worker.py --production --daemon --chunk-size 15 --max-workers 3"
echo ""
echo "The worker will:"
echo "  - Connect to production database"
echo "  - Process queued jobs"
echo "  - Keep running and wait for new jobs"
echo "  - Not exit when queue is empty"
echo ""
read -p "Press Enter after starting the worker in another terminal..."
echo ""

# Test 4: Monitor queue progress
echo "Test 4: Monitoring queue progress..."
for i in {1..3}; do
    echo "Check #$i:"
    python auto_update.py --production --status
    echo ""
    sleep 5
done

# Test 5: Generate report
echo "Test 5: Generating update report..."
python auto_update.py --production --report --report-hours 1 --no-save
echo ""

echo "=========================================="
echo "✅ Test Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Review test results above"
echo "2. Check worker logs for any errors"
echo "3. Verify report data looks correct"
echo "4. If all tests pass, you're ready for production!"
echo ""
