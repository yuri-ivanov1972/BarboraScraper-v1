#!/usr/bin/env python3
"""
Auto Update Script - Queue all level2 categories for processing
Queries categories from normalized_categories and creates jobs in the queue
"""
import os
import sys
import argparse
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from core_parser import RimiParser
from update_report import UpdateReport


def queue_all_level2_categories(priority: int = 5, skip_recent_days: int = None, update_mode: str = 'incremental'):
    """
    Queue all level2 categories for processing
    
    Args:
        priority: Job priority (1-10, higher = more urgent)
        skip_recent_days: Skip categories updated within this many days (None = don't skip)
        update_mode: Update mode - 'full' (complete re-scrape) or 'incremental' (new products + price/availability, default)
    
    Returns:
        Number of jobs created
    """
    db_url = os.environ['DATABASE_URL']
    conn = None
    jobs_created = 0
    jobs_skipped = 0
    
    try:
        conn = psycopg2.connect(db_url, cursor_factory=RealDictCursor)
        cur = conn.cursor()
        
        # Get all level2 categories sorted by product count (descending)
        # Note: We'll count products per category by querying the products table
        print("📊 Fetching level2 categories...")
        cur.execute("""
            SELECT 
                nc.category_id,
                nc.rimi_category_code,
                nc.name_lv,
                nc.level,
                COUNT(p.product_id) as product_count
            FROM normalized_categories nc
            LEFT JOIN products p ON nc.category_id = p.category_id
            WHERE nc.level = 2
            GROUP BY nc.category_id, nc.rimi_category_code, nc.name_lv, nc.level
            ORDER BY product_count DESC, nc.name_lv ASC
        """)
        
        categories = cur.fetchall()
        print(f"✓ Found {len(categories)} level2 categories")
        
        # Initialize parser for SKU collection
        def parser_callback(msg):
            print(f"  {msg}")
        
        parser = RimiParser(parser_callback)
        
        # Process each category - isolated transactions for reliability
        for idx, category in enumerate(categories, 1):
            category_code = category['rimi_category_code']
            category_name = category['name_lv']
            existing_products = category['product_count']
            
            print(f"\n[{idx}/{len(categories)}] {category_name} ({category_code})")
            print(f"  Current products in DB: {existing_products}")
            
            # Each category is processed in its own try-catch block to ensure
            # failures in one category don't abort remaining categories
            try:
                # Check if job already exists BEFORE scraping (optimization)
                cur.execute("""
                    SELECT id, status
                    FROM category_processing_jobs
                    WHERE category_code = %s
                    AND status IN ('queued', 'in_progress')
                """, (category_code,))
                
                existing_job = cur.fetchone()
                if existing_job:
                    print(f"  ⏭️  Job already exists (status: {existing_job['status']})")
                    jobs_skipped += 1
                    conn.commit()  # Commit read to release locks
                    continue
                
                # Check if we should skip this category (completed recently)
                if skip_recent_days:
                    cur.execute("""
                        SELECT MAX(last_updated) as last_update
                        FROM category_processing_jobs
                        WHERE category_code = %s
                        AND status = 'completed'
                        AND last_updated > CURRENT_TIMESTAMP - (%s * INTERVAL '1 day')
                    """, (category_code, skip_recent_days))
                    
                    recent_update = cur.fetchone()
                    if recent_update and recent_update['last_update']:
                        print(f"  ⏭️  Skipping (updated {recent_update['last_update']})")
                        jobs_skipped += 1
                        conn.commit()  # Commit read to release locks
                        continue
                
                # Collect SKUs from category (network operation - can fail)
                print(f"  📥 Collecting products from Rimi...")
                all_skus = parser.collect_category_skus(category_code)
                
                if not all_skus:
                    print(f"  ⚠️  No products found on Rimi website")
                    conn.commit()  # Commit to ensure transaction is closed
                    continue
                
                print(f"  ✓ Found {len(all_skus)} products on Rimi")
                
                # Create job in queue
                try:
                    cur.execute("""
                        INSERT INTO category_processing_jobs 
                        (category_code, category_id, total_products, processed_count, status, priority, requested_by, update_mode)
                        VALUES (%s, %s, %s, 0, 'queued', %s, 'auto_update', %s)
                        RETURNING id
                    """, (category_code, category['category_id'], len(all_skus), priority, update_mode))
                    
                    job_id = cur.fetchone()['id']
                    
                    # Log all SKUs as pending
                    for sku in all_skus:
                        cur.execute("""
                            INSERT INTO product_processing_log (job_id, sku, status)
                            VALUES (%s, %s, 'pending')
                        """, (job_id, sku))
                    
                    # Log event
                    cur.execute("""
                        INSERT INTO job_events (job_id, event_type, message)
                        VALUES (%s, 'job_created', %s)
                    """, (job_id, f"Auto-queued {category_name} with {len(all_skus)} products (priority: {priority})"))
                    
                    # CRITICAL: Commit after EACH successful category
                    # This ensures one category failure doesn't abort all remaining categories
                    conn.commit()
                    
                    jobs_created += 1
                    print(f"  ✅ Job #{job_id} created ({len(all_skus)} products queued)")
                    
                except psycopg2.IntegrityError as e:
                    conn.rollback()
                    if 'idx_unique_active_category' in str(e):
                        print(f"  ⚠️  Job already queued for this category")
                        jobs_skipped += 1
                    else:
                        print(f"  ❌ Database integrity error: {e}")
                        # Rollback and continue to next category
                        conn.rollback()
                
            except Exception as e:
                # Category-level exception handler - logs error and continues
                print(f"  ❌ Error processing category: {e}")
                conn.rollback()  # Rollback failed category transaction
                # Continue to next category instead of aborting entire queue run
                continue
        
        # Print summary
        print(f"\n{'='*60}")
        print(f"📊 Summary:")
        print(f"  Total categories: {len(categories)}")
        print(f"  Jobs created: {jobs_created}")
        print(f"  Jobs skipped: {jobs_skipped}")
        print(f"{'='*60}")
        
        if jobs_created > 0:
            print(f"\n✅ {jobs_created} jobs queued successfully!")
            print(f"🔧 Run worker to process: python worker.py --resume-all --chunk-size 15")
        
        return jobs_created
        
    except Exception as e:
        print(f"❌ Error: {e}")
        if conn:
            conn.rollback()
        return 0
    finally:
        if conn:
            conn.close()


