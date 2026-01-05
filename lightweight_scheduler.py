#!/usr/bin/env python3
"""
Lightweight Update Scheduler - Runs daily at 2am Latvia time
Designed to run on Reserved VM alongside the worker process.

Usage:
    python lightweight_scheduler.py                    # Run scheduler loop (checks every minute)
    python lightweight_scheduler.py --run-now          # Run update immediately (for testing)
    python lightweight_scheduler.py --dry-run          # Show what would be done
    
Schedule: 2:00 AM Europe/Riga (Latvia time)
"""

import os
import time
import argparse
from datetime import datetime
import pytz

ENABLED = False
SCHEDULE_HOUR = 2
SCHEDULE_MINUTE = 0
TIMEZONE = 'Europe/Riga'


def get_latvia_time():
    """Get current time in Latvia"""
    tz = pytz.timezone(TIMEZONE)
    return datetime.now(tz)


def is_scheduled_time():
    """Check if it's time to run the update"""
    now = get_latvia_time()
    return now.hour == SCHEDULE_HOUR and now.minute == SCHEDULE_MINUTE


def run_lightweight_update():
    """Execute the lightweight update"""
    from barbora_lightweight_updater import BarboraLightweightUpdater
    
    def log_status(msg):
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")
    
    def progress(current, total, name):
        if current % 10 == 0 or current == total:
            print(f"  [{current}/{total}] {name}")
    
    log_status("Starting scheduled lightweight update...")
    
    updater = BarboraLightweightUpdater(status_callback=log_status)
    summary = updater.run_full_update(progress_callback=progress)
    
    log_status("Update completed!")
    log_status(f"  Categories: {summary.get('categories_processed', 0)}")
    log_status(f"  Products checked: {summary.get('products_checked', 0)}")
    log_status(f"  Products updated: {summary.get('products_updated', 0)}")
    log_status(f"  Price changes: {summary.get('price_changes', 0)}")
    log_status(f"  Availability changes: {summary.get('availability_changes', 0)}")
    log_status(f"  New products found: {summary.get('new_products_found', 0)}")
    log_status(f"  Duration: {summary.get('duration_seconds', 0):.1f}s")
    
    try:
        run_id = updater.save_run_history(summary)
        log_status(f"  Saved to history (run_id: {run_id})")
    except Exception as e:
        log_status(f"  Warning: Could not save to history: {e}")
    
    new_products = summary.get('new_products_found', 0)
    if new_products > 0:
        log_status(f"Processing {new_products} new products with worker...")
        try:
            from barbora_worker import BarboraWorker
            worker = BarboraWorker()
            worker.run(exit_when_empty=True)
            log_status("Worker finished processing new products")
        except Exception as e:
            log_status(f"Warning: Worker failed: {e}")
    
    return summary


def scheduler_loop(enabled_override=False):
    """Main scheduler loop - runs indefinitely, checking every minute"""
    is_enabled = ENABLED or enabled_override
    
    print(f"Lightweight Update Scheduler started")
    print(f"  Schedule: {SCHEDULE_HOUR:02d}:{SCHEDULE_MINUTE:02d} {TIMEZONE}")
    print(f"  Enabled: {is_enabled}")
    print(f"  Press Ctrl+C to stop")
    print()
    
    last_run_date = None
    
    while True:
        now = get_latvia_time()
        today = now.date()
        
        if is_enabled and is_scheduled_time() and last_run_date != today:
            print(f"\n{'='*60}")
            print(f"Scheduled run triggered at {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            print(f"{'='*60}\n")
            
            try:
                run_lightweight_update()
                last_run_date = today
            except Exception as e:
                print(f"ERROR: Update failed: {e}")
                import traceback
                traceback.print_exc()
            
            print(f"\n{'='*60}")
            print(f"Next run: tomorrow at {SCHEDULE_HOUR:02d}:{SCHEDULE_MINUTE:02d} {TIMEZONE}")
            print(f"{'='*60}\n")
        
        time.sleep(60)


def main():
    parser = argparse.ArgumentParser(description="Lightweight Update Scheduler")
    parser.add_argument('--run-now', action='store_true', help="Run update immediately")
    parser.add_argument('--dry-run', action='store_true', help="Show what would be done")
    parser.add_argument('--enable', action='store_true', help="Enable scheduler (overrides ENABLED flag)")
    args = parser.parse_args()
    
    if args.dry_run:
        from barbora_lightweight_updater import BarboraLightweightUpdater
        updater = BarboraLightweightUpdater()
        categories = updater.get_all_level3_categories()
        existing = updater.get_existing_skus()
        
        print(f"Dry run summary:")
        print(f"  Scheduler enabled: {ENABLED}")
        print(f"  Schedule: {SCHEDULE_HOUR:02d}:{SCHEDULE_MINUTE:02d} {TIMEZONE}")
        print(f"  Current time: {get_latvia_time().strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(f"  Categories to process: {len(categories)}")
        print(f"  Existing products in DB: {len(existing)}")
        return
    
    if args.run_now:
        run_lightweight_update()
        return
    
    scheduler_loop(enabled_override=args.enable)


if __name__ == "__main__":
    main()
