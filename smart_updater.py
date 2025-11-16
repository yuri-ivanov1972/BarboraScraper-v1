"""
Smart Update Logic for Product Data
Compares existing product data with newly scraped data and determines what changed.
"""
from typing import Dict, Set, Optional
from decimal import Decimal
import psycopg2
from psycopg2.extras import RealDictCursor


class UpdateComparison:
    """Represents the result of comparing existing vs new product data"""
    
    def __init__(self):
        self.is_new_product = False
        self.price_changed = False
        self.availability_changed = False
        self.data_updated = False  # Other fields changed
        self.needs_update = False
        self.changes = []  # List of field names that changed
    
    def __repr__(self):
        if self.is_new_product:
            return "UpdateComparison(NEW_PRODUCT)"
        if not self.needs_update:
            return "UpdateComparison(UNCHANGED)"
        return f"UpdateComparison(changes={self.changes})"


class SmartUpdater:
    """Handles smart comparison and selective updates of product data"""
    
    PRICE_THRESHOLD = Decimal('0.01')  # Only update if price changed by >0.01 EUR
    
    def __init__(self, db_url: str):
        self.db_url = db_url
    
    def _get_connection(self):
        """Get database connection"""
        return psycopg2.connect(self.db_url, cursor_factory=RealDictCursor)
    
    def get_existing_product(self, sku: str) -> Optional[Dict]:
        """Fetch existing product data from database"""
        conn = None
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            
            cur.execute("""
                SELECT 
                    p.product_id,
                    p.sku,
                    p.name,
                    p.name_norm,
                    p.category_id,
                    p.quantity_value,
                    p.quantity_unit,
                    p.country_of_origin,
                    pr.current_price,
                    pr.is_available
                FROM products p
                LEFT JOIN pricing pr ON p.product_id = pr.product_id
                WHERE p.sku = %s
            """, (sku,))
            
            result = cur.fetchone()
            return dict(result) if result else None
            
        except Exception as e:
            raise Exception(f"Failed to fetch existing product {sku}: {e}")
        finally:
            if conn:
                conn.close()
    
    def compare_products(self, existing: Optional[Dict], new_data: Dict) -> UpdateComparison:
        """
        Compare existing product with newly scraped data.
        
        Args:
            existing: Existing product data from database (None if new product)
            new_data: Newly scraped product data
        
        Returns:
            UpdateComparison object indicating what changed
        """
        comparison = UpdateComparison()
        
        # New product
        if existing is None:
            comparison.is_new_product = True
            comparison.needs_update = True
            comparison.changes.append('new_product')
            return comparison
        
        # Compare price (threshold: >0.01 EUR)
        existing_price = existing.get('current_price')
        new_price = new_data.get('price')
        
        if existing_price is not None and new_price is not None:
            price_diff = abs(Decimal(str(new_price)) - Decimal(str(existing_price)))
            if price_diff > self.PRICE_THRESHOLD:
                comparison.price_changed = True
                comparison.needs_update = True
                comparison.changes.append('price')
        elif existing_price != new_price:  # One is None, other isn't
            comparison.price_changed = True
            comparison.needs_update = True
            comparison.changes.append('price')
        
        # Compare availability (exact match: True/False)
        existing_availability = existing.get('is_available')
        new_availability = new_data.get('is_available')
        
        if existing_availability != new_availability:
            comparison.availability_changed = True
            comparison.needs_update = True
            comparison.changes.append('availability')
        
        # Compare other fields (name, quantity, country)
        # Only update if significantly different or was NULL
        fields_to_check = {
            'name': ('name', 'name'),
            'quantity_value': ('quantity_value', 'quantity_value'),
            'quantity_unit': ('quantity_unit', 'quantity_unit'),
            'country': ('country_of_origin', 'country_of_origin')
        }
        
        for field_key, (existing_key, new_key) in fields_to_check.items():
            existing_value = existing.get(existing_key)
            new_value = new_data.get(new_key)
            
            # Update if existing was NULL/empty and new has data
            if (not existing_value) and new_value:
                comparison.data_updated = True
                comparison.needs_update = True
                comparison.changes.append(field_key)
            # Update if values are different
            elif existing_value != new_value and new_value is not None:
                comparison.data_updated = True
                comparison.needs_update = True
                comparison.changes.append(field_key)
        
        return comparison
    
    def get_fields_to_update(self, comparison: UpdateComparison) -> Set[str]:
        """
        Determine which database fields should be updated based on comparison.
        
        Returns:
            Set of field names to update
        """
        fields = set()
        
        if comparison.is_new_product:
            # New product - update everything except photos
            fields.update(['name', 'category', 'quantity', 'price', 'availability', 'country'])
        else:
            # Existing product - selective update
            if comparison.price_changed:
                fields.add('price')
            if comparison.availability_changed:
                fields.add('availability')
            if comparison.data_updated:
                # Only update specific fields that changed
                if 'name' in comparison.changes:
                    fields.add('name')
                if 'quantity_value' in comparison.changes or 'quantity_unit' in comparison.changes:
                    fields.add('quantity')
                if 'country' in comparison.changes:
                    fields.add('country')
        
        return fields
    
    def should_skip_photos(self, comparison: UpdateComparison) -> bool:
        """
        Determine if photo updates should be skipped.
        For daily updates, skip photos unless it's a new product.
        """
        return not comparison.is_new_product


class UpdateStatisticsCollector:
    """Collects and stores update statistics for a job"""
    
    def __init__(self, db_url: str, job_id: int, category_code: str):
        self.db_url = db_url
        self.job_id = job_id
        self.category_code = category_code
        
        # Statistics counters
        self.total_checked = 0
        self.new_products = 0
        self.price_changed = 0
        self.availability_changed = 0
        self.data_updated = 0
        self.unchanged = 0
        self.failed = 0
    
    def record_comparison(self, comparison: UpdateComparison):
        """Record the result of a product comparison"""
        self.total_checked += 1
        
        if comparison.is_new_product:
            self.new_products += 1
        elif not comparison.needs_update:
            self.unchanged += 1
        else:
            if comparison.price_changed:
                self.price_changed += 1
            if comparison.availability_changed:
                self.availability_changed += 1
            if comparison.data_updated:
                self.data_updated += 1
    
    def record_failure(self):
        """Record a failed product processing"""
        self.total_checked += 1
        self.failed += 1
    
    def save_to_database(self):
        """Save statistics to database"""
        conn = None
        try:
            conn = psycopg2.connect(self.db_url)
            cur = conn.cursor()
            
            cur.execute("""
                INSERT INTO update_statistics 
                (job_id, category_code, total_checked, new_products, price_changed,
                 availability_changed, data_updated, unchanged, failed)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                self.job_id,
                self.category_code,
                self.total_checked,
                self.new_products,
                self.price_changed,
                self.availability_changed,
                self.data_updated,
                self.unchanged,
                self.failed
            ))
            
            conn.commit()
            
        except Exception as e:
            if conn:
                conn.rollback()
            raise Exception(f"Failed to save update statistics: {e}")
        finally:
            if conn:
                conn.close()
    
    def get_summary(self) -> str:
        """Get human-readable summary of statistics"""
        return (
            f"Update Statistics for {self.category_code}:\n"
            f"  Total checked: {self.total_checked}\n"
            f"  New products: {self.new_products}\n"
            f"  Price changes: {self.price_changed}\n"
            f"  Availability changes: {self.availability_changed}\n"
            f"  Data updates: {self.data_updated}\n"
            f"  Unchanged: {self.unchanged}\n"
            f"  Failed: {self.failed}"
        )
