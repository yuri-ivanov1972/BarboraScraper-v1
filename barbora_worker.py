#!/usr/bin/env python3
"""
Barbora Worker - Processes jobs from category_processing_jobs queue
"""
import os
import sys
import time
import logging
import argparse
import signal
import socket
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
import unicodedata
import re

from barbora_parser import BarboraParser


def normalize_latvian_text(text: str) -> str:
    """Convert Latvian letters to ASCII equivalents for easier searching"""
    if not text:
        return ""
    
    latvian_map = {
        'ā': 'a', 'Ā': 'A',
        'č': 'c', 'Č': 'C',
        'ē': 'e', 'Ē': 'E',
        'ģ': 'g', 'Ģ': 'G',
        'ī': 'i', 'Ī': 'I',
        'ķ': 'k', 'Ķ': 'K',
        'ļ': 'l', 'Ļ': 'L',
        'ņ': 'n', 'Ņ': 'N',
        'š': 's', 'Š': 'S',
        'ū': 'u', 'Ū': 'U',
        'ž': 'z', 'Ž': 'Z',
    }
    
    result = text
    for latvian_char, ascii_char in latvian_map.items():
        result = result.replace(latvian_char, ascii_char)
    
    result = unicodedata.normalize('NFKD', result).encode('ascii', 'ignore').decode('ascii')
    result = result.lower().strip()
    result = re.sub(r'\s+', ' ', result)
    
    return result

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


