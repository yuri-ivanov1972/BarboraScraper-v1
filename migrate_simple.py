#!/usr/bin/env python3
"""
Simplified Database Migration Script: Development → Production

This version works without superuser privileges and is optimized for
migrating to an EMPTY production database.

Usage:
    export PROD_DATABASE_URL='your_production_connection_string'
    python migrate_simple.py

Environment Variables Required:
    DATABASE_URL - Development database connection string (automatically set)
    PROD_DATABASE_URL - Production database connection string (must be set manually)

Tables migrated (in correct dependency order):
    1. normalized_categories
    2. ingredient_analysis
    3. products
    4. category_processing_jobs (parent of processing_workers)
    5. processing_workers (child of category_processing_jobs)
    6. nutritionfacts, productphotos, product_price_history
    7. job_events, product_processing_log, update_statistics
    8. ingredient_product_mapping
"""

import os
import sys
import psycopg2
from psycopg2.extras import execute_batch
from typing import Tuple, Any
import time

# ANSI color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def print_header(msg: str):
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{msg.center(60)}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.ENDC}\n")

def print_success(msg: str):
    print(f"{Colors.OKGREEN}✓ {msg}{Colors.ENDC}")

def print_info(msg: str):
    print(f"{Colors.OKCYAN}ℹ {msg}{Colors.ENDC}")

def print_warning(msg: str):
    print(f"{Colors.WARNING}⚠ {msg}{Colors.ENDC}")

def print_error(msg: str):
    print(f"{Colors.FAIL}✗ {msg}{Colors.ENDC}")

def get_database_connections() -> Tuple[Any, Any]:
    """Establish connections to both development and production databases."""
    dev_url = os.environ.get('DATABASE_URL')
    prod_url = os.environ.get('PROD_DATABASE_URL')
    
    if not dev_url:
        print_error("DATABASE_URL environment variable not set")
        sys.exit(1)
    
    if not prod_url:
        print_error("PROD_DATABASE_URL environment variable not set")
        print_info("Set it with: export PROD_DATABASE_URL='your_production_connection_string'")
        sys.exit(1)
    
    print_info(f"Connecting to development database...")
    try:
        dev_conn = psycopg2.connect(dev_url)
        print_success("Connected to development database")
    except Exception as e:
        print_error(f"Failed to connect to development database: {e}")
        sys.exit(1)
    
    print_info(f"Connecting to production database...")
    try:
        prod_conn = psycopg2.connect(prod_url)
        print_success("Connected to production database")
    except Exception as e:
        print_error(f"Failed to connect to production database: {e}")
        dev_conn.close()
        sys.exit(1)
    
    return dev_conn, prod_conn

def count_records(conn: Any, table_name: str) -> int:
    """Count records in a table."""
    cursor = conn.cursor()
    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    count = cursor.fetchone()[0]
    cursor.close()
    return count

def migrate_table(dev_conn: Any, prod_conn: Any, table_name: str, 
                  batch_size: int = 1000) -> Tuple[int, int]:
    """
    Migrate all data from a table in dev to prod.
    Assumes production table is EMPTY (no truncation needed).
    
    Returns:
        Tuple of (source_count, inserted_count)
    """
    print_info(f"Migrating table: {table_name}")
    
    # Count source records
    source_count = count_records(dev_conn, table_name)
    print_info(f"  Source records: {source_count}")
    
    if source_count == 0:
        print_warning(f"  No records to migrate from {table_name}")
        return 0, 0
    
    # Get column names
    dev_cursor = dev_conn.cursor()
    dev_cursor.execute(f"""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = '{table_name}' 
        ORDER BY ordinal_position
    """)
    columns = [row[0] for row in dev_cursor.fetchall()]
    column_list = ', '.join(columns)
    placeholders = ', '.join(['%s'] * len(columns))
    
    # Read all data from source
    dev_cursor.execute(f"SELECT {column_list} FROM {table_name}")
    all_rows = dev_cursor.fetchall()
    dev_cursor.close()
    
    # Insert in batches to destination
    prod_cursor = prod_conn.cursor()
    insert_query = f"INSERT INTO {table_name} ({column_list}) VALUES ({placeholders})"
    
    inserted = 0
    for i in range(0, len(all_rows), batch_size):
        batch = all_rows[i:i + batch_size]
        execute_batch(prod_cursor, insert_query, batch)
        inserted += len(batch)
        print_info(f"  Inserted {inserted}/{source_count} records...")
    
    prod_conn.commit()
    prod_cursor.close()
    
    # Verify destination count
    dest_count = count_records(prod_conn, table_name)
    
    if dest_count == source_count:
        print_success(f"  ✓ Migration complete: {dest_count} records")
    else:
        print_warning(f"  Record count mismatch: source={source_count}, dest={dest_count}")
    
    return source_count, dest_count

