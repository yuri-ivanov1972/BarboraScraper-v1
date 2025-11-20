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
from core_parser import RimiParser


def queue_all_level2_categories(priority: int = 5, skip_recent_days: int = None):
    """
    Queue all level2 categories for processing
    
    Args:
        priority: Job priority (1-10, higher = more urgent)
        skip_recent_days: Skip categories updated within this many days (None = don't skip)
    
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
        
        # Process each category
        for idx, category in enumerate(categories, 1):
            category_code = category['rimi_category_code']
            category_name = category['name_lv']
            existing_products = category['product_count']
            
            print(f"\n[{idx}/{len(categories)}] {category_name} ({category_code})")
            print(f"  Current products in DB: {existing_products}")
            
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
                    continue
            
            # Collect SKUs from category
            print(f"  📥 Collecting products from Rimi...")
            try:
                all_skus = parser.collect_category_skus(category_code)
                
                if not all_skus:
                    print(f"  ⚠️  No products found on Rimi website")
                    continue
                
                print(f"  ✓ Found {len(all_skus)} products on Rimi")
                
                # Create job in queue
                try:
                    cur.execute("""
                        INSERT INTO category_processing_jobs 
                        (category_code, category_id, total_products, processed_count, status, priority, requested_by)
                        VALUES (%s, %s, %s, 0, 'queued', %s, 'auto_update')
                        RETURNING id
                    """, (category_code, category['category_id'], len(all_skus), priority))
                    
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
                    
                    conn.commit()
                    
                    jobs_created += 1
                    print(f"  ✅ Job #{job_id} created ({len(all_skus)} products queued)")
                    
                except psycopg2.IntegrityError as e:
                    conn.rollback()
                    if 'idx_unique_active_category' in str(e):
                        print(f"  ⚠️  Job already queued for this category")
                        jobs_skipped += 1
                    else:
                        raise
                
            except Exception as e:
                print(f"  ❌ Error collecting SKUs: {e}")
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


def main():
    parser = argparse.ArgumentParser(description='Auto-update script for category processing')
    parser.add_argument('--queue-all', action='store_true', help='Queue all level2 categories')
    parser.add_argument('--priority', type=int, default=5, help='Job priority (1-10, default: 5)')
    parser.add_argument('--skip-recent-days', type=int, default=None, help='Skip categories updated within N days')
    parser.add_argument('--status', action='store_true', help='Show queue status')
    
    args = parser.parse_args()
    
    if args.status:
        show_queue_status()
    elif args.queue_all:
        print("🚀 Auto-Update: Queueing all level2 categories")
        print(f"   Priority: {args.priority}")
        if args.skip_recent_days:
            print(f"   Skip recent: {args.skip_recent_days} days")
        print()
        
        jobs_created = queue_all_level2_categories(
            priority=args.priority,
            skip_recent_days=args.skip_recent_days
        )
        
        if jobs_created == 0:
            print("\n⚠️  No jobs were created. All categories may already be queued.")
            print("   Use --status to see queue status")
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