class BarboraWorker:
    """Worker for processing Barbora category scraping jobs"""
    
    def __init__(self, worker_id: str = None):
        self.worker_id = worker_id or f"worker_{socket.gethostname()}_{os.getpid()}"
        self.running = True
        self.db_url = os.environ['DATABASE_URL']
        self.parser = BarboraParser(status_callback=lambda msg: logger.info(msg))
        
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        
        logger.info(f"Worker {self.worker_id} initialized")
        
    def _signal_handler(self, signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False
        
    def _get_connection(self):
        return psycopg2.connect(self.db_url)
    
    def claim_job(self) -> dict:
        """Claim the next available job from the queue"""
        conn = self._get_connection()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            cur.execute("""
                UPDATE category_processing_jobs
                SET status = 'processing',
                    current_worker_id = %s,
                    started_at = CURRENT_TIMESTAMP,
                    last_updated = CURRENT_TIMESTAMP
                WHERE id = (
                    SELECT id FROM category_processing_jobs
                    WHERE status = 'queued'
                    ORDER BY priority DESC, scheduled_for ASC NULLS LAST
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING *
            """, (self.worker_id,))
            
            job = cur.fetchone()
            conn.commit()
            return dict(job) if job else None
        finally:
            conn.close()
    
    def get_pending_products(self, job_id: int) -> list:
        """Get all pending products (SKU + URL) for a job"""
        conn = self._get_connection()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT sku, product_url FROM product_processing_log
                WHERE job_id = %s AND status = 'pending'
                ORDER BY id
            """, (job_id,))
            return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()
    
    def update_sku_status(self, job_id: int, sku: str, status: str, error: str = None):
        """Update the status of a single SKU"""
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE product_processing_log
                SET status = %s, 
                    error_message = %s,
                    processed_at = CURRENT_TIMESTAMP
                WHERE job_id = %s AND sku = %s
            """, (status, error, job_id, sku))
            conn.commit()
        finally:
            conn.close()
    
    def update_job_progress(self, job_id: int, processed_count: int):
        """Update job progress count"""
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE category_processing_jobs
                SET processed_count = %s,
                    last_updated = CURRENT_TIMESTAMP,
                    last_heartbeat = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (processed_count, job_id))
            conn.commit()
        finally:
            conn.close()
    
    def complete_job(self, job_id: int, status: str = 'completed', error: str = None):
        """Mark job as completed or failed"""
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE category_processing_jobs
                SET status = %s,
                    completed_at = CURRENT_TIMESTAMP,
                    last_updated = CURRENT_TIMESTAMP,
                    notes = %s
                WHERE id = %s
            """, (status, error, job_id))
            
            cur.execute("""
                INSERT INTO job_events (job_id, event_type, message)
                VALUES (%s, %s, %s)
            """, (job_id, f'job_{status}', error or f'Job {status}'))
            
            conn.commit()
        finally:
            conn.close()
    
    def get_category_path(self, category_id: int) -> str:
        """Build the category URL path from the hierarchy"""
        conn = self._get_connection()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                WITH RECURSIVE category_path AS (
                    SELECT category_id, normalized_category, parent_category_id, 
                           normalized_category as path
                    FROM normalized_categories
                    WHERE category_id = %s
                    
                    UNION ALL
                    
                    SELECT parent.category_id, parent.normalized_category, parent.parent_category_id,
                           parent.normalized_category || '/' || cp.path
                    FROM normalized_categories parent
                    JOIN category_path cp ON parent.category_id = cp.parent_category_id
                )
                SELECT path FROM category_path
                WHERE parent_category_id IS NULL
            """, (category_id,))
            result = cur.fetchone()
            return result['path'] if result else None
        finally:
            conn.close()
    
    def process_job(self, job: dict):
        """Process a single job - scrape product details for all products"""
        job_id = job['id']
        category_id = job['category_id']
        update_mode = job.get('update_mode', 'full')
        
        logger.info(f"Processing job #{job_id} for category {category_id} (mode: {update_mode})")
        
        pending_products = self.get_pending_products(job_id)
        logger.info(f"Found {len(pending_products)} pending products to process")
        
        processed = 0
        errors = 0
        
        for product_record in pending_products:
            if not self.running:
                logger.info("Shutdown requested, stopping processing")
                break
            
            sku = product_record['sku']
            product_url = product_record['product_url']
            
            if not product_url:
                self.update_sku_status(job_id, sku, 'failed', 'No product URL stored')
                errors += 1
                continue
            
            try:
                product_data = self.parser.extract_product_details(product_url)
                
                if product_data:
                    self.save_product(product_data, category_id, product_url)
                    self.update_sku_status(job_id, sku, 'completed')
                    logger.info(f"Processed: {sku} - {product_data.name[:50] if product_data.name else 'Unknown'}")
                else:
                    self.update_sku_status(job_id, sku, 'failed', 'Could not extract product data')
                    errors += 1
                    
            except Exception as e:
                self.update_sku_status(job_id, sku, 'failed', str(e)[:500])
                errors += 1
                logger.error(f"Error processing {sku}: {e}")
            
            processed += 1
            self.update_job_progress(job_id, processed)
            
            time.sleep(0.5)
        
        final_status = 'completed' if errors == 0 else 'completed_with_errors'
        self.complete_job(job_id, final_status, f"Processed {processed} products, {errors} errors" if errors else None)
        logger.info(f"Job #{job_id} completed: {processed} processed, {errors} errors")
    
    def save_product(self, product, category_id: int, product_url: str):
        """Save or update product in the database"""
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            
            name_norm = normalize_latvian_text(product.name) if product.name else None
            
            cur.execute("""
                INSERT INTO products (sku, name, name_norm, barbora_url, category_id, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (sku) DO UPDATE SET
                    name = EXCLUDED.name,
                    name_norm = EXCLUDED.name_norm,
                    barbora_url = EXCLUDED.barbora_url,
                    category_id = EXCLUDED.category_id,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING product_id
            """, (product.sku, product.name, name_norm, product_url, category_id))
            
            product_id = cur.fetchone()[0]
            
            if product.ingredients:
                cur.execute("""
                    UPDATE products SET ingredients = %s WHERE product_id = %s
                """, (product.ingredients, product_id))
            
            if product.nutrition:
                cur.execute("""
                    INSERT INTO nutritionfacts (product_id, energy_kj, energy_kcal, fat_total, fat_saturated, 
                                                carbs_total, carbs_sugars, protein, salt, fiber, ingredients_text)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (product_id) DO UPDATE SET
                        energy_kj = EXCLUDED.energy_kj,
                        energy_kcal = EXCLUDED.energy_kcal,
                        fat_total = EXCLUDED.fat_total,
                        fat_saturated = EXCLUDED.fat_saturated,
                        carbs_total = EXCLUDED.carbs_total,
                        carbs_sugars = EXCLUDED.carbs_sugars,
                        protein = EXCLUDED.protein,
                        salt = EXCLUDED.salt,
                        fiber = EXCLUDED.fiber,
                        ingredients_text = EXCLUDED.ingredients_text
                """, (product_id, 
                      product.nutrition.energy_kj, product.nutrition.energy_kcal,
                      product.nutrition.fat, product.nutrition.saturated_fat,
                      product.nutrition.carbohydrates, product.nutrition.sugars,
                      product.nutrition.protein, product.nutrition.salt, product.nutrition.fiber,
                      product.ingredients))
            
            conn.commit()
        finally:
            conn.close()
    
    def run(self, single_run: bool = False):
        """Main worker loop"""
        logger.info(f"Worker {self.worker_id} starting...")
        
        while self.running:
            job = self.claim_job()
            
            if job:
                try:
                    self.process_job(job)
                except Exception as e:
                    logger.error(f"Job processing error: {e}")
                    self.complete_job(job['id'], 'failed', str(e)[:500])
            else:
                if single_run:
                    logger.info("No jobs found, exiting (single-run mode)")
                    break
                logger.info("No jobs in queue, waiting 30s...")
                time.sleep(30)
        
        logger.info("Worker stopped")


def main():
    parser = argparse.ArgumentParser(description='Barbora Worker')
    parser.add_argument('--worker-id', help='Worker ID (auto-generated if not provided)')
    parser.add_argument('--single-run', action='store_true', help='Process one job and exit')
    args = parser.parse_args()
    
    worker = BarboraWorker(worker_id=args.worker_id)
    worker.run(single_run=args.single_run)


if __name__ == '__main__':
    main()