def show_queue_status():
    """Show current job queue status"""
    db_url = os.environ['DATABASE_URL']
    conn = None
    
    try:
        conn = psycopg2.connect(db_url, cursor_factory=RealDictCursor)
        cur = conn.cursor()
        
        # Get job statistics
        cur.execute("""
            SELECT 
                status,
                COUNT(*) as count,
                SUM(total_products) as total_products,
                SUM(processed_count) as processed
            FROM category_processing_jobs
            GROUP BY status
            ORDER BY status
        """)
        
        stats = cur.fetchall()
        
        print("\n📊 Job Queue Status:")
        print(f"{'='*60}")
        for stat in stats:
            print(f"  {stat['status']:15} {stat['count']:3} jobs  ({stat['processed'] or 0}/{stat['total_products'] or 0} products)")
        print(f"{'='*60}\n")
        
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if conn:
            conn.close()


def generate_update_report(hours: int = 24, save: bool = True, exit_on_complete: bool = True):
    """
    Generate and display update report for recent period
    
    Args:
        hours: Report time window in hours
        save: Save report to database
        exit_on_complete: If True, call sys.exit() on completion (for CLI use).
                         If False, return status code instead (for scheduler use).
    
    Returns:
        If exit_on_complete=False: returns (success: bool, report: dict or None, message: str)
        If exit_on_complete=True: calls sys.exit() and never returns
    """
    db_url = os.environ['DATABASE_URL']
    
    # Generate report
    reporter = UpdateReport(db_url)
    end_time = datetime.now()
    start_time = end_time - timedelta(hours=hours)
    
    print(f"\n🔍 Generating report for last {hours} hours...")
    report = reporter.generate_update_report(start_time, end_time)
    
    if report:
        reporter.print_report(report)
        
        if save:
            log_id = reporter.save_report_to_database(report, update_type='daily' if hours >= 20 else 'manual')
            if not log_id:
                print("⚠️  Warning: Failed to save report to database")
                if exit_on_complete:
                    sys.exit(1)
                else:
                    return (False, report, "Failed to save report to database")
        
        # Check for stuck jobs or failures
        if report.get('jobs_stuck', 0) > 0:
            print(f"\n⚠️  WARNING: {report['jobs_stuck']} stuck jobs detected!")
            if exit_on_complete:
                sys.exit(1)
            else:
                return (True, report, f"{report['jobs_stuck']} stuck jobs detected")
        
        if report.get('jobs_failed', 0) > 0:
            print(f"\n⚠️  WARNING: {report['jobs_failed']} failed jobs detected!")
            if exit_on_complete:
                sys.exit(1)
            else:
                return (True, report, f"{report['jobs_failed']} failed jobs detected")
        
        if exit_on_complete:
            sys.exit(0)
        else:
            return (True, report, "Report generated successfully")
    else:
        print("❌ Failed to generate report")
        if exit_on_complete:
            sys.exit(1)
        else:
            return (False, None, "Failed to generate report")


def main():
    parser = argparse.ArgumentParser(description='Auto-update script for category processing')
    parser.add_argument('--queue-all', action='store_true', help='Queue all level2 categories')
    parser.add_argument('--priority', type=int, default=5, help='Job priority (1-10, default: 5)')
    parser.add_argument('--skip-recent-days', type=int, default=None, help='Skip categories updated within N days')
    parser.add_argument('--full-update', action='store_true', help='Force full re-scrape (default: incremental)')
    parser.add_argument('--status', action='store_true', help='Show queue status')
    parser.add_argument('--report', action='store_true', help='Generate update report')
    parser.add_argument('--report-hours', type=int, default=24, help='Report time window in hours (default: 24)')
    parser.add_argument('--no-save', action='store_true', help='Do not save report to database')
    
    args = parser.parse_args()
    
    if args.status:
        show_queue_status()
    elif args.report:
        generate_update_report(
            hours=args.report_hours,
            save=not args.no_save
        )
    elif args.queue_all:
        update_mode = 'full' if args.full_update else 'incremental'
        print("🚀 Auto-Update: Queueing all level2 categories")
        print(f"   Priority: {args.priority}")
        print(f"   Update Mode: {update_mode}")
        if args.skip_recent_days:
            print(f"   Skip recent: {args.skip_recent_days} days")
        print()
        
        jobs_created = queue_all_level2_categories(
            priority=args.priority,
            skip_recent_days=args.skip_recent_days,
            update_mode=update_mode
        )
        
        if jobs_created == 0:
            print("\n⚠️  No jobs were created. All categories may already be queued.")
            print("   Use --status to see queue status")
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
