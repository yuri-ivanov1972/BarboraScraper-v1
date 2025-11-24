"""
Lightweight updater for existing products - updates price/availability without detail page scraping
"""

import os
import psycopg2
from typing import Optional, Dict
import re


class LightweightUpdater:
    """
    Lightweight product updater that uses listing-level data (price) without detail page scraping.
    Used in incremental mode to quickly update existing products.
    """
    
    def __init__(self, db_connection=None):
        """
        Initialize lightweight updater
        
        Args:
            db_connection: Optional database connection (will create if not provided)
        """
        self.db_connection = db_connection
        self._should_close_connection = db_connection is None
    
    def _get_connection(self):
        """Get database connection (create if needed)"""
        if self.db_connection:
            return self.db_connection
        return psycopg2.connect(os.environ['DATABASE_URL'])
    
    def _parse_price(self, price_str: str) -> Optional[float]:
        """
        Parse price string to float
        
        Args:
            price_str: Price string like "€2.99" or "2.99€"
        
        Returns:
            Float price or None if parsing fails
        """
        if not price_str:
            return None
        
        try:
            # Remove currency symbols and whitespace
            cleaned = re.sub(r'[€$\s]', '', price_str)
            # Replace comma with dot for decimal
            cleaned = cleaned.replace(',', '.')
            return float(cleaned)
        except (ValueError, AttributeError):
            return None
    
    def update_from_listing_data(self, sku: str, listing_data: Dict) -> Dict:
        """
        Update existing product using listing-level data (price only, no detail scraping)
        Note: Prices are stored in product_price_history table, not products table
        
        Args:
            sku: Product SKU
            listing_data: Dictionary with 'price' and optionally 'name' from listing
        
        Returns:
            Dictionary with update results
        """
        conn = None
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            
            # Parse price
            price_str = listing_data.get('price', '')
            price = self._parse_price(price_str)
            
            if price is None:
                return {
                    'success': False,
                    'sku': sku,
                    'error': f'Could not parse price: {price_str}'
                }
            
            # Get current product data and latest price from price_history
            cur.execute("""
                SELECT 
                    p.product_id,
                    p.name,
                    pph.price,
                    pph.is_available
                FROM products p
                LEFT JOIN LATERAL (
                    SELECT price, is_available, recorded_at
                    FROM product_price_history
                    WHERE product_id = p.product_id
                    ORDER BY recorded_at DESC
                    LIMIT 1
                ) pph ON true
                WHERE p.sku = %s
            """, (sku,))
            
            row = cur.fetchone()
            if not row:
                return {
                    'success': False,
                    'sku': sku,
                    'error': 'Product not found in database'
                }
            
            product_id, product_name, old_price, old_availability = row
            old_price = float(old_price) if old_price is not None else None
            
            # Track changes
            price_changed = (old_price != price) if old_price is not None else True
            availability_changed = False  # Assume available if in listing
            
            if old_availability is False:
                availability_changed = True  # Product back in stock
            
            # Only insert new price history record if price actually changed
            # or if availability changed
            if price_changed or availability_changed:
                cur.execute("""
                    INSERT INTO product_price_history (product_id, price, is_available, data_source, recorded_at)
                    VALUES (%s, %s, TRUE, 'lightweight_update', CURRENT_TIMESTAMP)
                """, (product_id, price))
            
            # Update product timestamp
            cur.execute("""
                UPDATE products
                SET updated_at = CURRENT_TIMESTAMP
                WHERE sku = %s
            """, (sku,))
            
            conn.commit()
            
            return {
                'success': True,
                'sku': sku,
                'price_changed': price_changed,
                'old_price': old_price,
                'new_price': price,
                'availability_changed': availability_changed,
                'update_type': 'lightweight'
            }
            
        except Exception as e:
            if conn:
                conn.rollback()
            return {
                'success': False,
                'sku': sku,
                'error': str(e)
            }
        finally:
            if self._should_close_connection and conn:
                conn.close()
    
    def batch_update_from_listing(self, listing_products: Dict[str, Dict]) -> Dict:
        """
        Update multiple products from listing data
        
        Args:
            listing_products: Dictionary mapping SKU to listing data
        
        Returns:
            Summary of batch update results
        """
        results = {
            'total': len(listing_products),
            'successful': 0,
            'failed': 0,
            'price_changes': 0,
            'availability_changes': 0,
            'errors': []
        }
        
        for sku, listing_data in listing_products.items():
            update_result = self.update_from_listing_data(sku, listing_data)
            
            if update_result['success']:
                results['successful'] += 1
                if update_result.get('price_changed'):
                    results['price_changes'] += 1
                if update_result.get('availability_changed'):
                    results['availability_changes'] += 1
            else:
                results['failed'] += 1
                results['errors'].append({
                    'sku': sku,
                    'error': update_result.get('error')
                })
        
        return results


if __name__ == "__main__":
    # Quick test
    updater = LightweightUpdater()
    
    test_data = {
        'sku': '123456',
        'price': '€2.99',
        'name': 'Test Product'
    }
    
    result = updater.update_from_listing_data('123456', test_data)
    print(f"Update result: {result}")
