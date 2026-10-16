"""
Barbora Lightweight Updater - Fast price/availability updates from category listing pages
Updates existing products without visiting individual product pages.
Detects new products and queues them for full scraping.
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, List, Optional, Callable
from datetime import datetime
import time

from barbora_parser import BarboraParser, BarboraProductInfo


class BarboraLightweightUpdater:
    """
    Fast updater that uses category listing data (JSON) to update prices/availability.
    10-50x faster than full scraping since it doesn't visit individual product pages.
    """
    
    def __init__(self, status_callback: Optional[Callable[[str], None]] = None):
        self.status_callback = status_callback or (lambda x: None)
        self.parser = BarboraParser(status_callback)
        self.photo_tracking = False
        
    def _get_connection(self, retries: int = 5, delay: int = 10):
        """Get database connection with retry logic for Neon cold-start wake-up.

        Neon suspends idle databases and the first connection after a long pause
        can fail with "Control plane request failed" while the instance is waking.
        Retrying a few times (with a short wait) is all that's needed.
        """
        last_err = None
        for attempt in range(1, retries + 1):
            try:
                return psycopg2.connect(os.environ['DATABASE_URL'], cursor_factory=RealDictCursor)
            except psycopg2.OperationalError as e:
                last_err = e
                if attempt < retries:
                    self._log(f"DB connection attempt {attempt}/{retries} failed — retrying in {delay}s... ({e})")
                    time.sleep(delay)
        raise last_err
    
    def _log(self, message: str):
        """Log status message"""
        self.status_callback(message)
        
    def get_all_level3_categories(self) -> List[Dict]:
        """Get all level 3 categories for processing"""
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT category_id, name_lv, barbora_category_code, level
                FROM normalized_categories
                WHERE level = 3 AND barbora_category_code IS NOT NULL
                ORDER BY name_lv
            """)
            return cur.fetchall()
        finally:
            conn.close()
    
    def get_category_path_for_url(self, category_id: int) -> Optional[str]:
        """Build category path from database hierarchy for URL construction"""
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            
            path_parts = []
            current_id = category_id
            
            while current_id:
                cur.execute("""
                    SELECT category_id, parent_category_id, normalized_category
                    FROM normalized_categories
                    WHERE category_id = %s
                """, (current_id,))
                row = cur.fetchone()
                
                if not row:
                    break
                    
                if row['normalized_category']:
                    path_parts.insert(0, row['normalized_category'])
                    
                current_id = row['parent_category_id']
            
            return '/'.join(path_parts) if path_parts else None
        finally:
            conn.close()
    
    def get_existing_skus(self) -> set:
        """Get all existing product SKUs from database"""
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT sku FROM products")
            return {row['sku'] for row in cur.fetchall()}
        finally:
            conn.close()
    
    def update_product_price(self, conn, product: BarboraProductInfo) -> Dict:
        """
        Update price/availability for a single product.
        Returns dict with update results.
        """
        cur = conn.cursor()
        
        cur.execute("""
            SELECT 
                p.product_id,
                p.name,
                pph.price,
                pph.is_available,
                pph.price_per_unit,
                pph.price_per_unit_type,
                pph.discount_price
            FROM products p
            LEFT JOIN LATERAL (
                SELECT price, is_available, price_per_unit, price_per_unit_type, discount_price
                FROM product_price_history
                WHERE product_id = p.product_id
                ORDER BY recorded_at DESC
                LIMIT 1
            ) pph ON true
            WHERE p.sku = %s
        """, (product.sku,))
        
        row = cur.fetchone()
        if not row:
            return {'success': False, 'sku': product.sku, 'error': 'Product not found'}
        
        product_id = row['product_id']
        if self.photo_tracking and product.is_available:
            from photo_maintenance import PhotoMaintenance
            cur.execute("SAVEPOINT photo_candidate")
            try:
                PhotoMaintenance.observe(cur, product_id, product.big_image_url or product.image_url)
            except Exception as exc:
                cur.execute("ROLLBACK TO SAVEPOINT photo_candidate")
                self._log(f"Photo candidate deferred for {product.sku}: {exc}")
            finally:
                cur.execute("RELEASE SAVEPOINT photo_candidate")
        old_price = float(row['price']) if row['price'] else None
        old_available = row['is_available']
        old_price_per_unit = float(row['price_per_unit']) if row['price_per_unit'] else None
        old_discount = float(row['discount_price']) if row['discount_price'] else None
        
        new_available = product.is_available
        new_price_per_unit = product.comparative_unit_price
        new_price_per_unit_type = product.comparative_unit
        
        # Barbora JSON: price = sale price (what customer pays), retail_price = regular base price
        # DB schema: price = regular price, discount_price = discounted sale price
        if product.retail_price and product.price and product.price < product.retail_price:
            # Product is discounted
            new_price = product.retail_price  # Regular price goes in 'price' column
            new_discount = product.price      # Discounted price goes in 'discount_price' column
        else:
            # No discount
            new_price = product.price
            new_discount = None
        
        price_changed = old_price != new_price
        availability_changed = old_available != new_available
        discount_changed = old_discount != new_discount
        price_per_unit_changed = old_price_per_unit != new_price_per_unit
        
        any_change = price_changed or availability_changed or discount_changed or price_per_unit_changed
        
        if any_change:
            cur.execute("""
                INSERT INTO product_price_history (
                    product_id, price, is_available, data_source, recorded_at,
                    price_per_unit, price_per_unit_type, discount_price
                )
                VALUES (%s, %s, %s, 'lightweight_update', CURRENT_TIMESTAMP, %s, %s, %s)
            """, (product_id, new_price, new_available, new_price_per_unit, new_price_per_unit_type, new_discount))
            
            cur.execute("""
                UPDATE products SET updated_at = CURRENT_TIMESTAMP WHERE product_id = %s
            """, (product_id,))
        
        return {
            'success': True,
            'sku': product.sku,
            'price_changed': price_changed,
            'availability_changed': availability_changed,
            'discount_changed': discount_changed,
            'old_price': old_price,
            'new_price': new_price
        }
    
    def queue_new_products(self, conn, new_products: List[BarboraProductInfo], category_id: int, category_code: str) -> int:
        """Queue new products for full scraping. Returns job_id or None."""
        if not new_products:
            return None
            
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO category_processing_jobs 
            (category_code, category_id, total_products, processed_count, status, priority, requested_by, update_mode)
            VALUES (%s, %s, %s, 0, 'queued', 10, 'lightweight_updater', 'full')
            RETURNING id
        """, (category_code, category_id, len(new_products)))
        
        job_id = cur.fetchone()['id']
        
        import json
        for p in new_products:
            promo_json = json.dumps(p.promotion) if p.promotion else None
            cur.execute("""
                INSERT INTO product_processing_log 
                (job_id, sku, product_url, status, price, retail_price,
                 price_per_unit, price_per_unit_type, is_available, promotion_data)
                VALUES (%s, %s, %s, 'pending', %s, %s, %s, %s, %s, %s)
            """, (job_id, p.sku, p.url, p.price, p.retail_price,
                  p.comparative_unit_price, p.comparative_unit, p.is_available, promo_json))
        
        cur.execute("""
            INSERT INTO job_events (job_id, event_type, message)
            VALUES (%s, 'job_created', %s)
        """, (job_id, f"Lightweight updater found {len(new_products)} new products"))
        
        return job_id
    
    def process_category(self, category: Dict, existing_skus: set) -> Dict:
        """
        Process a single category - update existing products, detect new ones.
        Returns processing statistics.
        """
        category_id = category['category_id']
        category_name = category['name_lv']
        category_code = category['barbora_category_code']
        
        category_path = self.get_category_path_for_url(category_id)
        if not category_path:
            return {'error': f'No category path for {category_name}'}
        
        products = self.parser.extract_products_from_category(category_path)
        valid_products = [p for p in products if p.sku and p.url]
        
        if not valid_products:
            return {'category': category_name, 'products_found': 0, 'updated': 0, 'new': 0}
        
        existing_products = [p for p in valid_products if p.sku in existing_skus]
        new_products = [p for p in valid_products if p.sku not in existing_skus]
        
        stats = {
            'category': category_name,
            'products_found': len(valid_products),
            'existing': len(existing_products),
            'new': len(new_products),
            'updated': 0,
            'price_changes': 0,
            'availability_changes': 0,
            'new_job_id': None,
            'errors': []
        }
        
        conn = self._get_connection()
        try:
            for product in existing_products:
                result = self.update_product_price(conn, product)
                if result['success']:
                    stats['updated'] += 1
                    if result.get('price_changed'):
                        stats['price_changes'] += 1
                    if result.get('availability_changed'):
                        stats['availability_changes'] += 1
                else:
                    stats['errors'].append(result.get('error'))
            
            if new_products:
                stats['new_job_id'] = self.queue_new_products(conn, new_products, category_id, category_code)
                for p in new_products:
                    existing_skus.add(p.sku)
            
            conn.commit()
        except Exception as e:
            conn.rollback()
            stats['errors'].append(str(e))
        finally:
            conn.close()
        
        return stats
    
    def apply_hidden_overrides(self) -> int:
        """
        After each nightly run, insert an is_available=false history row for every
        product that is manually hidden (is_hidden=true) but whose latest price-history
        row still shows is_available=true.  Idempotent: skipped when the latest row
        already records unavailability.

        Returns the number of rows inserted.
        """
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO product_price_history (
                    product_id, price, is_available, data_source, recorded_at,
                    price_per_unit, price_per_unit_type, discount_price
                )
                SELECT
                    p.product_id,
                    latest.price,
                    FALSE,
                    'hidden_override',
                    CURRENT_TIMESTAMP,
                    latest.price_per_unit,
                    latest.price_per_unit_type,
                    latest.discount_price
                FROM products p
                JOIN LATERAL (
                    SELECT price, price_per_unit, price_per_unit_type, discount_price, is_available
                    FROM product_price_history
                    WHERE product_id = p.product_id
                    ORDER BY recorded_at DESC
                    LIMIT 1
                ) latest ON true
                WHERE p.is_hidden = TRUE
                  AND latest.is_available = TRUE
            """)
            count = cur.rowcount
            conn.commit()
            return count
        except Exception as e:
            conn.rollback()
            self._log(f"Hidden override error: {e}")
            return 0
        finally:
            conn.close()

    def run_full_update(self, progress_callback: Optional[Callable[[int, int, str], None]] = None) -> Dict:
        """
        Run lightweight update on all level 3 categories.
        
        Args:
            progress_callback: Optional callback(current, total, category_name)
        
        Returns:
            Summary statistics for the entire run
        """
        start_time = datetime.now()
        self._log("Starting lightweight update...")
        try:
            from photo_maintenance import PhotoMaintenance
            PhotoMaintenance(os.environ["DATABASE_URL"]).initialize()
            self.photo_tracking = True
        except Exception as exc:
            self._log(f"Photo tracking unavailable; price updates continue: {exc}")
        
        categories = self.get_all_level3_categories()
        existing_skus = self.get_existing_skus()
        
        self._log(f"Processing {len(categories)} categories, {len(existing_skus)} existing products in DB")
        
        summary = {
            'start_time': start_time.isoformat(),
            'categories_total': len(categories),
            'categories_processed': 0,
            'categories_with_errors': 0,
            'products_checked': 0,
            'products_updated': 0,
            'price_changes': 0,
            'availability_changes': 0,
            'new_products_found': 0,
            'new_product_jobs_created': 0,
            'errors': []
        }
        
        for i, category in enumerate(categories):
            if progress_callback:
                progress_callback(i + 1, len(categories), category['name_lv'])
            
            try:
                stats = self.process_category(category, existing_skus)
                
                summary['categories_processed'] += 1
                summary['products_checked'] += stats.get('products_found', 0)
                summary['products_updated'] += stats.get('updated', 0)
                summary['price_changes'] += stats.get('price_changes', 0)
                summary['availability_changes'] += stats.get('availability_changes', 0)
                summary['new_products_found'] += stats.get('new', 0)
                
                if stats.get('new_job_id'):
                    summary['new_product_jobs_created'] += 1
                
                if stats.get('errors'):
                    summary['categories_with_errors'] += 1
                    summary['errors'].extend(stats['errors'][:3])
                    
            except Exception as e:
                summary['categories_with_errors'] += 1
                summary['errors'].append(f"{category['name_lv']}: {str(e)}")
            
            time.sleep(0.3)
        
        summary['end_time'] = datetime.now().isoformat()
        summary['duration_seconds'] = (datetime.now() - start_time).total_seconds()

        hidden_overrides = self.apply_hidden_overrides()
        summary['hidden_overrides'] = hidden_overrides

        self._log(f"Completed: {summary['products_updated']} updated, {summary['new_products_found']} new, {summary['price_changes']} price changes")
        self._log(f"Hidden override: {hidden_overrides} products forced unavailable")

        return summary
    
    def save_run_history(self, summary: Dict) -> int:
        """Save run summary to database for tracking. Returns run_id."""
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO lightweight_update_runs (
                    started_at, ended_at, duration_seconds,
                    categories_processed, products_checked, products_updated,
                    price_changes, availability_changes, new_products_found,
                    new_product_jobs_created, errors_count, status
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                ) RETURNING run_id
            """, (
                summary.get('start_time'),
                summary.get('end_time'),
                summary.get('duration_seconds'),
                summary.get('categories_processed', 0),
                summary.get('products_checked', 0),
                summary.get('products_updated', 0),
                summary.get('price_changes', 0),
                summary.get('availability_changes', 0),
                summary.get('new_products_found', 0),
                summary.get('new_product_jobs_created', 0),
                len(summary.get('errors', [])),
                'completed'
            ))
            run_id = cur.fetchone()['run_id']
            conn.commit()
            return run_id
        finally:
            conn.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Barbora Lightweight Updater")
    parser.add_argument('--dry-run', action='store_true', help="Show what would be done without making changes")
    parser.add_argument('--limit', type=int, help="Limit number of categories to process")
    args = parser.parse_args()
    
    def log_status(msg):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    
    def progress(current, total, name):
        print(f"[{current}/{total}] {name}")
    
    updater = BarboraLightweightUpdater(status_callback=log_status)
    
    if args.dry_run:
        categories = updater.get_all_level3_categories()
        existing = updater.get_existing_skus()
        print(f"Would process {len(categories)} categories")
        print(f"Existing products in DB: {len(existing)}")
    else:
        summary = updater.run_full_update(progress_callback=progress)
        print("\n=== Summary ===")
        for key, value in summary.items():
            if key != 'errors':
                print(f"{key}: {value}")
        if summary.get('errors'):
            print(f"\nErrors ({len(summary['errors'])}):")
            for err in summary['errors'][:10]:
                print(f"  - {err}")
