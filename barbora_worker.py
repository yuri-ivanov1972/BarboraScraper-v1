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
from fiber_estimator import FiberEstimator


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
        
        try:
            self.fiber_estimator = FiberEstimator()
            logger.info("FiberEstimator initialized with category mappings")
        except Exception as e:
            logger.warning(f"FiberEstimator not available: {e}")
            self.fiber_estimator = None
        
        try:
            signal.signal(signal.SIGTERM, self._signal_handler)
            signal.signal(signal.SIGINT, self._signal_handler)
        except ValueError:
            pass
        
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
                    if product_id:
                        self.apply_fiber_estimation(product_id)
                    
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
    
    def _parse_quantity(self, name: str, neto_str: str = None):
        """
        Parse quantity_value and quantity_unit from product name and optional HTML neto value.

        neto_str: raw number string from 'Neto daudzums (g/ml)' HTML field.
                  The field is always expressed in grams or millilitres.

        Returns: (Decimal or None, str or None)
        """
        from decimal import Decimal, InvalidOperation

        if not name:
            return None, None

        name_stripped = name.strip()

        # --- Variable weight: ends with "sver." (sold loose by weight) ---
        if re.search(r'sver\.\s*$', name_stripped, re.IGNORECASE):
            return None, None

        # --- Multi-pack: NxM unit  e.g. "20x2,25g", "6 x 100g", "3 x 35g" ---
        multi_match = re.search(
            r'(\d+)\s*[xX×]\s*(\d+(?:[.,]\d+)?)\s*(g|kg|ml|l)\b',
            name_stripped, re.IGNORECASE
        )
        if multi_match:
            try:
                count    = Decimal(multi_match.group(1))
                unit_qty = Decimal(multi_match.group(2).replace(',', '.'))
                unit     = multi_match.group(3).lower()
                return count * unit_qty, unit
            except (InvalidOperation, ValueError):
                pass

        # --- Standard weight/volume: NUMBER g/kg/ml/l ---
        # Word boundary after unit prevents "g" in "gab" from matching.
        weight_match = re.search(
            r'(\d+(?:[.,]\d+)?)\s*(g|kg|ml|l)\b',
            name_stripped, re.IGNORECASE
        )
        if weight_match:
            unit = weight_match.group(2).lower()
            if neto_str:
                try:
                    neto_val = Decimal(neto_str.strip())
                    # neto is always in g/ml; convert to kg/l if name uses those units
                    if unit in ('kg', 'l'):
                        return neto_val / 1000, unit
                    else:
                        return neto_val, unit
                except (InvalidOperation, ValueError):
                    pass
            try:
                return Decimal(weight_match.group(1).replace(',', '.')), unit
            except (InvalidOperation, ValueError):
                return None, unit

        # --- Bare "kg" at end of name without a leading number ---
        # e.g. "Sīpoli sarkanie kg", "Cūkgaļas lāpstiņa bez kaula ar ādu kg"
        if re.search(r'\bkg\s*$', name_stripped, re.IGNORECASE):
            if neto_str:
                try:
                    # neto is in grams; convert to kg
                    return Decimal(neto_str.strip()) / 1000, 'kg'
                except (InvalidOperation, ValueError):
                    pass
            return None, 'kg'

        # --- Piece count: "6gab." or bare "gab." at end ---
        gab_match = re.search(r'(\d+)\s*gab\.?\b', name_stripped, re.IGNORECASE)
        if gab_match:
            try:
                return Decimal(gab_match.group(1)), 'gab'
            except (InvalidOperation, ValueError):
                pass

        if re.search(r'\bgab\.?\s*$', name_stripped, re.IGNORECASE):
            return None, 'gab'

        # --- neto_str only with no recognisable unit — don't assume g/ml ---
        return None, None

    def backfill_quantity_from_names(self, status_callback=None) -> dict:
        """
        Backfill quantity_value / quantity_unit for existing products that have
        NULL values by re-parsing their stored product names.

        Returns a summary dict with counts.
        """
        log = status_callback or (lambda msg: None)
        conn = self._get_connection()
        updated = 0
        skipped = 0
        failed  = 0

        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT product_id, name
                FROM products
                WHERE quantity_value IS NULL AND quantity_unit IS NULL
                ORDER BY product_id
            """)
            rows = cur.fetchall()
            total = len(rows)
            log(f"Found {total} products with no quantity data")

            for i, row in enumerate(rows):
                if isinstance(row, dict):
                    pid, name = row['product_id'], row['name']
                else:
                    pid, name = row[0], row[1]

                qty_val, qty_unit = self._parse_quantity(name)

                if qty_val is None and qty_unit is None:
                    skipped += 1
                    continue

                try:
                    cur.execute("""
                        UPDATE products
                        SET quantity_value = %s, quantity_unit = %s
                        WHERE product_id = %s
                    """, (qty_val, qty_unit, pid))
                    updated += 1
                except Exception as e:
                    logger.warning(f"Failed to update quantity for product_id={pid}: {e}")
                    failed += 1

                if (i + 1) % 500 == 0:
                    conn.commit()
                    log(f"  Progress: {i + 1}/{total} processed, {updated} updated so far")

            conn.commit()
            log(f"Backfill complete: {updated} updated, {skipped} no pattern found, {failed} errors")
            return {'total': total, 'updated': updated, 'skipped': skipped, 'failed': failed}

        except Exception as e:
            conn.rollback()
            logger.error(f"Backfill failed: {e}")
            return {'total': 0, 'updated': 0, 'skipped': 0, 'failed': 1, 'error': str(e)}
        finally:
            conn.close()

    def save_product(self, product, category_id: int, product_url: str) -> int:
        """Save or update product in the database. Returns product_id."""
        conn = self._get_connection()
        product_id = None
        try:
            cur = conn.cursor()

            name_norm = normalize_latvian_text(product.name) if product.name else None

            # Parse quantity from the HTML neto field (number-only string) + product name (unit)
            qty_value, qty_unit = self._parse_quantity(product.name, getattr(product, 'weight', None))

            cur.execute("""
                INSERT INTO products (sku, name, name_norm, barbora_url, category_id,
                                      country_of_origin, quantity_value, quantity_unit,
                                      created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (sku) DO UPDATE SET
                    name = EXCLUDED.name,
                    name_norm = EXCLUDED.name_norm,
                    barbora_url = EXCLUDED.barbora_url,
                    category_id = EXCLUDED.category_id,
                    country_of_origin = EXCLUDED.country_of_origin,
                    quantity_value = COALESCE(EXCLUDED.quantity_value, products.quantity_value),
                    quantity_unit  = COALESCE(EXCLUDED.quantity_unit,  products.quantity_unit),
                    updated_at = CURRENT_TIMESTAMP
                RETURNING product_id
            """, (product.sku, product.name, name_norm, product_url, category_id,
                  product.country_of_origin, qty_value, qty_unit))
            
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
    
    def apply_fiber_estimation(self, product_id: int) -> bool:
        """
        Apply fiber estimation for a product if:
        - Product has rimi_category_code
        - Fiber is NULL or 0
        - FiberEstimator is available
        
        Returns True if fiber was estimated and Nutri-Score recalculated.
        """
        if not self.fiber_estimator:
            return False
        
        conn = self._get_connection()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            cur.execute("""
                SELECT p.product_id, p.name, p.rimi_category_code, p.category_id,
                       nf.fiber, nf.energy_kj, nf.fat_saturated, nf.carbs_sugars,
                       nf.salt, nf.protein
                FROM products p
                JOIN nutritionfacts nf ON p.product_id = nf.product_id
                WHERE p.product_id = %s
            """, (product_id,))
            
            product = cur.fetchone()
            if not product:
                return False
            
            rimi_code = product.get('rimi_category_code')
            current_fiber = product.get('fiber')
            
            if not rimi_code:
                return False
            
            if current_fiber is not None and current_fiber > 0:
                return False
            
            fiber_value, source, should_update, match_type = self.fiber_estimator.estimate_fiber(
                product_name=product['name'],
                rimi_category_code=rimi_code,
                current_fiber=current_fiber
            )
            
            if not should_update:
                return False
            
            cur.execute("""
                UPDATE nutritionfacts 
                SET fiber = %s, is_fiber_correct = FALSE
                WHERE product_id = %s
            """, (fiber_value, product_id))
            
            if product['energy_kj'] is not None:
                result = self.nutriscore_calculator.calculate_single_product(
                    energy_kj=float(product['energy_kj']),
                    sugars=float(product['carbs_sugars']) if product['carbs_sugars'] else 0,
                    saturated_fat=float(product['fat_saturated']) if product['fat_saturated'] else 0,
                    salt=float(product['salt']) if product['salt'] else 0,
                    protein=float(product['protein']) if product['protein'] else 0,
                    fiber=float(fiber_value),
                    category_id=product['category_id']
                )
                
                if result.get('success'):
                    cur.execute("""
                        UPDATE nutritionfacts 
                        SET nutri_score_points = %s, nutri_score_grade = %s
                        WHERE product_id = %s
                    """, (result['score'], result['grade'], product_id))
                    
                    logger.debug(f"Product {product_id}: Fiber estimated {fiber_value}g ({match_type}), "
                                f"Nutri-Score: {result['grade']}")
            
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error applying fiber estimation for product {product_id}: {e}")
            conn.rollback()
            return False
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
