"""
SKU Classification - Determine which products are new vs existing for incremental updates
"""

import os
import psycopg2
from typing import Dict, List, Set


class SkuClassifier:
    """Classifies SKUs into new, existing, and removed products for incremental updates"""
    
    def __init__(self, db_connection=None):
        """
        Initialize SKU classifier
        
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
    
    def classify_skus(self, category_code: str, listing_skus: List[str]) -> Dict[str, List[str]]:
        """
        Classify SKUs into new, existing, and removed products
        
        Args:
            category_code: Rimi category code (e.g., 'SH-11-6')
            listing_skus: List of SKUs from current Rimi category listing
        
        Returns:
            Dictionary with keys:
                - 'new': SKUs not in database (need full scrape)
                - 'existing': SKUs already in database (lightweight update)
                - 'removed': SKUs in database but not in listing (mark inactive)
                - 'stats': Summary statistics
        """
        conn = None
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            
            # Convert listing SKUs to set for efficient lookups
            listing_skus_set = set(listing_skus)
            
            # Get all existing SKUs for this category from database
            # Include: 
            # 1. The category itself
            # 2. All its CHILDREN (descendants) - hierarchical DOWN
            # 3. All its ANCESTORS (parents) - hierarchical UP
            # This is critical because products may be stored in parent categories
            # (e.g., product in SH-2-2 should be found when processing SH-2-2-12)
            cur.execute("""
                WITH RECURSIVE 
                -- Find the target category
                target_category AS (
                    SELECT category_id, parent_category_id
                    FROM normalized_categories 
                    WHERE rimi_category_code = %s
                ),
                -- Find all descendants (children, grandchildren, etc.) - search DOWN
                descendants AS (
                    SELECT category_id FROM target_category
                    UNION ALL
                    SELECT nc.category_id 
                    FROM normalized_categories nc
                    JOIN descendants d ON nc.parent_category_id = d.category_id
                ),
                -- Find all ancestors (parents, grandparents, etc.) - search UP
                ancestors AS (
                    SELECT category_id, parent_category_id FROM target_category
                    UNION ALL
                    SELECT nc.category_id, nc.parent_category_id
                    FROM normalized_categories nc
                    JOIN ancestors a ON nc.category_id = a.parent_category_id
                    WHERE a.parent_category_id IS NOT NULL
                ),
                -- Combine all related categories
                all_related_categories AS (
                    SELECT category_id FROM descendants
                    UNION
                    SELECT category_id FROM ancestors
                )
                SELECT DISTINCT p.sku 
                FROM products p
                WHERE p.category_id IN (SELECT category_id FROM all_related_categories)
            """, (category_code,))
            
            db_skus = set(row[0] for row in cur.fetchall())
            
            # Classify SKUs
            new_skus = list(listing_skus_set - db_skus)
            existing_skus = list(listing_skus_set & db_skus)
            removed_skus = list(db_skus - listing_skus_set)
            
            # Sort for consistent ordering
            new_skus.sort()
            existing_skus.sort()
            removed_skus.sort()
            
            stats = {
                'total_in_listing': len(listing_skus),
                'total_in_db': len(db_skus),
                'new_count': len(new_skus),
                'existing_count': len(existing_skus),
                'removed_count': len(removed_skus)
            }
            
            return {
                'new': new_skus,
                'existing': existing_skus,
                'removed': removed_skus,
                'stats': stats
            }
            
        finally:
            if self._should_close_connection and conn:
                conn.close()
    
    def get_existing_product_data(self, skus: List[str]) -> Dict[str, Dict]:
        """
        Get current price and availability data for existing products
        
        Args:
            skus: List of SKUs to fetch data for
        
        Returns:
            Dictionary mapping SKU to product data (price, availability, last_updated)
        """
        if not skus:
            return {}
        
        conn = None
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            
            # Get current price and availability from price history (latest record per product)
            cur.execute("""
                SELECT 
                    p.sku,
                    pph.price,
                    pph.is_available,
                    p.updated_at
                FROM products p
                LEFT JOIN LATERAL (
                    SELECT price, is_available, recorded_at
                    FROM product_price_history
                    WHERE product_id = p.product_id
                    ORDER BY recorded_at DESC
                    LIMIT 1
                ) pph ON true
                WHERE p.sku = ANY(%s)
            """, (skus,))
            
            result = {}
            for row in cur.fetchall():
                sku, price, is_available, updated_at = row
                result[sku] = {
                    'price': float(price) if price is not None else None,
                    'is_available': is_available if is_available is not None else True,
                    'last_updated': updated_at
                }
            
            return result
            
        finally:
            if self._should_close_connection and conn:
                conn.close()
    
    def mark_products_inactive(self, skus: List[str], category_code: str) -> int:
        """
        Mark products as inactive (removed from store) by adding price history record
        Note: is_available is stored in product_price_history table, not products table
        
        Args:
            skus: List of SKUs to mark inactive
            category_code: Category code for logging
        
        Returns:
            Number of products marked inactive
        """
        if not skus:
            return 0
        
        conn = None
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            
            # Add price history records marking products as unavailable
            # Include: target category + all descendants + all ancestors (bidirectional)
            cur.execute("""
                WITH RECURSIVE 
                -- Find the target category
                target_category AS (
                    SELECT category_id, parent_category_id
                    FROM normalized_categories 
                    WHERE rimi_category_code = %s
                ),
                -- Find all descendants (children, grandchildren, etc.) - search DOWN
                descendants AS (
                    SELECT category_id FROM target_category
                    UNION ALL
                    SELECT nc.category_id 
                    FROM normalized_categories nc
                    JOIN descendants d ON nc.parent_category_id = d.category_id
                ),
                -- Find all ancestors (parents, grandparents, etc.) - search UP
                ancestors AS (
                    SELECT category_id, parent_category_id FROM target_category
                    UNION ALL
                    SELECT nc.category_id, nc.parent_category_id
                    FROM normalized_categories nc
                    JOIN ancestors a ON nc.category_id = a.parent_category_id
                    WHERE a.parent_category_id IS NOT NULL
                ),
                -- Combine all related categories
                all_related_categories AS (
                    SELECT category_id FROM descendants
                    UNION
                    SELECT category_id FROM ancestors
                ),
                matching_products AS (
                    SELECT p.product_id, p.sku
                    FROM products p
                    WHERE p.sku = ANY(%s)
                      AND p.category_id IN (SELECT category_id FROM all_related_categories)
                )
                INSERT INTO product_price_history (product_id, price, is_available, data_source, recorded_at)
                SELECT 
                    product_id,
                    0.00,
                    FALSE,
                    'incremental_update',
                    CURRENT_TIMESTAMP
                FROM matching_products
            """, (category_code, skus))
            
            count = cur.rowcount
            conn.commit()
            
            return count
            
        finally:
            if self._should_close_connection and conn:
                conn.close()


def print_classification_summary(classification: Dict):
    """Print a human-readable summary of SKU classification"""
    stats = classification['stats']
    
    print("\n" + "="*60)
    print("📊 SKU CLASSIFICATION SUMMARY")
    print("="*60)
    print(f"Total in listing:    {stats['total_in_listing']:>5}")
    print(f"Total in database:   {stats['total_in_db']:>5}")
    print("-"*60)
    print(f"✨ New products:     {stats['new_count']:>5}  (need full scrape)")
    print(f"🔄 Existing products: {stats['existing_count']:>5}  (lightweight update)")
    print(f"❌ Removed products:  {stats['removed_count']:>5}  (mark inactive)")
    print("="*60 + "\n")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python sku_classifier.py <category_code>")
        print("Example: python sku_classifier.py SH-11-6")
        sys.exit(1)
    
    category_code = sys.argv[1]
    
    # Quick test: collect SKUs and classify them
    from core_parser import RimiParser
    
    print(f"Collecting SKUs for category {category_code}...")
    parser = RimiParser(lambda msg: print(msg))
    listing_skus = parser.collect_category_skus(category_code)
    
    if not listing_skus:
        print(f"No SKUs found for category {category_code}")
        sys.exit(1)
    
    print(f"Found {len(listing_skus)} SKUs in listing")
    
    # Classify them
    classifier = SkuClassifier()
    classification = classifier.classify_skus(category_code, listing_skus)
    
    # Print summary
    print_classification_summary(classification)
    
    # Show some examples
    if classification['new']:
        print(f"First 5 new SKUs: {classification['new'][:5]}")
    if classification['removed']:
        print(f"First 5 removed SKUs: {classification['removed'][:5]}")
