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
from nutriscore_calculator import NutriscoreCalculator
from ingredient_processor import IngredientProcessor


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
        
        init_conn = psycopg2.connect(self.db_url)
        try:
            self.nutriscore_calculator = NutriscoreCalculator(init_conn)
            logger.info("NutriscoreCalculator initialized with category mappings from database")
        finally:
            init_conn.close()
        
        self.ingredient_processor = IngredientProcessor(status_callback=lambda msg: logger.info(msg))
        logger.info("IngredientProcessor initialized")
        
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
        """Get all pending products (SKU + URL + price data) for a job"""
        conn = self._get_connection()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT sku, product_url, price, retail_price, price_per_unit, 
                       price_per_unit_type, is_available, promotion_data
                FROM product_processing_log
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
                    product_id = self.save_product(product_data, category_id, product_url)
                    if product_id and product_record.get('price') is not None:
                        self.save_price_history_from_listing(product_id, product_record)
                    
                    if product_id and product_data.ingredients:
                        try:
                            self.ingredient_processor.process_product_ingredients(sku, product_data.ingredients)
                        except Exception as ing_err:
                            logger.warning(f"Ingredient processing failed for {sku}: {ing_err}")
                    
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
    
    def save_product(self, product, category_id: int, product_url: str) -> int:
        """Save or update product in the database. Returns product_id."""
        conn = self._get_connection()
        product_id = None
        try:
            cur = conn.cursor()
            
            name_norm = normalize_latvian_text(product.name) if product.name else None
            
            cur.execute("""
                INSERT INTO products (sku, name, name_norm, barbora_url, category_id, country_of_origin, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (sku) DO UPDATE SET
                    name = EXCLUDED.name,
                    name_norm = EXCLUDED.name_norm,
                    barbora_url = EXCLUDED.barbora_url,
                    category_id = EXCLUDED.category_id,
                    country_of_origin = EXCLUDED.country_of_origin,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING product_id
            """, (product.sku, product.name, name_norm, product_url, category_id, product.country_of_origin))
            
            product_id = cur.fetchone()[0]
            
            if product.ingredients:
                cur.execute("""
                    UPDATE products SET ingredients = %s WHERE product_id = %s
                """, (product.ingredients, product_id))
            
            if product.nutrition:
                nutri_score_points = None
                nutri_score_grade = None
                
                n = product.nutrition
                if n.energy_kj is not None:
                    result = self.nutriscore_calculator.calculate_single_product(
                        energy_kj=n.energy_kj,
                        sugars=n.sugars if n.sugars is not None else 0,
                        saturated_fat=n.saturated_fat if n.saturated_fat is not None else 0,
                        salt=n.salt if n.salt is not None else 0,
                        protein=n.protein if n.protein is not None else 0,
                        fiber=n.fiber if n.fiber is not None else 0,
                        category_id=category_id
                    )
                    if result.get('success'):
                        nutri_score_points = result['score']
                        nutri_score_grade = result['grade']
                        logger.debug(f"Nutri-Score: {nutri_score_grade} ({nutri_score_points} pts)")
                
                energy_kj = n.energy_kj
                energy_kcal = n.energy_kcal
                fat_total = n.fat if n.fat is not None else (0 if energy_kj is not None else None)
                fat_saturated = n.saturated_fat if n.saturated_fat is not None else (0 if energy_kj is not None else None)
                carbs_total = n.carbohydrates if n.carbohydrates is not None else (0 if energy_kj is not None else None)
                carbs_sugars = n.sugars if n.sugars is not None else (0 if energy_kj is not None else None)
                protein_val = n.protein if n.protein is not None else (0 if energy_kj is not None else None)
                salt_val = n.salt if n.salt is not None else (0 if energy_kj is not None else None)
                fiber_val = n.fiber if n.fiber is not None else (0 if energy_kj is not None else None)
                
                cur.execute("""
                    INSERT INTO nutritionfacts (product_id, energy_kj, energy_kcal, fat_total, fat_saturated, 
                                                carbs_total, carbs_sugars, protein, salt, fiber, ingredients_text,
                                                nutri_score_points, nutri_score_grade)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                        ingredients_text = EXCLUDED.ingredients_text,
                        nutri_score_points = EXCLUDED.nutri_score_points,
                        nutri_score_grade = EXCLUDED.nutri_score_grade
                """, (product_id, 
                      energy_kj, energy_kcal, fat_total, fat_saturated,
                      carbs_total, carbs_sugars, protein_val, salt_val, fiber_val,
                      product.ingredients, nutri_score_points, nutri_score_grade))
            
            if product.photo_urls:
                cur.execute("DELETE FROM productphotos WHERE product_id = %s", (product_id,))
                for i, photo_url in enumerate(product.photo_urls):
                    is_primary = (i == 0)
                    cur.execute("""
                        INSERT INTO productphotos (product_id, photo_url, is_primary)
                        VALUES (%s, %s, %s)
                    """, (product_id, photo_url, is_primary))
            
            conn.commit()
            return product_id
        finally:
            conn.close()
    
    def save_price_history_from_listing(self, product_id: int, product_record: dict):
        """
        Save price history from a product_processing_log record with deduplication.
        Only creates a new record if any price field has changed.
        
        Args:
            product_id: Database product ID
            product_record: Dict from product_processing_log with price data
        """
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            
            new_price = float(product_record['price']) if product_record.get('price') else None
            retail_price = float(product_record['retail_price']) if product_record.get('retail_price') else None
            new_is_available = product_record.get('is_available', True)
            new_price_per_unit = float(product_record['price_per_unit']) if product_record.get('price_per_unit') else None
            new_price_per_unit_type = product_record.get('price_per_unit_type')
            
            promo = product_record.get('promotion_data')
            if isinstance(promo, str):
                import json
                promo = json.loads(promo) if promo else None
            
            new_discount_price = None
            new_discount_price_per_unit = None
            
            if promo and 'oldPrice' in promo:
                new_discount_price = new_price
                new_price = promo.get('oldPrice')
                if 'oldComparativeRate' in promo:
                    new_discount_price_per_unit = new_price_per_unit
                    new_price_per_unit = promo.get('oldComparativeRate')
            elif retail_price and new_price and retail_price > new_price:
                new_discount_price = new_price
                new_price = retail_price
            
            cur.execute("""
                SELECT price, is_available, price_per_unit, price_per_unit_type, 
                       discount_price, discount_price_per_unit
                FROM product_price_history
                WHERE product_id = %s
                ORDER BY recorded_at DESC
                LIMIT 1
            """, (product_id,))
            
            last_record = cur.fetchone()
            
            should_insert = False
            if last_record is None:
                should_insert = True
            else:
                last_price = float(last_record[0]) if last_record[0] else None
                last_available = last_record[1]
                last_ppu = float(last_record[2]) if last_record[2] else None
                last_ppu_type = last_record[3]
                last_discount = float(last_record[4]) if last_record[4] else None
                last_discount_ppu = float(last_record[5]) if last_record[5] else None
                
                def values_differ(a, b, tolerance=0.01):
                    if a is None and b is None:
                        return False
                    if a is None or b is None:
                        return True
                    return abs(float(a) - float(b)) > tolerance
                
                price_changed = values_differ(new_price, last_price)
                availability_changed = new_is_available != last_available
                ppu_changed = values_differ(new_price_per_unit, last_ppu)
                ppu_type_changed = new_price_per_unit_type != last_ppu_type
                discount_changed = values_differ(new_discount_price, last_discount)
                discount_ppu_changed = values_differ(new_discount_price_per_unit, last_discount_ppu)
                
                should_insert = (price_changed or availability_changed or ppu_changed or 
                               ppu_type_changed or discount_changed or discount_ppu_changed)
            
            if should_insert:
                cur.execute("""
                    INSERT INTO product_price_history 
                    (product_id, price, currency, is_available, price_per_unit, price_per_unit_type,
                     discount_price, discount_price_per_unit, data_source, recorded_at, created_at)
                    VALUES (%s, %s, 'EUR', %s, %s, %s, %s, %s, 'barbora_scrape', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """, (product_id, new_price, new_is_available, new_price_per_unit, 
                      new_price_per_unit_type, new_discount_price, new_discount_price_per_unit))
                conn.commit()
                logger.debug(f"Price history recorded for product {product_id}: €{new_price}")
                return True
            else:
                logger.debug(f"Price unchanged for product {product_id}, skipping")
                return False
                
        finally:
            conn.close()
    
    def save_price_history(self, product_id: int, listing_product, conn=None):
        """
        Save price history with deduplication logic.
        Only creates a new record if any price field has changed.
        
        Args:
            product_id: Database product ID
            listing_product: BarboraProductInfo from category listing
            conn: Optional existing connection (if None, creates new one)
        """
        close_conn = False
        if conn is None:
            conn = self._get_connection()
            close_conn = True
        
        try:
            cur = conn.cursor()
            
            new_price = listing_product.price
            new_is_available = listing_product.is_available
            new_price_per_unit = listing_product.comparative_unit_price
            new_price_per_unit_type = listing_product.comparative_unit
            
            promo = listing_product.promotion
            new_discount_price = None
            new_discount_price_per_unit = None
            if promo:
                if 'oldPrice' in promo:
                    new_discount_price = new_price
                    new_price = promo.get('oldPrice')
                if 'oldComparativeRate' in promo:
                    new_discount_price_per_unit = new_price_per_unit
                    new_price_per_unit = promo.get('oldComparativeRate')
            
            cur.execute("""
                SELECT price, is_available, price_per_unit, price_per_unit_type, 
                       discount_price, discount_price_per_unit
                FROM product_price_history
                WHERE product_id = %s
                ORDER BY recorded_at DESC
                LIMIT 1
            """, (product_id,))
            
            last_record = cur.fetchone()
            
            should_insert = False
            if last_record is None:
                should_insert = True
            else:
                last_price = float(last_record[0]) if last_record[0] else None
                last_available = last_record[1]
                last_ppu = float(last_record[2]) if last_record[2] else None
                last_ppu_type = last_record[3]
                last_discount = float(last_record[4]) if last_record[4] else None
                last_discount_ppu = float(last_record[5]) if last_record[5] else None
                
                def values_differ(a, b, tolerance=0.01):
                    if a is None and b is None:
                        return False
                    if a is None or b is None:
                        return True
                    return abs(float(a) - float(b)) > tolerance
                
                price_changed = values_differ(new_price, last_price)
                availability_changed = new_is_available != last_available
                ppu_changed = values_differ(new_price_per_unit, last_ppu)
                ppu_type_changed = new_price_per_unit_type != last_ppu_type
                discount_changed = values_differ(new_discount_price, last_discount)
                discount_ppu_changed = values_differ(new_discount_price_per_unit, last_discount_ppu)
                
                should_insert = (price_changed or availability_changed or ppu_changed or 
                               ppu_type_changed or discount_changed or discount_ppu_changed)
            
            if should_insert:
                cur.execute("""
                    INSERT INTO product_price_history 
                    (product_id, price, currency, is_available, price_per_unit, price_per_unit_type,
                     discount_price, discount_price_per_unit, data_source, recorded_at, created_at)
                    VALUES (%s, %s, 'EUR', %s, %s, %s, %s, %s, 'barbora_scrape', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """, (product_id, new_price, new_is_available, new_price_per_unit, 
                      new_price_per_unit_type, new_discount_price, new_discount_price_per_unit))
                conn.commit()
                logger.debug(f"Price history recorded for product {product_id}: €{new_price}")
                return True
            else:
                logger.debug(f"Price unchanged for product {product_id}, skipping")
                return False
                
        finally:
            if close_conn:
                conn.close()
    
    def run(self, single_run: bool = False, exit_when_empty: bool = False):
        """Main worker loop"""
        logger.info(f"Worker {self.worker_id} starting...")
        processed_any = False
        
        try:
            while self.running:
                job = self.claim_job()
                
                if job:
                    processed_any = True
                    try:
                        self.process_job(job)
                    except Exception as e:
                        logger.error(f"Job processing error: {e}")
                        self.complete_job(job['id'], 'failed', str(e)[:500])
                else:
                    if single_run:
                        logger.info("No jobs found, exiting (single-run mode)")
                        break
                    if exit_when_empty and processed_any:
                        logger.info("Queue empty after processing, exiting (--exit-when-empty)")
                        break
                    if exit_when_empty and not processed_any:
                        logger.info("No jobs in queue, exiting (--exit-when-empty)")
                        break
                    logger.info("No jobs in queue, waiting 30s...")
                    time.sleep(30)
        finally:
            self._cleanup()
        
        logger.info("Worker stopped")
    
    def _cleanup(self):
        """Clean up resources before shutdown"""
        try:
            if self.ingredient_processor:
                self.ingredient_processor.close()
                logger.info("IngredientProcessor closed")
        except Exception as e:
            logger.warning(f"Error closing IngredientProcessor: {e}")
    
    def refresh_product_ingredient_cards(self):
        """Refresh the materialized view for product card data sharing"""
        conn = None
        try:
            logger.info("Refreshing product_ingredient_cards materialized view...")
            start_time = time.time()
            
            conn = psycopg2.connect(self.db_url)
            conn.autocommit = True
            cur = conn.cursor()
            
            cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY product_ingredient_cards")
            
            elapsed = time.time() - start_time
            logger.info(f"Materialized view refreshed in {elapsed:.1f}s")
            
        except Exception as e:
            logger.error(f"Failed to refresh materialized view: {e}")
        finally:
            if conn:
                conn.close()


def main():
    parser = argparse.ArgumentParser(description='Barbora Worker')
    parser.add_argument('--worker-id', help='Worker ID (auto-generated if not provided)')
    parser.add_argument('--single-run', action='store_true', help='Process one job and exit')
    parser.add_argument('--exit-when-empty', action='store_true', help='Exit when queue is empty (instead of waiting)')
    args = parser.parse_args()
    
    worker = BarboraWorker(worker_id=args.worker_id)
    worker.run(single_run=args.single_run, exit_when_empty=args.exit_when_empty)


if __name__ == '__main__':
    main()