def reset_sequences(prod_conn: Any):
    """Reset PostgreSQL sequences for tables with serial/auto-increment columns."""
    print_info("Resetting sequences for auto-increment columns...")
    
    cursor = prod_conn.cursor()
    
    sequence_mappings = {
        'category_processing_jobs': ('category_processing_jobs_id_seq', 'id'),
        'ingredient_analysis': ('ingredient_analysis_id_seq', 'id'),
        'job_events': ('job_events_id_seq', 'id'),
        'nutritionfacts': ('nutritionfacts_nutrition_id_seq', 'nutrition_id'),
        'processing_workers': ('processing_workers_id_seq', 'id'),
        'product_price_history': ('product_price_history_price_history_id_seq', 'price_history_id'),
        'product_processing_log': ('product_processing_log_id_seq', 'id'),
        'productphotos': ('productphotos_photo_id_seq', 'photo_id'),
        'products': ('products_product_id_seq', 'product_id'),
        'update_statistics': ('update_statistics_id_seq', 'id')
    }
    
    for table, (sequence, id_col) in sequence_mappings.items():
        try:
            cursor.execute(f"SELECT setval('{sequence}', (SELECT COALESCE(MAX({id_col}), 1) FROM {table}))")
            print_success(f"  Reset sequence for {table}")
        except Exception as e:
            print_warning(f"  Could not reset sequence for {table}: {e}")
    
    prod_conn.commit()
    cursor.close()

def main():
    """Main migration function."""
    print_header("SIMPLIFIED MIGRATION: DEV → PROD")
    print_info("Optimized for migrating to an EMPTY production database")
    print()
    
    start_time = time.time()
    
    # Connect to databases
    dev_conn, prod_conn = get_database_connections()
    
    # Define migration order (respects foreign key dependencies)
    # CRITICAL: Parent tables MUST be migrated before children
    migration_order = [
        # Base tables (no dependencies)
        'normalized_categories',
        'ingredient_analysis',
        
        # Products (depends on normalized_categories)
        'products',
        
        # Category processing jobs (depends on normalized_categories)
        # MUST come before processing_workers to avoid foreign key violations
        'category_processing_jobs',
        
        # Processing workers (depends on category_processing_jobs via current_job_id FK)
        'processing_workers',
        
        # Product-related tables (depend on products)
        'nutritionfacts',
        'productphotos',
        'product_price_history',
        
        # Job-related tables (depend on category_processing_jobs)
        'job_events',
        'product_processing_log',
        'update_statistics',
        
        # Mapping table (depends on both products and ingredient_analysis)
        'ingredient_product_mapping'
    ]
    
    # Track migration results
    results = {}
    
    print_header("STARTING MIGRATION")
    
    try:
        # Migrate each table (no need to disable FK checks - we respect dependencies!)
        for table in migration_order:
            source_count, dest_count = migrate_table(dev_conn, prod_conn, table)
            results[table] = {
                'source': source_count,
                'destination': dest_count,
                'success': source_count == dest_count
            }
            print()  # Blank line for readability
        
        # Reset sequences for auto-increment columns
        reset_sequences(prod_conn)
        print()
        
        # Final verification
        print_info("Performing final verification of all migrated data...")
        for table in migration_order:
            current_count = count_records(prod_conn, table)
            expected_count = results[table]['destination']
            
            if current_count != expected_count:
                print_error(f"  Data loss detected in {table}!")
                print_error(f"    Expected: {expected_count}, Found: {current_count}")
                results[table]['destination'] = current_count
                results[table]['success'] = False
            else:
                print_success(f"  {table}: {current_count} records verified")
        
    except Exception as e:
        print_error(f"Migration failed: {e}")
        import traceback
        traceback.print_exc()
        prod_conn.rollback()
        raise
    finally:
        # Close connections
        dev_conn.close()
        prod_conn.close()
    
    # Print summary
    print_header("MIGRATION SUMMARY")
    
    total_records = 0
    failed_tables = []
    
    for table, result in results.items():
        total_records += result['destination']
        status = "✓" if result['success'] else "✗"
        color = Colors.OKGREEN if result['success'] else Colors.FAIL
        
        print(f"{color}{status} {table:30s} {result['source']:>8d} → {result['destination']:>8d}{Colors.ENDC}")
        
        if not result['success']:
            failed_tables.append(table)
    
    print()
    print_info(f"Total records migrated: {total_records}")
    print_info(f"Total tables migrated: {len(results)}")
    
    elapsed = time.time() - start_time
    print_info(f"Migration completed in {elapsed:.2f} seconds")
    
    if failed_tables:
        print_warning(f"Tables with mismatched counts: {', '.join(failed_tables)}")
        sys.exit(1)
    else:
        print_success("All tables migrated successfully!")
        print()

if __name__ == '__main__':
    main()
