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
            # Include both the category itself AND all its children (hierarchical)
            cur.execute("""
                WITH target_category AS (
                    SELECT category_id 
                    FROM normalized_categories 
                    WHERE rimi_category_code = %s
                )
                SELECT DISTINCT p.sku 
                FROM products p
                JOIN normalized_categories nc ON p.category_id = nc.category_id
                WHERE nc.category_id IN (
                    SELECT category_id FROM target_category
                    UNION
                    SELECT category_id FROM normalized_categories 
                    WHERE parent_category_id IN (SELECT category_id FROM target_category)
                )
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
            
            # Get current price and availability for existing products
            cur.execute("""
                SELECT 
                    p.sku,
                    p.is_available,
                    p.updated_at
                FROM products p
                WHERE p.sku = ANY(%s)
            """, (skus,))
            
            result = {}
            for row in cur.fetchall():
                sku, is_available, updated_at = row
                result[sku] = {
                    'is_available': is_available,
                    'last_updated': updated_at
                }
            
            return result
            
        finally:
            if self._should_close_connection and conn:
                conn.close()
    
    def mark_products_inactive(self, skus: List[str], category_code: str) -> int:
        """
        Mark products as inactive (removed from store)
        
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
            
            # Mark products as unavailable
            # Include both the category itself AND all its children (hierarchical)
            cur.execute("""
                WITH target_category AS (
                    SELECT category_id 
                    FROM normalized_categories 
                    WHERE rimi_category_code = %s
                )
                UPDATE products p
                SET is_available = FALSE,
                    updated_at = CURRENT_TIMESTAMP
                FROM normalized_categories nc
                WHERE p.category_id = nc.category_id
                  AND p.sku = ANY(%s)
                  AND nc.category_id IN (
                    SELECT category_id FROM target_category
                    UNION
                    SELECT category_id FROM normalized_categories 
                    WHERE parent_category_id IN (SELECT category_id FROM target_category)
                  )
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
