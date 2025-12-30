#!/usr/bin/env python3
"""
Worker with Built-in Scheduler for Reserved VM
Combines background job processing with scheduled daily updates.

Features:
- Processes queued jobs continuously
- Queues all categories daily at 2:00 AM Latvia time
- Generates reports at 6:00 AM Latvia time
- Runs both worker and scheduler in single process
"""

import os
import sys
import time
import signal
import socket
import logging
import argparse
import threading
from datetime import datetime
import pytz

# Set production mode from args before imports
if '--production' in sys.argv:
    os.environ['ENVIRONMENT'] = 'production'

from worker import ProcessingWorker
from auto_update import queue_all_level2_categories, generate_update_report

# Create logs directory
os.makedirs('logs', exist_ok=True)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f'logs/worker_scheduler_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    ]
)
logger = logging.getLogger(__name__)

# Latvia timezone
LATVIA_TZ = pytz.timezone('Europe/Riga')


class SchedulerThread(threading.Thread):
    """Background thread that runs scheduled tasks"""
    
    def __init__(self, use_production: bool = False):
        super().__init__(daemon=True)
        self.use_production = use_production
        self.running = True
        self.last_queue_date = None
        self.last_report_date = None
        self.last_heartbeat_hour = None
        self.start_time = datetime.now(LATVIA_TZ)
        
    def stop(self):
        self.running = False
    
    def run(self):
        """Run scheduler loop - checks every minute for scheduled tasks"""
        logger.info("Scheduler thread started")
        logger.info("  - Daily queue at 02:00 Latvia time")
        logger.info("  - Daily report at 06:00 Latvia time")
        logger.info("  - Hourly heartbeat logging enabled")
        
        while self.running:
            try:
                now_latvia = datetime.now(LATVIA_TZ)
                current_date = now_latvia.date()
                current_hour = now_latvia.hour
                current_minute = now_latvia.minute
                
                # Hourly heartbeat logging
                if self.last_heartbeat_hour != current_hour:
                    uptime = now_latvia - self.start_time
                    uptime_hours = int(uptime.total_seconds() // 3600)
                    uptime_minutes = int((uptime.total_seconds() % 3600) // 60)
                    logger.info(f"💓 Scheduler heartbeat - {now_latvia.strftime('%Y-%m-%d %H:%M')} Latvia time (uptime: {uptime_hours}h {uptime_minutes}m)")
                    self.last_heartbeat_hour = current_hour
                
                # 2:00 AM - Queue all categories
                if current_hour == 2 and current_minute < 5:
                    if self.last_queue_date != current_date:
                        self._queue_all_categories()
                        self.last_queue_date = current_date
                
                # 6:00 AM - Generate daily report
                if current_hour == 6 and current_minute < 5:
                    if self.last_report_date != current_date:
                        self._generate_daily_report()
                        self.last_report_date = current_date
                
                # Sleep for 1 minute before next check
                time.sleep(60)
                
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                time.sleep(60)
    
    def _queue_all_categories(self):
        """Queue all level2 categories for processing"""
        logger.info("=" * 60)
        logger.info("SCHEDULED: Queueing all categories for daily update (02:00)")
        logger.info("=" * 60)
        
        try:
            queue_all_level2_categories(
                priority=10,
                use_production=self.use_production,
                update_mode='incremental'
            )
            logger.info("Successfully queued all categories")
        except Exception as e:
            logger.error(f"Failed to queue categories: {e}")
    
    def _generate_daily_report(self):
        """Generate daily update report"""
        logger.info("=" * 60)
        logger.info("SCHEDULED: Generating daily report (06:00)")
        logger.info("=" * 60)
        
        try:
            generate_update_report(hours=12, use_production=self.use_production)
            logger.info("Successfully generated daily report")
        except Exception as e:
            logger.error(f"Failed to generate report: {e}")


def main():
    parser = argparse.ArgumentParser(description='Worker with built-in scheduler for Reserved VM')
    parser.add_argument('--production', action='store_true', help='Use production database')
    parser.add_argument('--chunk-size', type=int, default=15, help='Products per processing chunk')
    parser.add_argument('--max-workers', type=int, default=3, help='Max concurrent workers per chunk')
    parser.add_argument('--heartbeat-interval', type=int, default=30, help='Heartbeat interval in seconds')
    
    args = parser.parse_args()
    
    use_production = args.production
    
    logger.info("=" * 60)
    logger.info("Rimi Product Scraper - Worker with Scheduler")
    logger.info("=" * 60)
    if use_production:
        logger.info("MODE: PRODUCTION")
    else:
        logger.info("MODE: DEVELOPMENT")
    logger.info(f"Current Latvia time: {datetime.now(LATVIA_TZ).strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("")
    
    # Start scheduler thread
    scheduler = SchedulerThread(use_production=use_production)
    scheduler.start()
    logger.info("Scheduler thread started in background")
    
    # Generate worker ID
    worker_id = f"sched_{socket.gethostname()}_{os.getpid()}_{int(time.time())}"
    
    # Create and run worker in continuous/daemon mode
    logger.info(f"Starting worker: {worker_id}")
    logger.info(f"  Chunk size: {args.chunk_size}")
    logger.info(f"  Max workers: {args.max_workers}")
    logger.info(f"  Heartbeat: {args.heartbeat_interval}s")
    
    worker = ProcessingWorker(
        worker_id=worker_id,
        heartbeat_interval=args.heartbeat_interval,
        chunk_size=args.chunk_size,
        max_workers=args.max_workers,
        use_production=use_production
    )
    
    try:
        # Run worker in continuous mode (daemon-like, keeps running)
        worker.run(mode='continuous')
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    finally:
        scheduler.stop()
        logger.info("Scheduler stopped")
        logger.info("Worker with scheduler shutdown complete")


if __name__ == '__main__':
    main()
